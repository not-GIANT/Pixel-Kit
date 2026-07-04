"""Pixel factory-image firmware flashing service — framework-agnostic (zero Qt).

Flashes a complete official Pixel factory-image ZIP from inside the app, with no
external Command Prompt window. The design principle is deliberate:

    We NEVER execute Google's bundled ``flash-all.bat``.

Google's script spawns its own console window and auto-reboots — neither of which
we can monitor or control. Instead we *parse* ``flash-all.bat`` into an ordered
list of fastboot steps and *re-run each step ourselves* via the shared
:class:`~pixelkit.services.command_executor.CommandExecutor`, capturing stdout +
stderr line-by-line so the UI can stream and colorize them live.

Public surface (all pure Python; the UI marshals callbacks onto its own thread):

    validate_package(zip_path)                  -> FactoryImage
    parse_flash_all(script_text)                -> list[FlashStep]
    build_command_sequence(steps, serial, opts) -> list[Command]
    detect_fastboot_device(executor)            -> FastbootDevice | None
    FirmwareService(executor, config, log).flash(...)   # the runner

Scope: official **factory-image** ZIPs only. OTA/sideload packages and boot-image
patching (rooting) are intentionally out of scope for this module.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..config import IS_WINDOWS


# ---------------------------------------------------------------------------
# Marketing-name map — codename -> human name (from the README device table).
# Used to show "Pixel 8 Pro" alongside the raw "husky" codename.
# ---------------------------------------------------------------------------
CODENAME_TO_MARKETING: dict[str, str] = {
    "oriole": "Pixel 6",
    "raven": "Pixel 6 Pro",
    "bluejay": "Pixel 6a",
    "panther": "Pixel 7",
    "cheetah": "Pixel 7 Pro",
    "lynx": "Pixel 7a",
    "shiba": "Pixel 8",
    "husky": "Pixel 8 Pro",
    "akita": "Pixel 8a",
    "tokay": "Pixel 9",
    "caiman": "Pixel 9 Pro",
    "komodo": "Pixel 9 Pro XL",
    "comet": "Pixel 9 Pro Fold",
    "tegu": "Pixel 9a",
    "manta": "Pixel 9a",
    "blazer": "Pixel 10 Pro",
    "mustang": "Pixel 10 Pro XL",
    "frankel": "Pixel 10",
}

# Pixel 6 family — flashing these to Android 13+ bumped anti-rollback (ARB); the
# community guidance is to flash BOTH slots or risk a hard brick on downgrade.
# We surface this as a warning, not a hard block.
ARB_SENSITIVE_CODENAMES = {"oriole", "raven", "bluejay"}

# Partitions that belong to the "radio/modem" group — used by the skip-radio
# option to drop those flash steps.
RADIO_PARTITIONS = {"radio", "modem"}
# Partitions that belong to the "bootloader" group — used by skip-bootloader.
BOOTLOADER_PARTITIONS = {"bootloader", "abl", "xbl", "sbl1"}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class FlashStep:
    """One parsed action from flash-all.bat.

    kind:
      - "flash"            -> partition + image set (single-partition flash)
      - "reboot-bootloader"
      - "update"           -> the big `-w update image-*.zip` step (wipe flag)
    """
    kind: str
    partition: str = ""
    image: str = ""
    wipe: bool = False

    @property
    def is_radio(self) -> bool:
        return self.kind == "flash" and self.partition in RADIO_PARTITIONS

    @property
    def is_bootloader(self) -> bool:
        return self.kind == "flash" and self.partition in BOOTLOADER_PARTITIONS


@dataclass
class FlashOptions:
    """User-selected flashing options (mirrors the checkboxes in the view)."""
    wipe: bool = False                 # -w : wipe userdata
    both_slots: bool = False           # --slot all
    inactive_slot: bool = False        # --set-active=other before flashing
    skip_reboot: bool = False          # do NOT reboot after flashing
    skip_bootloader: bool = False      # drop bootloader flash step
    skip_radio: bool = False           # drop radio/modem flash step
    force: bool = False                # --force (on the update step)
    disable_verity: bool = False       # --disable-verity
    disable_verification: bool = False  # --disable-verification
    verbose: bool = False              # --verbose
    dry_run: bool = False              # log commands, do not execute
    verify_device: bool = True         # pre-flight device presence/match check


@dataclass
class ValidationResult:
    """Outcome of validate_package — structured so the UI can render it."""
    ok: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    found_images: list[str] = field(default_factory=list)


@dataclass
class FactoryImage:
    """A validated (or rejected) Pixel factory-image ZIP."""
    zip_path: str
    codename: str = ""
    build_id: str = ""
    package_root: str = ""             # top-level "<codename>-<build>/" folder
    inner_image_zip: str = ""          # "image-<codename>-<build>.zip" (arcname)
    sha256: str = ""
    steps: list[FlashStep] = field(default_factory=list)
    validation: ValidationResult = field(default_factory=ValidationResult)

    @property
    def is_valid(self) -> bool:
        return self.validation.ok

    @property
    def marketing_name(self) -> str:
        return CODENAME_TO_MARKETING.get(self.codename, "Unknown Pixel")

    @property
    def has_radio(self) -> bool:
        return any(s.is_radio for s in self.steps)

    @property
    def has_bootloader(self) -> bool:
        return any(s.is_bootloader for s in self.steps)


@dataclass
class FastbootDevice:
    """Live details read from a device in fastboot/bootloader mode."""
    serial: str = ""
    codename: str = ""                 # getvar product
    current_slot: str = ""             # "a" / "b" / ""
    unlocked: bool | None = None       # None = unknown
    bootloader_version: str = ""

    @property
    def marketing_name(self) -> str:
        return CODENAME_TO_MARKETING.get(self.codename, "Unknown Pixel")

    @property
    def bootloader_status(self) -> str:
        if self.unlocked is None:
            return "Unknown"
        return "Unlocked" if self.unlocked else "Locked"


# ---------------------------------------------------------------------------
# Package validation (no full extraction — inspect the ZIP central directory)
# ---------------------------------------------------------------------------
def validate_package(zip_path: str) -> FactoryImage:
    """Inspect a factory-image ZIP and return a populated FactoryImage.

    Never raises for a bad package — every failure mode is captured as a
    structured error in the returned ``FactoryImage.validation`` so the UI can
    present actionable messages. Only truly unexpected conditions propagate.

    Checks performed (all against the ZIP central directory + the nested
    ``flash-all.bat`` text; the multi-GB payload is NOT extracted here):
      1. Path exists and is a readable ZIP.
      2. A top-level ``<codename>-<build>/`` folder containing BOTH
         ``flash-all.bat`` and ``flash-all.sh``.
      3. The inner ``image-<codename>-<build>.zip`` and the bootloader/radio
         ``.img`` files referenced by the script are present.
      4. SHA-256 8-hex prefix cross-check against the filename (warn only).
      5. "You picked the inner image- zip" heuristic (a common user error).
    """
    fi = FactoryImage(zip_path=zip_path)
    res = fi.validation

    p = Path(zip_path)
    if not p.exists():
        res.errors.append(f"File not found: {zip_path}")
        return fi
    if not zipfile.is_zipfile(zip_path):
        res.errors.append("Selected file is not a valid ZIP archive.")
        return fi

    # Heuristic: the extracted inner zip is named image-<codename>-<build>.zip.
    # Flashing that directly is a common mistake — it lacks bootloader/radio.
    if p.name.lower().startswith("image-"):
        res.warnings.append(
            "This looks like the inner 'image-*.zip' rather than the full "
            "factory-image download. It may be missing the bootloader and "
            "radio images. Select the original factory ZIP from Google.")

    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()

            # Locate flash-all.bat to derive the package root folder.
            bat = _find_arcname(names, "flash-all.bat")
            sh = _find_arcname(names, "flash-all.sh")
            if not bat:
                res.errors.append(
                    "No 'flash-all.bat' found — this is not a Pixel factory "
                    "image ZIP.")
                return fi
            if not sh:
                res.warnings.append(
                    "No 'flash-all.sh' found (Windows script present). "
                    "Proceeding with flash-all.bat.")

            # "<codename>-<build>/flash-all.bat" -> root, codename, build.
            fi.package_root = bat.rsplit("/", 1)[0] if "/" in bat else ""
            folder = fi.package_root.rsplit("/", 1)[-1]
            m = re.match(r"^([a-z0-9]+)-([a-z0-9._]+)$", folder, re.IGNORECASE)
            if m:
                fi.codename = m.group(1).lower()
                fi.build_id = m.group(2)
            else:
                # Fall back to filename parsing (codename-build-....zip).
                parts = p.stem.split("-")
                if parts:
                    fi.codename = parts[0].lower()
                if len(parts) > 1:
                    fi.build_id = parts[1]

            if fi.codename and fi.codename not in CODENAME_TO_MARKETING:
                res.warnings.append(
                    f"Unrecognized device codename '{fi.codename}'. "
                    f"Flashing will still work if the device matches.")

            # Parse the script into steps.
            try:
                script_text = zf.read(bat).decode("utf-8", errors="replace")
            except Exception as e:  # pragma: no cover - unexpected zip error
                res.errors.append(f"Could not read flash-all.bat: {e}")
                return fi
            fi.steps = parse_flash_all(script_text)
            if not fi.steps:
                res.errors.append(
                    "flash-all.bat contained no recognizable fastboot "
                    "commands — the package may be corrupt.")
                return fi

            # Verify every image the script references actually exists in the
            # archive (either at the package root or inside the inner image zip).
            name_set = {n.rsplit("/", 1)[-1] for n in names}
            fi.inner_image_zip = _find_inner_image_zip(names, fi.package_root)
            inner_names: set[str] = set()
            if fi.inner_image_zip:
                # The partition images (boot/vendor/etc.) live in the inner zip;
                # we only need to confirm the inner zip exists, not open it,
                # since `fastboot update` consumes it as a whole. Record its
                # presence for the found-images checklist.
                res.found_images.append(fi.inner_image_zip.rsplit("/", 1)[-1])

            missing: list[str] = []
            for step in fi.steps:
                if step.kind == "flash" and step.image:
                    img = step.image.rsplit("/", 1)[-1]
                    if img in name_set or img in inner_names:
                        res.found_images.append(img)
                    else:
                        missing.append(img)
                elif step.kind == "update" and step.image:
                    img = step.image.rsplit("/", 1)[-1]
                    if img in name_set:
                        if img not in res.found_images:
                            res.found_images.append(img)
                    else:
                        missing.append(img)

            if missing:
                res.errors.append(
                    "Package is missing required image(s): "
                    + ", ".join(sorted(set(missing))))
                return fi

        # SHA-256 8-hex prefix cross-check (Google embeds it in the filename).
        fi.sha256 = _sha256_prefix(zip_path)
        if fi.sha256 and fi.sha256[:8] not in p.name.lower():
            res.warnings.append(
                "Checksum prefix not found in the filename — the download may "
                "have been renamed or could be incomplete. Verify the SHA-256 "
                "against Google's published value.")

    except zipfile.BadZipFile:
        res.errors.append("The ZIP archive is corrupt and could not be read.")
        return fi
    except Exception as e:  # pragma: no cover - unexpected
        res.errors.append(f"Unexpected error inspecting package: {e}")
        return fi

    res.ok = not res.errors
    return fi


def _find_arcname(names: list[str], basename: str) -> str:
    """Return the first archive entry whose basename matches, else ''."""
    lb = basename.lower()
    for n in names:
        if n.rsplit("/", 1)[-1].lower() == lb:
            return n
    return ""


def _find_inner_image_zip(names: list[str], package_root: str) -> str:
    """Return the arcname of the inner image-<codename>-<build>.zip, else ''."""
    for n in names:
        base = n.rsplit("/", 1)[-1].lower()
        if base.startswith("image-") and base.endswith(".zip"):
            return n
    return ""


def _sha256_prefix(zip_path: str, chunk: int = 1 << 20) -> str:
    """Compute the SHA-256 of the file (streamed). Returns hex digest."""
    h = hashlib.sha256()
    try:
        with open(zip_path, "rb") as f:
            for block in iter(lambda: f.read(chunk), b""):
                h.update(block)
        return h.hexdigest()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# flash-all.bat parsing
# ---------------------------------------------------------------------------
def parse_flash_all(script_text: str) -> list[FlashStep]:
    """Parse a flash-all.bat / flash-all.sh body into ordered FlashSteps.

    We classify each line and keep only the ones that matter for flashing:
      - ``fastboot flash <partition> <image>``     -> FlashStep("flash", ...)
      - ``fastboot reboot-bootloader``             -> FlashStep("reboot-bootloader")
      - ``fastboot -w update <image.zip>`` (any    -> FlashStep("update", wipe=…)
        order of ``-w`` / ``update``)
    Everything else (``PATH=``, ``@ECHO OFF``, ``ping``/``sleep`` delays, the
    ``if`` fastboot-version guard blocks) is ignored — we drive the reboot and
    timing ourselves in the runner.
    """
    steps: list[FlashStep] = []
    for raw in script_text.splitlines():
        line = raw.strip()
        if not line or line.startswith((":", "#", "@", "rem ", "REM ")):
            continue
        low = line.lower()
        if "fastboot" not in low:
            continue

        # Tokenize after the 'fastboot' word.
        try:
            after = line[low.index("fastboot") + len("fastboot"):].strip()
        except ValueError:
            continue
        tokens = after.split()
        if not tokens:
            continue

        # reboot-bootloader (Google uses this between bootloader/radio/system).
        if "reboot-bootloader" in tokens:
            steps.append(FlashStep(kind="reboot-bootloader"))
            continue

        # -w update image-*.zip  (flags may appear in any order)
        if "update" in tokens:
            wipe = "-w" in tokens
            image = ""
            idx = tokens.index("update")
            if idx + 1 < len(tokens):
                image = tokens[idx + 1].strip('"')
            steps.append(FlashStep(kind="update", image=image, wipe=wipe))
            continue

        # flash <partition> <image>
        if "flash" in tokens:
            idx = tokens.index("flash")
            # Skip flags like --slot between 'flash' and the partition.
            rest = [t for t in tokens[idx + 1:] if not t.startswith("-")]
            if len(rest) >= 2:
                steps.append(FlashStep(
                    kind="flash", partition=rest[0],
                    image=rest[1].strip('"')))
            continue

    return steps


# ---------------------------------------------------------------------------
# Command sequence builder
# ---------------------------------------------------------------------------
@dataclass
class Command:
    """One concrete fastboot invocation to run, with a human label."""
    args: list[str]                    # e.g. ["-s","SER","flash","boot","boot.img"]
    label: str                         # "Flash boot" / "Reboot bootloader" / …
    partition: str = ""                # for progress display ("" if n/a)


def build_command_sequence(steps: list[FlashStep], serial: str,
                           options: FlashOptions) -> list[Command]:
    """Translate parsed FlashSteps + options into concrete fastboot commands.

    Flag accumulation (two parallel sets, matching factory-tool behavior):
      - ``flash_flags``  apply to single-partition ``flash`` commands.
      - ``update_flags`` apply to the big ``update`` command and additionally
        carry ``--force`` (which is meaningless on a single-partition flash).

    The ``update`` command ALWAYS gets ``--skip-reboot`` so the runner controls
    the final reboot itself (honoring the skip-reboot option) rather than
    letting fastboot auto-reboot mid-sequence.
    """
    base = ["-s", serial] if serial else []

    flash_flags: list[str] = []
    update_flags: list[str] = ["--skip-reboot"]

    if options.verbose:
        flash_flags.append("--verbose")
        update_flags.append("--verbose")
    if options.both_slots:
        flash_flags.append("--slot")
        flash_flags.append("all")
        update_flags.append("--slot")
        update_flags.append("all")
    if options.disable_verity:
        update_flags.append("--disable-verity")
    if options.disable_verification:
        update_flags.append("--disable-verification")
    if options.force:
        update_flags.append("--force")

    cmds: list[Command] = []

    # Optionally switch to the inactive slot before flashing (mutually
    # exclusive with both_slots — the view enforces that, we just honor it).
    if options.inactive_slot and not options.both_slots:
        cmds.append(Command(
            args=base + ["--set-active=other"],
            label="Set active slot → other"))

    for step in steps:
        if step.kind == "reboot-bootloader":
            cmds.append(Command(
                args=base + ["reboot-bootloader"],
                label="Reboot bootloader"))
        elif step.kind == "flash":
            if options.skip_bootloader and step.is_bootloader:
                continue
            if options.skip_radio and step.is_radio:
                continue
            cmds.append(Command(
                args=base + flash_flags + ["flash", step.partition, step.image],
                label=f"Flash {step.partition}",
                partition=step.partition))
        elif step.kind == "update":
            args = list(base) + list(update_flags)
            # The wipe flag is driven by the user's option, NOT the script's
            # original -w, so "preserve data" reliably disables the wipe.
            if options.wipe:
                args.append("-w")
            args += ["update", step.image]
            cmds.append(Command(
                args=args, label="Flash system (update)",
                partition="system"))

    # Final reboot to the OS unless the user opted out.
    if not options.skip_reboot:
        cmds.append(Command(args=base + ["reboot"], label="Reboot to system"))

    return cmds


# ---------------------------------------------------------------------------
# Device detection (fastboot mode)
# ---------------------------------------------------------------------------
def detect_fastboot_device(executor) -> FastbootDevice | None:
    """Read live details from a device in fastboot/bootloader mode.

    Returns None if no fastboot device is present. Pure reads — never mutates
    device state. Each getvar is tolerant of failure (a field just stays blank).
    """
    serial = _first_fastboot_serial(executor)
    if not serial:
        return None

    dev = FastbootDevice(serial=serial)
    dev.codename = _getvar(executor, serial, "product")
    dev.current_slot = _getvar(executor, serial, "current-slot").lower()
    dev.bootloader_version = _getvar(executor, serial, "version-bootloader")

    unlocked_raw = _getvar(executor, serial, "unlocked").lower()
    if unlocked_raw in ("yes", "true"):
        dev.unlocked = True
    elif unlocked_raw in ("no", "false"):
        dev.unlocked = False
    else:
        dev.unlocked = None
    return dev


def _first_fastboot_serial(executor) -> str:
    """Return the serial of the first fastboot device, or ''."""
    out = _run_fastboot(executor, ["devices"], timeout=5)
    for line in out.splitlines():
        if "\t" in line and "fastboot" in line:
            return line.split("\t")[0].strip()
    return ""


def _getvar(executor, serial: str, var: str) -> str:
    """Run `fastboot -s <serial> getvar <var>` and return the value text.

    fastboot prints getvar output to STDERR as ``<var>: <value>``; the executor
    combines streams, so we scan for the ``<var>:`` line.
    """
    out = _run_fastboot(executor, ["-s", serial, "getvar", var], timeout=8)
    needle = f"{var}:".lower()
    for line in out.splitlines():
        if line.lower().startswith(needle):
            return line.split(":", 1)[1].strip()
    return ""


def _run_fastboot(executor, args: list[str], timeout: int = 8) -> str:
    """Run a fastboot command to completion and return combined output text."""
    try:
        proc = executor.execute_tool_command("fastboot", args,
                                              combine_output=True)
        if not proc:
            return ""
        out, _ = executor.communicate_with_timeout(proc, timeout=timeout)
        return out or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# The flashing runner
# ---------------------------------------------------------------------------
class FirmwareFlashError(Exception):
    """Raised inside the worker thread to abort a flash with a clear message.

    Caught by the runner and surfaced via the on_error callback; never allowed
    to propagate into the GUI thread.
    """


class FirmwareService:
    """Runs an in-process factory-image flash, streaming output via callbacks."""

    def __init__(self, executor, config, log=None):
        self.executor = executor
        self.config = config
        self.log = log
        self.stop_event = threading.Event()
        self._temp_dir: str | None = None

    # -- public API ---------------------------------------------------------

    def cancel(self) -> None:
        """Request cancellation. Honored between commands (safe boundaries)."""
        self.stop_event.set()

    def flash(self, factory: FactoryImage, device: FastbootDevice,
              options: FlashOptions, *,
              on_line=None, on_stage=None, on_partition=None,
              on_progress=None, on_error=None, on_done=None) -> bool:
        """Execute the full flash sequence. Returns True on success.

        Callbacks (all optional; each called from THIS worker thread — the UI is
        responsible for marshalling onto its own thread):
          on_line(text, level)      raw output line + level (info/warn/error/success)
          on_stage(text)            coarse stage label ("Extracting package…")
          on_partition(name)        current partition being flashed
          on_progress(fraction)     0.0–1.0 overall progress
          on_error(message)         fatal error message (also ends the run)
          on_done(success, summary) final summary dict

        Guarantees:
          - Temp extraction dir is always cleaned up.
          - Any exception becomes an on_error callback, never a crash.
          - Cancellation between commands stops cleanly.
        """
        started = time.time()
        flashed: list[str] = []
        self.stop_event.clear()

        def emit(text, level="info"):
            if on_line:
                on_line(text, level)

        def stage(text):
            if on_stage:
                on_stage(text)
            emit(text + "\n", "info")

        try:
            # 1. Extract the package to a temp dir.
            stage("Extracting firmware package…")
            work = self._extract(factory, emit)

            # 2. Rewrite step image paths to their on-disk absolute locations.
            steps = self._resolve_step_paths(factory, work, emit)

            # 3. Build the concrete command list.
            serial = device.serial if device else ""
            commands = build_command_sequence(steps, serial, options)
            total = len(commands)
            if total == 0:
                raise FirmwareFlashError(
                    "Nothing to flash — the package produced no commands.")

            emit(f"Prepared {total} fastboot command(s).\n", "info")
            if options.dry_run:
                emit("DRY RUN — commands will be printed, not executed.\n",
                     "warn")

            # 4. Run each command, streaming output.
            for i, cmd in enumerate(commands):
                if self.stop_event.is_set():
                    raise FirmwareFlashError("Flashing cancelled by user.")

                if on_partition and cmd.partition:
                    on_partition(cmd.partition)
                if on_progress:
                    on_progress(i / total)
                stage(f"[{i + 1}/{total}] {cmd.label}")

                printable = "fastboot " + " ".join(cmd.args)
                emit(f"$ {printable}\n", "info")

                if options.dry_run:
                    emit("(dry run — skipped)\n", "warn")
                    if cmd.partition:
                        flashed.append(cmd.partition)
                    continue

                rc = self._run_streaming(cmd, emit)
                if rc != 0:
                    raise FirmwareFlashError(
                        f"'{cmd.label}' failed with exit code {rc}. "
                        f"See the log above for details.")
                if cmd.partition:
                    flashed.append(cmd.partition)

            if on_progress:
                on_progress(1.0)

            elapsed = time.time() - started
            summary = {
                "success": True,
                "partitions": flashed,
                "elapsed": elapsed,
                "exit_code": 0,
            }
            emit(f"\n✓ Flashing completed successfully in "
                 f"{elapsed:.0f}s.\n", "success")
            if on_done:
                on_done(True, summary)
            return True

        except FirmwareFlashError as e:
            emit(f"\n✗ {e}\n", "error")
            if on_error:
                on_error(str(e))
            if on_done:
                on_done(False, {
                    "success": False, "partitions": flashed,
                    "elapsed": time.time() - started, "error": str(e)})
            return False
        except Exception as e:  # pragma: no cover - defensive catch-all
            msg = f"Unexpected flashing error: {e}"
            emit(f"\n✗ {msg}\n", "error")
            if on_error:
                on_error(msg)
            if on_done:
                on_done(False, {
                    "success": False, "partitions": flashed,
                    "elapsed": time.time() - started, "error": msg})
            return False
        finally:
            self._cleanup_temp(emit)

    # -- internals ----------------------------------------------------------

    def _extract(self, factory: FactoryImage, emit) -> str:
        """Extract the factory ZIP to a fresh temp dir; return the dir path."""
        try:
            self._temp_dir = tempfile.mkdtemp(prefix="pixelkit_fw_")
        except Exception as e:
            raise FirmwareFlashError(f"Could not create a temp directory: {e}")

        try:
            with zipfile.ZipFile(factory.zip_path) as zf:
                zf.extractall(self._temp_dir)
        except zipfile.BadZipFile:
            raise FirmwareFlashError(
                "The firmware ZIP is corrupt and could not be extracted.")
        except Exception as e:
            raise FirmwareFlashError(f"Failed to extract firmware ZIP: {e}")

        emit(f"Extracted to temporary folder.\n", "info")
        return self._temp_dir

    def _resolve_step_paths(self, factory: FactoryImage, work: str,
                            emit) -> list[FlashStep]:
        """Rewrite each step's image to an absolute on-disk path in `work`.

        The extracted tree is ``<work>/<codename>-<build>/…``. Image basenames
        from the script are resolved by walking that folder once (basename →
        full path), so we don't care whether an image sits at the root or in a
        subfolder. Missing files raise (pre-flight — before any fastboot call).
        """
        index: dict[str, str] = {}
        for root, _dirs, files in os.walk(work):
            for f in files:
                index.setdefault(f.lower(), os.path.join(root, f))

        resolved: list[FlashStep] = []
        for step in factory.steps:
            if step.kind == "reboot-bootloader":
                resolved.append(step)
                continue
            base = step.image.rsplit("/", 1)[-1].lower()
            full = index.get(base)
            if not full:
                raise FirmwareFlashError(
                    f"Image '{step.image}' referenced by the flash script was "
                    f"not found in the extracted package.")
            resolved.append(FlashStep(
                kind=step.kind, partition=step.partition,
                image=full, wipe=step.wipe))
        return resolved

    def _run_streaming(self, cmd: Command, emit) -> int:
        """Run one fastboot command, streaming combined output line-by-line.

        Returns the process exit code (or -1 if it couldn't start). Each line is
        classified into a log level so the UI colorizes it. Honors stop_event by
        terminating the child if cancellation is requested mid-command.
        """
        proc = self.executor.execute_tool_command(
            "fastboot", cmd.args, combine_output=True)
        if not proc:
            emit("Failed to start fastboot process.\n", "error")
            return -1

        self.executor.current_process = proc
        try:
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                emit(line, _classify_line(line))
                if self.stop_event.is_set():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    break
            try:
                proc.stdout.close()
            except Exception:
                pass
            return proc.wait()
        finally:
            self.executor.current_process = None

    def _cleanup_temp(self, emit) -> None:
        """Remove the temp extraction dir (best-effort)."""
        if self._temp_dir and os.path.isdir(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
                emit("Cleaned up temporary files.\n", "info")
            except Exception:
                pass
        self._temp_dir = None


# ---------------------------------------------------------------------------
# Output line classification (for colorization)
# ---------------------------------------------------------------------------
_ERROR_MARKERS = ("failed", "error", "cannot", "not found", "no such",
                  "unknown partition", "write to device failed",
                  "too many links", "permission denied")
_WARN_MARKERS = ("warning", "skip", "rollback", "unlock", "locked")
_SUCCESS_MARKERS = ("okay", "finished", "success", "wrote", "done")


def _classify_line(line: str) -> str:
    """Map a fastboot output line to a log level: error/warn/success/info."""
    low = line.lower()
    if any(m in low for m in _ERROR_MARKERS):
        return "error"
    if any(m in low for m in _SUCCESS_MARKERS):
        return "success"
    if any(m in low for m in _WARN_MARKERS):
        return "warn"
    return "info"

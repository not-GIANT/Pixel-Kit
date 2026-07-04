# Pixel Firmware Flashing Module — Implementation Plan

## Context

The app currently supports single-partition flashing (`flashing_view.py`) but has no way to
flash a **complete official Pixel factory-image ZIP**. Users must fall back to Google's
`flash-all.bat`, which opens an external Command Prompt window — inconsistent with the app's
UI and impossible to monitor in-app. This module adds a dedicated **Firmware** page that
runs the entire factory-image flash inside the application, streaming all output into the
existing log console with no external window.

**Key design principle** (confirmed via PixelFlasher research): never execute
`flash-all.bat`. Instead **parse** it into an ordered command list and **re-run each
fastboot command in-process**, capturing stdout/stderr live. This is what keeps the whole
workflow inside the app.

## Architecture (mirrors the existing service/view split)

### New files

**1. `pixelkit/services/firmware_service.py`** (~450 lines) — framework-agnostic, zero Qt,
same style as `cpid_service.py` / `pixel10_service.py`.

- `FactoryImage` dataclass: zip path, codename, build id, inner `image-*.zip` name, parsed
  flash steps, validation result.
- `validate_package(zip_path)` → inspects the ZIP **without full extraction** (nested
  `zipfile`): confirms `flash-all.bat` + `flash-all.sh` exist, derives `<codename>-<build>`
  from the top-level folder, verifies the inner `image-<codename>-<build>.zip` plus the
  bootloader/radio `.img` files are present. Computes SHA-256 and cross-checks the 8-hex
  prefix embedded in Google's filenames. Returns structured errors (missing script, missing
  images, bad archive, "looks like the inner image- zip") — never raises to the UI.
- `parse_flash_all(script_text)` → ordered typed steps: `("flash", partition, image)`,
  `("reboot-bootloader",)`, `("update", zip, wipe)`. Ignores `PATH=`, `ping`/`sleep`, and
  `if` version-guard blocks (same classification as the reference).
- `build_command_sequence(steps, serial, options, slot_info)` → concrete
  `["fastboot","-s",serial, ...flags..., "flash", part, path]` lists. Accumulates flags from
  options: `-w`/no-`-w` (wipe), `--skip-reboot` always on `update` (so *we* own the reboot),
  `--slot all` (both slots — single-pass, per user's choice), `--set-active=other`
  (inactive-slot), `--force`, `--disable-verity` / `--disable-verification`, skip-bootloader
  (drop bootloader flash step), skip-radio (drop radio flash step). Two flag sets: one for
  `flash`, one for `update` (carries `--force`).
- `flash(...)` — callback-driven runner: puts the device in bootloader, extracts the package
  to a **temp dir** (`tempfile.mkdtemp`), runs each command via the existing
  `CommandExecutor.execute_tool_command`, streams every line through callbacks
  (`on_line`, `on_stage`, `on_partition`, `on_progress`), honors a `stop_event` for
  cancellation between commands, and cleans up the temp dir in `finally`.
- `detect_fastboot_device(executor)` → codename (`getvar product`), current-slot
  (`getvar current-slot`), unlocked state (`getvar unlocked`), bootloader version. Pure reads.
- Marketing-name map (codename → "Pixel 8 Pro") built from the README device table.

**2. `pixelkit_qt/views/firmware_view.py`** (~550 lines) — the page, same idioms as
`cpid_view.py` / `fastboot_view.py` (SectionTitle, ActionCard, StepIndicator, dialogs,
worker-thread + Signal marshalling).

- Dismissible, theme-aware **safety banner** (reuse `flashing_view` banner pattern +
  `update_colors`).
- **Device info** section: codename, marketing name, serial, bootloader (Locked/Unlocked),
  slot A/B, fastboot status, Android version. Refreshes on the existing `device_status`
  signal; pulls fastboot-only details on demand.
- **Package selection** `ActionCard`: Browse (`dialogs.pick_open_file`, `*.zip`),
  selected-path label, "Validate" → green found-images checklist or red actionable errors.
- **Flashing options** `ActionCard`: QCheckBoxes for the full matrix — both slots / active
  only, wipe vs preserve (`-w`), reboot after / no-reboot, skip bootloader, skip radio,
  force, disable verity/verification, verify device first. Mutually-incompatible options
  auto-disable (both-slots ⊕ inactive-slot; skip-radio greys out when the package has no
  radio image).
- **Flash controls**: primary "Flash Firmware" (danger variant) + "Cancel" (enabled only
  mid-flash). `StepIndicator` shows stage + overall progress; a live label shows the current
  fastboot command and current partition.
- **Summary** panel filled at the end (success/fail, partitions flashed, elapsed, exit code).
- All long work on a `threading.Thread`; all GUI touches marshalled back via `Signal`s
  exactly like `cpid_view.py` (`_show_info`, `_show_error`, new `_line`, `_stage`,
  `_partition`, `_progress`, `_done`).
- Logs stream into the **existing** LogView through the executor's `on_console_output`
  callback (already wired bridge → LogView), so colorization (info/warn/error/success) and
  the Clear/Save buttons work for free. (Copy = add a "Copy" button to `log_view.py`.)

### Wiring changes (small, surgical)

- **`pixelkit_qt/views/__init__.py`** — export `FirmwareView`.
- **`pixelkit_qt/theme/icons.py`** — add `"nav-firmware"` (e.g. `SP_DriveFDIcon`).
- **`pixelkit_qt/app.py`** — instantiate `FirmwareService`, add `FirmwareView` as the 5th
  stacked page, add the nav-rail "Firmware" item, extend the `_on_nav_change` page map, and
  route `device_status` to the firmware view.
- **`pixelkit_qt/widgets/log_view.py`** — add a "Copy" button (spec asks for copy-logs).

## Safety gates (before any flash)
1. Fastboot device present (else actionable error).
2. Package validated + codename matches the connected device (mismatch → hard confirm).
3. Bootloader locked → warning (flashing needs unlocked).
4. Wipe selected → explicit data-loss confirm.
5. Final "Start flashing?" confirm. All dialog helpers already exist in `dialogs.py`.

## Error handling
Every fastboot invocation's non-zero exit is caught and reported; device-disconnect,
missing-image, bad-archive, locked-bootloader, fastboot-not-found each get a distinct,
actionable message. The service never raises into the GUI thread — errors arrive as
`_show_error` signals, so a flash error can never crash the app.

## Testing
- Import/compile smoke test of every new + modified module.
- `validate_package` tested against a synthetic factory-image zip built in a temp dir
  (correct structure + broken variants) — no device needed.
- `parse_flash_all` tested against a real `flash-all.bat` text sample.
- Headless construction of the 5-page nav wiring to confirm it builds.
- A **dry-run mode** (log the exact fastboot command sequence without executing) so you can
  verify commands are correct before touching real hardware. Live flashing on a device is
  left for you to run.

## Out of scope (called out, not silently dropped)
- OTA / sideload packages and boot-image patching/rooting (PixelFlasher does these; not in
  your spec). This module targets **factory-image ZIP flashing**; both are easy to add later.
- Full per-codename anti-rollback version table. I'll include the Pixel-6-family
  (oriole/raven/bluejay) both-slots ARB warning but not the exhaustive bootloader-version map.

"""Driver installation service for PixelKit.

Provides two installation paths for the bundled ADB/Fastboot driver archive:

- **Automatic** — launches the bundled ``Drivers.exe`` with elevation and waits
  for it to finish.
- **Manual** — copies the pre-extracted ``adb`` folder from
  ``resources/platform-tools`` to ``%SystemDrive%\adb`` and runs the inner
  Google USB Driver installer (``DPInst_x64.exe`` or ``DPInst_x86.exe``).
  The privileged copy/install work is done by an elevated helper subprocess so
  the main PixelKit process stays unprivileged.

All work runs on a background thread and reports progress through plain Python
callbacks so the caller (the Qt dialog) can marshal updates to the UI thread.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from ..config import IS_WINDOWS


# ---------------------------------------------------------------------------
# Callback types
# ---------------------------------------------------------------------------
LogCallback = Callable[[str, str], None]
ProgressCallback = Callable[[float], None]
FinishedCallback = Callable[[bool, str], None]


# ---------------------------------------------------------------------------
# Windows elevation helpers
# ---------------------------------------------------------------------------
class _SHELLEXECUTEINFO(ctypes.Structure):
    """ctypes mapping for Win32 SHELLEXECUTEINFOW."""

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", wintypes.INT),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),  # union member; unused here
        ("hProcess", wintypes.HANDLE),
    ]


_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_NOASYNC = 0x00000100
_SW_SHOWNORMAL = 1
_INFINITE = 0xFFFFFFFF


def _run_elevated(executable: str, parameters: str = "") -> int:
    """Launch ``executable`` with the ``runas`` verb and wait for completion.

    Args:
        executable: Path to the executable to launch.
        parameters: Command-line parameters string.

    Returns:
        The process exit code.

    Raises:
        OSError: If elevation is requested on a non-Windows platform.
        RuntimeError: If the Windows API reports a launch failure.
        WindowsError: If the underlying API call fails.
    """
    if not IS_WINDOWS:
        raise OSError("Elevation is only supported on Windows")

    sei = _SHELLEXECUTEINFO()
    sei.cbSize = ctypes.sizeof(_SHELLEXECUTEINFO)
    sei.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_NOASYNC
    sei.lpVerb = "runas"
    sei.lpFile = executable
    sei.lpParameters = parameters
    sei.nShow = _SW_SHOWNORMAL
    sei.hProcess = None

    ok = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    if sei.hInstApp <= 32:
        raise RuntimeError(f"ShellExecuteExW launch failed, hInstApp={sei.hInstApp}")
    if not sei.hProcess:
        raise RuntimeError("ShellExecuteExW did not return a process handle")

    try:
        ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, _INFINITE)
        exit_code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(exit_code))
        return exit_code.value
    finally:
        ctypes.windll.kernel32.CloseHandle(sei.hProcess)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def _drivers_exe_path(config) -> Path:
    """Resolve the path to the bundled ``Drivers.exe`` archive."""
    directory = config.platform_tools_dir
    exact = directory / "Drivers.exe"
    if exact.is_file():
        return exact
    if directory.is_dir():
        for entry in directory.iterdir():
            if entry.is_file() and entry.name.lower() == "drivers.exe":
                return entry
    return exact


def _find_child_path(parent: Path, name: str) -> Path:
    """Return ``parent/name`` with a case-insensitive fallback scan."""
    exact = parent / name
    if exact.exists():
        return exact
    if parent.is_dir():
        lowered = name.lower()
        for entry in parent.iterdir():
            if entry.name.lower() == lowered:
                return entry
    return exact


def _dpinst_name() -> str:
    """Return the DPInst executable name matching the OS architecture."""
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64", "arm64"):
        return "DPInst_x64.exe"
    return "DPInst_x86.exe"


def _python_interpreter_path(config) -> str:
    """Return a usable Python interpreter path.

    In the standalone PyInstaller build ``resources/python.exe`` is bundled.
    When running from source, ``sys.executable`` is used.
    """
    bundled = config.resources_dir / "python.exe"
    if bundled.is_file():
        return str(bundled)
    return sys.executable


# ---------------------------------------------------------------------------
# Helper script materialisation
# ---------------------------------------------------------------------------
def _helper_source() -> str:
    """Read the source of the self-contained elevated helper script."""
    helper_path = Path(__file__).with_name("_driver_helper.py")
    return helper_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Progress mapping
# ---------------------------------------------------------------------------
_STATUS_TO_PROGRESS = {
    "START": 0.10,
    "COPYING": 0.40,
    "COPY_OK": 0.60,
    "INSTALLING_DRIVER": 0.75,
    "INSTALL_OK": 0.90,
    "DONE": 1.0,
}


class DriverInstaller:
    """Service that performs automatic or manual driver installations.

    Args:
        config: ``AppConfig`` instance — used to locate ``resources/``.
        log: Optional ``PixelKitLogger`` for structured logging.
        on_log: Callback ``func(message, level)`` emitted for each status line.
        on_progress: Callback ``func(value)`` with ``value`` in ``[0.0, 1.0]``.
        on_finished: Callback ``func(success, message)`` when work completes.
    """

    def __init__(
        self,
        config,
        log=None,
        on_log: LogCallback | None = None,
        on_progress: ProgressCallback | None = None,
        on_finished: FinishedCallback | None = None,
    ):
        self.config = config
        self.log = log
        self.on_log = on_log
        self.on_progress = on_progress
        self.on_finished = on_finished

        self._cancel_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._helper_temp_dir: Path | None = None

    # --- public API --------------------------------------------------------

    def install_automatic(self) -> None:
        """Start the automatic installer on a background thread."""
        self._start_worker(self._do_automatic)

    def install_manual(self) -> None:
        """Start the manual installer on a background thread."""
        self._start_worker(self._do_manual)

    def cancel(self) -> None:
        """Request cancellation.

        Cancellation is cooperative: the current blocking wait is interrupted
        but any already-launched external installer will continue until it
        exits.
        """
        self._cancel_event.set()
        self._info("Cancellation requested.")

    # --- internals ---------------------------------------------------------

    def _start_worker(self, target: Callable[[], None]) -> None:
        self._cancel_event.clear()
        self._worker = threading.Thread(target=self._safe_run, args=(target,))
        self._worker.daemon = True
        self._worker.start()

    def _safe_run(self, target: Callable[[], None]) -> None:
        try:
            target()
        except Exception as exc:  # noqa: BLE001
            self._error(f"Unexpected installer error: {exc}")
            self._finish(False, f"Unexpected error: {exc}")

    # --- logging / progress helpers ----------------------------------------

    def _emit_log(self, message: str, level: str = "info") -> None:
        if self.log is not None:
            if level == "error":
                self.log.error(message)
            else:
                self.log.info(message)
        if self.on_log is not None:
            self.on_log(message, level)

    def _info(self, message: str) -> None:
        self._emit_log(message, "info")

    def _error(self, message: str) -> None:
        self._emit_log(message, "error")

    def _progress(self, value: float) -> None:
        if self.on_progress is not None:
            self.on_progress(max(0.0, min(1.0, value)))

    def _finish(self, success: bool, message: str) -> None:
        self._cleanup_temp_dir()
        if self.on_finished is not None:
            self.on_finished(success, message)

    # --- cleanup -----------------------------------------------------------

    def _cleanup_temp_dir(self) -> None:
        if self._helper_temp_dir is not None:
            try:
                shutil.rmtree(self._helper_temp_dir, ignore_errors=True)
            except Exception:
                pass
            self._helper_temp_dir = None

    # --- automatic installation --------------------------------------------

    def _do_automatic(self) -> None:
        self._info("Starting automatic driver installation.")
        self._progress(0.1)

        drivers_exe = _drivers_exe_path(self.config)
        if not drivers_exe.is_file():
            self._error(f"Bundled driver installer not found: {drivers_exe}")
            self._finish(False, "Driver installer not found. The bundle may be incomplete.")
            return

        self._info(f"Launching {drivers_exe.name} with Administrator rights...")
        self._progress(0.3)

        try:
            exit_code = _run_elevated(f'"{drivers_exe}"')
        except OSError as exc:
            self._error(str(exc))
            self._finish(False, "Automatic installation is only supported on Windows.")
            return
        except Exception as exc:  # noqa: BLE001
            self._error(f"Failed to launch installer: {exc}")
            self._finish(
                False,
                "Failed to launch the installer. Make sure you allow the UAC prompt.",
            )
            return

        if exit_code != 0:
            self._error(f"Installer exited with code {exit_code}.")
            self._finish(False, f"The installer exited with code {exit_code}.")
            return

        self._info("Automatic installation completed successfully.")
        self._progress(1.0)
        self._finish(True, "Drivers installed successfully.")

    # --- manual installation -----------------------------------------------

    def _do_manual(self) -> None:
        self._info("Starting manual driver installation.")
        self._progress(0.05)

        source_adb = _find_child_path(self.config.platform_tools_dir, "adb")
        driver_dir = _find_child_path(self.config.platform_tools_dir, "driver")
        dpinst = _find_child_path(driver_dir, _dpinst_name())

        if not source_adb.is_dir():
            self._error(f"ADB folder not found in platform-tools: {source_adb}")
            self._finish(
                False,
                "ADB source folder not found. Make sure the platform-tools bundle is complete.",
            )
            return
        if not dpinst.is_file():
            self._error(f"Driver installer not found: {dpinst}")
            self._finish(
                False,
                "Google USB Driver installer not found. Make sure the driver folder is present.",
            )
            return

        self._helper_temp_dir = Path(tempfile.mkdtemp(prefix="pixelkit_drivers_"))
        helper_script = self._helper_temp_dir / "driver_helper.py"
        status_log = self._helper_temp_dir / "status.log"
        output_log = self._helper_temp_dir / "output.log"

        try:
            helper_script.write_text(_helper_source(), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._error(f"Failed to prepare installer helper: {exc}")
            self._finish(False, "Failed to prepare the installer helper.")
            return

        system_drive = os.environ.get("SystemDrive", "C:")
        system_drive_letter = system_drive[0].upper() if system_drive else "C"

        args = {
            "source_adb": str(source_adb),
            "dpinst": str(dpinst),
            "status_file": str(status_log),
            "output_file": str(output_log),
            "system_drive": system_drive_letter,
        }
        args_file = self._helper_temp_dir / "args.json"
        try:
            args_file.write_text(json.dumps(args), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._error(f"Failed to write helper arguments: {exc}")
            self._finish(False, "Failed to prepare the installer helper.")
            return

        interpreter = _python_interpreter_path(self.config)
        params = f'"{helper_script}" "{args_file}"'

        self._info("Launching elevated helper to copy adb and install drivers...")
        self._info(f"Helper: {helper_script}")
        self._info(f"Interpreter: {interpreter}")
        self._progress(0.1)

        poller_stop = threading.Event()
        poller = threading.Thread(
            target=self._poll_status_log_loop,
            args=(status_log, poller_stop),
            daemon=True
        )
        poller.start()

        try:
            exit_code = _run_elevated(f'"{interpreter}"', params)
        except OSError as exc:
            poller_stop.set()
            poller.join(timeout=1.0)
            self._error(str(exc))
            self._finish(False, "Manual installation is only supported on Windows.")
            return
        except Exception as exc:  # noqa: BLE001
            poller_stop.set()
            poller.join(timeout=1.0)
            self._error(f"Failed to launch elevated helper: {exc}")
            self._finish(
                False,
                "Failed to launch the elevated helper. Make sure you allow the UAC prompt.",
            )
            return
        finally:
            poller_stop.set()
            poller.join(timeout=2.0)

        if exit_code != 0:
            detail = self._read_output_log(output_log)
            msg = (
                f"The manual driver installation did not complete successfully "
                f"(exit code {exit_code})."
            )
            if detail:
                msg += f"\n\nDetails:\n{detail}"
            self._finish(False, msg)
            return

        self._info("Manual installation completed successfully.")
        self._progress(1.0)
        self._finish(True, "Drivers and ADB/Fastboot binaries installed successfully.")

    # --- status log polling ------------------------------------------------

    def _poll_status_log_loop(self, status_log: Path, stop_event: threading.Event) -> None:
        """Poll the status log in a loop until stop_event is set."""
        lines_processed = 0
        while not stop_event.is_set():
            lines_processed = self._read_and_process_status(status_log, lines_processed)
            time.sleep(0.2)
        # Final flush
        self._read_and_process_status(status_log, lines_processed)

    def _read_and_process_status(self, status_log: Path, lines_processed: int) -> int:
        """Read and process new lines in the status log, returning the updated count."""
        try:
            if not status_log.is_file():
                return lines_processed
            lines = status_log.read_text(encoding="utf-8", errors="replace").splitlines()
            if len(lines) > lines_processed:
                for line in lines[lines_processed:]:
                    self._process_status_line(line)
                return len(lines)
        except Exception:
            pass
        return lines_processed

    def _poll_status_log(self, status_log: Path, block_until_done: bool) -> None:
        """Read new status lines from the helper's log and emit progress."""
        last_size = 0
        terminal_seen = False
        deadline: float | None = None
        if block_until_done:
            deadline = time.monotonic() + 2.0

        while True:
            try:
                current_size = status_log.stat().st_size
            except FileNotFoundError:
                current_size = 0

            if current_size > last_size:
                last_size = current_size
                try:
                    lines = status_log.read_text(encoding="utf-8", errors="replace").splitlines()
                except Exception:
                    lines = []
                for line in lines:
                    self._process_status_line(line)
                    if line.startswith("STATUS:DONE") or line.startswith("ERROR:"):
                        terminal_seen = True

            if terminal_seen:
                break
            if not block_until_done:
                break
            if self._cancel_event.is_set():
                break
            time.sleep(0.2)
            if deadline is not None and time.monotonic() > deadline:
                break

    def _process_status_line(self, line: str) -> None:
        line = line.strip()
        if line.startswith("STATUS:"):
            status = line.split(":", 1)[1]
            self._info(f"Installer step: {status}")
            progress = _STATUS_TO_PROGRESS.get(status)
            if progress is not None:
                self._progress(progress)
        elif line.startswith("ERROR:"):
            message = line.split(":", 1)[1]
            self._error(message)
        elif line.startswith("INFO:"):
            message = line.split(":", 1)[1]
            self._info(message)

    def _read_output_log(self, output_log: Path, max_chars: int = 2000) -> str:
        """Return the tail of the helper's captured stdout/stderr, if available."""
        try:
            if not output_log.is_file():
                return ""
            text = output_log.read_text(encoding="utf-8", errors="replace")
            if len(text) > max_chars:
                text = "..." + text[-max_chars:]
            return text.strip()
        except Exception:
            return ""

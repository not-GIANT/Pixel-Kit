"""Elevated helper script for the manual driver-installation method.

This file is intentionally self-contained: it imports only the Python standard
library so it can be copied to a temporary location and executed by a separate
(elevated) Python interpreter without relying on the PixelKit package being on
``sys.path``.

Command-line invocation::

    python _driver_helper.py <args_json_file>

``args_json_file`` is a JSON file containing::

    {
      "source_adb": "path/to/platform-tools/adb",
      "dpinst": "path/to/platform-tools/driver/DPInst_x64.exe",
      "status_file": "path/to/status.log",
      "output_file": "path/to/output.log",
      "system_drive": "C"  // optional, defaults to %SystemDrive%
    }

Status lines are appended to ``status_file`` as plain text:

- ``STATUS:START``
- ``STATUS:COPYING``
- ``STATUS:COPY_OK``
- ``STATUS:INSTALLING_DRIVER``
- ``STATUS:INSTALL_OK``
- ``STATUS:DONE``
- ``ERROR:<message>``

All stdout/stderr from the helper (including any Python traceback) is captured
in ``output_file`` so the main PixelKit process can report the exact failure
reason to the user.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path


def _system_drive() -> str:
    """Return the Windows system drive letter (e.g., 'C')."""
    drive = os.environ.get("SystemDrive", "C:")
    return drive.rstrip("\\").upper()


def _log(status_file: Path, message: str) -> None:
    """Append a status line to the status log; failures are silently ignored."""
    try:
        with open(status_file, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(message + "\n")
            fh.flush()
    except Exception:
        pass


def _capture_output(output_file: Path) -> None:
    """Redirect stdout/stderr to the output log so nothing is lost."""
    try:
        fh = open(output_file, "a", encoding="utf-8", errors="replace")
        sys.stdout = fh
        sys.stderr = fh
    except Exception:
        pass


def run(args: dict) -> int:
    """Execute the manual installation sequence.

    Args:
        args: Dictionary with ``source_adb``, ``dpinst``, ``status_file``,
            ``output_file`` and optionally ``system_drive``.

    Returns:
        Process exit code (0 for success, 1 for failure).
    """
    source_adb = Path(args["source_adb"])
    dpinst = Path(args["dpinst"])
    status_file = Path(args["status_file"])
    output_file = Path(args.get("output_file", status_file))
    system_drive = args.get("system_drive", _system_drive())

    _capture_output(output_file)

    print(f"Helper started")
    print(f"source_adb={source_adb}")
    print(f"dpinst={dpinst}")
    print(f"status_file={status_file}")
    print(f"output_file={output_file}")
    print(f"system_drive={system_drive}")

    _log(status_file, "STATUS:START")

    if not source_adb.is_dir():
        msg = f"ADB source folder not found: {source_adb}"
        print(msg)
        _log(status_file, f"ERROR:{msg}")
        return 1
    if not dpinst.is_file():
        msg = f"Driver installer not found: {dpinst}"
        print(msg)
        _log(status_file, f"ERROR:{msg}")
        return 1

    # 1. Copy the adb folder to the root of the Windows system drive.
    dest = Path(f"{system_drive}:\\adb")
    try:
        _log(status_file, "STATUS:COPYING")
        print(f"Copying {source_adb} -> {dest}")
        if dest.exists():
            try:
                shutil.rmtree(dest)
            except Exception as exc:
                print(f"Warning: could not remove existing {dest}: {exc}")
        shutil.copytree(source_adb, dest, dirs_exist_ok=True)
        _log(status_file, "STATUS:COPY_OK")
        print(f"Copy complete")
    except Exception as exc:  # noqa: BLE001
        msg = f"Copy failed: {exc}"
        print(msg)
        traceback.print_exc()
        _log(status_file, f"ERROR:{msg}")
        return 1

    # 2. Run the Google USB Driver installer from its own folder so it finds
    # the associated .inf/.cat files.
    driver_dir = dpinst.parent
    try:
        _log(status_file, "STATUS:INSTALLING_DRIVER")
        print(f"Running {dpinst} in cwd {driver_dir}")
        proc = subprocess.run(
            [str(dpinst)],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            cwd=str(driver_dir),
        )
        print(f"DPInst raw exit code: {proc.returncode}")
        if proc.stdout:
            print("DPInst stdout:", proc.stdout)
        if proc.stderr:
            print("DPInst stderr:", proc.stderr)

        # DPInst encodes results in a DWORD. The high byte (0xWW) has the
        # 0x80 bit set only when a package could not be installed; all other
        # non-zero codes are success / success-with-reboot / copied-to-store.
        if proc.returncode == 0:
            _log(status_file, "STATUS:INSTALL_OK")
        elif (proc.returncode & 0x80000000) == 0:
            _log(status_file, "STATUS:INSTALL_OK")
            print(f"Treating DPInst exit code {proc.returncode:#010x} as success")
        else:
            stderr = proc.stderr.strip() if proc.stderr else ""
            stdout = proc.stdout.strip() if proc.stdout else ""
            detail = stderr or stdout or f"exit code {proc.returncode}"
            msg = f"Driver installer failed (code {proc.returncode}): {detail}"
            print(msg)
            _log(status_file, f"ERROR:{msg}")
            return proc.returncode if proc.returncode else 1
    except Exception as exc:  # noqa: BLE001
        msg = f"Driver installer error: {exc}"
        print(msg)
        traceback.print_exc()
        _log(status_file, f"ERROR:{msg}")
        return 1

    _log(status_file, "STATUS:DONE")
    print("Helper finished successfully")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: _driver_helper.py <args_json_file>", file=sys.stderr)
        sys.exit(2)
    args_file = Path(sys.argv[1])
    if not args_file.is_file():
        print(f"Arguments file not found: {args_file}", file=sys.stderr)
        sys.exit(2)
    try:
        arguments = json.loads(args_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON arguments: {exc}", file=sys.stderr)
        sys.exit(2)

    status_file = Path(arguments.get("status_file", str(args_file) + ".status"))
    output_file = Path(arguments.get("output_file", str(args_file) + ".out"))
    _capture_output(output_file)

    try:
        sys.exit(run(arguments))
    except Exception as exc:  # noqa: BLE001
        msg = f"Unhandled helper exception: {exc}"
        print(msg)
        traceback.print_exc()
        _log(status_file, f"ERROR:{msg}")
        sys.exit(1)

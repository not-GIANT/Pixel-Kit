import os
import time
import threading
import shutil
import subprocess
import sys
from pathlib import Path

# Ensure resources dir is on sys.path for cpid_logic import
_cpid_resources = Path(__file__).resolve().parent.parent.parent / "resources"
if str(_cpid_resources) not in sys.path:
    sys.path.insert(0, str(_cpid_resources))

import cpid_logic


class CpidService:
    """Backend service for CPID IMEI repair and Pixel 6 DevInfo editing.

    All subprocess communication uses the CommandExecutor's safe
    interactive shell method to prevent pipe-buffer deadlocks.
    """

    def __init__(self, executor, config, log=None):
        self.executor = executor
        self.config = config
        self.log = log

    # --- Root check ---

    def is_root_granted(self):
        """Check if the connected ADB device has root access."""
        try:
            process = self.executor.execute_tool_command(
                "adb", ["shell", "su", "-c", "id"], combine_output=True
            )
            if process:
                output, _ = self.executor.communicate_with_timeout(process, timeout=5)
                return output and "uid=0" in output.lower()
        except Exception:
            pass
        return False

    # --- Backup ---

    def backup_critical_files(self, is_auto=False):
        """Backup critical device partitions (efs, devinfo, cpsha)."""
        try:
            self._log("Fetching device serial...\n")
            serial_proc = self.executor.execute_tool_command(
                "adb", ["get-serialno"], combine_output=True
            )
            serial_out, _ = self.executor.communicate_with_timeout(serial_proc, timeout=5)
            raw_serial = serial_out.strip() if serial_out else ""
            # Guard: adb prints "error: no devices/emulators found" when nothing is
            # connected. That string is an invalid path component on Windows and would
            # cause an OSError when trying to create the backup directory. Treat any
            # adb error line, empty output, or multi-word output (no serial is ever
            # multi-word) as "no device present".
            if (raw_serial
                    and not raw_serial.lower().startswith("error")
                    and "\n" not in raw_serial
                    and " " not in raw_serial):
                device_serial = raw_serial
            else:
                # No device — log the error and bail out immediately.
                msg = raw_serial if raw_serial else "(no output)"
                self._log(f"No device connected (adb get-serialno returned: {msg!r}).\n"
                          f"Connect a device and try again.\n", "error")
                return False

            backup_dir = self.config.persistent_dir / "backups" / device_serial
            backup_dir.mkdir(parents=True, exist_ok=True)

            files_to_backup = [
                ("efs.img", "/dev/block/bootdevice/by-name/efs"),
                ("efs_backup.img", "/dev/block/bootdevice/by-name/efs_backup"),
                ("devinfo.img", "/dev/block/bootdevice/by-name/devinfo"),
                ("cpsha.bak", "/mnt/vendor/persist/modem/cpsha"),
            ]

            all_exist = all((backup_dir / f[0]).exists() for f in files_to_backup)

            if all_exist:
                self._log(f"Backup already exists in {backup_dir.name}. Skipping.\n", "command_output")
                if is_auto:
                    self._copy_backup_to_resources(backup_dir)
                return True

            self._log(f"Creating backup in {backup_dir.name}...\n")
            failed_files = []
            for fname, path in files_to_backup:
                self._log(f"Backing up {fname}...\n")
                # Step 1: copy the partition to /data/local/tmp on the device.
                if "cpsha" in fname:
                    rc1 = self.executor.run_command(
                        "adb", ["shell", "su", "-c", f"cat {path} > /data/local/tmp/{fname}"]
                    )
                else:
                    rc1 = self.executor.run_command(
                        "adb", ["shell", "su", "-c", f"dd if={path} of=/data/local/tmp/{fname}"]
                    )
                if rc1 != 0:
                    self._log(f"Failed to read {fname} from device (rc={rc1}).\n", "error")
                    failed_files.append(fname)
                    continue

                # Step 2: pull the file to the host.
                rc2 = self.executor.run_command(
                    "adb", ["pull", f"/data/local/tmp/{fname}",
                            str((backup_dir / fname).absolute())]
                )
                if rc2 != 0:
                    self._log(f"Failed to pull {fname} from device (rc={rc2}).\n", "error")
                    failed_files.append(fname)

            if failed_files:
                self._log(
                    f"Backup incomplete — {len(failed_files)} file(s) could not be saved: "
                    f"{', '.join(failed_files)}.\n"
                    f"Ensure the device is connected with root access and try again.\n",
                    "error"
                )
                return False

            if is_auto:
                self._copy_backup_to_resources(backup_dir)

            self._log("--- Backup Completed Successfully ---\n\n", "status")
            return True

        except Exception as e:
            self._log(f"Backup Error: {e}\n", "error")
            return False

    def _copy_backup_to_resources(self, backup_dir):
        """Copy backup files to resources/ for use by the repair sequence."""
        for name in ["cpsha.bak", "devinfo.img"]:
            src = backup_dir / name
            if src.exists():
                shutil.copy(src, self.config.resources_dir / name)

    # --- Pixel 6 template handling ---

    def load_pixel6_template(self, model_id):
        """Load a Pixel 6 series devinfo template and parse IMEIs.

        Returns:
            (template_data_bytes, imei1_str, imei2_str, records_dict)
        Raises:
            FileNotFoundError, ValueError
        """
        template_path = self.config.resources_dir / "models" / model_id / "devinfo.img"
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")

        with open(template_path, "rb") as f:
            template_data = f.read()

        records = cpid_logic.parse_devinfo_records(template_data)

        imei1 = ""
        imei2 = ""
        if "imei1" in records:
            imei1 = records["imei1"]["value_bytes"].decode("ascii", errors="ignore").rstrip("\x00")
        if "imei2" in records:
            imei2 = records["imei2"]["value_bytes"].decode("ascii", errors="ignore").rstrip("\x00")

        return template_data, imei1, imei2, records

    def patch_and_export_pixel6(self, template_data, new_imei1, new_imei2):
        """Patch template with new IMEIs and export to persistent directory.

        Returns:
            (patched_bytes, dest_path)
        Raises:
            ValueError on validation failure.
        """
        new_imei1 = new_imei1.strip()
        new_imei2 = new_imei2.strip()

        if len(new_imei1) != 15 or len(new_imei2) != 15:
            raise ValueError("Both IMEIs must be exactly 15 digits.")
        if not (new_imei1.isdigit() and new_imei2.isdigit()):
            raise ValueError("IMEIs must contain numeric digits only.")
        if new_imei1 == new_imei2:
            raise ValueError("Slot 1 and Slot 2 cannot have identical IMEIs.")
        if not cpid_logic.luhn_check(new_imei1) or not cpid_logic.luhn_check(new_imei2):
            raise ValueError("One or both IMEIs failed Luhn checksum validation.")

        patched_bytes = cpid_logic.patch_devinfo_tlv(template_data, new_imei1, new_imei2)

        dest_dir = self.config.persistent_dir
        dest_path = dest_dir / "devinfo.img"

        if dest_path.exists():
            counter = 1
            while True:
                candidate = dest_dir / f"devinfo_{counter}.img"
                if not candidate.exists():
                    dest_path = candidate
                    break
                counter += 1

        with open(dest_path, "wb") as f:
            f.write(patched_bytes)

        return patched_bytes, dest_path

    # --- CPID 10-step repair ---

    def run_cpid_repair(self, imei1, imei2, progress_callback=None):
        """Execute the full 10-step CPID IMEI repair sequence.

        This method is designed to run in a background thread.
        Subprocess communication uses the executor's safe shell method
        to prevent pipe-buffer deadlocks.
        """
        devinfo_path = self.config.resources_dir / "devinfo.img"
        mod_devinfo_path = self.config.resources_dir / "modified_devinfo.img"

        # Step 1: Pre-flight checks
        self._log("[Step 1/10] Pre-flight checks...\n", "status")
        if progress_callback:
            progress_callback(1, 10, "Pre-flight checks")
        if not self.is_root_granted():
            raise RuntimeError("Root access is required. Please grant 'su' permission on the device.")

        # Step 2: Backup
        self._log("[Step 2/10] Handling device backups...\n", "status")
        if progress_callback:
            progress_callback(2, 10, "Handling device backups")
        success = self.backup_critical_files(is_auto=True)
        if not success:
            raise RuntimeError("Backup process failed or was aborted.")
        if not devinfo_path.exists():
            raise RuntimeError("Failed to retrieve devinfo.img during backup stage.")

        # Step 3: Patch devinfo
        self._log("[Step 3/10] Patching devinfo binary...\n", "status")
        if progress_callback:
            progress_callback(3, 10, "Patching devinfo binary")
        cpid_logic.patch_devinfo(
            str(devinfo_path.absolute()),
            str(mod_devinfo_path.absolute()),
            imei1, imei2
        )
        self._log("Successfully patched IMEI offsets.\n", "command_output")

        # Step 4: Flash in fastboot
        self._log("[Step 4/10] Rebooting to Bootloader for flashing...\n", "status")
        if progress_callback:
            progress_callback(4, 10, "Rebooting to Bootloader")
        self.executor.run_command("adb", ["reboot", "bootloader"])
        self._wait_for_fastboot()
        self._log("Flashing modified devinfo...\n")
        self.executor.run_command("fastboot", ["flash", "devinfo", str(mod_devinfo_path.absolute())])

        # Step 5: Set factory bootmode
        self._log("[Step 5/10] Setting Factory Bootmode...\n", "status")
        if progress_callback:
            progress_callback(5, 10, "Setting Factory Bootmode")
        self.executor.run_command("fastboot", ["oem", "set_config", "bootmode", "factory"])
        self.executor.run_command("fastboot", ["reboot"])

        # Step 6: Wait for factory mode ADB
        self._log("[Step 6/10] Waiting for device to boot in Factory Mode...\n", "status")
        if progress_callback:
            progress_callback(6, 10, "Waiting for Factory Mode ADB")
        self._wait_for_adb()

        # Step 7: AT commands (FIXED: uses drain-thread to prevent deadlock)
        self._log("[Step 7/10] Sending AT commands to modem...\n", "status")
        if progress_callback:
            progress_callback(7, 10, "Sending AT commands to modem")
        self._send_at_commands(imei1, imei2)

        # Step 8: Modem refresh
        self._log("[Step 8/10] Refreshing modem state...\n", "status")
        if progress_callback:
            progress_callback(8, 10, "Refreshing modem state")
        self._refresh_modem()

        # Step 9: SHA fix via lexipwn
        self._log("[Step 9/10] Synchronizing SHA hash with lexipwn...\n", "status")
        if progress_callback:
            progress_callback(9, 10, "Synchronizing SHA hash")
        self._run_lexipwn()

        # Step 10: Finalize
        self._log("[Step 10/10] Finalizing device state...\n", "status")
        if progress_callback:
            progress_callback(10, 10, "Finalizing device state")
        self._finalize_repair()

        self._log("\n--- CPID Repair Sequence Completed Successfully! ---\n", "status")

    def _wait_for_fastboot(self):
        """Poll until device appears in fastboot mode."""
        while not self.executor.stop_event.is_set():
            fb_check = self.executor.execute_tool_command(
                "fastboot", ["devices"], combine_output=True
            )
            out, _ = self.executor.communicate_with_timeout(fb_check, timeout=5)
            if out and out.strip():
                break
            time.sleep(3)

    def _wait_for_adb(self):
        """Poll until device appears in ADB mode."""
        while not self.executor.stop_event.is_set():
            adb_check = self.executor.execute_tool_command(
                "adb", ["shell", "echo", "ready"], combine_output=True
            )
            out, _ = self.executor.communicate_with_timeout(adb_check, timeout=10)
            if out and "ready" in out:
                break
            time.sleep(5)

    def _send_at_commands(self, imei1, imei2):
        """Send AT commands to modem via interactive shell with deadlock-safe I/O.

        Uses the executor's run_interactive_shell which drains stdout/stderr
        in separate reader threads to prevent pipe-buffer deadlocks.
        """
        adb_path = self.executor.cached_paths.get(
            "adb", str((self.config.platform_tools_dir / "adb").absolute())
        )
        at_commands = cpid_logic.get_imei_at_commands(imei1, imei2)

        self.executor.run_interactive_shell(adb_path, at_commands, timeout=30)

    def _refresh_modem(self):
        """Toggle airplane mode and send NV backup command.

        Uses the drain-thread pattern for the interactive shell
        to prevent pipe-buffer deadlock.
        """
        refresh_cmds = [
            ["adb", "shell", "su", "-c", "settings put global airplane_mode_on 1"],
            ["adb", "shell", "su", "-c",
             "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true"],
            ["adb", "shell", "su", "-c", "settings put global airplane_mode_on 0"],
            ["adb", "shell", "su", "-c",
             "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false"],
        ]
        for r_cmd in refresh_cmds:
            self.executor.run_command(r_cmd[0], r_cmd[1:])

        time.sleep(2)

        adb_path = self.executor.cached_paths.get(
            "adb", str((self.config.platform_tools_dir / "adb").absolute())
        )
        backup_cmds = [
            "echo 'AT+GOOGBACKUPNV\r' > /dev/umts_router",
            "cat /dev/umts_router",
        ]
        self.executor.run_interactive_shell(adb_path, backup_cmds, timeout=30)

    def _run_lexipwn(self):
        """Push and execute lexipwn binary for SHA hash fix."""
        lexipwn_path = self.config.resources_dir / "lexipwn"
        if lexipwn_path.exists():
            self.executor.run_command(
                "adb", ["push", str(lexipwn_path.absolute()), "/data/local/tmp/lexipwn"]
            )
            self.executor.run_command(
                "adb", ["shell", "su", "-c", "chmod +x /data/local/tmp/lexipwn"]
            )
            self.executor.run_command(
                "adb", ["shell", "su", "-c", "/data/local/tmp/lexipwn fiximeisha"]
            )
            self.executor.run_command(
                "adb", ["shell", "su", "-c", "setprop vendor.sys.modem_reset 1"]
            )
            time.sleep(2)
        else:
            self._log("Warning: lexipwn binary not found. Skipping SHA fix.\n", "error")

    def _finalize_repair(self):
        """Set normal bootmode and reboot."""
        self.executor.run_command("adb", ["reboot", "bootloader"])
        self._wait_for_fastboot()
        self.executor.run_command("fastboot", ["oem", "rm_config", "bootmode"])
        self.executor.run_command("fastboot", ["reboot"])

    # --- Internal ---

    def _log(self, text, tag=None):
        if self.log:
            if tag == "status":
                self.log.status(text)
            elif tag == "error":
                self.log.error(text)
            elif tag == "command_output":
                self.log.command_output(text)
            else:
                self.log.info(text)

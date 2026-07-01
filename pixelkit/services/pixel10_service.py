import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

# cpid_logic is shared via the resources path added by cpid_service import
import cpid_logic


class Pixel10Service:
    """Backend service for Pixel 10 Series CPID IMEI repair.

    Workflow:
      1. Detect device model and product name.
      2. Create a timestamped, device-specific backup under Device_Backups/.
      3. Pull devinfo from the device, patch with new IMEIs.
      4. Flash patched devinfo via fastboot, set factory bootmode.
      5. Send AT commands to write IMEIs to modem NVRAM.
      6. Refresh modem state (airplane toggle + NV backup).
      7. Fetch SHA hash via AT+GOOGGETIMEISHA, write to cpsha.
      8. Reset bootmode to normal and reboot.

    All subprocess communication uses the executor's deadlock-safe
    interactive shell method.
    """

    DEVINFO_BLOCK = '/dev/block/by-name/devinfo'
    UMT_DEVICE = '/dev/umts_router'
    CPSHA_PATH = '/mnt/vendor/persist/modem/cpsha'

    BACKUP_PARTS = ['devinfo', 'efs', 'efs_backup', 'modem']

    def __init__(self, executor, config, log=None):
        self.executor = executor
        self.config = config
        self.log = log
        self._log_func = None
        self._error_func = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_full_repair(self, imei1, imei2, progress_callback=None,
                        log_func=None, error_func=None):
        """Run the full Pixel 10 CPID repair workflow with progress callback.

        Args:
            imei1: First IMEI (15 digits).
            imei2: Second IMEI (15 digits).
            progress_callback: Called with (current_step, total_steps) after each step.
            log_func: Ignored — service uses its own PixelKitLogger instance.
            error_func: Ignored — service uses its own PixelKitLogger instance.
        """
        self.run_repair(imei1, imei2, progress_callback)

    def run_repair(self, imei1, imei2, progress_callback=None):
        """Run the full Pixel 10 CPID repair workflow (blocks until done)."""
        self._log("[1/8] Detecting device\u2026\n", "status")
        if progress_callback:
            progress_callback(1, 8)
        product, model = self._detect_device_model()

        self._log("[2/8] Creating device backup\u2026\n", "status")
        if progress_callback:
            progress_callback(2, 8)
        backup_dir = self._create_backup(product, model)

        self._log("[3/8] Pulling and patching devinfo\u2026\n", "status")
        if progress_callback:
            progress_callback(3, 8)
        mod_devinfo = self._patch_devinfo(imei1, imei2)

        self._log("[4/8] Flashing devinfo + factory bootmode\u2026\n", "status")
        if progress_callback:
            progress_callback(4, 8)
        self._flash_devinfo(mod_devinfo)

        self._log("[5/8] Sending AT commands to modem\u2026\n", "status")
        if progress_callback:
            progress_callback(5, 8)
        self._send_at_commands(imei1, imei2)

        self._log("[6/8] Refreshing modem state\u2026\n", "status")
        if progress_callback:
            progress_callback(6, 8)
        self._refresh_modem()

        self._log("[7/8] Synchronising SHA hash\u2026\n", "status")
        if progress_callback:
            progress_callback(7, 8)
        self._perform_sha_ops()

        self._log("[8/8] Finalising device state\u2026\n", "status")
        if progress_callback:
            progress_callback(8, 8)
        self._finalize()

        # Write operation log
        self._write_operation_log(backup_dir, imei1, imei2)

        self._log("\n--- Pixel 10 CPID Repair Completed Successfully! ---\n", "status")

    # ------------------------------------------------------------------
    # Device detection
    # ------------------------------------------------------------------

    def _detect_device_model(self):
        """Query device properties and return (safe_product, safe_model)."""
        product = "unknown_device"
        model = "unknown_model"

        try:
            prod_proc = self.executor.execute_tool_command(
                "adb", ["shell", "getprop", "ro.product.name"], combine_output=True
            )
            if prod_proc:
                out, _ = self.executor.communicate_with_timeout(prod_proc, timeout=5)
                if out:
                    product = out.strip()

            model_proc = self.executor.execute_tool_command(
                "adb", ["shell", "getprop", "ro.product.model"], combine_output=True
            )
            if model_proc:
                out, _ = self.executor.communicate_with_timeout(model_proc, timeout=5)
                if out:
                    model = out.strip()
        except Exception:
            pass

        safe_product = re.sub(r'[<>:"/\\|?*]', '_', product or "unknown_device")
        safe_model = re.sub(r'[<>:"/\\|?*]', '_', model or "unknown_model")
        self._log(f"Device: {safe_model} ({safe_product})\n")
        return safe_product, safe_model

    # ------------------------------------------------------------------
    # Backup system
    # ------------------------------------------------------------------

    def _create_backup(self, product, model):
        """Back up critical partitions to a timestamped device-specific folder.

        Directory structure:
            Device_Backups/<Model>_<Product>/YYYY-MM-DD_HH-MM-SS/
        """
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup_dir = (
            self.config.persistent_dir
            / "Device_Backups"
            / f"{model}_{product}"
            / timestamp
        )
        backup_dir.mkdir(parents=True, exist_ok=True)
        self._log(f"Backup folder \u2192 {backup_dir}\n")

        for part in self.BACKUP_PARTS:
            self._log(f"  Backing up {part}\u2026\n")
            try:
                dd_path = (
                    f"dd if={self.DEVINFO_BLOCK}"
                    if part == "devinfo"
                    else f"dd if=/dev/block/bootdevice/by-name/{part}"
                )
                self.executor.run_command(
                    "adb",
                    ["shell", "su", "-c", f"{dd_path} of=/data/local/tmp/{part}.img"],
                )
                self.executor.run_command(
                    "adb",
                    ["pull", f"/data/local/tmp/{part}.img",
                     str(backup_dir / f"{part}.img")],
                )
                self.executor.run_command(
                    "adb",
                    ["shell", "su", "-c", f"rm /data/local/tmp/{part}.img"],
                )
            except Exception as e:
                if part == "devinfo":
                    raise RuntimeError(
                        f"Critical backup failed for {part}. Aborting."
                    ) from e
                self._log(f"  Warning: could not back up {part} \u2014 {e}\n", "error")

        # Write metadata
        meta = {
            "device_product": product,
            "device_model": model,
            "series": "Pixel 10 Series",
            "timestamp": timestamp,
            "partitions": self.BACKUP_PARTS,
            "devinfo_block_device": self.DEVINFO_BLOCK,
        }
        meta_path = backup_dir / "metadata.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
        self._log(f"  Metadata written \u2192 {meta_path}\n")

        # Verify backups
        for part in self.BACKUP_PARTS:
            part_path = backup_dir / f"{part}.img"
            if not part_path.exists() or part_path.stat().st_size == 0:
                if part == "devinfo":
                    raise RuntimeError(
                        f"Backup verification failed: {part}.img missing or empty."
                    )
                self._log(
                    f"  Warning: {part}.img missing or empty\n", "error"
                )

        self._log("Backup complete.\n")
        return backup_dir

    # ------------------------------------------------------------------
    # DevInfo patching
    # ------------------------------------------------------------------

    def _patch_devinfo(self, imei1, imei2):
        """Pull devinfo from device, patch with new IMEIs, return path to modified image."""
        devinfo_path = self.config.resources_dir / "devinfo.img"
        mod_devinfo_path = self.config.resources_dir / "modified_devinfo.img"

        self._log("  Pulling devinfo from device\u2026\n")
        self.executor.run_command(
            "adb",
            [
                "shell", "su", "-c",
                f"dd if={self.DEVINFO_BLOCK} of=/data/local/tmp/devinfo.img",
            ],
        )
        self.executor.run_command(
            "adb",
            ["pull", "/data/local/tmp/devinfo.img", str(devinfo_path.absolute())],
        )

        self._log("  Patching IMEI offsets\u2026\n")
        cpid_logic.patch_devinfo(
            str(devinfo_path.absolute()),
            str(mod_devinfo_path.absolute()),
            imei1,
            imei2,
        )
        self._log("  Patched successfully.\n", "command_output")
        return mod_devinfo_path

    # ------------------------------------------------------------------
    # Flash operations
    # ------------------------------------------------------------------

    def _flash_devinfo(self, mod_devinfo_path):
        """Reboot to fastboot, flash modified devinfo, set factory bootmode, reboot."""
        self._log("  Rebooting to bootloader\u2026\n")
        self.executor.run_command("adb", ["reboot", "bootloader"])
        self._wait_for_fastboot()

        self._log("  Flashing modified devinfo\u2026\n")
        self.executor.run_command(
            "fastboot", ["flash", "devinfo", str(mod_devinfo_path.absolute())]
        )

        self._log("  Setting factory bootmode\u2026\n")
        self.executor.run_command(
            "fastboot", ["oem", "set_config", "bootmode", "factory"]
        )

        self._log("  Rebooting\u2026\n")
        self.executor.run_command("fastboot", ["reboot"])
        self._wait_for_adb()

    # ------------------------------------------------------------------
    # AT commands
    # ------------------------------------------------------------------

    def _send_at_commands(self, imei1, imei2):
        """Write IMEIs to modem NVRAM via AT+GOOGSETNV over /dev/umts_router.

        Uses the executor's deadlock-safe interactive shell method.
        """
        adb_path = self.executor.cached_paths.get(
            "adb", str((self.config.platform_tools_dir / "adb").absolute())
        )

        parts1 = cpid_logic.prepare_imei_parts(imei1)
        parts2 = cpid_logic.prepare_imei_parts(imei2)

        commands = []
        for idx, part in enumerate(parts1):
            commands.append(
                f"echo 'AT+GOOGSETNV=\"CAL.Common.Imei\",{idx},\"{part}\"\\r' "
                f"> {self.UMT_DEVICE}"
            )
        for idx, part in enumerate(parts2):
            commands.append(
                f"echo 'AT+GOOGSETNV=\"CAL.Common.Imei_2nd\",{idx},\"{part}\"\\r' "
                f"> {self.UMT_DEVICE}"
            )

        self.executor.run_interactive_shell(adb_path, commands, timeout=45)
        self._log("  AT commands sent.\n")

    # ------------------------------------------------------------------
    # Modem refresh
    # ------------------------------------------------------------------

    def _refresh_modem(self):
        """Toggle airplane mode and send AT+GOOGBACKUPNV."""
        self._log("  Toggling airplane mode\u2026\n")
        refresh_cmds = [
            ["adb", "shell", "su", "-c",
             "settings put global airplane_mode_on 1"],
            ["adb", "shell", "su", "-c",
             "am broadcast -a android.intent.action.AIRPLANE_MODE "
             "--ez state true"],
            ["adb", "shell", "su", "-c",
             "settings put global airplane_mode_on 0"],
            ["adb", "shell", "su", "-c",
             "am broadcast -a android.intent.action.AIRPLANE_MODE "
             "--ez state false"],
        ]
        for cmd in refresh_cmds:
            self.executor.run_command(cmd[0], cmd[1:])

        time.sleep(2)

        self._log("  Sending AT+GOOGBACKUPNV\u2026\n")
        adb_path = self.executor.cached_paths.get(
            "adb", str((self.config.platform_tools_dir / "adb").absolute())
        )
        backup_cmds = [
            f"echo 'AT+GOOGBACKUPNV\\r' > {self.UMT_DEVICE}",
            f"head -c 4096 {self.UMT_DEVICE}",
        ]
        self.executor.run_interactive_shell(adb_path, backup_cmds, timeout=20)
        self._log("  NV backup done.\n")

    # ------------------------------------------------------------------
    # SHA operations
    # ------------------------------------------------------------------

    def _perform_sha_ops(self):
        """Fetch SHA hash from modem, write to cpsha, trigger modem reset."""
        adb_path = self.executor.cached_paths.get(
            "adb", str((self.config.platform_tools_dir / "adb").absolute())
        )

        self._log("  Fetching IMEI SHA hash\u2026\n")
        sha_cmds = [
            f"printf 'AT+GOOGGETIMEISHA\\r' > {self.UMT_DEVICE}",
            f"head -c 4096 {self.UMT_DEVICE}",
        ]

        output = self.executor.run_interactive_shell(
            adb_path, sha_cmds, timeout=25
        )

        sha_hash = None
        for line in output:
            if "+GOOGGETIMEISHA:" in line:
                sha_hash = line.split(":", 1)[-1].strip().strip('"')
                break

        if not sha_hash:
            raise RuntimeError(
                "Could not parse SHA hash from AT+GOOGGETIMEISHA output. "
                "The repair may be incomplete."
            )

        self._log(f"  SHA hash: {sha_hash}\n")

        write_cmds = [
            f'echo -n "{sha_hash}" > {self.CPSHA_PATH}',
            "setprop vendor.sys.modem_reset 1",
        ]
        self.executor.run_interactive_shell(adb_path, write_cmds, timeout=15)
        self._log("  SHA written to cpsha, modem reset triggered.\n")

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def _finalize(self):
        """Reboot to bootloader, reset bootmode to normal, reboot."""
        self._log("  Rebooting to bootloader\u2026\n")
        self.executor.run_command("adb", ["reboot", "bootloader"])
        self._wait_for_fastboot()

        self._log("  Resetting bootmode to normal\u2026\n")
        self.executor.run_command("fastboot", ["oem", "rm_config", "bootmode"])

        self._log("  Rebooting to system\u2026\n")
        self.executor.run_command("fastboot", ["reboot"])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _wait_for_fastboot(self):
        """Poll until device appears in fastboot mode."""
        while not self.executor.stop_event.is_set():
            proc = self.executor.execute_tool_command(
                "fastboot", ["devices"], combine_output=True
            )
            out, _ = self.executor.communicate_with_timeout(proc, timeout=5)
            if out and out.strip():
                break
            time.sleep(3)

    def _wait_for_adb(self):
        """Poll until device appears in ADB mode."""
        while not self.executor.stop_event.is_set():
            proc = self.executor.execute_tool_command(
                "adb", ["shell", "echo", "ready"], combine_output=True
            )
            out, _ = self.executor.communicate_with_timeout(proc, timeout=10)
            if out and "ready" in out:
                break
            time.sleep(5)

    def _write_operation_log(self, backup_dir, imei1, imei2):
        """Write an operation log to the backup directory."""
        try:
            log_path = backup_dir / "operation_log.txt"
            with open(log_path, "w") as f:
                f.write(f"Pixel 10 CPID Repair - {datetime.now()}\n")
                f.write(f"IMEI1: {imei1}\n")
                f.write(f"IMEI2: {imei2}\n")
                f.write("Status: Completed\n")
                f.write(
                    "Rollback: Flash the backed-up devinfo.img via fastboot.\n"
                )
            self._log(f"  Operation log \u2192 {log_path}\n")
        except Exception as e:
            self._log(f"  Warning: could not write operation log: {e}\n", "error")

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

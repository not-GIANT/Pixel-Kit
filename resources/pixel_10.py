import json
import os
import queue as _queue
import re
import subprocess
import threading
import time
from datetime import datetime

from core.adb import SCRIPT_DIR, adb_path, fastboot_path, execute_command, _wait_for_fastboot, _wait_for_adb_ready, _poll_fastboot_devices
from core.patcher import get_offsets_from_di_py, write_imeis_to_devinfo, prepare_imei
from workflows.base import AbstractWorkflow


class Pixel10Workflow(AbstractWorkflow):
    SERIES_NAME = 'Pixel 10 Series'
    BACKUP_PARTS = ['devinfo', 'efs', 'efs_backup', 'modem']
    DEVINFO_BLOCK_DEVICE = '/dev/block/by-name/devinfo'
    UMT_DEVICE = '/dev/umts_router'
    CPSHA_PATH = '/mnt/vendor/persist/modem/cpsha'
    BOOTMODE_FACTORY_CMD = ['oem', 'set_config', 'bootmode', 'factory']
    BOOTMODE_NORMAL_CMD = ['oem', 'rm_config', 'bootmode']
    AT_LABEL_IMEI1 = 'CAL.Common.Imei'
    AT_LABEL_IMEI2 = 'CAL.Common.Imei_2nd'

    BACKUP_BASE_DIR = os.path.join(SCRIPT_DIR, 'Device_Backups')

    def _detect_device_model(self, adb):
        log = self._log
        product = 'unknown_device'
        model = 'unknown_model'
        try:
            product = execute_command([adb, 'shell', 'getprop', 'ro.product.name'], log).strip()
            model = execute_command([adb, 'shell', 'getprop', 'ro.product.model'], log).strip()
        except Exception:
            pass
        if not product:
            product = 'unknown_device'
        if not model:
            model = 'unknown_model'
        safe_product = re.sub(r'[<>:"/\\|?*]', '_', product)
        safe_model = re.sub(r'[<>:"/\\|?*]', '_', model)
        return safe_product, safe_model

    def _create_backup(self, adb):
        log = self._log
        log('Detecting device model\u2026')
        product, model = self._detect_device_model(adb)
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup_dir = os.path.join(self.BACKUP_BASE_DIR, f'{model}_{product}', timestamp)
        os.makedirs(backup_dir, exist_ok=True)
        log(f'Backup folder \u2192 {backup_dir}')

        for part in self.BACKUP_PARTS:
            log(f'Backing up {part}\u2026')
            try:
                dd_path = (f'dd if={self.DEVINFO_BLOCK_DEVICE}'
                           if part == 'devinfo' else
                           f'dd if=/dev/block/bootdevice/by-name/{part}')
                execute_command([adb, 'shell', 'su', '-c',
                    f'{dd_path} of=/data/local/tmp/{part}.img'], log)
                execute_command([adb, 'pull', f'/data/local/tmp/{part}.img',
                    os.path.join(backup_dir, f'{part}.img')], log)
                execute_command([adb, 'shell', 'su', '-c',
                    f'rm /data/local/tmp/{part}.img'], log)
            except Exception as e:
                if part == 'devinfo':
                    raise RuntimeError(f'Critical backup failed for {part}. Aborting.')
                log(f'   Warning: could not back up {part} \u2014 {e}')

        metadata = {
            'device_product': product,
            'device_model': model,
            'series': self.SERIES_NAME,
            'timestamp': timestamp,
            'partitions': self.BACKUP_PARTS,
            'devinfo_block_device': self.DEVINFO_BLOCK_DEVICE,
        }
        meta_path = os.path.join(backup_dir, 'metadata.json')
        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        log(f'Metadata written \u2192 {meta_path}')

        for part in self.BACKUP_PARTS:
            part_path = os.path.join(backup_dir, f'{part}.img')
            if not os.path.isfile(part_path) or os.path.getsize(part_path) == 0:
                if part == 'devinfo':
                    raise RuntimeError(f'Backup verification failed: {part}.img missing or empty.')
                log(f'   Warning: {part}.img missing or empty \u2014 backup incomplete for this partition')
        log('Backup complete.')

    def run(self):
        try:
            adb = adb_path()
            fboot = fastboot_path()
            log = self._log

            for path, name in [(adb, 'ADB'), (fboot, 'fastboot')]:
                if not os.path.exists(path):
                    raise FileNotFoundError(f'{name} not found at {path}')

            log('Checking for connected ADB device\u2026')
            out = execute_command([adb, 'devices'], log)
            if not any('\tdevice' in l for l in out.splitlines()[1:]):
                raise RuntimeError('No ADB device connected.')

            self._verify_root(adb)
            self._create_backup(adb)

            devinfo = os.path.join(SCRIPT_DIR, 'devinfo.img')
            log('Pulling devinfo from device\u2026')
            execute_command([adb, 'shell', 'su', '-c',
                f'dd if={self.DEVINFO_BLOCK_DEVICE} '
                f'of=/data/local/tmp/devinfo.img'], log)
            execute_command([adb, 'pull', '/data/local/tmp/devinfo.img', devinfo], log)

            log('Patching devinfo.img\u2026')
            off1, off2 = get_offsets_from_di_py(devinfo)
            modified = write_imeis_to_devinfo(devinfo, self.imei1, self.imei2, off1, off2)
            log(f'Saved patched image \u2192 {modified}')

            log('Rebooting to bootloader\u2026')
            execute_command([adb, 'reboot', 'bootloader'], log)
            _wait_for_fastboot(fboot, log, poll=4)

            log('Flashing devinfo\u2026')
            execute_command([fboot, 'flash', 'devinfo', modified], log)

            log('Setting bootmode \u2192 factory\u2026')
            execute_command([fboot] + self.BOOTMODE_FACTORY_CMD, log)

            log('Rebooting device\u2026')
            execute_command([fboot, 'reboot'], log)
            _wait_for_adb_ready(adb, log, poll=10)

            self._set_imei_shell(adb)
            self._complete_modem_ops(adb)
            time.sleep(3)
            self._perform_sha_ops(adb, fboot)

            self.success.emit('All operations completed successfully.')
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    def run_reset_bootmode(self):
        try:
            adb = adb_path()
            fboot = fastboot_path()
            log = self._log

            for path, name in [(adb, 'ADB'), (fboot, 'fastboot')]:
                if not os.path.exists(path):
                    raise FileNotFoundError(f'{name} not found at {path}')

            log('Checking for fastboot device\u2026')
            out = _poll_fastboot_devices(fboot)
            in_fastboot = any('fastboot' in line for line in out.splitlines())

            if not in_fastboot:
                log('Device not in fastboot. Checking ADB\u2026')
                out = execute_command([adb, 'devices'], log)
                if any('\tdevice' in l for l in out.splitlines()[1:]):
                    log('Rebooting to bootloader via ADB\u2026')
                    execute_command([adb, 'reboot', 'bootloader'], log)
                else:
                    raise RuntimeError('No device found in fastboot or ADB mode. '
                                       'Connect a device and try again.')
                _wait_for_fastboot(fboot, log, poll=4)

            log('Resetting bootmode\u2026')
            execute_command([fboot] + self.BOOTMODE_NORMAL_CMD, log)
            log('Bootmode reset. Rebooting device\u2026')
            execute_command([fboot, 'reboot'], log)

            self.success.emit('Bootmode reset to normal. Device is rebooting.')
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    def _set_imei_shell(self, adb):
        log = self._log
        log('Opening ADB shell to write IMEI via AT commands\u2026')
        proc = subprocess.Popen([adb, 'shell'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)

        at_errors = []
        def _collect():
            try:
                for line in proc.stdout:
                    stripped = line.strip()
                    if 'ERROR' in stripped:
                        at_errors.append(stripped)
            except Exception:
                pass
        threading.Thread(target=_collect, daemon=True).start()

        self._safe_write(proc, 'su\n')
        time.sleep(1)
        for label, imei in [(self.AT_LABEL_IMEI1, self.imei1),
                             (self.AT_LABEL_IMEI2, self.imei2)]:
            for idx, part in enumerate(prepare_imei(imei)):
                cmd = f"printf 'AT+GOOGSETNV=\"{label}\",{idx},\"{part}\"\\r' > {self.UMT_DEVICE}\n"
                log(f'   {cmd.strip()}')
                self._safe_write(proc, cmd)
                time.sleep(0.2)
        self._safe_write(proc, 'exit\nexit\n')
        self._safe_wait(proc, timeout=30)
        if at_errors:
            for err in at_errors:
                log(f'   [WARN] Modem error: {err}')
        log('IMEI AT commands sent.')

    def _complete_modem_ops(self, adb):
        log = self._log
        log('Toggling airplane mode\u2026')
        for val, state in [('1', 'true'), ('0', 'false')]:
            execute_command([adb, 'shell', 'su', '-c',
                f'settings put global airplane_mode_on {val}'], log)
            execute_command([adb, 'shell', 'su', '-c',
                f'am broadcast -a android.intent.action.AIRPLANE_MODE --ez state {state}'], log)
            time.sleep(1)
        log('Sending AT+GOOGBACKUPNV\u2026')
        proc = subprocess.Popen([adb, 'shell'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        self._safe_write(proc, 'su\n')
        time.sleep(1)
        self._safe_write(proc, f"printf 'AT+GOOGBACKUPNV\\r' > {self.UMT_DEVICE}\n")
        self._safe_write(proc, f'head -c 4096 {self.UMT_DEVICE}\n')
        try:
            stdout, _ = proc.communicate(timeout=10)
            if stdout.strip():
                for line in stdout.strip().splitlines():
                    log(f'   {line}')
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log('AT+GOOGBACKUPNV done.')

    def _perform_sha_ops(self, adb, fboot):
        log = self._log
        log('Fetching IMEI SHA hash (parallel fetch)\u2026')
        proc = subprocess.Popen([adb, 'shell'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        self._safe_write(proc, 'su\n')
        time.sleep(1)
        self._safe_write(proc,
            f"printf 'AT+GOOGGETIMEISHA\\r' > {self.UMT_DEVICE} & head -c 4096 {self.UMT_DEVICE}\n")

        q = _queue.Queue()
        stop_event = threading.Event()

        def _reader():
            try:
                for raw in proc.stdout:
                    if stop_event.is_set():
                        break
                    q.put(raw.strip())
            except Exception:
                pass
            finally:
                q.put(None)

        reader_thread = threading.Thread(target=_reader, daemon=True)
        reader_thread.start()

        sha_output = ''
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                line = q.get(timeout=min(0.5, deadline - time.time()))
            except _queue.Empty:
                continue
            if line is None:
                break
            if line:
                sha_output += '\n' + line
                log(f'   {line}')
                if '+GOOGGETIMEISHA:' in line or line == 'OK':
                    break

        stop_event.set()

        if not sha_output.strip():
            proc.kill()
            proc.wait()
            raise RuntimeError('Timed out waiting for AT+GOOGGETIMEISHA response.')

        sha_hash = None
        for line in sha_output.splitlines():
            if '+GOOGGETIMEISHA:' in line:
                sha_hash = line.split(':', 1)[-1].strip().strip('"')
                break
        if not sha_hash:
            proc.kill()
            proc.wait()
            raise ValueError('Could not parse SHA hash from AT+GOOGGETIMEISHA output.')

        log(f'SHA hash: {sha_hash}')
        safe_hash = sha_hash.replace('"', '\\"')
        self._safe_write(proc, f'echo -n "{safe_hash}" > {self.CPSHA_PATH}\n')
        time.sleep(1)
        self._safe_write(proc, 'setprop vendor.sys.modem_reset 1\n')
        time.sleep(2)
        self._safe_write(proc, 'reboot bootloader\n')
        time.sleep(3)
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        reader_thread.join(timeout=5)

        _wait_for_fastboot(fboot, log, poll=7)
        execute_command([fboot] + self.BOOTMODE_NORMAL_CMD, log)
        time.sleep(2)
        execute_command([fboot, 'reboot'], log)
        log('SHA operations complete.')

import threading
import time
from ..models.device import DeviceInfo


class DeviceMonitor:
    """Background device status polling service.

    Two-tier polling keeps the UI feeling instant without hammering the device:

    1. Cheap probe every ~2s — just `adb devices` and (if needed)
       `fastboot devices`. This detects connect/disconnect within seconds.
    2. Expensive property fetch (model / android version / battery) — runs
       ONLY when the connected device's identity (serial + mode) changes,
       not on every poll. Steady-state polling of an already-known device
       does zero shell calls.

    This fixes both problems with the old design:
      - Old poll interval was 10s, so a freshly-plugged device took up to
        10s to register. Now ~2s.
      - Old poll ran up to 4 subprocesses (devices + 3 getprop/dumpsys)
        every cycle, blocking the poll thread and racing with the UI's
        tools-check on startup. Now the probe is one call and the heavy
        fetch only fires once per device.
    """

    def __init__(self, executor, log=None, on_status_change=None):
        self.executor = executor
        self.log = log
        self.on_status_change = on_status_change  # callback(DeviceInfo)

        self._running = False
        self._poll_interval = 2  # seconds between cheap probes
        self._thread = None

        # Last reported identity ("adb:<serial>" / "fastboot:<serial>" / "").
        # When this changes we re-fetch the expensive properties.
        self._last_identity = None

    def start(self):
        """Start the background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the background polling thread."""
        self._running = False

    # ------------------------------------------------------------------
    # Cheap probe — who is connected right now? (one subprocess, fast)
    # ------------------------------------------------------------------

    def _probe(self) -> tuple[str, str]:
        """Return (mode, serial) for the currently connected device.

        mode is "ADB", "Fastboot", or "" (nothing connected). Uses a single
        `adb devices` call; only falls back to `fastboot devices` if adb
        reports nothing. Each call gets its own short timeout so a hung
        tool can't stall the poll thread for long.
        """
        out = self._run_tool("adb", ["devices"], timeout=3)
        serial = self._parse_devices_output(out, "device")
        if serial:
            return "ADB", serial

        # No adb device — check fastboot.
        out = self._run_tool("fastboot", ["devices"], timeout=3)
        serial = self._parse_devices_output(out, "fastboot")
        if serial:
            return "Fastboot", serial

        return "", ""

    @staticmethod
    def _parse_devices_output(output: str, keyword: str) -> str:
        """Pull the first device serial out of `adb devices` / `fastboot devices`.

        Output looks like:
            List of devices attached
            <serial>\tdevice
        or:
            <serial>\tfastboot
        The first line is the header; subsequent lines that contain the
        keyword and a tab separator carry a serial.
        """
        if not output:
            return ""
        for line in output.strip().splitlines()[1:]:
            if keyword in line and "\t" in line:
                return line.split("\t")[0].strip()
        return ""

    def _run_tool(self, tool: str, args: list, timeout: int = 3) -> str:
        """Run a single tool command, returning combined stdout+stderr text.

        Errors and timeouts return "" so the probe never raises — a failed
        probe just means "treat as disconnected this cycle".
        """
        try:
            proc = self.executor.execute_tool_command(
                tool, args, combine_output=True
            )
            if not proc:
                return ""
            out, _ = self.executor.communicate_with_timeout(proc, timeout=timeout)
            return out or ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Expensive fetch — model / android / battery (only on change)
    # ------------------------------------------------------------------

    def _fetch_properties(self, mode: str, serial: str) -> DeviceInfo:
        """Build a fully-populated DeviceInfo for the given device."""
        info = DeviceInfo()
        info.serial = serial
        if mode == "ADB":
            info.status = "Connected (ADB)"
            info.status_color = "#4caf50"
            info.connection_type = "ADB"
            self._fill_adb(info, serial)
        else:  # Fastboot
            info.status = "Connected (Fastboot)"
            info.status_color = "#4caf50"
            info.connection_type = "Fastboot"
            self._fill_fastboot(info)
        return info

    def _fill_adb(self, info: DeviceInfo, serial: str) -> None:
        s = ["-s", serial, "shell"]
        model = self._run_tool("adb", s + ["getprop", "ro.product.model"])
        if model:
            info.model = model.strip()
        version = self._run_tool(
            "adb", s + ["getprop", "ro.build.version.release"])
        if version:
            info.android_version = version.strip()
        battery = self._run_tool("adb", s + ["dumpsys", "battery"])
        if battery:
            for line in battery.splitlines():
                if "level:" in line:
                    info.battery_level = line.split(":")[-1].strip() + "%"
                    break

    def _fill_fastboot(self, info: DeviceInfo) -> None:
        prod = self._run_tool("fastboot", ["getvar", "product"])
        if prod:
            for line in prod.splitlines():
                low = line.lower()
                if ("product:" in low) or ("product" in low and ":" in line):
                    info.model = line.split(":", 1)[1].strip()
                    break
        bat = self._run_tool("fastboot", ["getvar", "battery-level"])
        if bat and "battery-level" in bat.lower():
            for line in bat.splitlines():
                if "battery-level:" in line.lower():
                    info.battery_level = line.split(":")[-1].strip() + "%"
                    break

    # ------------------------------------------------------------------
    # Public single-shot poll (used by manual "refresh")
    # ------------------------------------------------------------------

    def poll_once(self):
        """Force a full re-probe + property fetch and return DeviceInfo."""
        mode, serial = self._probe()
        if not mode:
            self._last_identity = None
            return DeviceInfo()
        info = self._fetch_properties(mode, serial)
        self._last_identity = f"{mode.lower()}:{serial}"
        return info

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _poll_loop(self):
        """Cheap-probe every _poll_interval; full fetch only on change."""
        while self._running:
            try:
                self._tick()
            except Exception:
                # Never let the poll thread die — a bad tick shouldn't kill
                # device monitoring for the rest of the session.
                pass
            # Short sleeps so stop() is responsive.
            time.sleep(self._poll_interval)

    def _tick(self) -> None:
        mode, serial = self._probe()
        identity = f"{mode.lower()}:{serial}" if mode else ""

        if not mode:
            # Disconnected.
            if self._last_identity:  # was connected → notify the change
                self._last_identity = None
                self._notify(DeviceInfo())
            return

        if identity == self._last_identity:
            # Same device as last time — nothing to do. This is the steady-
            # state path and involves zero shell calls, so polling a known
            # device is essentially free.
            return

        # New device (or mode change) — fetch full details once.
        info = self._fetch_properties(mode, serial)
        self._last_identity = identity
        self._notify(info)

    def _notify(self, info: DeviceInfo) -> None:
        if self.on_status_change and self._running:
            self.on_status_change(info)

from dataclasses import dataclass, field


@dataclass
class DeviceInfo:
    status: str = "Disconnected"
    status_color: str = "#f44336"
    model: str = "N/A"
    serial: str = "N/A"
    android_version: str = "N/A"
    battery_level: str = "N/A"
    connection_type: str = ""  # "ADB", "Fastboot", or ""

    @property
    def is_connected(self):
        return self.status != "Disconnected"

    @property
    def is_adb(self):
        return "ADB" in self.status

    @property
    def is_fastboot(self):
        return "Fastboot" in self.status

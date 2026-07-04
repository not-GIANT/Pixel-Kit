import os
import sys
import json
import subprocess
from pathlib import Path


IS_WINDOWS = os.name == 'nt'
WIN_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0


class AppConfig:
    """Manages application paths, constants, and user configuration persistence."""

    def __init__(self):
        self._setup_paths()
        self.config_data = self.load()

    def _setup_paths(self):
        if hasattr(sys, '_MEIPASS'):
            self.resources_dir = Path(sys._MEIPASS) / "resources"
            self.persistent_dir = Path(sys.executable).parent
        else:
            self.persistent_dir = Path(__file__).resolve().parent.parent
            self.resources_dir = self.persistent_dir / "resources"

        if str(self.resources_dir) not in sys.path:
            sys.path.append(str(self.resources_dir))

        self.platform_tools_dir = self.resources_dir / "platform-tools"
        self.config_file = self.persistent_dir / "pixelkit_config.json"
        self.required_tools = ["adb", "fastboot", "scrcpy"]

    @property
    def theme(self):
        return self.config_data.get("theme", "Dark")

    @theme.setter
    def theme(self, value):
        self.config_data["theme"] = value

    @property
    def window_position(self):
        return self.config_data.get("position", "1192x661+242+89")

    @window_position.setter
    def window_position(self, value):
        self.config_data["position"] = value

    @property
    def skip_cpid_warning(self):
        return self.config_data.get("skip_cpid_warning", False)

    @skip_cpid_warning.setter
    def skip_cpid_warning(self, value):
        self.config_data["skip_cpid_warning"] = value

    def load(self):
        defaults = {"theme": "Dark", "position": "1192x661+242+89"}
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                return {**defaults, **config}
            except Exception as e:
                print(f"Error loading config: {e}")
        return defaults

    def save(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config_data, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")

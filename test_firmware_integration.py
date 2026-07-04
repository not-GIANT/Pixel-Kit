import os
import sys
import unittest
import tempfile
import zipfile
from pathlib import Path

# Ensure project root is in sys.path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pixelkit.services.firmware_service import (
    validate_package, parse_flash_all, build_command_sequence,
    FlashOptions, FlashStep, CODENAME_TO_MARKETING
)

class TestFirmwareService(unittest.TestCase):
    def test_parse_flash_all(self):
        script_text = """@echo off
PATH=%PATH%;"%~dp0\\platform-tools"
fastboot %* flash bootloader bootloader-husky-g111-1.img
fastboot %* reboot-bootloader
ping -n 5 127.0.0.1 >nul
fastboot %* flash radio radio-husky-g111-2.img
fastboot %* reboot-bootloader
ping -n 5 127.0.0.1 >nul
fastboot %* -w update image-husky-g111.zip
"""
        steps = parse_flash_all(script_text)
        self.assertEqual(len(steps), 5)
        
        self.assertEqual(steps[0].kind, "flash")
        self.assertEqual(steps[0].partition, "bootloader")
        self.assertEqual(steps[0].image, "bootloader-husky-g111-1.img")
        self.assertTrue(steps[0].is_bootloader)
        self.assertFalse(steps[0].is_radio)

        self.assertEqual(steps[1].kind, "reboot-bootloader")

        self.assertEqual(steps[2].kind, "flash")
        self.assertEqual(steps[2].partition, "radio")
        self.assertEqual(steps[2].image, "radio-husky-g111-2.img")
        self.assertTrue(steps[2].is_radio)
        self.assertFalse(steps[2].is_bootloader)

        self.assertEqual(steps[3].kind, "reboot-bootloader")

        self.assertEqual(steps[4].kind, "update")
        self.assertEqual(steps[4].image, "image-husky-g111.zip")
        self.assertTrue(steps[4].wipe)

    def test_validate_package_success(self):
        # Create a temporary ZIP file that represents a valid firmware package
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "husky-g111-factory.zip")
            
            with zipfile.ZipFile(zip_path, "w") as zf:
                # Write bat script
                zf.writestr("husky-g111/flash-all.bat", """@echo off
fastboot %* flash bootloader bootloader-husky-g111-1.img
fastboot %* flash radio radio-husky-g111-2.img
fastboot %* -w update image-husky-g111.zip
""")
                zf.writestr("husky-g111/flash-all.sh", "#!/bin/sh\n")
                zf.writestr("husky-g111/bootloader-husky-g111-1.img", "dummy bootloader")
                zf.writestr("husky-g111/radio-husky-g111-2.img", "dummy radio")
                zf.writestr("husky-g111/image-husky-g111.zip", "dummy system images")

            factory = validate_package(zip_path)
            self.assertTrue(factory.is_valid, f"Validation failed: {factory.validation.errors}")
            self.assertEqual(factory.codename, "husky")
            self.assertEqual(factory.build_id, "g111")
            self.assertEqual(factory.marketing_name, "Pixel 8 Pro")
            self.assertTrue(factory.has_radio)
            self.assertTrue(factory.has_bootloader)
            self.assertEqual(len(factory.steps), 3)

    def test_validate_package_missing_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "husky-g111-bad.zip")
            
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("husky-g111/flash-all.bat", """@echo off
fastboot %* flash bootloader bootloader-husky-g111-1.img
fastboot %* flash radio radio-husky-g111-2.img
fastboot %* -w update image-husky-g111.zip
""")
                # Missing other referenced images (e.g. bootloader-husky-g111-1.img, image-husky-g111.zip)

            factory = validate_package(zip_path)
            self.assertFalse(factory.is_valid)
            self.assertTrue(any("missing required image" in e.lower() for e in factory.validation.errors))

    def test_build_command_sequence(self):
        steps = [
            FlashStep(kind="flash", partition="bootloader", image="bootloader.img"),
            FlashStep(kind="reboot-bootloader"),
            FlashStep(kind="flash", partition="radio", image="radio.img"),
            FlashStep(kind="reboot-bootloader"),
            FlashStep(kind="update", image="image.zip", wipe=True)
        ]
        
        # Test default options (preserve data, reboot after)
        opts = FlashOptions(wipe=False, skip_reboot=False)
        cmds = build_command_sequence(steps, "SERIAL123", opts)
        
        # We expect:
        # 1. flash bootloader (with serial)
        # 2. reboot-bootloader
        # 3. flash radio
        # 4. reboot-bootloader
        # 5. update image.zip (no -w, with --skip-reboot)
        # 6. reboot
        self.assertEqual(len(cmds), 6)
        self.assertEqual(cmds[0].args, ["-s", "SERIAL123", "flash", "bootloader", "bootloader.img"])
        self.assertEqual(cmds[1].args, ["-s", "SERIAL123", "reboot-bootloader"])
        self.assertEqual(cmds[2].args, ["-s", "SERIAL123", "flash", "radio", "radio.img"])
        self.assertEqual(cmds[3].args, ["-s", "SERIAL123", "reboot-bootloader"])
        self.assertEqual(cmds[4].args, ["-s", "SERIAL123", "--skip-reboot", "update", "image.zip"])
        self.assertEqual(cmds[5].args, ["-s", "SERIAL123", "reboot"])

        # Test wipe option
        opts_wipe = FlashOptions(wipe=True, skip_reboot=True)
        cmds_wipe = build_command_sequence(steps, "SERIAL123", opts_wipe)
        self.assertEqual(len(cmds_wipe), 5)  # No final reboot
        # The update step should have -w
        self.assertEqual(cmds_wipe[4].args, ["-s", "SERIAL123", "--skip-reboot", "-w", "update", "image.zip"])

        # Test skip bootloader/radio options
        opts_skip = FlashOptions(skip_bootloader=True, skip_radio=True)
        cmds_skip = build_command_sequence(steps, "SERIAL123", opts_skip)
        # We skipped bootloader and radio flash, but reboot-bootloader is kept since it's type reboot-bootloader, not flash
        self.assertEqual(len(cmds_skip), 4)
        self.assertEqual(cmds_skip[0].args, ["-s", "SERIAL123", "reboot-bootloader"])
        self.assertEqual(cmds_skip[1].args, ["-s", "SERIAL123", "reboot-bootloader"])
        self.assertEqual(cmds_skip[2].args, ["-s", "SERIAL123", "--skip-reboot", "update", "image.zip"])
        self.assertEqual(cmds_skip[3].args, ["-s", "SERIAL123", "reboot"])

class TestFirmwareQtWiring(unittest.TestCase):
    def test_app_wiring(self):
        # Initialize QApplication
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication([])

        from pixelkit_qt.app import MainWindow
        from pixelkit_qt.views import FirmwareView

        win = MainWindow()
        
        # Verify the pages count is 5 (page_adb, page_fastboot, page_flashing, page_cpid, page_firmware)
        self.assertEqual(win.page_stack.count(), 5)
        self.assertIsInstance(win.page_firmware, FirmwareView)
        
        # Verify nav rail item count is 5
        self.assertEqual(len(win.nav_rail._items), 5)
        
        # Verify nav switching to index 4 switches to page_firmware
        win.nav_rail.select(4)
        self.assertEqual(win.page_stack.currentWidget(), win.page_firmware)

        # Verify options and controls cards are initially hidden
        self.assertTrue(win.page_firmware._options_card.isHidden())
        self.assertTrue(win.page_firmware._controls_card.isHidden())

        # Simulate a valid package validation and check that options and controls become visible
        from pixelkit.services.firmware_service import FactoryImage, ValidationResult
        dummy_factory = FactoryImage(zip_path="dummy.zip")
        dummy_factory.validation = ValidationResult(ok=True)
        win.page_firmware._factory = dummy_factory
        win.page_firmware._render_validation()
        
        self.assertFalse(win.page_firmware._options_card.isHidden())
        self.assertFalse(win.page_firmware._controls_card.isHidden())

        # Verify colors are propagated on theme change
        dummy_scheme = {"primary": "#123456", "error": "#ff0000", "outline": "#777777"}
        win._on_theme_change(dummy_scheme)
        self.assertEqual(win.page_firmware._scheme, dummy_scheme)

        # Verify dynamic icons
        from pixelkit_qt.theme import icons
        nav_icon = icons.icon_for("nav-firmware")
        self.assertFalse(nav_icon.isNull())
        
        # Verify update_icons works on the nav rail
        win.nav_rail.update_icons()
        
        # Clean up
        win.close()


class TestDeviceMonitorAndCustomCommand(unittest.TestCase):
    def test_device_monitor_parsing(self):
        from pixelkit.services.device_monitor import DeviceMonitor

        # ADB devices output with header
        adb_out = "List of devices attached\n1234567890\tdevice\n"
        serial = DeviceMonitor._parse_devices_output(adb_out, "device")
        self.assertEqual(serial, "1234567890")

        # Fastboot devices output (no header, single device)
        fb_out = "abcdef123456\tfastboot\n"
        serial_fb = DeviceMonitor._parse_devices_output(fb_out, "fastboot")
        self.assertEqual(serial_fb, "abcdef123456")

        # ADB devices with daemon startup prefix
        adb_prefix_out = "* daemon not running; starting now\n* daemon started successfully\nList of devices attached\n9876543210\tdevice\n"
        serial_prefix = DeviceMonitor._parse_devices_output(adb_prefix_out, "device")
        self.assertEqual(serial_prefix, "9876543210")

    def test_custom_command_routing(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])

        from pixelkit_qt.app import MainWindow
        win = MainWindow()

        # Mock the executor.run_command_threaded method to capture calls
        win.executor.run_command_threaded_calls = []
        def mock_run_command_threaded(tool, parts, task_name=None):
            win.executor.run_command_threaded_calls.append((tool, parts, task_name))
        win.executor.run_command_threaded = mock_run_command_threaded

        # Test adb view with adb command
        from pixelkit_qt.views import AdbView, FastbootView
        adb_view = AdbView(win.executor, win.app_config)
        
        # We simulate custom command by calling the core logic directly on shlex parsed command
        # or we mock dialogs.prompt_text to return predefined strings.
        from pixelkit_qt.widgets import dialogs
        orig_prompt = dialogs.prompt_text
        
        try:
            # Case 1: ADB command in ADB view (without prefix)
            dialogs.prompt_text = lambda *args, **kwargs: "shell getprop ro.product.model"
            adb_view.custom_command()
            self.assertEqual(win.executor.run_command_threaded_calls[-1][0], "adb")
            self.assertEqual(win.executor.run_command_threaded_calls[-1][1], ["shell", "getprop", "ro.product.model"])

            # Case 2: Fastboot command in ADB view (with explicit fastboot prefix)
            dialogs.prompt_text = lambda *args, **kwargs: "fastboot flashing unlock"
            adb_view.custom_command()
            self.assertEqual(win.executor.run_command_threaded_calls[-1][0], "fastboot")
            self.assertEqual(win.executor.run_command_threaded_calls[-1][1], ["flashing", "unlock"])

            # Case 3: Fastboot command in Fastboot view (without prefix)
            fb_view = FastbootView(win.executor, win.app_config)
            dialogs.prompt_text = lambda *args, **kwargs: "getvar all"
            fb_view.custom_command()
            self.assertEqual(win.executor.run_command_threaded_calls[-1][0], "fastboot")
            self.assertEqual(win.executor.run_command_threaded_calls[-1][1], ["getvar", "all"])

            # Case 4: ADB command in Fastboot view (with explicit adb prefix)
            dialogs.prompt_text = lambda *args, **kwargs: "adb devices"
            fb_view.custom_command()
            self.assertEqual(win.executor.run_command_threaded_calls[-1][0], "adb")
            self.assertEqual(win.executor.run_command_threaded_calls[-1][1], ["devices"])
        finally:
            dialogs.prompt_text = orig_prompt
            win.close()


if __name__ == "__main__":
    unittest.main()

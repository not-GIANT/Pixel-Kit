"""ADB operations view — M3 grouped action cards over the same executor.

Replaces the legacy 2-column flat button list. Same 21 actions, regrouped by
intent into 4 cards:
  - Power        (reboot submenu: System / Bootloader / Recovery / EDL)
  - Apps & Files (install / uninstall / sideload / push / pull / magisk)
  - Server & Net (start/kill server, tcpip, connect, get-serialno)
  - Device Tools (list devices, open shell, scrcpy, reset EFS, diag, custom)

Every handler delegates to self.executor exactly as the legacy tab did — same
commands, same argument lists, same confirm dialogs. The only change is visual.
"""
from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from pixelkit.config import IS_WINDOWS, WIN_CREATION_FLAGS
from ..widgets import (ActionCard, FitScrollArea, LabeledField,
                       SectionTitle, dialogs, equalize_card_heights)


REFLOW_THRESHOLD = 620  # px — switch from 2-col to 1-col below this width


class AdbView(QWidget):
    """The ADB operations page."""

    def __init__(self, executor, app_config, parent=None):
        super().__init__(parent)
        self.executor = executor
        self.app_config = app_config
        # All ActionCards in this section, tracked so we can equalize their
        # heights after layout (tallest card wins → every card the same height,
        # borders aligned across the whole grid, not just per row).
        self._cards: list = []
        self._current_cols = 0
        self._scroll: "FitScrollArea | None" = None  # set in _build_ui
        self._build_ui()

    # =====================================================================
    # Layout
    # =====================================================================

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        # Header
        outer.addWidget(SectionTitle("ADB Operations"))

        # Scrollable card area. FitScrollArea forces the card grid to reflow
        # against the visible viewport width (no horizontal overflow) so the
        # 2-column card layout never clips under the Command Matrix.
        scroll = FitScrollArea()
        scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        self._grid = QGridLayout(host)
        self._grid.setSpacing(10)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)
        self._scroll = scroll

        # Build the four cards. Order matches the ADB workflow:
        #   wide:   row 0: Device Tools | Apps & Files
        #           row 1: Server & Net  | Power
        #   narrow: single column, same reading order
        # Device Tools (device-info commands) first, Power (reboots) last.
        self._build_device_tools_card()
        self._build_apps_files_card()
        self._build_server_net_card()
        self._build_power_card()

        # Each card now ends in an elastic spacer: when the card is stretched
        # to the section's shared height, the slack lands below the buttons so
        # title/description/buttons stay anchored at the top (no button stretch).
        for card in self._cards:
            card.append_bottom_spacer()

        # Hook the scroll area's viewport so we reflow exactly when the visible
        # width changes — not when AdbView itself resizes (which can be before
        # Qt has propagated the new size down to the viewport).
        scroll.viewport().installEventFilter(self)

    def _add_card(self, card) -> None:
        self._cards.append(card)

    def _reflow_grid(self, force: bool = False) -> None:
        """Place cards in the grid according to the current viewport width.

        Switches between 2-column (wide) and 1-column (narrow) layouts when
        the view crosses REFLOW_THRESHOLD px. The reflow is a no-op when the
        column count hasn't changed — this keeps resize overhead minimal.

        Uses the FitScrollArea's viewport width rather than self.width() because
        the grid lives inside the scroll area's host widget which is sized to the
        viewport, not to the outer page widget.
        """
        if self._scroll is not None:
            vw = self._scroll.viewport().width()
        else:
            vw = self.width()
        cols = 2
        if not force and cols == self._current_cols:
            return
        self._current_cols = cols

        # Remove every card from the grid without destroying it.
        for card in self._cards:
            self._grid.removeWidget(card)
            card.setMinimumHeight(0)  # reset equalization

        # Clear column stretches and set new ones.
        for c in range(2):
            self._grid.setColumnStretch(c, 0)
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)

        # Re-insert cards in reading order.
        for i, card in enumerate(self._cards):
            if cols == 2:
                self._grid.addWidget(card, i // 2, i % 2)
            else:
                self._grid.addWidget(card, i, 0)

    def eventFilter(self, obj, event):
        """Reflow cards when the scroll viewport actually changes size."""
        from PySide6.QtCore import QEvent
        if obj is self._scroll.viewport() and event.type() == QEvent.Resize:
            self._reflow_grid()
            QTimer.singleShot(0, lambda: equalize_card_heights(self._cards) if self._current_cols == 2 else None)
        return super().eventFilter(obj, event)


    def showEvent(self, event):
        """Reflow cards (initial or after tab-switch) and re-equalize heights."""
        super().showEvent(event)
        # Defer so Qt has finished laying out the scroll area and the viewport
        # has its real width before we decide 1-col vs 2-col.
        QTimer.singleShot(0, self._do_initial_reflow)

    def _do_initial_reflow(self):
        self._reflow_grid(force=(self._current_cols == 0))
        if self._current_cols == 2:
            equalize_card_heights(self._cards)

    def resizeEvent(self, event):
        """Reflow and re-equalize when the window is resized (fallback path).
        The viewport eventFilter is the primary trigger; this catches edge cases
        where AdbView resizes but the viewport event hasn't fired yet."""
        super().resizeEvent(event)
        # Use singleShot so the viewport has settled before we measure it.
        QTimer.singleShot(0, self._do_resize_reflow)

    def _do_resize_reflow(self):
        prev_cols = self._current_cols
        self._reflow_grid()
        if self._current_cols == 2:
            equalize_card_heights(self._cards)
        elif prev_cols == 2:
            for card in self._cards:
                card.setMinimumHeight(0)

    # ---------------------------------------------------------------------
    # Card: Power (reboot submenu — no longer a hidden toggle, always visible)
    # ---------------------------------------------------------------------

    def _build_power_card(self) -> None:
        card = ActionCard("Power", "Reboot the connected device", columns=2)
        self._reboot_btn(card, "System", "Reboot to Android OS",
                         lambda: self._adb(["reboot"], "Reboot System"))
        self._reboot_btn(card, "Bootloader", "Reboot to bootloader/fastboot",
                         lambda: self._adb(["reboot", "bootloader"],
                                           "Reboot Bootloader"))
        self._reboot_btn(card, "Recovery", "Reboot to recovery mode",
                         lambda: self._adb(["reboot", "recovery"],
                                           "Reboot Recovery"))
        # EDL is destructive — danger styling + confirm.
        btn_edl = self._mk_button("EDL", "danger",
                                  "DANGEROUS: reboot to emergency download")
        btn_edl.clicked.connect(self._reboot_edl)
        card.add_button(btn_edl)
        self._add_card(card)

    # ---------------------------------------------------------------------
    # Card: Apps & Files
    # ---------------------------------------------------------------------

    def _build_apps_files_card(self) -> None:
        card = ActionCard("Apps & Files", "Install, transfer, sideload",
                          columns=2)
        self._action_btn(card, "Install APK", "Select and install an APK",
                         self.install_apk)
        self._action_btn(card, "Uninstall APK", "Uninstall a package",
                         self.uninstall_apk)
        self._action_btn(card, "Sideload ZIP", "Sideload an update ZIP",
                         self.adb_sideload)
        self._action_btn(card, "Install Magisk", "Install bundled Magisk.apk",
                         self.install_magisk, variant="tonal")
        self._action_btn(card, "Push File", "Push a file to the device",
                         self.adb_push)
        self._action_btn(card, "Pull File", "Pull a file from the device",
                         self.adb_pull)
        self._add_card(card)

    # ---------------------------------------------------------------------
    # Card: Server & Network
    # ---------------------------------------------------------------------

    def _build_server_net_card(self) -> None:
        card = ActionCard("Server & Network", "ADB server & wireless",
                          columns=2)
        self._action_btn(card, "Start Server", "Start the ADB server",
                         lambda: self._adb(["start-server"], "Start Server"))
        self._action_btn(card, "Kill Server", "Kill the ADB server",
                         lambda: self._adb(["kill-server"], "Kill Server"))
        self._action_btn(card, "Get Serial", "Print device serial number",
                         lambda: self._adb(["get-serialno"], "Get Serialno"))
        self._action_btn(card, "TCP/IP 5555",
                         "Restart adbd listening on TCP 5555",
                         lambda: self._adb(["tcpip", "5555"], "TCP/IP 5555"))
        self._action_btn(card, "Connect", "Connect to a device over Wi-Fi",
                         self.adb_connect, variant="tonal")
        self._add_card(card)

    # ---------------------------------------------------------------------
    # Card: Device Tools
    # ---------------------------------------------------------------------

    def _build_device_tools_card(self) -> None:
        card = ActionCard("Device Tools", "Shell, mirroring, low-level ops",
                          columns=2)
        self._action_btn(card, "List Devices", "List connected ADB devices",
                         lambda: self._adb(["devices"], "List Devices"))
        self._action_btn(card, "Open Shell", "Open an interactive shell",
                         self._open_shell)
        self._action_btn(card, "Start Scrcpy", "Mirror the device screen",
                         self.start_scrcpy, variant="tonal")
        self._action_btn(card, "Reset EFS",
                         "DANGEROUS: wipe EFS partitions (root)",
                         self.reset_efs, variant="danger")
        self._action_btn(card, "Enable Diag",
                         "Enable Qualcomm diag mode (root)",
                         self.enable_diag_mode, variant="danger")
        self._action_btn(card, "Custom Command",
                         "Run an arbitrary adb command",
                         self.custom_command, variant="outlined")
        self._add_card(card)

    # =====================================================================
    # Button factory helpers
    # =====================================================================

    def _mk_button(self, text: str, variant: str = "",
                   tip: str = "") -> QPushButton:
        btn = QPushButton(text)
        if variant:
            btn.setProperty("variant", variant)
        if tip:
            btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _action_btn(self, card: ActionCard, text: str, tip: str,
                    handler, variant: str = "") -> None:
        btn = self._mk_button(text, variant, tip)
        btn.clicked.connect(handler)
        card.add_button(btn)

    def _reboot_btn(self, card: ActionCard, text: str, tip: str,
                    handler, variant: str = "") -> None:
        self._action_btn(card, text, tip, handler, variant)

    # =====================================================================
    # Thin executor wrappers (match legacy arg lists exactly)
    # =====================================================================

    def _adb(self, args: list, task_name: str) -> None:
        self.executor.run_command_threaded("adb", args, task_name=task_name)

    def _open_shell(self) -> None:
        self.executor.run_command_threaded(
            "adb", ["shell"], is_shell=True, task_name="Open Shell")

    def _reboot_edl(self) -> None:
        """EDL reboot is destructive — confirm first."""
        from ..widgets import dialogs
        if dialogs.confirm(
            self, "Confirm EDL Reboot",
            "Rebooting to EDL (emergency download) mode can be risky.\n"
            "Only proceed if you know how to recover from EDL. Continue?",
            danger=True,
        ):
            self._adb(["reboot", "edl"], "Reboot EDL")

    # =====================================================================
    # Action handlers (ported 1:1 from pixelkit/gui/app.py)
    # =====================================================================

    def install_apk(self) -> None:
        path = dialogs.pick_open_file(
            self, "Select APK file",
            [("Android Package", "*.apk"), ("All files", "*.*")])
        if path:
            self._adb(["install", path], "Install APK")

    def uninstall_apk(self) -> None:
        pkg = dialogs.prompt_text(
            self, "Uninstall APK", "Enter package name to uninstall:")
        if pkg:
            self._adb(["uninstall", pkg], "Uninstall APK")

    def adb_sideload(self) -> None:
        path = dialogs.pick_open_file(
            self, "Select ZIP file",
            [("ZIP Archive", "*.zip"), ("All files", "*.*")])
        if path:
            self._adb(["sideload", path], "Sideload ZIP")

    def install_magisk(self) -> None:
        magisk = self.app_config.platform_tools_dir / "Magisk.apk"
        if magisk.exists():
            self._adb(["install", str(magisk.absolute())], "Install Magisk")
        else:
            dialogs.error(self, "File Not Found",
                          "Magisk.apk not found in platform-tools.")

    def adb_push(self) -> None:
        path = dialogs.pick_open_file(self, "Select file to push", [("All files", "*.*")])
        if not path:
            return
        dest = dialogs.prompt_text(
            self, "Push File", "Enter remote destination path:",
            default="/sdcard/")
        if dest:
            self._adb(["push", path, dest], "Push File")

    def adb_pull(self) -> None:
        remote = dialogs.prompt_text(
            self, "Pull File",
            "Enter remote file path to pull (e.g., /sdcard/file.txt):")
        if not remote:
            return
        dest = dialogs.pick_save_file(
            self, "Save as", default_name=os.path.basename(remote))
        if dest:
            self._adb(["pull", remote, dest], "Pull File")

    def adb_connect(self) -> None:
        addr = dialogs.prompt_text(
            self, "ADB Connect",
            "Enter IP address and port (e.g., 192.168.1.5:5555):")
        if addr:
            self._adb(["connect", addr], "Connect")

    def start_scrcpy(self) -> None:
        scrcpy = self.executor.cached_paths.get("scrcpy")
        if not scrcpy:
            dialogs.error(self, "File Not Found",
                          "scrcpy was not found in platform-tools.")
            return

        # scrcpy shells out to `adb` to push its server and forward the video
        # socket. By default it uses whatever `adb` is on the system PATH — and
        # if that differs in version from the adb the app polls with (the
        # bundled platform-tools one), the two fight over the single adb server:
        # scrcpy starts its server, the device monitor's adb kills+restarts a
        # different-version server 2s later, and scrcpy's connection drops
        # ("Device disconnected"). Force scrcpy onto the SAME bundled adb via
        # the ADB env var so both sides share one server version.
        env = os.environ.copy()
        adb = self.executor.cached_paths.get("adb")
        if adb:
            env["ADB"] = adb
        # Run from platform-tools so scrcpy always finds its co-located
        # scrcpy-server, regardless of the app's working directory.
        cwd = os.path.dirname(scrcpy)
        subprocess.Popen([scrcpy], creationflags=WIN_CREATION_FLAGS,
                         env=env, cwd=cwd)

    def reset_efs(self) -> None:
        if not dialogs.confirm(
            self, "Confirm EFS Reset",
            "WARNING: This is a dangerous operation that wipes EFS partitions. "
            "Are you sure you want to continue?",
            danger=True,
        ):
            return
        commands = [
            ["adb", "shell", "su", "-c",
             "dd if=/dev/zero of=/dev/block/bootdevice/by-name/modemst1"],
            ["adb", "shell", "su", "-c",
             "dd if=/dev/zero of=/dev/block/bootdevice/by-name/modemst2"],
            ["adb", "shell", "su", "-c",
             "dd if=/dev/zero of=/dev/block/bootdevice/by-name/fsg"],
        ]
        self.executor.run_multiple_commands(commands, task_name="Reset EFS")

    def enable_diag_mode(self) -> None:
        if not dialogs.confirm(
            self, "Enable Diag Mode",
            "This feature is intended only for rooted Qualcomm Snapdragon "
            "devices with full root access.\n\nPlease ensure your device is "
            "properly rooted before enabling DIAG mode.\nProceed at your own risk.",
            danger=True,
        ):
            return
        commands = [
            ["adb", "shell", "su", "-c", "resetprop ro.bootmode usbradio"],
            ["adb", "shell", "su", "-c", "resetprop ro.build.type userdebug"],
            ["adb", "shell", "su", "-c",
             "setprop sys.usb.config diag,diag_mdm,adb"],
            ["adb", "shell", "su", "-c", "diag_mdlog"],
        ]
        self.executor.run_multiple_commands(commands, task_name="Enable Diag Mode")

    def custom_command(self) -> None:
        """Free-form adb/fastboot command. Runs fastboot if explicitly requested."""
        import shlex
        raw = dialogs.prompt_text(
            self, "Custom ADB Command",
            "Enter an adb command (the 'adb' prefix is optional):",
            default="adb ")
        if not raw:
            return
        parts = shlex.split(raw)
        if not parts:
            return

        tool = "adb"
        if parts[0].lower() == "adb":
            tool = "adb"
            parts = parts[1:]
        elif parts[0].lower() == "fastboot":
            tool = "fastboot"
            parts = parts[1:]

        if not parts:
            return
        self.executor.run_command_threaded(tool, parts, task_name=f"Custom: {tool} {' '.join(parts[:2])}")

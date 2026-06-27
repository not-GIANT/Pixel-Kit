"""Fastboot operations view — M3 grouped action cards over the same executor.

Mirrors the legacy Fastboot tab: 15 actions regrouped into 4 cards:
  - Bootloader   (unlock / lock, with flashing-vs-oem variant chooser)
  - Power        (reboot submenu: System / Bootloader / Fastbootd / Recovery)
  - Maintenance  (erase cache, erase FRP, wipe data)
  - Device       (list devices, getvar all, oem device-info, set_active other,
                  boot image, custom command)

Every handler delegates to self.executor exactly as the legacy tab did — same
commands, same argument lists, same variant chooser for lock/unlock.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QPushButton,
                               QGridLayout, QScrollArea, QVBoxLayout, QWidget)

from ..widgets import (ActionCard, FitScrollArea, SectionTitle, dialogs,
                       equalize_card_heights)


class FastbootView(QWidget):
    """The Fastboot operations page."""

    def __init__(self, executor, app_config, parent=None):
        super().__init__(parent)
        self.executor = executor
        self.app_config = app_config
        # All ActionCards in this section, tracked so we can equalize their
        # heights after layout (tallest card wins → every card the same height,
        # borders aligned across the whole grid, not just per row).
        self._cards: list = []
        self._build_ui()

    # =====================================================================
    # Layout
    # =====================================================================

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        outer.addWidget(SectionTitle("Fastboot Operations"))

        # FitScrollArea forces the card grid to reflow against the visible
        # viewport width so the 2-column layout never overflows/clips.
        scroll = FitScrollArea()
        scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        self._grid = QGridLayout(host)
        self._grid.setSpacing(10)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        # Card order reflects the fastboot workflow: device-info commands first,
        # then the most-used operations (Maintenance, Power), with the
        # destructive Bootloader lock/unlock card last. 2-column reading order:
        #   row 0: Device | Maintenance
        #   row 1: Power   | Bootloader
        self._build_device_card(0, 0)
        self._build_maintenance_card(0, 1)
        self._build_power_card(1, 0)
        self._build_bootloader_card(1, 1)

        # Each card now ends in an elastic spacer: when the card is stretched
        # to the section's shared height, the slack lands below the buttons so
        # title/description/buttons stay anchored at the top (no button stretch).
        for card in self._cards:
            card.append_bottom_spacer()

    def _add_card(self, card, row: int, col: int) -> None:
        # NOTE: no Qt.AlignTop — a top alignment would clamp the cell to the
        # card's natural height and defeat the section-wide height equalization
        # (the card must be free to fill the cell vertically to match siblings).
        self._grid.addWidget(card, row, col)
        self._cards.append(card)

    def showEvent(self, event):
        """Re-equalize card heights once the cards have been laid out and know
        their real size hints. Re-run on every show so a theme toggle / window
        resize (which can change text wrapping and thus card heights) keeps the
        borders aligned."""
        super().showEvent(event)
        QTimer.singleShot(0, lambda: equalize_card_heights(self._cards))

    def resizeEvent(self, event):
        """Re-equalize card heights when the window is resized to adapt to new
        text wrapping and layout constraints."""
        super().resizeEvent(event)
        equalize_card_heights(self._cards)



    # ---------------------------------------------------------------------
    # Card: Bootloader (lock/unlock with variant chooser)
    # ---------------------------------------------------------------------

    def _build_bootloader_card(self, row: int, col: int) -> None:
        card = ActionCard("Bootloader", "Lock or unlock (wipes data)",
                          columns=2)
        self._action_btn(card, "Unlock", "Unlock bootloader (wipes data)",
                         lambda: self._prompt_bootloader_action("unlock"),
                         variant="tonal")
        self._action_btn(card, "Lock", "Lock bootloader",
                         lambda: self._prompt_bootloader_action("lock"))
        self._add_card(card, row, col)

    # ---------------------------------------------------------------------
    # Card: Power (reboot submenu)
    # ---------------------------------------------------------------------

    def _build_power_card(self, row: int, col: int) -> None:
        card = ActionCard("Power", "Reboot the connected device", columns=2)
        self._action_btn(card, "System", "Reboot to Android OS",
                         lambda: self._fb(["reboot"], "Reboot System"))
        self._action_btn(card, "Bootloader", "Reboot back to bootloader",
                         lambda: self._fb(["reboot", "bootloader"],
                                           "Reboot Bootloader"))
        self._action_btn(card, "Fastbootd", "Reboot to fastbootd mode",
                         lambda: self._fb(["reboot", "fastboot"],
                                           "Reboot Fastbootd"))
        self._action_btn(card, "Recovery", "Reboot to recovery mode",
                         lambda: self._fb(["reboot", "recovery"],
                                           "Reboot Recovery"))
        self._add_card(card, row, col)

    # ---------------------------------------------------------------------
    # Card: Maintenance
    # ---------------------------------------------------------------------

    def _build_maintenance_card(self, row: int, col: int) -> None:
        card = ActionCard("Maintenance", "Wipes & partition erasures",
                          columns=2)
        self._action_btn(card, "Erase Cache", "Erase the cache partition",
                         lambda: self._fb(["erase", "cache"], "Erase Cache"))
        self._action_btn(card, "Erase FRP",
                         "Erase Factory Reset Protection partition",
                         lambda: self._fb(["erase", "frp"], "Erase FRP"),
                         variant="tonal")
        self._action_btn(card, "Wipe Data", "Wipe user data and cache (-w)",
                         lambda: self._confirm_wipe(),
                         variant="danger")
        self._add_card(card, row, col)

    # ---------------------------------------------------------------------
    # Card: Device
    # ---------------------------------------------------------------------

    def _build_device_card(self, row: int, col: int) -> None:
        card = ActionCard("Device", "Info, slots, boot image", columns=2)
        self._action_btn(card, "List Devices", "List connected fastboot devices",
                         lambda: self._fb(["devices"], "List Devices"))
        self._action_btn(card, "Get Info", "fastboot getvar all",
                         lambda: self._fb(["getvar", "all"], "Get Device Info"),
                         variant="tonal")
        self._action_btn(card, "OEM Info", "fastboot oem device-info",
                         lambda: self._fb(["oem", "device-info"],
                                           "OEM Device Info"))
        self._action_btn(card, "Set Active Other",
                         "Switch to the other A/B slot",
                         lambda: self._fb(["set_active", "other"],
                                           "Switch A/B Slot"))
        self._action_btn(card, "Boot Image",
                         "Temporarily boot from a selected .img",
                         self.fastboot_boot, variant="tonal")
        self._action_btn(card, "Custom Command",
                         "Run an arbitrary fastboot command",
                         self.custom_command, variant="outlined")
        self._add_card(card, row, col)

    # =====================================================================
    # Button factory helpers
    # =====================================================================

    def _mk_button(self, text: str, variant: str = "", tip: str = "") -> QPushButton:
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

    # =====================================================================
    # Executor wrapper
    # =====================================================================

    def _fb(self, args: list, task_name: str) -> None:
        self.executor.run_command_threaded("fastboot", args, task_name=task_name)

    # =====================================================================
    # Action handlers (ported from pixelkit/gui/app.py)
    # =====================================================================

    def _prompt_bootloader_action(self, action: str) -> None:
        """Choose between `flashing <action>` (modern/Pixel) and `oem <action>`
        (legacy). Ported from the legacy variant-chooser popup.

        Modern/Pixel devices and anything running Android 10+ use
        `fastboot flashing <unlock|lock>`; older devices use `fastboot oem`.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{action.capitalize()} Bootloader")
        dlg.resize(480, 200)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            f"Choose command version to {action} the bootloader:"))

        def run_flashing():
            dlg.accept()
            self._fb(["flashing", action],
                     f"{action.capitalize()} Bootloader (flashing)")

        def run_oem():
            dlg.accept()
            self._fb(["oem", action],
                     f"{action.capitalize()} Bootloader (oem)")

        btn_frame = QGridLayout()
        btn_frame.setSpacing(8)
        b1 = QPushButton("fastboot flashing " + action + "\n(Modern / Pixel)")
        b1.setProperty("variant", "filled")
        b1.setToolTip("Use for Pixel and modern devices (Android 10+)")
        b1.clicked.connect(run_flashing)
        btn_frame.addWidget(b1, 0, 0)

        b2 = QPushButton("fastboot oem " + action + "\n(Legacy / Other)")
        b2.setProperty("variant", "tonal")
        b2.setToolTip("Use for older devices")
        b2.clicked.connect(run_oem)
        btn_frame.addWidget(b2, 0, 1)
        layout.addLayout(btn_frame)

        cancel = QPushButton("Cancel")
        cancel.setProperty("variant", "text")
        cancel.clicked.connect(dlg.reject)
        layout.addWidget(cancel, alignment=Qt.AlignRight)

        dlg.exec()

    def _confirm_wipe(self) -> None:
        """Wipe data (-w) is destructive — confirm first."""
        if dialogs.confirm(
            self, "Confirm Wipe Data",
            "fastboot -w will wipe all user data and cache on the device.\n"
            "This cannot be undone. Continue?",
            danger=True,
        ):
            self._fb(["-w"], "Wipe Data")

    def fastboot_boot(self) -> None:
        """Temporarily boot from a .img without flashing."""
        path = dialogs.pick_open_file(
            self, "Select Boot Image",
            [("Image File", "*.img"), ("All files", "*.*")])
        if path:
            self._fb(["boot", path], "Boot Image")

    def custom_command(self) -> None:
        """Free-form fastboot command. 'fastboot' prefix is stripped if present."""
        import shlex
        raw = dialogs.prompt_text(
            self, "Custom Fastboot Command",
            "Enter a fastboot command (the 'fastboot' prefix is optional):",
            default="fastboot ")
        if not raw:
            return
        parts = shlex.split(raw)
        if not parts:
            return
        if parts[0].lower() in ("adb", "fastboot"):
            parts = parts[1:]
        if not parts:
            return
        self._fb(parts, f"Custom: {' '.join(parts[:3])}")

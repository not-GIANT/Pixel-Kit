"""Device status card — M3 outlined card showing live device info.

Replaces the old CTk device-info row (4 plain "Model: N/A" labels in a row).
Shows a connection-state chip, device model, serial, Android version, battery
level. Empty state when disconnected. Updates from DeviceMonitor via the
bridge's device_status signal.

The connection-state chip is fully theme-aware: its colors are derived from
M3 scheme roles (error / tertiary / a green-ish "ok" tint), never hardcoded.
`update_colors()` re-applies the *current* chip state on every theme change so
both light and dark modes read correctly.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..theme import stylesheet


def _chip_style(fg_hex: str, bg_rgba: str) -> str:
    return (f"padding: 4px 12px; border-radius: 8px; "
            f"background-color: {bg_rgba}; color: {fg_hex};")


class DeviceCard(QFrame):
    """M3 outlined card summarizing the connected device's state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("card", True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Current chip state — re-applied on theme change. One of:
        # "disconnected" / "adb" / "fastboot".
        self._chip_state = "disconnected"
        self._scheme: dict = {}

        # Compact layout: the card only needs to show the status chip + the four
        # device fields. Two detail rows (a 2×2 key/value grid) hold all of
        # Model/Serial/Android/Battery inline instead of stacking four tall
        # rows, so the card shrinks to the height its content needs.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(4)

        # Header row: title + connection chip
        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel("Device")
        title.setProperty("role", "label-l")
        top.addWidget(title)
        top.addStretch()

        self._chip = QLabel("Disconnected")
        self._chip.setProperty("role", "label-m")
        self._chip.setAlignment(Qt.AlignCenter)
        top.addWidget(self._chip)
        layout.addLayout(top)

        # Detail grid: 2 columns × 2 rows — Model/Serial on the top line,
        # Android/Battery on the next. Keeps every field visible without the
        # card growing tall.
        details = QGridLayout()
        details.setHorizontalSpacing(24)
        details.setVerticalSpacing(2)
        self._row_model = self._detail_cell(details, 0, 0, "Model", "—")
        self._row_serial = self._detail_cell(details, 0, 1, "Serial", "—")
        self._row_android = self._detail_cell(details, 1, 0, "Android", "—")
        self._row_battery = self._detail_cell(details, 1, 1, "Battery", "—")
        layout.addLayout(details)

    def _detail_cell(self, grid: QGridLayout, row: int, col: int,
                     key: str, value: str):
        """A caption/value pair placed in a grid cell (key stacked over value).

        Returns the (key_label, value_label) tuple so the controller can update
        the value label without touching the layout.
        """
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        k = QLabel(key)
        k.setProperty("role", "caption")
        v = QLabel(value)
        v.setProperty("role", "body")
        box.addWidget(k)
        box.addWidget(v)
        # Wrap the cell's column layout in a QWidget so it sits in the grid.
        host = QWidget()
        host.setLayout(box)
        grid.addWidget(host, row, col)
        return (k, v)

    # --- public API ---

    @Slot(object)
    def update_device(self, device_info) -> None:
        """Populate fields from a DeviceInfo object (or None for disconnected).

        DeviceInfo.is_connected is driven by `status` ("Disconnected" → False).
        The monitor stores the mode on `connection_type` ("ADB"/"Fastboot"),
        and `battery_level` is already a formatted string ("85%" or "N/A"), so
        we must not append another "%" here.
        """
        if device_info is None or not getattr(device_info, "is_connected", False):
            self._set_disconnected()
            return
        model = getattr(device_info, "model", None)
        if not model or model == "N/A":
            model = "Unknown"
        serial = getattr(device_info, "serial", None)
        serial = serial if serial and serial != "N/A" else "—"
        android = getattr(device_info, "android_version", None)
        android = android if android and android != "N/A" else "—"
        battery = getattr(device_info, "battery_level", None)
        battery_str = battery if battery and battery != "N/A" else "—"

        self._row_model[1].setText(str(model))
        self._row_serial[1].setText(str(serial))
        self._row_android[1].setText(str(android))
        self._row_battery[1].setText(str(battery_str))

        # Mode-aware chip: tertiary for fastboot, a green "ok" tint for adb.
        if getattr(device_info, "is_fastboot", False) or \
                getattr(device_info, "connection_type", "") == "Fastboot":
            self._set_state("fastboot", "Fastboot")
        else:
            self._set_state("adb", "ADB")

    def update_colors(self, scheme: dict) -> None:
        """Re-apply the current chip's colors from the active M3 scheme.

        Called on every theme change. Derives fg/bg from scheme roles so there
        are no hardcoded colors in either light or dark mode.
        """
        self._scheme = scheme
        self._repaint_chip()

    # --- internals ---

    def _set_disconnected(self) -> None:
        for _, v in (self._row_model, self._row_serial,
                     self._row_android, self._row_battery):
            v.setText("—")
        self._set_state("disconnected", "Disconnected")

    def _set_state(self, state: str, text: str) -> None:
        self._chip_state = state
        self._chip.setText(text)
        self._repaint_chip()

    def _repaint_chip(self) -> None:
        """Re-derive + apply chip colors for the current state from the scheme.

        Uses only M3 scheme roles (no hardcoded green/amber), so the chip reads
        correctly in both light and dark modes:
          disconnected → error (red) tint
          adb          → primary (brand) tint — the "connected/active" state
          fastboot     → tertiary (accent) tint — a distinct "other mode" state
        """
        s = self._scheme
        if self._chip_state == "disconnected":
            fg = s.get("on_error_container", s.get("error", "#b00020"))
            container = s.get("error_container", fg)
        elif self._chip_state == "fastboot":
            fg = s.get("on_tertiary_container", "#000000")
            container = s.get("tertiary_container", fg)
        else:  # adb
            fg = s.get("on_primary_container", "#000000")
            container = s.get("primary_container", fg)
        bg = stylesheet.rgba(container, 0.55) \
            if container != fg else stylesheet.rgba(fg, 0.14)
        self._chip.setStyleSheet(_chip_style(fg, bg))

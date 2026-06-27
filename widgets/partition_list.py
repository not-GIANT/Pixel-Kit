"""Searchable, categorized partition list — replaces the 31-button grid.

The legacy UI rendered all 31 partitions as identical green buttons in a 3-col
grid: visually loud, no hierarchy, no way to find one fast. This widget:

- Groups partitions by function (Boot chain / System / Vendor / Radio / Misc)
  via selectable category chips.
- Live-filters by a search box (instant, case-insensitive, substring).
- Renders each partition as a row: name + description + a Flash button, so the
  action is inline rather than a separate dialog step.
- Falls back to "All" when no chip is selected.

The flash action itself is delegated to a callback, keeping this widget
reusable and free of executor coupling.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

# ---------------------------------------------------------------------------
# Partition catalog — name → (category, short description)
# Same 31 partitions as the legacy tab, now annotated for findability.
# Categories double as the chip labels.
# ---------------------------------------------------------------------------
PARTITIONS: list[tuple[str, str, str]] = [
    # Boot chain
    ("boot",         "Boot chain", "Kernel + ramdisk (primary boot image)"),
    ("init_boot",    "Boot chain", "Boot image (Android 13+ split)"),
    ("dtbo",         "Boot chain", "Device-tree overlay"),
    ("recovery",     "Boot chain", "Recovery partition"),
    ("vbmeta",       "Boot chain", "Verified-boot metadata"),
    ("vbmeta_system","Boot chain", "Verified-boot metadata (system)"),
    ("vbmeta_vendor","Boot chain", "Verified-boot metadata (vendor)"),
    # System
    ("system",       "System",     "Android OS (A-only / base of system)"),
    ("product",      "System",     "Product image (preinstalled apps)"),
    ("super",        "System",     "Super partition (dynamic partitions)"),
    ("userdata",     "System",     "User data (wipe target)"),
    ("cust",         "System",     "Carrier/customization partition"),
    # Vendor / SoC
    ("vendor",       "Vendor",     "HALs + vendor modules"),
    ("modem",        "Vendor",     "Modem firmware (radio)"),
    ("abl",          "Vendor",     "Android bootloader (Qualcomm)"),
    ("xbl",          "Vendor",     "Secondary bootloader (Qualcomm)"),
    ("sbl",          "Vendor",     "Secondary bootloader (legacy)"),
    ("devinfo",      "Vendor",     "Device info (bootloader flags)"),
    # Radio / modem (MediaTek)
    ("preloader",    "Radio",      "MTK preloader"),
    ("lk",           "Radio",      "MTK little kernel"),
    ("logo",         "Radio",      "MTK boot logo"),
    ("gz",           "Radio",      "MTK trustzone"),
    ("nvram",        "Radio",      "NVRAM (radio calibration)"),
    ("nvdata",       "Radio",      "NVRAM data"),
    ("md1img",       "Radio",      "MTK modem image"),
    ("tee",          "Radio",      "MTK trust image"),
    # Misc
    ("rescue",       "Misc",       "Rescue party"),
    ("dpm",          "Misc",       "Deep power management"),
    ("scp",          "Misc",       "System control processing"),
    ("spmfw",        "Misc",       "SPM firmware"),
    ("efuse",        "Misc",       "eFuse (OTP — flash with extreme caution)"),
]

CATEGORIES = ["All", "Boot chain", "System", "Vendor", "Radio", "Misc"]


class PartitionRow(QFrame):
    """A single partition: name + description + inline Flash button."""

    flash_requested = Signal(str)  # emits the partition name

    def __init__(self, name: str, description: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PartitionRow")
        self._name = name

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        name_lbl = QLabel(name)
        name_lbl.setProperty("role", "label-m")
        name_lbl.setStyleSheet("font-family: 'Consolas','Cascadia Mono',monospace;")
        name_lbl.setMinimumWidth(110)
        layout.addWidget(name_lbl)

        desc_lbl = QLabel(description)
        desc_lbl.setProperty("role", "caption")
        layout.addWidget(desc_lbl, 1)

        self._btn = QPushButton("Flash")
        self._btn.setProperty("variant", "tonal")
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setToolTip(f"Select a {name}.img and flash it")
        self._btn.clicked.connect(lambda: self.flash_requested.emit(self._name))
        layout.addWidget(self._btn)


class PartitionList(QWidget):
    """Searchable, chip-filtered list of flashable partitions."""

    flash_requested = Signal(str)  # forwarded from rows: partition name

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_category = "All"
        self._rows: list[tuple[PartitionRow, str, str]] = []  # (row, name, category)
        self._build_ui()
        self._populate()

    # =====================================================================
    # UI
    # =====================================================================

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Search box
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search partitions (e.g. boot, vbmeta, modem)…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        # Category chips
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self._chip_buttons: list[QPushButton] = []
        for cat in CATEGORIES:
            chip = QPushButton(cat)
            chip.setCheckable(True)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setObjectName("CategoryChip")
            chip.clicked.connect(lambda _=False, c=cat: self._select_category(c))
            self._chip_buttons.append(chip)
            chips.addWidget(chip)
        chips.addStretch()
        layout.addLayout(chips)

        # Scrollable row list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        self._rows_layout = QVBoxLayout(host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        self._rows_layout.addStretch()
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        # Default chip = All
        self._chip_buttons[0].setChecked(True)

    def _populate(self) -> None:
        for name, category, desc in PARTITIONS:
            row = PartitionRow(name, desc)
            row.flash_requested.connect(self.flash_requested.emit)
            # Insert before the trailing stretch.
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
            self._rows.append((row, name, category))
        self._apply_filter()

    # =====================================================================
    # Filtering
    # =====================================================================

    def _select_category(self, category: str) -> None:
        self._active_category = category
        # Enforce exclusive selection across the chip group.
        for chip in self._chip_buttons:
            chip.setChecked(chip.text() == category)
        self._apply_filter()

    def _apply_filter(self, *_args) -> None:
        needle = self._search.text().strip().lower()
        for row, name, category in self._rows:
            cat_ok = (self._active_category == "All" or category == self._active_category)
            text_ok = (not needle or needle in name.lower())
            row.setVisible(cat_ok and text_ok)

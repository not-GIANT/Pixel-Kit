"""Partition flashing view — searchable list over the same flash_image handler.

Replaces the legacy 31-button green grid with:
  - A persistent (dismissible) safety banner.
  - The PartitionList widget: search box + category chips + annotated rows.
  - Each row's Flash button opens a file dialog and runs
    `fastboot flash <partition> <path>` — identical to the legacy handler.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..theme import stylesheet
from ..widgets import (PartitionList, SectionTitle, dialogs)


class FlashingView(QWidget):
    """The partition-flashing page."""

    def __init__(self, executor, app_config, parent=None):
        super().__init__(parent)
        self.executor = executor
        self.app_config = app_config
        self._scheme: dict = {}
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        outer.addWidget(SectionTitle("Partition Flashing"))

        # Safety banner — dismissible.
        self._banner = self._build_banner()
        outer.addWidget(self._banner)

        # The searchable partition list (the main upgrade).
        self.partition_list = PartitionList()
        self.partition_list.flash_requested.connect(self.flash_partition)
        outer.addWidget(self.partition_list, 1)

    def _build_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("SafetyBanner")
        banner.setProperty("card", True)
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(16, 10, 16, 10)

        text = QLabel(
            "<b>Caution:</b> Flashing the wrong image or partition can brick "
            "the device. Always verify the image matches your model before "
            "flashing. <code>efuse</code> and <code>userdata</code> are "
            "especially destructive.")
        text.setProperty("role", "body")
        text.setWordWrap(True)
        layout.addWidget(text, 1)

        dismiss = QPushButton("Dismiss")
        dismiss.setProperty("variant", "text")
        dismiss.clicked.connect(banner.hide)
        layout.addWidget(dismiss, 0, Qt.AlignTop)
        return banner

    def update_colors(self, scheme: dict) -> None:
        """Re-tint the safety banner from the active M3 scheme (no hardcoded
        colors — uses the error role so it reads correctly in both themes)."""
        self._scheme = scheme
        err = scheme.get("error", "#b00020")
        outline_var = scheme.get("outline_variant", "#cccccc")
        self._banner.setStyleSheet(
            f"QFrame#SafetyBanner {{ "
            f"background-color: {stylesheet.rgba(err, 0.10)}; "
            f"border: 1px solid {stylesheet.rgba(err, 0.35)}; "
            f"border-radius: 12px; }}")

    # =====================================================================
    # Action handler (ported 1:1 from pixelkit/gui/app.py:flash_image)
    # =====================================================================

    def flash_partition(self, partition: str) -> None:
        """Open a file dialog for <partition>.img, then fastboot flash it."""
        path = dialogs.pick_open_file(
            self,
            f"Select {partition.replace('_', ' ')} Image",
            [("Image File", "*.img"), ("All files", "*.*")],
        )
        if path:
            self.executor.run_command_threaded(
                "fastboot", ["flash", partition, path],
                task_name=f"Flash {partition}")

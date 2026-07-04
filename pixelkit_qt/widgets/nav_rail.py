"""M3 Navigation Rail — vertical primary navigation on the left edge.

Replaces the top CTkTabview (ADB/Fastboot/CPID/Flashing). Each rail item is an
icon-over-label button; the selected one shows the M3 "pill" indicator
(second-layer of the active-item container). Switches the QStackedWidget page.

Desktop M3 spec favors a rail over tabs for ~5 top-level destinations because
it frees vertical space for content and reads as more "application-like".
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QFrame, QSizePolicy, QToolButton,
                               QVBoxLayout)


class NavItem(QToolButton):
    """A rail entry: icon stacked above a label (M3 navigation-rail item).

    Uses QToolButton, NOT QPushButton. QPushButton does not support hosting
    child widgets cleanly — it paints over them and checkable state misbehaves
    with embedded layouts, which caused the earlier "glitched" rendering.
    QToolButton natively supports icon-over-label via
    setToolButtonStyle(ToolButtonTextUnderIcon) and works correctly with
    QButtonGroup + setChecked.
    """

    def __init__(self, icon: QIcon, label: str, index: int, symbolic_name: str = "", parent=None):
        super().__init__(parent)
        self.index = index
        self.symbolic_name = symbolic_name
        self.setCheckable(True)
        self.setAutoRaise(True)  # flat by default, raised on hover/check
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("NavItem")
        self.setText(label)
        if icon is not None and not icon.isNull():
            self.setIcon(icon)
        self.setIconSize(QSize(22, 22))
        # Icon-over-label is the M3 navigation-rail item shape.
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setMinimumHeight(58)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class NavRail(QFrame):
    """Vertical navigation rail driving a QStackedWidget."""

    page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavRail")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setFixedWidth(84)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._items: list[NavItem] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 10, 6, 10)
        layout.setSpacing(4)
        layout.addStretch()

    def add_item(self, icon, label: str, symbolic_name: str = "") -> int:
        """Append a destination. `icon` may be a QIcon or None. Returns index."""
        icon_obj = icon if isinstance(icon, QIcon) else QIcon()
        item = NavItem(icon_obj, label, len(self._items), symbolic_name)
        item.clicked.connect(lambda _=False, i=item.index: self.select(i))
        self._group.addButton(item)
        self._items.append(item)
        # Insert before the trailing stretch.
        self.layout().insertWidget(self.layout().count() - 1, item)
        return item.index

    def select(self, index: int) -> None:
        """Programmatically select a page (also fires page_changed)."""
        if 0 <= index < len(self._items):
            self._items[index].setChecked(True)
            self.page_changed.emit(index)

    def update_icons(self) -> None:
        """Reload all navigation rail icons with the current theme colors."""
        from ..theme import icons
        for item in self._items:
            if item.symbolic_name:
                item.setIcon(icons.icon_for(item.symbolic_name))

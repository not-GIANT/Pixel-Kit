"""Icon helpers — zero-dependency icons via Qt's built-in standard icons.

Rather than bundle a Material Symbols font or add qtawesome, we use QStyle's
SP_* standard icons, which render crisply at any DPI and automatically adapt to
the active theme. A consistent fallback (a generic file/document icon) is used
when a requested icon isn't available on the platform.

The nav rail and action buttons consume icons via icon_for("name"), keeping
the mapping in one place so it's trivial to swap the icon set later (e.g. to
Material Symbols if the font is bundled in Phase 5 packaging).
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QPointF, Qt
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter, QPen, QBrush, QPolygonF
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QStyle

# Symbolic name → QStyle.SP_* enum value. Add new mappings here.
_ICON_MAP = {
    # Navigation destinations
    "nav-adb":      QStyle.SP_ComputerIcon,        # device / computer
    "nav-fastboot": QStyle.SP_BrowserReload,        # reboot/refresh feel
    "nav-flashing": QStyle.SP_DriveHDIcon,          # disk / partition
    "nav-firmware": QStyle.SP_DriveFDIcon,           # firmware image / media
    "nav-cpid":     QStyle.SP_FileDialogContentsView,  # detailed repair view
    # Common actions
    "refresh":      QStyle.SP_BrowserReload,
    "play":         QStyle.SP_MediaPlay,
    "stop":         QStyle.SP_MediaStop,
    "pause":        QStyle.SP_MediaPause,
    "save":         QStyle.SP_DialogSaveButton,
    "open":         QStyle.SP_DialogOpenButton,
    "ok":           QStyle.SP_DialogOkButton,
    "cancel":       QStyle.SP_DialogCancelButton,
    "warn":         QStyle.SP_MessageBoxWarning,
    # Directions
    "arrow-up":     QStyle.SP_ArrowUp,
    "arrow-down":   QStyle.SP_ArrowDown,
    "arrow-right":  QStyle.SP_ArrowRight,
}

# Fallback when a name isn't in the map or the platform lacks it.
_FALLBACK = QStyle.SP_FileIcon


def draw_social_icon(name: str, color_hex: str, size: int = 20) -> QIcon:
    """Draw social media icons dynamically with high-quality QPainter vectors."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    color = QColor(color_hex)
    pen = QPen(color)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)

    # Scale coordinate system to [0, 20]
    painter.scale(size / 20.0, size / 20.0)

    if name == "email":
        # Envelope icon
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.drawRect(2, 4, 16, 12)
        painter.drawLine(2, 4, 10, 10)
        painter.drawLine(10, 10, 18, 4)

    elif name == "github":
        # GitHub Octocat representation
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.setBrush(QBrush(color))
        # Head
        painter.drawEllipse(4, 5, 12, 11)
        # Ears
        ear_l = QPolygonF([QPointF(5, 6), QPointF(4, 2), QPointF(7, 5)])
        ear_r = QPolygonF([QPointF(15, 6), QPointF(16, 2), QPointF(13, 5)])
        painter.drawPolygon(ear_l)
        painter.drawPolygon(ear_r)
        # Tentacles / base chord
        painter.drawChord(6, 14, 8, 4, 0, 180 * 16)

    elif name == "tiktok":
        # TikTok musical note 'd' logo representation
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        # Head of the note
        painter.drawEllipse(5, 10, 6, 6)
        # Stem
        painter.drawLine(11, 4, 11, 13)
        # Hook/Flag at top
        painter.drawArc(11, 1, 6, 6, 90 * 16, 90 * 16)

    elif name == "twitter / x":
        # The 'X' logo
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.drawLine(3, 3, 17, 17)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawLine(17, 3, 3, 17)

    elif name == "instagram":
        # Instagram camera
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(3, 3, 14, 14, 4, 4)
        painter.drawEllipse(7, 7, 6, 6)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(13, 5, 2, 2)
    else:
        painter.end()
        return QIcon()

    painter.end()
    icon = QIcon()
    icon.addPixmap(pixmap)
    return icon


# ---------------------------------------------------------------------------
# Material Design SVG icon files for navigation rail destinations.
# Each .svg in nav_icons/ uses fill="currentColor" so we can inject any color
# at render-time without modifying the file.
# ---------------------------------------------------------------------------
_NAV_ICONS_DIR = __file__.replace("icons.py", "nav_icons")


def draw_nav_icon_pixmap(name: str, color_hex: str, size: int) -> QPixmap:
    """Load a per-icon SVG file, inject the theme color, and render to a pixmap.

    SVG files live in pixelkit_qt/theme/nav_icons/<name>.svg and use
    fill="currentColor" as their fill placeholder. We do a simple string
    replace so the rendered result matches the active M3 color exactly.
    QSvgRenderer handles anti-aliasing and scaling — the output is crisp
    at any DPI.
    """
    import os
    svg_path = os.path.join(_NAV_ICONS_DIR, f"{name}.svg")
    if not os.path.isfile(svg_path):
        return QPixmap()

    with open(svg_path, "r", encoding="utf-8") as f:
        svg_text = f.read()

    # Inject theme color: replace the fill="currentColor" placeholder.
    colored_svg = svg_text.replace("currentColor", color_hex)

    svg_bytes = QByteArray(colored_svg.encode("utf-8"))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    renderer = QSvgRenderer(svg_bytes)
    if not renderer.isValid():
        return QPixmap()
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    return pixmap


def icon_for(name: str, size: int = 24, color: str | None = None) -> QIcon:
    """Return a QIcon for the symbolic name, themed for the current style."""
    if name.startswith("social-"):
        social_name = name[7:].lower()
        if color is None:
            from ._state import active_scheme
            scheme = active_scheme()
            color = scheme.get("on_primary_container", "#ffffff") if scheme else "#ffffff"
        return draw_social_icon(social_name, color, size)

    if name.startswith("nav-"):
        from ._state import active_scheme
        scheme = active_scheme()
        normal_color = scheme.get("on_surface_variant", "#888888") if scheme else "#888888"
        active_color = scheme.get("primary", "#0061e6") if scheme else "#0061e6"
        
        pix_normal = draw_nav_icon_pixmap(name, normal_color, size)
        pix_active = draw_nav_icon_pixmap(name, active_color, size)
        
        icon = QIcon()
        icon.addPixmap(pix_normal, QIcon.Normal, QIcon.Off)
        icon.addPixmap(pix_active, QIcon.Normal, QIcon.On)
        icon.addPixmap(pix_active, QIcon.Active, QIcon.Off)
        icon.addPixmap(pix_active, QIcon.Active, QIcon.On)
        return icon

    app = QApplication.instance()
    if app is None:
        return QIcon()
    style = app.style()
    enum = _ICON_MAP.get(name, _FALLBACK)
    icon = style.standardIcon(enum)
    if icon.isNull():
        icon = style.standardIcon(_FALLBACK)
    return icon


def window_icon_from_png(png_path) -> QIcon:
    """Build a window icon from a PNG file (any resolution)."""
    if not png_path:
        return QIcon()
    # QPixmap loads the PNG; QIcon auto-scales it for each required size.
    pix = QPixmap(str(png_path))
    if pix.isNull():
        return QIcon()
    icon = QIcon()
    icon.addPixmap(pix)
    return icon

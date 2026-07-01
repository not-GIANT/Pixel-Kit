"""Rich, theme-aware About dialog — matches the legacy tool's depth.

Three tabs over the same M3 design language as the rest of the app:
  - Features         : grouped capability lists.
  - Changelog        : scrollable, version-by-version history.
  - Contact & Support: clickable links to every support channel.

Plus an Application Information header (name / version / build / copyright).

All colors come from the active M3 stylesheet (tabs, buttons, links already
styled in theme/stylesheet.py) or from the QApplication palette, so the dialog
re-skins correctly on light/dark toggle with zero hardcoded colors.

Contact channels mirror the legacy tool (Email, TikTok, Twitter/X, Instagram)
with the corrected email address; GitHub is included from the Qt migration.
"""
from __future__ import annotations

import sys
import webbrowser
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QScrollArea, QTabWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from ..theme import icons, stylesheet, tokens

# ---------------------------------------------------------------------------
# Application identity (single source of truth — keep in sync with app.py)
# ---------------------------------------------------------------------------
APP_NAME = "Pixel Kit"
APP_VERSION = "v3.8 (Qt/M3)"
APP_BUILD = (
    f"PySide6 / Material 3 rebuild \u00b7 Python {sys.version.split()[0]}")
APP_COPYRIGHT = "\u00a9 2026 GIANT. All rights reserved."
APP_TAGLINE = (
    "A modern GUI toolkit for ADB &amp; Fastboot \u2014 complex Android "
    "operations, one click away.")

# ---------------------------------------------------------------------------
# Features content (legacy structure, expanded to the requested categories)
# ---------------------------------------------------------------------------
# (category, accent_role, icon_name, [bullets])
# accent_role ∈ M3 container-role names — each card header is tinted from the
# live scheme so the categories read as color-coded but stay theme-coherent.
FEATURES: list[tuple[str, str, str, list[str]]] = [
    ("CPID Operations", "primary_container", "open", [
        "One-click ADB & Fastboot driver installer",
        "Automatic mode: detects and installs required drivers silently",
        "Manual mode: browse and install driver packages manually",
    ]),
    ("Driver Management", "primary_container", "open", [
        "IMEI repair for Pixel 7, 8 & 9 series (10-step automated workflow)",
        "8-step Pixel 10 Series CPID repair: detect, backup, patch, flash, AT, modem, SHA, finalize",
        "Secure NVRAM sync via persistent root shell",
        "Legal safety gates and pre-flight root checks",
        "Firmware prerequisites warning before any repair runs",
    ]),
    ("Device Detection", "tertiary_container", "refresh", [
        "Intelligent two-tier device polling (cheap connect probe + on-change property fetch)",
        "Live status chip: Disconnected / ADB / Fastboot",
        "Auto-detected model, serial, Android version & battery level",
        "Thread-safe status updates via Qt signals",
    ]),
    ("IMEI Management", "secondary_container", "open", [
        "Dual-IMEI entry with 15-digit numeric validation",
        "Persistent IMEI log (imei_list.txt)",
        "Luhn algorithm validation for Pixel 6 inputs",
        "Auto-detected current IMEI display",
    ]),
    ("DevInfo Editing", "primary_container", "save", [
        "Template-driven devinfo editing for Pixel 6, 6a & 6 Pro",
        "TLV structure parsing with auto-detected IMEIs",
        "Safe export with duplicate-name protection",
        "Offline patch & export \u2014 no device required",
    ]),
    ("Backup & Recovery", "tertiary_container", "save", [
        "One-click backup of EFS, devinfo and cpsha",
        "Structured Device_Backups/&lt;Model&gt;_&lt;Product&gt;/&lt;timestamp&gt; layout",
        "Smart snapshot preservation to prevent overwriting",
    ]),
    ("Logging & Diagnostics", "secondary_container", "open", [
        "Structured Command Matrix console with per-line timestamps",
        "Log-level color coding (info / success / warn / error)",
        "Auto-scroll with manual scroll-up detection",
        "Save console log to file; dedicated PixelKitLogger file output",
    ]),
    ("Pixel Device Support", "primary_container", "refresh", [
        "Pixel 6 / 6a / 6 Pro devinfo templates",
        "Pixel 7, 8 & 9 series CPID repair",
        "Pixel 10 series CPID repair",
    ]),
    ("Modern UI/UX", "tertiary_container", "open", [
        "Material 3 dynamic theming generated from a single seed color",
        "Responsive Light/Dark mode with persistence",
        "Searchable, categorized partition flashing (31 partitions)",
        "Live step-by-step CPID progress indicator",
        "Robust custom command parser with shlex & prefix validation",
    ]),
]

# ---------------------------------------------------------------------------
# Changelog content (legacy history + the 3.7 Qt release)
# ---------------------------------------------------------------------------
# (version, date, [(tag, change), ...])  — tag ∈ NEW/IMPROVED/FIXED/ADDED/etc.
CHANGELOG: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("3.8.0", "July 2026", [
        ("NEW", "ADB & Fastboot driver installer with automatic and manual modes"),
        ("FIXED", "Minor bug fixes across the UI and service layer"),
        ("IMPROVED", "Performance improvements"),
    ]),
    ("3.7.0", "June 2026", [
        ("FIXED", "Fastboot/ADB operations cards overlapping on startup (delayed equalization & layout filter refit)"),
        ("FIXED", "Theme toggle menu action label incorrectly showing the current theme state"),
        ("IMPROVED", "Added some minor titlebar improvements"),
    ]),
    ("3.6.0", "June 2026", [
        ("NEW", "Complete Qt / PySide6 + Material 3 UI rebuild (pixelkit_qt)"),
        ("NEW", "Dynamic M3 theming generated from a seed color (#0B57D0)"),
        ("NEW", "Left navigation rail replacing the legacy top tab strip"),
        ("NEW", "Searchable, categorized partition flashing (31 partitions)"),
        ("NEW", "Live CPID step indicator for Pixel 7\u20139 and Pixel 10 sequences"),
        ("NEW", "Rich About dialog: Features / Changelog / Contact tabs"),
        ("NEW", "Firmware prerequisites warning gate before every CPID repair"),
        ("IMPROVED", "Smaller, denser, professional diagnostic console"),
        ("IMPROVED", "Fully theme-aware widgets \u2014 no hardcoded colors in Light mode"),
        ("FIXED", "Contact email typo (gamil \u2192 gmail)"),
    ]),
    ("3.5.0", "June 2026", [
        ("NEW", "Pixel 10 Series CPID IMEI Repair (8-step automated workflow)"),
        ("NEW", "Device_Backups/<Model>_<Product>/<timestamp> structured backups"),
        ("FIXED", "Warning popups now center on the main window"),
        ("FIXED", "Title bar now shows Pixel Kit icon instead of Python logo"),
        ("IMPROVED", "Deadlock-safe subprocess handling for interactive shell"),
        ("IMPROVED", "Thread-safe busy flag with proper locking"),
        ("IMPROVED", "Dedicated logging framework with PixelKitLogger"),
        ("REFACTORED", "Monolithic PixelKit-Final.py split into modular pixelkit/ package"),
    ]),
    ("3.1.0", "June 2026", [
        ("NEW", "Pixel 6 Series DevInfo Editor (Pixel 6, 6a & 6 Pro)"),
        ("NEW", "TLV-structure template parsing with auto-detected current IMEIs"),
        ("NEW", "Luhn algorithm validation for Pixel 6 IMEI inputs"),
        ("NEW", "Android Version & Battery Level in device status panel"),
        ("NEW", "Determinate flashing progress bar with stage labels"),
        ("NEW", "Footer status label with auto-reset after command completion"),
        ("IMPROVED", "Custom command parser \u2014 shlex-based with validation"),
        ("FIXED", "Black corners on CPID tab widgets in Light mode"),
        ("FIXED", "Nested CTkTabview segmented button rendering"),
    ]),
    ("3.0.0", "May 2026", [
        ("INTEGRATED", "lexipwn for Android 16/17 IMEI hash fixes"),
        ("NEW", "Persistent device-specific critical backups (EFS/Devinfo/CPSHA)"),
        ("NEW", "Dedicated 'Backup Critical Files' button in CPID tab"),
        ("IMPROVED", "Smart snapshot preservation to prevent overwriting"),
        ("FIXED", "Null IMEI issue on latest Android versions"),
    ]),
    ("2.0.0", "May 2026", [
        ("INTEGRATED", "giant-CPID IMEI Repair tool"),
        ("NEW", "Dedicated 'CPID' tab for Pixel 7\u20139"),
        ("NEW", "Persistent Root Shell for modem sync"),
        ("FIXED", "Permission denied errors on /dev/umts_router"),
        ("FIXED", "Improved shell redirection handling"),
        ("ADDED", "Legal Warning popup and root gates"),
        ("ADDED", "IMEI logging to giant-CPID/imei_list.txt"),
    ]),
    ("1.5.0", "April 2026", [
        ("NEW", "Flashing Arsenal (30+ partitions)"),
        ("NEW", "Threaded runner for responsive UI"),
        ("NEW", "Real-time Command Matrix Console"),
        ("ADDED", "User configuration persistence"),
        ("IMPROVED", "High-DPI scaling support"),
    ]),
    ("1.0.0", "March 2026", [
        ("INITIAL", "Initial public release of Pixel Kit"),
        ("NEW", "Basic ADB and Fastboot operation suite"),
        ("NEW", "Real-time connection polling system"),
    ]),
]

# ---------------------------------------------------------------------------
# Contact channels (legacy set, with the corrected email)
# ---------------------------------------------------------------------------
# (label, display value, url, accent_role)
# accent_role drives each contact card's icon-tile tint, so channels read as
# distinct destinations while staying within the M3 scheme.
CONTACTS: list[tuple[str, str, str, str]] = [
    ("Email", "nott.giant@gmail.com",
     "mailto:nott.giant@gmail.com", "primary_container"),
    ("GitHub", "github.com/not-GIANT/Pixel-Kit",
     "https://github.com/not-GIANT/Pixel-Kit", "secondary_container"),
    ("TikTok", "@giant.notop",
     "https://www.tiktok.com/@giant.notop", "tertiary_container"),
    ("Twitter / X", "@giant_notop",
     "https://x.com/giant_notop", "primary_container"),
    ("Instagram", "@0xgiant",
     "https://www.instagram.com/0xgiant", "secondary_container"),
]

_TAG_ROLE = {  # changelog tag → M3 role used for the tag's accent text
    "NEW": "primary", "ADDED": "primary", "IMPROVED": "tertiary",
    "FIXED": "error", "INTEGRATED": "secondary", "REFACTORED": "on_surface_variant",
    "INITIAL": "on_surface_variant",
}


# Container role → its matching on-* role. Used so the accent-pair resolver
# always picks the correct high-contrast foreground for a given container tint.
_CONTAINER_ON_ROLE = {
    "primary_container": "on_primary_container",
    "secondary_container": "on_secondary_container",
    "tertiary_container": "on_tertiary_container",
    "error_container": "on_error_container",
}


def _accent_pair(scheme: dict, accent_role: str) -> tuple[str, str]:
    """Resolve an M3 container role to a (on_*_container, container) hex pair.

    Used by the Features + Contact card headers/tiles so their tints are always
    derived from the live scheme rather than hardcoded hues. Falls back to
    primary if the requested role is missing.
    """
    on_role = _CONTAINER_ON_ROLE.get(accent_role, "on_primary_container")
    on_col = scheme.get(on_role) or scheme.get("on_primary_container", "#000000")
    container = scheme.get(accent_role) or scheme.get("primary_container", on_col)
    return on_col, container


class AboutDialog(QDialog):
    """Tabbed About dialog — Application info + Features / Changelog / Contact.

    Fully theme-aware: every accent tint (feature category headers, contact
    icon tiles, changelog tag labels) is derived from the live M3 scheme and
    re-applied when the theme changes while the dialog is open. No hardcoded
    colors — all hues come from scheme roles.
    """

    def __init__(self, parent=None, window_icon=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.resize(640, 660)
        if window_icon is not None and not window_icon.isNull():
            self.setWindowIcon(window_icon)

        # Active scheme cache + references to the theme-dependent widgets so
        # they can be re-tinted on a theme toggle without rebuilding the UI.
        from ..theme import active_scheme
        self._scheme: dict = dict(active_scheme()) if active_scheme() else {}
        # Collected (role, widget) pairs whose accent tint must be repainted.
        self._accent_widgets: list[tuple[str, QFrame]] = []
        # Collected (tag_role, QLabel) pairs for changelog tag pills.
        self._tag_labels: list[tuple[str, QLabel]] = []
        # Collected (label, QLabel, accent_role) triplets for contact icons.
        self._contact_icons: list[tuple[str, QLabel, str]] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(10)

        outer.addLayout(self._build_header())
        self._tabs = QTabWidget()
        self._tabs.addTab(self._features_tab(), "Features")
        self._tabs.addTab(self._changelog_tab(), "Changelog")
        self._tabs.addTab(self._contact_tab(), "Contact & Support")
        outer.addWidget(self._tabs, 1)
        outer.addWidget(self._build_footer())

        # Repaint once with the current scheme so accents are correct at open.
        self.update_colors(self._scheme)
        # Subscribe to live theme changes (so a toggle while open re-tints).
        win = self._find_main_window(parent)
        if win is not None and hasattr(win, "theme") and \
                hasattr(win.theme, "on_change"):
            win.theme.on_change(self.update_colors)

    @staticmethod
    def _find_main_window(parent):
        """Walk up to the MainWindow so we can subscribe to its ThemeManager."""
        p = parent
        while p is not None:
            if hasattr(p, "theme") and hasattr(p.theme, "on_change"):
                return p
            p = p.parent() if hasattr(p, "parent") else None
        return None

    # ------------------------------------------------------------------
    # Header — application information
    # ------------------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        if self.windowIcon() is not None and not self.windowIcon().isNull():
            icon_lbl = QLabel()
            icon_lbl.setPixmap(self.windowIcon().pixmap(56, 56))
            row.addWidget(icon_lbl)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        name = QLabel(APP_NAME)
        name.setProperty("role", "title")
        titles.addWidget(name)
        ver = QLabel(f"{APP_VERSION} \u2014 {APP_TAGLINE}")
        ver.setProperty("role", "caption")
        ver.setWordWrap(True)
        titles.addWidget(ver)
        build = QLabel(APP_BUILD)
        build.setProperty("role", "caption")
        titles.addWidget(build)
        copy = QLabel(APP_COPYRIGHT)
        copy.setProperty("role", "caption")
        titles.addWidget(copy)
        titles.addStretch()
        row.addLayout(titles, 1)
        return row

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    def _features_tab(self) -> QWidget:
        """Features tab — one M3 card per category with a tinted header chip.

        Mirrors the Changelog tab's card aesthetic so the two information-heavy
        tabs read consistently: each category is an outlined card with a colored
        header row (icon tile + title + bullet count) and its bullets beneath.
        The header tint comes from the category's mapped M3 container role, so
        categories are color-coded without breaking the theme.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(10)

        for category, accent_role, icon_name, bullets in FEATURES:
            card = QFrame()
            card.setProperty("card", True)
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(0, 0, 0, 10)
            card_lay.setSpacing(8)

            # Tinted header band (icon tile + title + count). Painted from the
            # scheme so it re-tints on theme change; registered for repaint.
            header = QFrame()
            header.setObjectName("FeatureHeader")
            header_lay = QHBoxLayout(header)
            header_lay.setContentsMargins(14, 10, 14, 10)
            header_lay.setSpacing(10)

            tile = QLabel()
            tile.setFixedSize(26, 26)
            tile.setAlignment(Qt.AlignCenter)
            icn = icons.icon_for(icon_name)
            if icn is not None and not icn.isNull():
                tile.setPixmap(icn.pixmap(16, 16))
            header_lay.addWidget(tile)

            title = QLabel(category)
            title.setProperty("role", "label-l")
            title.setObjectName("FeatureTitle")
            header_lay.addWidget(title)
            header_lay.addStretch()

            count = QLabel(f"{len(bullets)}")
            count.setObjectName("FeatureCount")
            header_lay.addWidget(count)
            card_lay.addWidget(header)

            # Bullets — indented under the header, in the card body.
            body = QVBoxLayout()
            body.setContentsMargins(14, 2, 14, 0)
            body.setSpacing(4)
            for b in bullets:
                item = QLabel(f"\u2022  {b}")
                item.setProperty("role", "body")
                item.setWordWrap(True)
                item.setTextFormat(Qt.RichText)
                body.addWidget(item)
            card_lay.addLayout(body)

            layout.addWidget(card)
            # Register the header for theme-aware repaint.
            self._accent_widgets.append((accent_role, header))
        layout.addStretch()
        scroll.setWidget(host)
        return scroll
        scroll.setWidget(host)
        return scroll

    def _changelog_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(10)

        for version, date, changes in CHANGELOG:
            card = QFrame()
            card.setProperty("card", True)
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(12, 8, 12, 10)
            card_lay.setSpacing(4)
            head_row = QHBoxLayout()
            vlbl = QLabel(f"Version {version}")
            vlbl.setProperty("role", "label-l")
            head_row.addWidget(vlbl)
            head_row.addStretch()
            dlbl = QLabel(date)
            dlbl.setProperty("role", "caption")
            head_row.addWidget(dlbl)
            card_lay.addLayout(head_row)
            for tag, change in changes:
                line_row = QHBoxLayout()
                line_row.setSpacing(8)
                line_row.setContentsMargins(0, 0, 0, 0)
                # Tag pill — tinted from its mapped M3 role, repaints on theme
                # change via _tag_labels registration.
                pill = QLabel(tag)
                pill.setObjectName("ChangeTag")
                pill.setAlignment(Qt.AlignCenter)
                pill.setProperty("role", "label-s")
                self._tag_labels.append((_TAG_ROLE.get(tag, "on_surface_variant"), pill))
                line_row.addWidget(pill)
                # Change text.
                line = QLabel(change)
                line.setProperty("role", "body")
                line.setWordWrap(True)
                line_row.addWidget(line, 1)
                line_host = QWidget()
                line_host.setLayout(line_row)
                card_lay.addWidget(line_host)
            layout.addWidget(card)
        layout.addStretch()
        scroll.setWidget(host)
        return scroll

    def _contact_tab(self) -> QWidget:
        """Contact tab — each channel is an M3 card with a tinted icon tile.

        Replaces the old label:text-button form rows with destination cards:
        a colored icon tile, the channel label + handle, and an Open action on
        the right. The tile tint comes from the channel's mapped M3 container
        role so channels read as distinct, branded destinations.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(10)

        head = QLabel("Connect & Support")
        head.setProperty("role", "headline")
        layout.addWidget(head)
        sub = QLabel("Reach out, report issues, or follow along:")
        sub.setProperty("role", "caption")
        layout.addWidget(sub)

        for label, value, url, accent_role in CONTACTS:
            layout.addWidget(self._contact_card(label, value, url, accent_role))

        layout.addStretch()
        note = QLabel(
            "If you want to donate and support this project, "
            "feel free to contact me.")
        note.setProperty("role", "caption")
        note.setAlignment(Qt.AlignCenter)
        note.setWordWrap(True)
        layout.addWidget(note)
        scroll.setWidget(host)
        return scroll

    def _contact_card(self, label: str, value: str, url: str,
                      accent_role: str) -> QWidget:
        """A single contact destination card.

        Layout: [tinted icon tile] [label + handle, stacked] [Open button].
        The tile frame is registered for theme-aware repaint.
        """
        card = QFrame()
        card.setProperty("card", True)
        h = QHBoxLayout(card)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(12)

        # Tinted icon tile — round-ish square, painted from the scheme.
        tile = QFrame()
        tile.setFixedSize(40, 40)
        tile.setObjectName("ContactTile")
        tile_lay = QHBoxLayout(tile)
        tile_lay.setContentsMargins(0, 0, 0, 0)
        icn_lbl = QLabel()
        icn_lbl.setAlignment(Qt.AlignCenter)
        self._contact_icons.append((label, icn_lbl, accent_role))
        tile_lay.addWidget(icn_lbl)
        h.addWidget(tile)

        # Channel name + handle, stacked vertically.
        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        name = QLabel(label)
        name.setProperty("role", "label-m")
        handle = QLabel(value)
        handle.setProperty("role", "caption")
        stack.addWidget(name)
        stack.addWidget(handle)
        text_host = QWidget()
        text_host.setLayout(stack)
        h.addWidget(text_host, 1)

        # Open action.
        btn = QPushButton("Open")
        btn.setProperty("variant", "tonal")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(f"Open {label}")
        btn.clicked.connect(lambda _=False, u=url: self._open_link(u))
        h.addWidget(btn)

        self._accent_widgets.append((accent_role, tile))
        return card

    def _open_link(self, url: str) -> None:
        webbrowser.open_new_tab(url)

    # ------------------------------------------------------------------
    # Theme-aware repaint
    # ------------------------------------------------------------------
    def update_colors(self, scheme: dict) -> None:
        """Re-tint every accent surface from the active M3 scheme.

        Called once at construction and again on every theme toggle while the
        dialog is open. Derives each tint from scheme roles so there are no
        hardcoded colors in either light or dark mode.
        """
        self._scheme = scheme or self._scheme
        s = self._scheme

        # Update contact icons dynamically with high-contrast on_col
        for label, icn_lbl, accent_role in self._contact_icons:
            on_col, container = _accent_pair(s, accent_role)
            icn = icons.icon_for(f"social-{label}", color=on_col)
            if icn is not None and not icn.isNull():
                icn_lbl.setPixmap(icn.pixmap(20, 20))

        # Feature category headers + contact icon tiles: tinted container band.
        for accent_role, w in self._accent_widgets:
            on_col, container = _accent_pair(s, accent_role)
            is_tile = w.objectName() == "ContactTile"
            if is_tile:
                # Round square icon tile: filled container, on-container icon.
                w.setStyleSheet(
                    f"QFrame#ContactTile {{"
                    f" background-color: {container};"
                    f" border-radius: 12px;"
                    f" border: none; }}")
            else:
                # Feature header: a subtle container-tinted band with a small
                # colored count chip on the right.
                w.setStyleSheet(
                    f"QFrame#FeatureHeader {{"
                    f" background-color: {stylesheet.rgba(container, 0.30)};"
                    f" border: none;"
                    f" border-top-left-radius: {tokens.SHAPE_MEDIUM}px;"
                    f" border-top-right-radius: {tokens.SHAPE_MEDIUM}px; }}"
                    f"QLabel#FeatureTitle {{ color: {on_col}; }}"
                    f"QLabel#FeatureCount {{"
                    f" color: {on_col};"
                    f" background-color: {stylesheet.rgba(container, 0.55)};"
                    f" border-radius: 9px;"
                    f" padding: 2px 8px; }}")

        # Changelog tag pills: tinted from their mapped role.
        for role, pill in self._tag_labels:
            fg = s.get(role, s.get("on_surface_variant", "#000000"))
            pill.setStyleSheet(
                f"QLabel#ChangeTag {{"
                f" color: {fg};"
                f" background-color: {stylesheet.rgba(fg, 0.14)};"
                f" border-radius: 6px;"
                f" padding: 2px 8px; }}")

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------
    def _build_footer(self) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        msg = QLabel("Coded with \u2764\ufe0f by GIANT")
        msg.setProperty("role", "caption")
        msg.setAlignment(Qt.AlignCenter)
        row.addWidget(msg, 1)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        container = QWidget()
        container.setLayout(row)
        return container


def show_about(parent=None, window_icon=None) -> None:
    """Open the About dialog modally."""
    dlg = AboutDialog(parent=parent, window_icon=window_icon)
    dlg.exec()

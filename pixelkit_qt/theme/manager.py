"""Theme manager — applies M3 scheme + stylesheet to the QApplication.

Holds the current light/dark mode and seed color, regenerates the scheme +
QSS, and pushes them to the app. Listeners (views, widgets) can subscribe to
theme changes to re-paint custom widgets that QSS can't reach (e.g. the log
view's colored text tags).
"""
from __future__ import annotations

from PySide6.QtGui import QPalette, QColor, QFontDatabase, QFont
from PySide6.QtWidgets import QApplication

from . import tokens, stylesheet
# Leaf module holding the active-scheme cache. Imported from the leaf (not the
# package __init__) to avoid a circular import: __init__ imports this module,
# so reaching back into the package for set_active_scheme would re-enter a
# partially-initialized package.
from ._state import set_active_scheme


def _hex_to_qcolor(hex_color: str) -> QColor:
    """Tolerant '#rrggbb' / '#aarrggbb' → QColor (leading alpha byte ignored)."""
    h = hex_color.lstrip("#")
    if len(h) == 8:
        h = h[2:]
    return QColor(f"#{h}") if h else QColor()


def build_palette(scheme: dict) -> QPalette:
    """Build a QPalette from an M3 scheme dict.

    QSS only styles widgets it explicitly targets; everything Qt draws from the
    palette (QScrollArea viewports, plain QWidget containers, native dialog
    chrome, placeholder text, selection colors) would otherwise stay at the
    platform default (Windows's #f0f0f0 gray) — which is the root cause of the
    long-standing light-theme mismatch. Mirroring the active scheme into the
    palette closes that gap so light and dark both read correctly.
    """
    pal = QPalette()
    surface = _hex_to_qcolor(scheme.get("surface", "#faf8ff"))
    on_surface = _hex_to_qcolor(scheme.get("on_surface", "#181b25"))
    on_surface_var = _hex_to_qcolor(scheme.get("on_surface_variant", "#434654"))
    card = _hex_to_qcolor(scheme.get("surface_container", surface.name()))
    card_low = _hex_to_qcolor(scheme.get("surface_container_low", card.name()))
    card_high = _hex_to_qcolor(scheme.get("surface_container_highest", card.name()))
    primary = _hex_to_qcolor(scheme.get("primary", "#0B57D0"))
    on_primary = _hex_to_qcolor(scheme.get("on_primary", "#ffffff"))
    outline_var = _hex_to_qcolor(scheme.get("outline_variant", "#cccccc"))
    disabled_text = QColor(on_surface)
    disabled_text.setAlphaF(0.38)

    for group in (QPalette.Active, QPalette.Inactive):
        pal.setColor(group, QPalette.Window, surface)             # window bg
        pal.setColor(group, QPalette.WindowText, on_surface)      # window fg
        pal.setColor(group, QPalette.Base, card_low)              # text-view bg
        pal.setColor(group, QPalette.AlternateBase, card)         # alt rows
        pal.setColor(group, QPalette.Text, on_surface)            # text-view fg
        pal.setColor(group, QPalette.Button, card)                # button bg
        pal.setColor(group, QPalette.ButtonText, on_surface)      # button fg
        pal.setColor(group, QPalette.ToolTipBase, card_high)
        pal.setColor(group, QPalette.ToolTipText, on_surface)
        pal.setColor(group, QPalette.Highlight, primary)          # selection
        pal.setColor(group, QPalette.HighlightedText, on_primary)
        pal.setColor(group, QPalette.Link, primary)
        pal.setColor(group, QPalette.LinkVisited, primary)
        pal.setColor(group, QPalette.PlaceholderText, on_surface_var)
        # A faint separator tint for native widget borders/splitters.
        pal.setColor(group, QPalette.Mid, outline_var)
    # Disabled group — keep backgrounds, fade the foreground so disabled
    # widgets (which QSS may not cover) still read as disabled.
    pal.setColor(QPalette.Disabled, QPalette.Window, surface)
    pal.setColor(QPalette.Disabled, QPalette.WindowText, disabled_text)
    pal.setColor(QPalette.Disabled, QPalette.Text, disabled_text)
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, disabled_text)
    return pal


class ThemeManager:
    """Owns the active M3 scheme and broadcasts changes."""

    def __init__(self, app: QApplication, seed: str = tokens.SEED,
                 dark: bool = False):
        self.app = app
        self.seed = seed
        self.dark = dark
        self._listeners: list = []
        self._scheme_cache: dict | None = None

    # --- public API ---

    def apply(self) -> dict:
        """Generate scheme + QSS + palette, apply to app, notify listeners.

        Returns scheme.
        """
        scheme = tokens.generate_scheme(self.seed, dark=self.dark)
        # Tag for the stylesheet header.
        scheme["is_dark"] = self.dark
        self._scheme_cache = scheme
        # Publish the active scheme so dialogs/popups (which can't rely on
        # QPalette — QSS doesn't populate it) can read theme-aware colors.
        set_active_scheme(scheme)
        # QSS skins every widget it targets, but Qt paints scroll-area
        # viewports, plain QWidget containers, and native dialog chrome from
        # the application palette. Mirroring the scheme into the palette keeps
        # those in sync with the QSS so the light theme no longer shows the
        # default Windows gray under/around themed widgets.
        self.app.setPalette(build_palette(scheme))
        self.app.setStyleSheet(stylesheet.build_qss(scheme))
        self._apply_app_font()
        for listener in self._listeners:
            listener(scheme)
        return scheme

    def toggle_mode(self) -> None:
        self.dark = not self.dark
        self.apply()

    def set_seed(self, seed_hex: str) -> None:
        self.seed = seed_hex
        self.apply()

    @property
    def scheme(self) -> dict:
        if self._scheme_cache is None:
            self._scheme_cache = tokens.generate_scheme(self.seed, self.dark)
        return self._scheme_cache

    def on_change(self, callback) -> None:
        """Register a callback(scheme_dict) fired on every theme change."""
        self._listeners.append(callback)

    # --- internals ---

    def _apply_app_font(self) -> None:
        """Set the app-wide font family, preferring the M3 type stack.

        Qt picks the first installed family from the family list; the rest are
        fallbacks for non-Windows platforms or unbundled font scenarios.
        """
        installed = set(QFontDatabase.families())
        chosen = next((f for f in tokens.TYPE_FAMILY if f in installed),
                      tokens.TYPE_FAMILY[-1])
        font = QFont(chosen, 10)
        self.app.setFont(font)

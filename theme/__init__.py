"""Material 3 theme package — tokens + QSS generator + palette builder + icons.

Single entry point: theme_manager.load(app, dark=...) applies the full M3
scheme (color tokens + stylesheet + QPalette + window font stack) to a
QApplication.

`active_scheme()` returns the most recently applied M3 scheme dict so that
widgets that paint their own colors (dialogs, popups) can read the live scheme
without holding a ThemeManager reference.
"""
from . import tokens
from .stylesheet import build_qss
from .manager import ThemeManager, build_palette
from . import icons
# Re-export the active-scheme accessors (state lives in the leaf _state module
# to keep imports acyclic: manager.py also imports from _state directly).
from ._state import active_scheme, set_active_scheme

__all__ = ["tokens", "build_qss", "build_palette", "ThemeManager", "icons",
           "active_scheme", "set_active_scheme"]

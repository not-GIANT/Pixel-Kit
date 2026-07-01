"""Pixel Kit — Qt/PySide6 + Material 3 UI package.

The application's user interface, built on PySide6 (Qt 6) and styled with
Google's Material 3 design system. Shares the unchanged services layer
(``pixelkit.services.*``) via QtBridge.

Launch with:
    python run.py             # or
    python -m pixelkit_qt     # or
    python -c "from pixelkit_qt import launch; launch()"
"""
from .app import launch, MainWindow

__all__ = ["launch", "MainWindow"]
__version__ = "3.8.0-qt-m3"

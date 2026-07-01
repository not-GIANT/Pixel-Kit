"""Module entry point so `python -m pixelkit_qt` works.

Delegates to app.launch(), which builds the QApplication and MainWindow.
"""
import sys

from .app import launch

if __name__ == "__main__":
    sys.exit(launch())

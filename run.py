"""Pixel Kit launcher — the canonical way to start the app.

    python run.py

Resolves the project root (this file's directory) onto ``sys.path`` so the
launcher works from any working directory, then hands off to the Qt/M3 entry
point in :mod:`pixelkit_qt`.

Double-clickable on Windows via the companion ``run.bat``; bundlable into a
standalone executable via ``pyinstaller "Pixel Kit.spec"`` (which targets this
file as its script).
"""
import sys
from pathlib import Path

# Ensure the project root is importable regardless of the caller's CWD.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pixelkit_qt import launch  # noqa: E402  (path set up above)


if __name__ == "__main__":
    sys.exit(launch())

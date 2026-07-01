"""Structured log view — replaces the CTk plain-textbox console.

Differences from the old console:
- Timestamp gutter (HH:MM:SS) on every line.
- Log-level color coding via M3 palette (info / success / warn / error),
  re-painted automatically on theme change.
- Auto-scroll toggle (stays at the tail unless the user scrolls up).
- Clear + save-to-file actions in the header.
- Soft cap on retained lines to keep memory bounded for long sessions.

Sizing note: the log face is intentionally smaller (≈11px) than the rest of
the UI so the console reads as a dense, professional diagnostic terminal. The
font + colors come from the central M3 theme so it stays crisp in both modes.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import (QFont, QFontDatabase, QTextCharFormat, QTextCursor,
                           QColor)
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from ..theme import tokens

# Soft cap on retained lines (older lines are trimmed from the top).
MAX_LINES = 5000

# Log point size — deliberately one notch below the UI font for density.
# 8.5pt (≈9 × 0.95) keeps the dense diagnostic feel while gaining a little
# vertical room for more lines per screen.
LOG_POINT_SIZE = 8.5


def _resolve_mono_font() -> QFont:
    """Build a real QFont from the M3 mono family stack.

    The previous code passed a comma string ("Consolas, 11") to QFont, which Qt
    treats as a single (nonexistent) family and silently falls back. We instead
    pick the first installed family from the token stack and set the point size
    explicitly, so the console actually renders in a monospaced face.
    """
    installed = set(QFontDatabase.families())
    family = next((f for f in tokens.MONO_FAMILY if f in installed),
                  tokens.MONO_FAMILY[-1])
    font = QFont(family)
    font.setPointSize(LOG_POINT_SIZE)
    font.setStyleHint(QFont.Monospace)
    return font


class LogView(QFrame):
    """Structured console: timestamped, level-colored, auto-scrolling."""

    def __init__(self, title: str = "Command Matrix", parent=None):
        super().__init__(parent)
        self.setObjectName("LogViewContainer")
        self.setProperty("card", True)

        # Per-level text colors + the timestamp-gutter color, refreshed on
        # theme change. Backed by M3 scheme roles — never hardcoded.
        self._level_colors: dict[str, str] = {}
        self._stamp_color = "#888888"
        self._mono_font = _resolve_mono_font()
        self._autoscroll = True

        self._build_ui(title)
        self._wire_autoscroll()

    # --- public API ---

    @Slot(str, str)
    def append(self, text: str, level: str = "info") -> None:
        """Append text with a timestamp and the given level's color.

        Multi-line payloads are split so each line gets its own timestamp.
        """
        if not text:
            return
        color = self._level_colors.get(
            level, self._level_colors.get("on_surface_variant", "#000000"))

        body_fmt = QTextCharFormat()
        body_fmt.setForeground(QColor(color))
        body_fmt.setFont(self._mono_font)

        cursor = self._edit.textCursor()
        cursor.movePosition(QTextCursor.End)

        stamp = datetime.now().strftime("%H:%M:%S")
        for i, line in enumerate(text.splitlines() or [""]):
            cursor.insertText(f"{stamp} ", self._stamp_fmt)
            cursor.insertText(line + "\n", body_fmt)

        self._trim()
        if self._autoscroll:
            self._edit.ensureCursorVisible()

    def set_level_colors(self, level_colors: dict[str, str]) -> None:
        """Update per-level colors (called on theme change)."""
        self._level_colors = dict(level_colors)

    def set_scheme(self, scheme: dict) -> None:
        """Apply scheme-derived colors for the timestamp gutter and the
        default body fallback. Called on theme change."""
        self._stamp_color = scheme.get("outline", "#888888")
        self._stamp_fmt.setForeground(QColor(self._stamp_color))

    def clear_log(self) -> None:
        self._edit.clear()

    # --- internals ---

    def _build_ui(self, title: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        # Header: title + actions
        header = QHBoxLayout()
        header.setSpacing(8)
        self._title = QLabel(title)
        self._title.setProperty("role", "headline")
        header.addWidget(self._title)
        header.addStretch()

        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setProperty("variant", "text")
        self._btn_clear.clicked.connect(self.clear_log)
        header.addWidget(self._btn_clear)

        self._btn_save = QPushButton("Save")
        self._btn_save.setProperty("variant", "text")
        self._btn_save.clicked.connect(self._save_to_file)
        header.addWidget(self._btn_save)

        self._btn_autoscroll = QPushButton("Auto-scroll: On")
        self._btn_autoscroll.setProperty("variant", "text")
        self._btn_autoscroll.setCheckable(True)
        self._btn_autoscroll.setChecked(True)
        self._btn_autoscroll.clicked.connect(self._toggle_autoscroll)
        header.addWidget(self._btn_autoscroll)

        layout.addLayout(header)

        # Timestamp gutter format — color is theme-aware (set via set_scheme).
        self._stamp_fmt = QTextCharFormat()
        self._stamp_fmt.setForeground(QColor(self._stamp_color))
        self._stamp_fmt.setFont(self._mono_font)

        # The editor itself — mono, word-wrapped, smaller for density.
        self._edit = QPlainTextEdit()
        self._edit.setObjectName("LogView")
        self._edit.setReadOnly(True)
        self._edit.setFont(self._mono_font)
        self._edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._edit.setMaximumBlockCount(MAX_LINES)
        layout.addWidget(self._edit, 1)

    def _wire_autoscroll(self) -> None:
        """Detect manual scroll-up and pause auto-scroll until user returns to bottom."""
        sb = self._edit.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll)

    def _on_scroll(self, value: int) -> None:
        sb = self._edit.verticalScrollBar()
        at_bottom = value >= sb.maximum() - 4
        # If the user scrolled up manually, suspend auto-scroll.
        if not at_bottom and self._autoscroll:
            self._autoscroll = False
            self._btn_autoscroll.setText("Auto-scroll: Paused")
            self._btn_autoscroll.setChecked(False)
        # Re-arm when they scroll back to the bottom.
        if at_bottom and not self._btn_autoscroll.isChecked():
            self._autoscroll = True
            self._btn_autoscroll.setText("Auto-scroll: On")
            self._btn_autoscroll.setChecked(True)

    def _toggle_autoscroll(self) -> None:
        self._autoscroll = self._btn_autoscroll.isChecked()
        self._btn_autoscroll.setText(
            "Auto-scroll: On" if self._autoscroll else "Auto-scroll: Off")

    def _trim(self) -> None:
        """MaximumBlockCount handles trimming; this is a hook for future use."""
        pass

    def _save_to_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Console Log", "pixelkit_console.txt",
            "Text Files (*.txt);;All Files (*)")
        if path:
            Path(path).write_text(self._edit.toPlainText(), encoding="utf-8")
            self.append(f"[saved log to {path}]\n", "info")

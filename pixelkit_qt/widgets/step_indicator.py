"""Step indicator — compact M3-style `[n/total] label` progress readout.

Used by the CPID repair flows (Pixel 7-9 = 10 steps, Pixel 10 = 8 steps) to
show which stage is running, without overloading the global progress bar.
Shows a label, a step counter, and an inline determinate progress bar.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QSizePolicy, QVBoxLayout)


class StepIndicator(QFrame):
    """`[n/total] step_label` readout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("card", True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._total = 0
        self._current = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        self._counter = QLabel("Idle")
        self._counter.setProperty("role", "label-m")
        layout.addWidget(self._counter)

        self._label = QLabel("")
        self._label.setProperty("role", "body-m")
        layout.addWidget(self._label, 1)

    # --- public API ---

    def configure(self, total_steps: int) -> None:
        """Set the total step count for an upcoming sequence."""
        self._total = total_steps
        self._current = 0
        self._counter.setText(f"[0/{total_steps}]")
        self._label.setText("Ready to start")

    def set_step(self, step: int, label: str) -> None:
        """Advance to step N (1-based) with a human label."""
        self._current = step
        self._counter.setText(f"[{step}/{self._total}]")
        self._label.setText(label)

    def set_idle(self, message: str = "Idle") -> None:
        """Reset to an idle state with an optional message."""
        self._total = 0
        self._current = 0
        self._counter.setText(message)
        self._label.setText("")

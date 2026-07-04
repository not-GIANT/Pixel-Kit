"""M3-styled dialog for installing ADB & Fastboot drivers.

Presents two installation methods:

- **Automatic** — runs the bundled ``Drivers.exe`` installer with elevation.
- **Manual** — extracts the archive, copies the ``adb`` folder to the system
  drive, and runs the inner DPInst installer via an elevated helper script.

All work is delegated to ``pixelkit.services.driver_installer.DriverInstaller``
so the dialog remains focused on presentation and user feedback.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from pixelkit.services.driver_installer import DriverInstaller

from ..theme import active_scheme
from . import dialogs


# ---------------------------------------------------------------------------
# Cross-thread signal relay
# ---------------------------------------------------------------------------
class _WorkerRelay(QObject):
    """Marshals installer callbacks from the worker thread to the Qt main thread."""

    log = Signal(str, str)       # (message, level)
    progress = Signal(float)     # 0.0 .. 1.0
    finished = Signal(bool, str) # (success, message)


# ---------------------------------------------------------------------------
# Option card widget
# ---------------------------------------------------------------------------
class _OptionCard(QFrame):
    """A single clickable option in the installer dialog."""

    def __init__(self, title: str, description: str, button_text: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.title = QLabel(title)
        self.title.setProperty("role", "headline")
        layout.addWidget(self.title)

        self.desc = QLabel(description)
        self.desc.setProperty("role", "body")
        self.desc.setWordWrap(True)
        self.desc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.desc, 1)

        self.button = QPushButton(button_text)
        layout.addWidget(self.button)


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------
class InstallDriversDialog(QDialog):
    """Modal dialog for installing ADB & Fastboot drivers."""

    def __init__(self, parent: QWidget | None, config, log=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Install Drivers")
        self.resize(540, 420)
        self.setModal(True)

        self.config = config
        self.log = log
        self.installer: DriverInstaller | None = None
        self._busy = False

        self._relay = _WorkerRelay(self)
        self._relay.log.connect(self._on_log)
        self._relay.progress.connect(self._on_progress)
        self._relay.finished.connect(self._on_finished)

        self._build_ui()
        self._apply_scheme()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        header = QLabel("Install ADB & Fastboot Drivers")
        header.setProperty("role", "headline")
        outer.addWidget(header)

        sub = QLabel("Choose how you want to install the Google USB drivers and "
                     "ADB/Fastboot binaries on your system.")
        sub.setProperty("role", "body")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        # --- Two option cards ---
        cards = QHBoxLayout()
        cards.setSpacing(12)

        self.auto_card = _OptionCard(
            title="Automatic Installation",
            description="Recommended. Runs the official bundled installer with "
                        "Administrator rights.",
            button_text="Install Automatically",
        )
        self.auto_card.button.clicked.connect(self._on_automatic)
        cards.addWidget(self.auto_card, 1)

        self.manual_card = _OptionCard(
            title="Manual Installation",
            description="Fix incomplete installations. Extracts the bundled "
                        "archive, copies the adb folder to %SystemDrive%\\adb, "
                        "and installs the driver.",
            button_text="Install Manually",
        )
        self.manual_card.button.clicked.connect(self._on_manual)
        cards.addWidget(self.manual_card, 1)

        outer.addLayout(cards)

        # --- Progress + log (hidden until work starts) ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        outer.addWidget(self.progress)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.log_view.setFont(font)
        self.log_view.hide()
        outer.addWidget(self.log_view, 1)

        # --- Footer buttons ---
        footer = QHBoxLayout()
        footer.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        outer.addLayout(footer)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def _apply_scheme(self) -> None:
        scheme = active_scheme() or {}
        error = scheme.get("error", "#b00020")
        for level, color in (("info", scheme.get("primary", "#0B57D0")),
                             ("error", error)):
            self.log_view.appendHtml(
                f'<span style="color:{color}; font-weight:600;">'
                f'{level.upper()}</span>'
            )
        # Clear the placeholder styling lines.
        self.log_view.clear()

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------
    def _on_automatic(self) -> None:
        self._start_install(automatic=True)

    def _on_manual(self) -> None:
        self._start_install(automatic=False)

    def _start_install(self, automatic: bool) -> None:
        self._busy = True
        self.auto_card.button.setEnabled(False)
        self.manual_card.button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.log_view.clear()
        self.log_view.show()

        self.installer = DriverInstaller(
            self.config,
            log=self.log,
            on_log=self._relay.log.emit,
            on_progress=self._relay.progress.emit,
            on_finished=self._relay.finished.emit,
        )

        method = "automatic" if automatic else "manual"
        self._append_log(f"Starting {method} installation...", "info")
        if automatic:
            self.installer.install_automatic()
        else:
            self.installer.install_manual()

    # ------------------------------------------------------------------
    # Relay handlers (always run on the Qt main thread)
    # ------------------------------------------------------------------
    def _on_log(self, message: str, level: str) -> None:
        self._append_log(message, level)

    def _on_progress(self, value: float) -> None:
        self.progress.setValue(int(value * 100))

    def _on_finished(self, success: bool, message: str) -> None:
        self.progress.setValue(100 if success else 0)
        if success:
            self._append_log(message, "info")
            dialogs.info(self, "Installation Complete", message)
        else:
            self._append_log(message, "error")
            dialogs.error(self, "Installation Failed", message)
        self._set_idle()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _append_log(self, message: str, level: str = "info") -> None:
        scheme = active_scheme() or {}
        if level == "error":
            color = scheme.get("error", "#b00020")
        else:
            color = scheme.get("primary", "#0B57D0")
        self.log_view.appendHtml(
            f'<span style="color:{color};">{self._escape(message)}</span>'
        )
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    @staticmethod
    def _escape(text: str) -> str:
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

    def _set_idle(self) -> None:
        self._busy = False
        self.auto_card.button.setEnabled(True)
        self.manual_card.button.setEnabled(True)
        self.close_button.setEnabled(True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        if self._busy:
            event.ignore()
            return
        if self.installer is not None:
            self.installer.cancel()
        super().closeEvent(event)

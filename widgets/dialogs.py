"""Small dialog helpers — M3-styled replacements for tkinter messageboxes and
CTkInputDialog. Kept tiny so views call one-liners instead of building popups.

Theme awareness: dialog accent colors are read from the active M3 scheme
(``theme.active_scheme()``), which the ThemeManager refreshes on every toggle.
QSS does NOT populate QPalette, so reading the palette would return Qt's
default (white/blue) colors in both modes — the scheme accessor is the correct
source of theme-aware colors for non-QSS code.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..theme import active_scheme


# ---------------------------------------------------------------------------
# Theme helpers
# ---------------------------------------------------------------------------
def _scheme_color(role: str, fallback_hex: str) -> str:
    """Read a color from the active M3 scheme, falling back to a literal.

    The fallback only applies before the ThemeManager has applied a scheme
    (e.g. a dialog shown very early in startup) — in normal use the scheme is
    always populated and theme-aware.
    """
    val = active_scheme().get(role)
    return val if isinstance(val, str) and val.startswith("#") else fallback_hex


def _danger_button_style() -> str:
    """A theme-aware stylesheet for a destructive (danger) button."""
    error = _scheme_color("error", "#b00020")
    on_error = _scheme_color("on_error", "#ffffff")
    return (f"QPushButton {{ background-color: {error}; color: {on_error}; "
            f"border: none; border-radius: 8px; padding: 6px 18px; "
            f"font-weight: 600; }}"
            f"QPushButton:hover {{ border: 1px solid rgba(255,255,255,0.25); }}")


# ---------------------------------------------------------------------------
# Basic confirm / info / error
# ---------------------------------------------------------------------------
def confirm(parent: QWidget, title: str, message: str,
            danger: bool = False) -> bool:
    """Yes/No confirmation. danger=True styles the accept button as destructive."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    yes = box.addButton("Yes", QMessageBox.AcceptRole)
    box.addButton("No", QMessageBox.RejectRole)
    if danger:
        # Theme-aware danger styling (reads from the active palette).
        yes.setStyleSheet(_danger_button_style())
    box.exec()
    return box.clickedButton() is yes


def info(parent: QWidget, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def error(parent: QWidget, title: str, message: str) -> None:
    QMessageBox.critical(parent, title, message)


def prompt_text(parent: QWidget, title: str, label: str,
                default: str = "") -> Optional[str]:
    """Single-line text input dialog. Returns None if cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(420, 140)
    layout = QVBoxLayout(dlg)
    lbl = QLabel(label)
    layout.addWidget(lbl)
    entry = QLineEdit(default)
    layout.addWidget(entry)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    entry.setFocus()
    if dlg.exec() == QDialog.Accepted:
        return entry.text().strip() or None
    return None


def prompt_multiline(parent: QWidget, title: str, label: str,
                     default: str = "") -> Optional[str]:
    """Multi-line text input. Returns None if cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(500, 260)
    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel(label))
    edit = QPlainTextEdit(default)
    layout.addWidget(edit)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    if dlg.exec() == QDialog.Accepted:
        return edit.toPlainText().strip() or None
    return None


def pick_open_file(parent: QWidget, title: str,
                   filetypes: list[tuple[str, str]]) -> str:
    """Open-file dialog. filetypes = [("Android Package", "*.apk"), ...]."""
    flt = ";;".join(f"{name} ({pat})" for name, pat in filetypes)
    path, _ = QFileDialog.getOpenFileName(parent, title, "", flt)
    return path


def pick_save_file(parent: QWidget, title: str, default_name: str = "",
                   filetypes: list[tuple[str, str]] | None = None) -> str:
    """Save-file dialog. Returns the chosen path or empty string."""
    if filetypes:
        flt = ";;".join(f"{name} ({pat})" for name, pat in filetypes)
    else:
        flt = ""
    path, _ = QFileDialog.getSaveFileName(parent, title, default_name, flt)
    return path


# ---------------------------------------------------------------------------
# CPID prerequisites warning (firmware/root gate before any repair)
# ---------------------------------------------------------------------------
# The single firmware build the CPID flow currently supports. Mirrors the
# legacy tool's gate so users don't attempt the repair on mismatched firmware.
SUPPORTED_FIRMWARE = "BP31.250605.031"


def show_cpid_prerequisites_warning(parent: QWidget, app_config,
                                    on_continue) -> None:
    """Firmware/root prerequisites dialog shown before any CPID repair.

    Mirrors the legacy `show_cpid_prerequisites_warning` gate:
      - Firmware requirement (BP31.250605.031).
      - Root requirement (Magisk) + recommended preparation steps.
      - Post-CPID update/reset information.
      - An acknowledgement checkbox that must be ticked before Continue enables.
      - A "Don't show this warning again" checkbox bound to
        `app_config.skip_cpid_warning` (persisted on Continue).

    Guarantees:
      - No CPID/repair code runs before the user acknowledges + presses Continue.
      - Cancel (or closing the dialog) aborts the operation entirely.

    Args:
        parent: owning widget (for window parenting).
        app_config: AppConfig — its `skip_cpid_warning` flag gates/saves state.
        on_continue: zero-arg callable invoked only after acknowledgement.
    """
    # If the user previously opted out, skip straight through (still no repair
    # code runs before this returns — the caller only proceeds via on_continue).
    if app_config.skip_cpid_warning:
        on_continue()
        return

    dlg = QDialog(parent)
    dlg.setWindowTitle("CPID Prerequisites")
    dlg.resize(620, 600)
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(20, 18, 20, 16)
    outer.setSpacing(10)

    # --- Header with warning glyph + title ---
    header = QHBoxLayout()
    header.setSpacing(10)
    warn = QLabel("\u26a0\ufe0f")
    warn.setStyleSheet("font-size: 26px;")
    header.addWidget(warn)
    title = QLabel("Important: Read Before Proceeding")
    title.setProperty("role", "headline")
    # Theme-aware amber via the tertiary container role.
    terr = _scheme_color("tertiary", "#bf360c")
    title.setStyleSheet(f"color: {terr};")
    header.addWidget(title, 1)
    outer.addLayout(header)

    # --- Scrollable body ---
    body_host = QScrollArea()
    body_host.setWidgetResizable(True)
    body_host.setFrameShape(QScrollArea.NoFrame)
    body = QWidget()
    body_lay = QVBoxLayout(body)
    body_lay.setContentsMargins(0, 4, 0, 4)
    body_lay.setSpacing(4)

    def section(text: str, role_hex: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("role", "label-l")
        lbl.setStyleSheet(f"color: {role_hex};")
        body_lay.addWidget(lbl)
        return lbl

    def line(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("role", "body")
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.RichText)
        body_lay.addWidget(lbl)
        return lbl

    primary = _scheme_color("primary", "#0B57D0")
    error_c = _scheme_color("error", "#b00020")

    section("Firmware Requirements", primary)
    line("This tool is currently supported only on devices running firmware "
         "version:")
    fw = QLabel(SUPPORTED_FIRMWARE)
    mono = QFont("Consolas")
    mono.setStyleHint(QFont.Monospace)
    mono.setPointSize(12)
    mono.setBold(True)
    fw.setFont(mono)
    fw.setStyleSheet(f"color: {error_c}; padding: 2px 0 6px 6px;")
    body_lay.addWidget(fw)

    section("Before Using This Tool", primary)
    for req in (
        f"Flash your device to firmware {SUPPORTED_FIRMWARE}",
        "Obtain root access using Magisk",
        "Verify root access is functioning correctly",
        "Run the CPID process using this tool",
    ):
        line(f"\u2022 {req}")

    section("After CPID Completes Successfully", primary)
    for item in (
        "You may safely update the device to newer Android versions, "
        "including Android 17",
        "You may perform a factory reset if required",
        "The repaired IMEI information will remain intact",
    ):
        line(f"\u2022 {item}")

    section("Important Note", primary)
    line("Failure to meet the firmware and root requirements may result in "
         "the CPID process failing or producing unexpected results.")

    body_lay.addStretch()
    body_host.setWidget(body)
    outer.addWidget(body_host, 1)

    # --- Checkboxes ---
    cb_ack = QCheckBox("I understand these requirements and wish to continue.")
    cb_dont_show = QCheckBox("Don't show this warning again")

    cb_layout = QVBoxLayout()
    cb_layout.setSpacing(4)
    cb_layout.addWidget(cb_ack)
    cb_layout.addWidget(cb_dont_show)
    outer.addLayout(cb_layout)

    # --- Buttons ---
    btn_row = QHBoxLayout()
    btn_cancel = QPushButton("Cancel")
    btn_cancel.setProperty("variant", "text")
    btn_continue = QPushButton("Continue")
    btn_continue.setProperty("variant", "danger")
    btn_continue.setEnabled(False)
    btn_row.addWidget(btn_cancel)
    btn_row.addStretch()
    btn_row.addWidget(btn_continue)
    outer.addLayout(btn_row)

    # --- Wiring ---
    def on_ack_toggled(_checked: bool = False) -> None:
        btn_continue.setEnabled(cb_ack.isChecked())

    cb_ack.toggled.connect(on_ack_toggled)

    def do_cancel() -> None:
        # Abort — no repair code runs.
        dlg.reject()

    def do_continue() -> None:
        app_config.skip_cpid_warning = cb_dont_show.isChecked()
        app_config.save()
        dlg.accept()

    btn_cancel.clicked.connect(do_cancel)
    btn_continue.clicked.connect(do_continue)

    btn_cancel.setFocus()
    dlg.exec()

    # Only proceed if the user acknowledged and accepted.
    if dlg.result() == QDialog.Accepted and cb_ack.isChecked():
        on_continue()

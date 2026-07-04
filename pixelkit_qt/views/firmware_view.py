"""Firmware flashing view — flash a full Pixel factory-image ZIP in-app.

The page runs Google's entire factory-image flash sequence from inside the
application: it validates the ZIP, shows the connected device, exposes the full
option matrix, and streams every fastboot command's output into the shared
Command Matrix console — no external Command Prompt window.

Threading model mirrors ``cpid_view.py``: all long work runs on a background
``threading.Thread`` and every GUI touch (dialogs, widget updates) is marshalled
back onto the GUI thread through Qt signals, since touching widgets from a worker
thread is illegal in Qt.

Logs reach the existing LogView through the executor's ``on_console_output``
callback (already wired executor → bridge → LogView), so the firmware service's
per-line output is colorized and timestamped by the same console as every other
operation.
"""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..theme import stylesheet
from ..widgets import ActionCard, SectionTitle, dialogs
from pixelkit.services import firmware_service as fw


class FirmwareView(QWidget):
    """The Firmware page — factory-image selection, options, and flashing."""

    busy_changed = Signal(bool)

    # --- Worker → GUI marshaling signals (see module docstring) ---
    _sig_line = Signal(str, str)          # (text, level) → console
    _sig_stage = Signal(str)              # coarse stage label
    _sig_partition = Signal(str)          # current partition
    _sig_progress = Signal(float)         # 0.0–1.0
    _sig_error = Signal(str, str)         # (title, message) dialog
    _sig_info = Signal(str, str)          # (title, message) dialog
    _sig_done = Signal(bool, object)      # (success, summary dict)

    def __init__(self, executor, app_config, firmware_service, log,
                 parent=None):
        super().__init__(parent)
        self.executor = executor
        self.app_config = app_config
        self.firmware = firmware_service
        self.log = log

        self._scheme: dict = {}
        self._factory: fw.FactoryImage | None = None
        self._device: fw.FastbootDevice | None = None
        self._flashing = False

        self._build_ui()

        # Marshal worker-thread callbacks back onto the GUI thread.
        self._sig_line.connect(self._on_line)
        self._sig_stage.connect(self._on_stage)
        self._sig_partition.connect(self._on_partition)
        self._sig_progress.connect(self._on_progress)
        self._sig_error.connect(lambda t, m: dialogs.error(self, t, m))
        self._sig_info.connect(lambda t, m: dialogs.info(self, t, m))
        self._sig_done.connect(self._on_done)

    # =====================================================================
    # Layout
    # =====================================================================

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        outer.addWidget(SectionTitle("Firmware Flashing"))

        # Everything below scrolls as one column so the page stays usable on a
        # small window (device + package + options + controls + summary).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        self._col = QVBoxLayout(host)
        self._col.setContentsMargins(0, 0, 4, 0)
        self._col.setSpacing(10)

        self._banner = self._build_banner()
        self._col.addWidget(self._banner)
        self._pkg_card = self._build_package_card()
        self._col.addWidget(self._pkg_card)
        self._options_card = self._build_options_card()
        self._options_card.setVisible(False)
        self._col.addWidget(self._options_card)
        self._controls_card = self._build_controls_card()
        self._controls_card.setVisible(False)
        self._col.addWidget(self._controls_card)
        self._summary_card = self._build_summary_card()
        self._summary_card.setVisible(False)
        self._col.addWidget(self._summary_card)
        self._col.addStretch()

        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        self._refresh_option_availability()

    def _build_banner(self):
        from PySide6.QtWidgets import QFrame
        banner = QFrame()
        banner.setObjectName("SafetyBanner")
        banner.setProperty("card", True)
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(16, 10, 16, 10)
        text = QLabel(
            "<b>Caution:</b> Flashing firmware rewrites the device's system "
            "partitions. Use only the official factory image for THIS exact "
            "model, keep the device connected, and do not disconnect during "
            "flashing. A wrong image or interruption can brick the device.")
        text.setProperty("role", "body")
        text.setWordWrap(True)
        layout.addWidget(text, 1)
        dismiss = QPushButton("Dismiss")
        dismiss.setProperty("variant", "text")
        dismiss.clicked.connect(banner.hide)
        layout.addWidget(dismiss, 0, Qt.AlignTop)
        return banner

    # Device card removed as app already has one. Detection logic is kept backend-only.

    # --- Package selection card ---
    def _build_package_card(self) -> ActionCard:
        card = ActionCard("Firmware Package",
                          "Official Pixel factory-image ZIP", columns=1)
        self._pkg_path_label = QLabel("No package selected.")
        self._pkg_path_label.setProperty("role", "caption")
        self._pkg_path_label.setWordWrap(True)
        card.layout().addWidget(self._pkg_path_label)

        row = QHBoxLayout()
        browse = QPushButton("Browse…")
        browse.setProperty("variant", "tonal")
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self.browse_package)
        row.addWidget(browse)
        self._btn_validate = QPushButton("Validate")
        self._btn_validate.setProperty("variant", "outlined")
        self._btn_validate.setCursor(Qt.PointingHandCursor)
        self._btn_validate.setEnabled(False)
        self._btn_validate.clicked.connect(self.validate_package)
        row.addWidget(self._btn_validate)
        row.addStretch()
        card.layout().addLayout(row)

        self._pkg_status = QLabel("")
        self._pkg_status.setProperty("role", "body")
        self._pkg_status.setWordWrap(True)
        self._pkg_status.setTextFormat(Qt.RichText)
        card.layout().addWidget(self._pkg_status)
        return card

    # --- Options card ---
    def _build_options_card(self) -> ActionCard:
        card = ActionCard("Flashing Options", "", columns=1)
        self._opt: dict[str, QCheckBox] = {}

        def add(key: str, text: str, checked=False, tip=""):
            cb = QCheckBox(text)
            cb.setChecked(checked)
            if tip:
                cb.setToolTip(tip)
            cb.toggled.connect(self._refresh_option_availability)
            card.layout().addWidget(cb)
            self._opt[key] = cb

        add("wipe", "Wipe user data (-w) — factory reset",
            tip="Erases all user data. Leave off to preserve data.")
        add("both_slots", "Flash both slots (--slot all)",
            tip="Flash to both A and B slots in one pass.")
        add("inactive_slot", "Flash inactive slot only (--set-active=other)",
            tip="Switch to the other slot before flashing.")
        add("skip_reboot", "Do not reboot after flashing",
            tip="Leave the device in the bootloader when finished.")
        add("skip_bootloader", "Skip bootloader flashing",
            tip="Do not reflash the bootloader partition.")
        add("skip_radio", "Skip radio flashing",
            tip="Do not reflash the radio/modem partition.")
        add("force", "Force flashing (--force)",
            tip="Override safety checks on the update step.")
        add("disable_verity", "Disable dm-verity (--disable-verity)")
        add("disable_verification",
            "Disable verification (--disable-verification)")
        add("verify_device", "Verify device before flashing", checked=True,
            tip="Confirm a matching device is in fastboot mode first.")
        add("dry_run", "Dry run (log commands, do not execute)",
            tip="Preview the exact fastboot commands without flashing.")
        return card

    # --- Controls card (progress + flash/cancel) ---
    def _build_controls_card(self) -> ActionCard:
        card = ActionCard("Flash", "", columns=1)
        self._status_label = QLabel("Ready")
        self._status_label.setProperty("role", "body")
        self._status_label.setWordWrap(True)
        card.layout().addWidget(self._status_label)

        self._current_cmd = QLabel("Idle")
        self._current_cmd.setProperty("role", "caption")
        self._current_cmd.setWordWrap(True)
        card.layout().addWidget(self._current_cmd)

        row = QHBoxLayout()
        self._btn_flash = QPushButton("Flash Firmware")
        self._btn_flash.setProperty("variant", "danger")
        self._btn_flash.setCursor(Qt.PointingHandCursor)
        self._btn_flash.clicked.connect(self.start_flash)
        row.addWidget(self._btn_flash)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setProperty("variant", "outlined")
        self._btn_cancel.setCursor(Qt.PointingHandCursor)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self.cancel_flash)
        row.addWidget(self._btn_cancel)
        row.addStretch()
        card.layout().addLayout(row)
        return card

    # --- Summary card ---
    def _build_summary_card(self) -> ActionCard:
        card = ActionCard("Flashing Summary", "", columns=1)
        self._summary_label = QLabel("")
        self._summary_label.setProperty("role", "body")
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextFormat(Qt.RichText)
        card.layout().addWidget(self._summary_label)
        return card

    # =====================================================================
    # Theme
    # =====================================================================

    def update_colors(self, scheme: dict) -> None:
        """Re-tint the safety banner from the active M3 scheme."""
        self._scheme = scheme
        err = scheme.get("error", "#b00020")
        self._banner.setStyleSheet(
            f"QFrame#SafetyBanner {{ "
            f"background-color: {stylesheet.rgba(err, 0.10)}; "
            f"border: 1px solid {stylesheet.rgba(err, 0.35)}; "
            f"border-radius: 12px; }}")

    # =====================================================================
    # Device detection
    # =====================================================================

    def on_device_status(self, device_info) -> None:
        """Slot for the app's device_status signal — refresh on any change."""
        # Only auto-probe fastboot details when the device is in fastboot mode;
        # otherwise just clear the fastboot-specific fields.
        if device_info is not None and getattr(
                device_info, "connection_type", "") == "Fastboot":
            self.refresh_device()
        else:
            self._device = None
            self._render_device(None,
                                android=getattr(device_info, "android_version",
                                                "") if device_info else "")

    def refresh_device(self) -> None:
        """Read fastboot details on a worker thread (shells out)."""
        def work():
            try:
                dev = fw.detect_fastboot_device(self.executor)
            except Exception:
                dev = None
            self._device = dev
            # Marshal the render back to the GUI thread.
            self._sig_stage.emit("__render_device__")
        threading.Thread(target=work, daemon=True).start()

    def _render_device(self, dev, android: str = "") -> None:
        pass

    # =====================================================================
    # Package selection & validation
    # =====================================================================

    def browse_package(self) -> None:
        path = dialogs.pick_open_file(
            self, "Select Pixel Factory Image ZIP",
            [("Factory Image", "*.zip"), ("All files", "*.*")])
        if not path:
            return
        self._pkg_path_label.setText(path)
        self._btn_validate.setEnabled(True)
        self._pkg_status.setText("")
        self._factory = None
        self._options_card.setVisible(False)
        self._controls_card.setVisible(False)
        # Auto-validate for immediate feedback.
        self.validate_package()

    def validate_package(self) -> None:
        path = self._pkg_path_label.text()
        if not path or path == "No package selected.":
            dialogs.error(self, "No Package", "Select a firmware ZIP first.")
            return
        self._pkg_status.setText("Validating package…")

        def work():
            factory = fw.validate_package(path)
            self._factory = factory
            self._sig_stage.emit("__render_validation__")
        threading.Thread(target=work, daemon=True).start()

    def _render_validation(self) -> None:
        f = self._factory
        if f is None:
            return
        v = f.validation
        parts: list[str] = []
        ok = stylesheet.rgba(self._scheme.get("primary", "#0B57D0"), 1.0) \
            if self._scheme else "#0B57D0"
        err = self._scheme.get("error", "#b00020") if self._scheme else "#b00020"
        warn = self._scheme.get("tertiary", "#bf6f00") if self._scheme else "#bf6f00"

        if f.codename:
            parts.append(
                f"<b>{f.marketing_name}</b> "
                f"(<code>{f.codename}</code>) · build <code>{f.build_id}</code>")
        if v.ok:
            parts.append(f"<span style='color:{ok}'>✓ Package is valid.</span>")
            if v.found_images:
                shown = ", ".join(v.found_images[:8])
                more = "" if len(v.found_images) <= 8 else \
                    f" (+{len(v.found_images) - 8} more)"
                parts.append(f"<span style='color:{ok}'>Found:</span> "
                             f"<code>{shown}</code>{more}")
        for e in v.errors:
            parts.append(f"<span style='color:{err}'>✗ {e}</span>")
        for w in v.warnings:
            parts.append(f"<span style='color:{warn}'>⚠ {w}</span>")
        self._pkg_status.setText("<br>".join(parts))
        self._refresh_option_availability()
        
        # Show options and controls cards only if package is valid
        is_valid = bool(f and f.is_valid)
        self._options_card.setVisible(is_valid)
        self._controls_card.setVisible(is_valid)

    # =====================================================================
    # Options availability
    # =====================================================================

    def _refresh_option_availability(self, *_args) -> None:
        """Disable options that are incompatible with each other or the package."""
        opt = getattr(self, "_opt", None)
        if not opt:
            return
        # both_slots ⊕ inactive_slot are mutually exclusive.
        both = opt["both_slots"].isChecked()
        inactive = opt["inactive_slot"].isChecked()
        opt["inactive_slot"].setEnabled(not both)
        opt["both_slots"].setEnabled(not inactive)

        # skip_radio only meaningful if the package has a radio image.
        has_radio = bool(self._factory and self._factory.has_radio)
        opt["skip_radio"].setEnabled(has_radio)
        if not has_radio:
            opt["skip_radio"].setChecked(False)

        has_bl = bool(self._factory and self._factory.has_bootloader)
        opt["skip_bootloader"].setEnabled(has_bl)
        if not has_bl:
            opt["skip_bootloader"].setChecked(False)

    def _collect_options(self) -> fw.FlashOptions:
        o = self._opt
        return fw.FlashOptions(
            wipe=o["wipe"].isChecked(),
            both_slots=o["both_slots"].isChecked(),
            inactive_slot=o["inactive_slot"].isChecked(),
            skip_reboot=o["skip_reboot"].isChecked(),
            skip_bootloader=o["skip_bootloader"].isChecked(),
            skip_radio=o["skip_radio"].isChecked(),
            force=o["force"].isChecked(),
            disable_verity=o["disable_verity"].isChecked(),
            disable_verification=o["disable_verification"].isChecked(),
            dry_run=o["dry_run"].isChecked(),
            verify_device=o["verify_device"].isChecked(),
        )

    # =====================================================================
    # Flash lifecycle
    # =====================================================================

    def start_flash(self) -> None:
        if self._flashing:
            return
        if self.executor.is_busy:
            dialogs.error(self, "Busy",
                          "Another operation is currently running.")
            return

        # --- Safety gate 1: validated package ---
        if self._factory is None or not self._factory.is_valid:
            dialogs.error(
                self, "No Valid Package",
                "Select and validate a factory-image ZIP before flashing.")
            return

        options = self._collect_options()

        # --- Safety gate 2: device present + codename match ---
        if options.verify_device or not options.dry_run:
            dev = self._device
            if dev is None:
                if not dialogs.confirm(
                        self, "No Fastboot Device",
                        "No device was detected in fastboot mode. Connect the "
                        "device and boot it into the bootloader.\n\n"
                        "Continue anyway?", danger=True):
                    return
            elif dev.codename and self._factory.codename and \
                    dev.codename != self._factory.codename:
                if not dialogs.confirm(
                        self, "Device Mismatch",
                        f"The firmware is for <b>{self._factory.marketing_name}</b> "
                        f"(<code>{self._factory.codename}</code>) but the "
                        f"connected device is <b>{dev.marketing_name}</b> "
                        f"(<code>{dev.codename}</code>).<br><br>"
                        f"Flashing mismatched firmware can brick the device. "
                        f"Continue anyway?", danger=True):
                    return
            # --- Safety gate 3: bootloader locked ---
            if dev is not None and dev.unlocked is False:
                if not dialogs.confirm(
                        self, "Bootloader Locked",
                        "The bootloader appears to be <b>locked</b>. Flashing "
                        "requires an unlocked bootloader and will fail on a "
                        "locked device.<br><br>Continue anyway?", danger=True):
                    return

        # --- Safety gate 4: wipe confirmation ---
        if options.wipe:
            if not dialogs.confirm(
                    self, "Confirm Data Wipe",
                    "The wipe option (-w) will <b>erase all user data</b> on "
                    "the device. This cannot be undone.<br><br>Continue?",
                    danger=True):
                return

        # --- ARB warning for Pixel 6 family ---
        if (self._factory.codename in fw.ARB_SENSITIVE_CODENAMES
                and not options.both_slots):
            if not dialogs.confirm(
                    self, "Anti-Rollback Warning",
                    "This Pixel 6-family device is sensitive to anti-rollback "
                    "(ARB). Flashing only one slot can leave the other slot on "
                    "older firmware and risk a brick on reboot.<br><br>"
                    "Consider enabling <b>Flash both slots</b>. Continue with a "
                    "single slot anyway?", danger=True):
                return

        # --- Safety gate 5: final confirmation ---
        mode = "DRY RUN (no changes)" if options.dry_run else "flash firmware"
        if not dialogs.confirm(
                self, "Start Flashing",
                f"Ready to {mode} for "
                f"<b>{self._factory.marketing_name}</b>.<br><br>"
                f"Do not disconnect the device during the process. Proceed?"):
            return

        self._begin_flash(options)

    def _begin_flash(self, options: fw.FlashOptions) -> None:
        self._flashing = True
        self._set_controls_running(True)
        self._summary_card.setVisible(False)
        self.executor._set_busy(True)
        self.busy_changed.emit(True)
        self._status_label.setText("Starting…")
        self.log.status("--- Starting Firmware Flash ---\n")

        thread = threading.Thread(
            target=self._run_flash, args=(options,), daemon=True)
        thread.start()

    def _run_flash(self, options: fw.FlashOptions) -> None:
        try:
            self.firmware.flash(
                self._factory, self._device, options,
                on_line=lambda t, l: self._sig_line.emit(t, l),
                on_stage=lambda t: self._sig_stage.emit(t),
                on_partition=lambda p: self._sig_partition.emit(p),
                on_progress=lambda f: self._sig_progress.emit(f),
                on_error=lambda m: self._sig_error.emit("Flashing Failed", m),
                on_done=lambda ok, s: self._sig_done.emit(ok, s),
            )
        except Exception as e:  # pragma: no cover - defensive
            self._sig_error.emit("Flashing Failed", str(e))
            self._sig_done.emit(False, {"success": False, "error": str(e)})

    def cancel_flash(self) -> None:
        if not self._flashing:
            return
        if dialogs.confirm(
                self, "Cancel Flashing",
                "Cancel after the current command finishes? Interrupting a "
                "flash mid-partition can leave the device in an inconsistent "
                "state.", danger=True):
            self.firmware.cancel()
            self._current_cmd.setText("Cancelling…")

    # =====================================================================
    # Worker → GUI slots
    # =====================================================================

    def _on_line(self, text: str, level: str) -> None:
        # Route to the shared console via the executor's callback so it reads
        # exactly like every other operation's output.
        if self.executor.on_console_output:
            self.executor.on_console_output(text, self._level_to_tag(level))

    @staticmethod
    def _level_to_tag(level: str) -> str:
        # The bridge maps CTk-style tags → M3 levels; pick tags that land on the
        # right color: status→info, command_output→success, error→error, warn→warn.
        return {
            "info": "status",
            "success": "command_output",
            "warn": "warn",
            "error": "error",
        }.get(level, "status")

    def _on_stage(self, text: str) -> None:
        # Internal render triggers reuse this signal to hop onto the GUI thread.
        if text == "__render_device__":
            self._render_device(self._device)
            return
        if text == "__render_validation__":
            self._render_validation()
            return
        self._current_cmd.setText(text)

    def _on_partition(self, name: str) -> None:
        self._status_label.setText(f"Partition: {name}")

    def _on_progress(self, fraction: float) -> None:
        if self.executor.on_progress_set:
            self.executor.on_progress_set(fraction)

    def _on_done(self, success: bool, summary) -> None:
        self._flashing = False
        self._set_controls_running(False)
        self.executor._set_busy(False)
        self.busy_changed.emit(False)
        self._current_cmd.setText("Idle")

        if summary is None:
            summary = {}
        elapsed = summary.get("elapsed", 0.0)
        parts = summary.get("partitions", [])
        ok = self._scheme.get("primary", "#0B57D0") if self._scheme else "#0B57D0"
        err = self._scheme.get("error", "#b00020") if self._scheme else "#b00020"

        lines = []
        if success:
            lines.append(f"<span style='color:{ok}'><b>✓ Flash completed "
                         f"successfully.</b></span>")
        else:
            lines.append(f"<span style='color:{err}'><b>✗ Flash failed.</b>"
                         f"</span>")
            if summary.get("error"):
                lines.append(f"<span style='color:{err}'>{summary['error']}"
                             f"</span>")
        lines.append(f"Elapsed: {elapsed:.0f}s")
        lines.append(f"Exit code: {summary.get('exit_code', 'n/a')}")
        if parts:
            lines.append("Flashed: <code>" + ", ".join(parts) + "</code>")
        self._summary_label.setText("<br>".join(lines))
        self._summary_card.setVisible(True)
        self._status_label.setText("Done" if success else "Failed")
        if self.executor.on_progress_stop:
            self.executor.on_progress_stop()

    def _set_controls_running(self, running: bool) -> None:
        self._btn_flash.setEnabled(not running)
        self._btn_cancel.setEnabled(running)
        self._btn_validate.setEnabled(not running)

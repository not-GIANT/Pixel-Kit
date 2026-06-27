"""CPID view — IMEI repair for Pixel 6/7-9/10, three sub-panels.

Mirrors the legacy nested-tab structure as a horizontal segmented control:
  - Pixel CPID   : Pixel 7-9 IMEI repair (10-step service sequence)
  - Pixel 6      : DevInfo template editor (offline patch + export)
  - Pixel 10     : Pixel 10 IMEI repair (8-step service sequence)

Every flow preserves the legacy safety gates:
  - Mandatory legal/prerequisites warning before any repair.
  - ADB-mode + root pre-flight checks.
  - IMEI validation (15-digit numeric).
  - Confirm dialog before the destructive multi-stage sequence.

Progress is shown via a dedicated StepIndicator instead of overloading the
global progress bar, since CPID is a deterministic N-step sequence.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from ..widgets import (ActionCard, LabeledField, SectionTitle, StepIndicator,
                       dialogs)


# ---------------------------------------------------------------------------
# Legal warning text — shown before any CPID repair (matches legacy intent).
# ---------------------------------------------------------------------------
LEGAL_WARNING = (
    "<b>⚠ IMEI Repair — Legal & Safety Notice</b><br><br>"
    "Changing a device's IMEI is <b>illegal in many jurisdictions</b> and may "
    "constitute fraud, theft recovery evasion, or warranty violation. This "
    "tool is intended <b>only</b> for:<br>"
    "• Repairing a corrupt/lost IMEI on a device you legitimately own.<br>"
    "• Authorized testing and research.<br><br>"
    "You are solely responsible for compliance with local law. The author "
    "accepts no liability for misuse.<br><br>"
    "The repair reboots the device several times and modifies modem/NVRAM "
    "partitions. A backup is strongly recommended. Proceed at your own risk."
)


class CpidView(QWidget):
    """The CPID page — three sub-panels under a segmented control."""

    # Emitted when a long CPID sequence wants the global UI to show busy state.
    busy_changed = Signal(bool)

    # --- Worker→GUI marshaling signals ---
    # The repair flows run on background threads; touching widgets/dialogs from
    # there is illegal in Qt (the parent widget lives in the GUI thread, hence
    # "Cannot set parent, new parent is in a different thread"). These signals
    # hop back to the GUI thread via Qt's queued-connection mechanism.
    _show_info = Signal(str, str)   # (title, message)
    _show_error = Signal(str, str)  # (title, message)
    _step_idle = Signal(str)        # (message)

    def __init__(self, executor, app_config, cpid_service, pixel10_service,
                 log, parent=None):
        super().__init__(parent)
        self.executor = executor
        self.app_config = app_config
        self.cpid_service = cpid_service
        self.pixel10_service = pixel10_service
        self.log = log
        self._p6_template_data: bytes | None = None
        self._build_ui()

        # Marshal worker-thread GUI touches back to the GUI thread. Each signal
        # below is emitted from a background thread and delivered to a slot that
        # runs on the GUI thread (queued connection), so dialogs and widgets are
        # only ever touched from the thread that owns them.
        self._show_info.connect(self._on_show_info)
        self._show_error.connect(self._on_show_error)
        self._step_idle.connect(self.step_indicator.set_idle)

    # =====================================================================
    # Layout
    # =====================================================================

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        outer.addWidget(SectionTitle("CPID IMEI Repair"))

        # Shared step indicator at the top of the page.
        self.step_indicator = StepIndicator()
        outer.addWidget(self.step_indicator)

        # Segmented sub-navigation (Pixel CPID / Pixel 6 / Pixel 10).
        self._seg_group = QButtonGroup(self)
        self._seg_group.setExclusive(True)
        seg_row = QHBoxLayout()
        seg_row.setSpacing(6)
        self._seg_buttons: list[QPushButton] = []
        for i, label in enumerate(["Pixel CPID", "Pixel 6 Series", "Pixel 10 Series"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setObjectName("CategoryChip")  # reuse chip styling
            btn.clicked.connect(lambda _=False, idx=i: self._show_panel(idx))
            self._seg_group.addButton(btn)
            self._seg_buttons.append(btn)
            seg_row.addWidget(btn)
        seg_row.addStretch()
        outer.addLayout(seg_row)

        # Stacked sub-panels.
        self._stack = QStackedWidget()
        self._panel_cpid = self._build_pixel_cpid_panel()
        self._panel_p6 = self._build_pixel6_panel()
        self._panel_p10 = self._build_pixel10_panel()
        self._stack.addWidget(self._panel_cpid)
        self._stack.addWidget(self._panel_p6)
        self._stack.addWidget(self._panel_p10)
        outer.addWidget(self._stack, 1)

        self._seg_buttons[0].setChecked(True)

    def _wrap_scroll(self, panel: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(panel)
        return scroll

    def _show_panel(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    # =====================================================================
    # Panel: Pixel CPID (7-9)
    # =====================================================================

    def _build_pixel_cpid_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        card = ActionCard("Pixel CPID IMEI Repair",
                          "Pixel 7–9 series · root required", columns=1)
        # IMEI inputs
        self._cpid_imei1 = LabeledField("IMEI 1", "15-digit IMEI")
        self._cpid_imei2 = LabeledField("IMEI 2", "15-digit IMEI")
        # Place labeled fields inside the card's grid by wrapping as widgets.
        card.layout().addWidget(self._cpid_imei1)
        card.layout().addWidget(self._cpid_imei2)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._btn_backup = QPushButton("Backup Critical Files")
        self._btn_backup.setProperty("variant", "tonal")
        self._btn_backup.setCursor(Qt.PointingHandCursor)
        self._btn_backup.setToolTip("Backup EFS, devinfo, and cpsha")
        self._btn_backup.clicked.connect(self._on_backup)
        btn_row.addWidget(self._btn_backup)

        self._btn_start_cpid = QPushButton("Start Repair Sequence")
        self._btn_start_cpid.setProperty("variant", "filled")
        self._btn_start_cpid.setCursor(Qt.PointingHandCursor)
        self._btn_start_cpid.setToolTip("Begin the full 10-step IMEI CPID process")
        self._btn_start_cpid.clicked.connect(self._on_start_cpid)
        btn_row.addWidget(self._btn_start_cpid)
        card.layout().addLayout(btn_row)

        layout.addWidget(card)
        layout.addStretch()
        return self._wrap_scroll(panel)

    # =====================================================================
    # Panel: Pixel 6 DevInfo Editor
    # =====================================================================

    def _build_pixel6_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        card = ActionCard("Pixel 6 Series DevInfo Editor",
                          "Offline template patch · no device required", columns=1)

        # Model selector (segmented)
        model_label = QLabel("Select target model")
        model_label.setProperty("role", "caption")
        card.layout().addWidget(model_label)

        self._p6_model_group = QButtonGroup(self)
        self._p6_model_group.setExclusive(True)
        model_row = QHBoxLayout()
        self._p6_model_buttons: dict[str, QPushButton] = {}
        for label, model_id in [("Pixel 6", "6"), ("Pixel 6A", "6a"),
                                ("Pixel 6 Pro", "pro")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setObjectName("CategoryChip")
            btn.clicked.connect(lambda _=False, mid=model_id: self._on_p6_model(mid))
            self._p6_model_group.addButton(btn)
            self._p6_model_buttons[model_id] = btn
            model_row.addWidget(btn)
        model_row.addStretch()
        card.layout().addLayout(model_row)

        # Current template IMEIs (read-only display)
        self._p6_cur_imei1 = LabeledField("Current IMEI 1 (auto-detected)")
        self._p6_cur_imei1.entry.setReadOnly(True)
        self._p6_cur_imei2 = LabeledField("Current IMEI 2 (auto-detected)")
        self._p6_cur_imei2.entry.setReadOnly(True)
        card.layout().addWidget(self._p6_cur_imei1)
        card.layout().addWidget(self._p6_cur_imei2)

        # New IMEIs
        self._p6_new_imei1 = LabeledField("New IMEI 1", "15-digit IMEI")
        self._p6_new_imei2 = LabeledField("New IMEI 2", "15-digit IMEI")
        card.layout().addWidget(self._p6_new_imei1)
        card.layout().addWidget(self._p6_new_imei2)

        # Patch & export
        self._btn_p6_patch = QPushButton("Patch & Export DevInfo")
        self._btn_p6_patch.setProperty("variant", "filled")
        self._btn_p6_patch.setCursor(Qt.PointingHandCursor)
        self._btn_p6_patch.setToolTip("Patch the template and export devinfo.img")
        self._btn_p6_patch.clicked.connect(self._on_p6_patch)
        card.layout().addWidget(self._btn_p6_patch)

        layout.addWidget(card)
        layout.addStretch()

        # Default-select Pixel 6 and load its template.
        self._p6_model_buttons["6"].setChecked(True)
        self._on_p6_model("6")
        return self._wrap_scroll(panel)

    # =====================================================================
    # Panel: Pixel 10
    # =====================================================================

    def _build_pixel10_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        card = ActionCard("Pixel 10 Series IMEI Repair",
                          "Pixel 10 series · root required", columns=1)
        self._p10_imei1 = LabeledField("IMEI 1", "15-digit IMEI")
        self._p10_imei2 = LabeledField("IMEI 2", "15-digit IMEI")
        card.layout().addWidget(self._p10_imei1)
        card.layout().addWidget(self._p10_imei2)

        self._btn_start_p10 = QPushButton("Start Repair Sequence")
        self._btn_start_p10.setProperty("variant", "filled")
        self._btn_start_p10.setCursor(Qt.PointingHandCursor)
        self._btn_start_p10.setToolTip("Begin the full 8-step IMEI CPID process")
        self._btn_start_p10.clicked.connect(self._on_start_p10)
        card.layout().addWidget(self._btn_start_p10)

        layout.addWidget(card)
        layout.addStretch()
        return self._wrap_scroll(panel)

    # =====================================================================
    # Helpers
    # =====================================================================

    def _set_busy(self, busy: bool) -> None:
        self.executor._set_busy(busy)
        self.busy_changed.emit(busy)

    def _on_show_info(self, title: str, message: str) -> None:
        """GUI-thread slot for the worker → info-dialog signal."""
        dialogs.info(self, title, message)

    def _on_show_error(self, title: str, message: str) -> None:
        """GUI-thread slot for the worker → error-dialog signal."""
        dialogs.error(self, title, message)

    # =====================================================================
    # Pixel CPID (7-9) handlers
    # =====================================================================

    def _on_backup(self) -> None:
        if self.executor.is_busy:
            dialogs.error(self, "Busy", "Another operation is currently running.")
            return
        self.executor.stop_event.clear()
        self.log.status("--- Starting Manual Critical Backup ---\n")
        threading.Thread(target=self._run_backup, daemon=True).start()

    def _run_backup(self) -> None:
        try:
            ok = self.cpid_service.backup_critical_files(is_auto=False)
            if ok:
                self._show_info.emit(
                    "Backup Success",
                    "Critical files backed up successfully.")
        except Exception as e:
            self.log.error(f"\nBackup failed: {e}\n")
            self._show_error.emit("Backup Failed", str(e))

    def _on_start_cpid(self) -> None:
        if self.executor.is_busy:
            dialogs.error(self, "Busy", "Another operation is currently running.")
            return
        # Firmware/root prerequisites gate — runs BEFORE any validation or
        # repair logic. The user must acknowledge; Cancel aborts entirely and
        # no CPID code runs. Respects app_config.skip_cpid_warning.
        dialogs.show_cpid_prerequisites_warning(
            self, self.app_config, on_continue=self._continue_start_cpid)

    def _continue_start_cpid(self) -> None:
        """Runs after the firmware prerequisites warning is acknowledged."""
        # Legal warning gate.
        if not dialogs.confirm(self, "CPID IMEI Repair — Please Read",
                               LEGAL_WARNING, danger=True):
            return
        imei1 = self._cpid_imei1.text()
        imei2 = self._cpid_imei2.text()
        if not (imei1.isdigit() and len(imei1) == 15 and
                imei2.isdigit() and len(imei2) == 15):
            dialogs.error(self, "Invalid Input",
                          "Please enter two valid 15-digit IMEIs.")
            return
        # Persist IMEIs to the list file (matches legacy behavior).
        try:
            list_file = self.app_config.resources_dir / "imei_list.txt"
            with open(list_file, "a") as f:
                f.write(f"IMEI1: {imei1}, IMEI2: {imei2}\n")
        except Exception as e:
            self.log.error(f"Warning: Failed to save IMEIs to list: {e}\n")

        if not dialogs.confirm(self, "Confirm CPID Repair",
                               "This is a complex multi-stage operation that will "
                               "reboot your device several times.\n\nProceed?"):
            return

        self.step_indicator.configure(10)
        threading.Thread(target=self._run_cpid_repair,
                         args=(imei1, imei2), daemon=True).start()

    def _run_cpid_repair(self, imei1: str, imei2: str) -> None:
        self._set_busy(True)
        self.executor.stop_event.clear()
        self.log.status("--- Starting Pixel CPID Repair Sequence ---\n")
        try:
            self.cpid_service.run_cpid_repair(imei1, imei2)
            self._show_info.emit(
                "Success",
                "IMEI Repair completed. Device is rebooting to normal mode.")
        except Exception as e:
            self.log.error(f"\nFATAL ERROR during repair: {e}\n")
            self._show_error.emit("Repair Failed", f"An error occurred: {e}")
        finally:
            self._set_busy(False)
            self._step_idle.emit("Repair finished")

    # =====================================================================
    # Pixel 6 handlers
    # =====================================================================

    def _on_p6_model(self, model_id: str) -> None:
        try:
            template_data, imei1, imei2, records = \
                self.cpid_service.load_pixel6_template(model_id)
            self._p6_template_data = template_data
            self._p6_cur_imei1.set_text(imei1 or "")
            self._p6_cur_imei2.set_text(imei2 or "")
            if imei1 and not imei2:
                dialogs.info(self, "Partial Match",
                             "Only one IMEI slot detected in this template.")
            elif not imei1 and not imei2:
                dialogs.info(self, "Detection Failed",
                             "No IMEI records found in the selected template.")
        except Exception as e:
            dialogs.error(self, "Error", f"Failed to load template: {e}")

    def _on_p6_patch(self) -> None:
        if not self._p6_template_data:
            dialogs.error(self, "Selection Required",
                          "Please select a device model to begin.")
            return
        # Determine selected model name from the checked button.
        selected_name = "Pixel 6"
        for label, btn in [("Pixel 6", "6"), ("Pixel 6A", "6a"), ("Pixel 6 Pro", "pro")]:
            if self._p6_model_buttons[btn].isChecked():
                selected_name = label
                break
        new_imei1 = self._p6_new_imei1.text()
        new_imei2 = self._p6_new_imei2.text()
        try:
            patched_bytes, dest_path = self.cpid_service.patch_and_export_pixel6(
                self._p6_template_data, new_imei1, new_imei2)
        except ValueError as e:
            dialogs.error(self, "Validation Error", str(e))
            return
        if not dialogs.confirm(self, "Confirm Patch & Export",
                               f"Patch {selected_name} template with new IMEIs "
                               f"and export devinfo.img?"):
            return
        try:
            with open(dest_path, "wb") as f:
                f.write(patched_bytes)
            self._p6_template_data = patched_bytes
            self._p6_cur_imei1.set_text(new_imei1)
            self._p6_cur_imei2.set_text(new_imei2)
            self._p6_new_imei1.set_text("")
            self._p6_new_imei2.set_text("")
            dialogs.info(self, "Export Successful",
                         f"DevInfo patched and exported to:\n{dest_path.absolute()}")
        except Exception as e:
            dialogs.error(self, "Export Failed", str(e))

    # =====================================================================
    # Pixel 10 handlers
    # =====================================================================

    def _on_start_p10(self) -> None:
        if self.executor.is_busy:
            dialogs.error(self, "Busy", "Another operation is currently running.")
            return
        # Firmware/root prerequisites gate — same as Pixel 7-9. Runs before any
        # validation or repair logic; Cancel aborts with no code executing.
        dialogs.show_cpid_prerequisites_warning(
            self, self.app_config, on_continue=self._continue_start_p10)

    def _continue_start_p10(self) -> None:
        """Runs after the firmware prerequisites warning is acknowledged."""
        if not dialogs.confirm(self, "CPID IMEI Repair — Please Read",
                               LEGAL_WARNING, danger=True):
            return
        imei1 = self._p10_imei1.text()
        imei2 = self._p10_imei2.text()
        if not imei1 or not imei2:
            dialogs.error(self, "Input Required",
                          "Please enter both IMEI 1 and IMEI 2.")
            return
        if len(imei1) != 15 or len(imei2) != 15 or \
                not imei1.isdigit() or not imei2.isdigit():
            dialogs.error(self, "Invalid IMEI", "IMEIs must be exactly 15 digits.")
            return
        self.step_indicator.configure(8)
        threading.Thread(target=self._run_p10_repair,
                         args=(imei1, imei2), daemon=True).start()

    def _run_p10_repair(self, imei1: str, imei2: str) -> None:
        self._set_busy(True)
        try:
            self.pixel10_service.run_full_repair(
                imei1=imei1, imei2=imei2,
                progress_callback=None,
                log_func=self.log.info,
                error_func=lambda m: self.log.error(f"\nERROR: {m}\n"),
            )
            self._show_info.emit("Success", "Pixel 10 CPID repair completed.")
        except Exception as e:
            self.log.error(f"\nFATAL ERROR during Pixel 10 repair: {e}\n")
            self._show_error.emit("Repair Failed", f"An error occurred: {e}")
        finally:
            self._set_busy(False)
            self._step_idle.emit("Repair finished")

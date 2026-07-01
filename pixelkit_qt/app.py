"""Pixel Kit — Qt/PySide6 + Material 3 main window.

Phase 1 proof-of-concept: wires the existing framework-agnostic services
(CommandExecutor, DeviceMonitor) to a Qt window via QtBridge, and exposes
a single working action (ADB "List Devices") to verify end-to-end streaming.

The full view set (ADB / Fastboot / CPID / Flashing) lands in later phases;
this shell proves the bridge, theming, and console all work with real device
output before we rebuild the rest.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QMainWindow, QMenu,
                               QMenuBar, QMessageBox, QProgressBar, QPushButton,
                               QSizePolicy, QSplitter, QStackedWidget,
                               QStatusBar, QVBoxLayout, QWidget)

# pixelkit_qt is a sibling of the legacy pixelkit package and shares its
# unchanged services layer (config, logger, services). Use absolute imports.
from pixelkit.config import AppConfig
from pixelkit.logger import PixelKitLogger
from pixelkit.services.command_executor import CommandExecutor
from pixelkit.services.cpid_service import CpidService
from pixelkit.services.pixel10_service import Pixel10Service
from pixelkit.services.device_monitor import DeviceMonitor

from .bridge import QtBridge
from .theme import ThemeManager, tokens, icons
from .views import AdbView, FastbootView, FlashingView, CpidView
from .widgets import DeviceCard, LogView, NavRail

APP_TITLE = "Pixel Kit"
APP_VERSION = "v3.8 (Qt/M3)"


class MainWindow(QMainWindow):
    """Top-level window — menu bar, device card, action area, log, status bar."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PixelKit-3.8 by GIANT")
        # Compact default sized for a 13" laptop (~1366×768). The content is
        # dense (device card + 2×2 action-card grid + console), so we keep the
        # window small rather than forcing maximize. Minimums ensure every
        # card stays visible without maximization.
        self.resize(1040, 700)
        self.setMinimumSize(880, 560)

        # --- App resources (config, logger, services) ---
        self.app_config = AppConfig()

        # Window icon — from the bundled icon.png (root or resources/).
        icon_path = self._resolve_icon_path()
        if icon_path:
            self.setWindowIcon(icons.window_icon_from_png(icon_path))

        log_dir = self.app_config.persistent_dir / "logs"
        self.log = PixelKitLogger(
            console_callback=lambda text, tag=None: None,  # log file only here
            log_dir=str(log_dir),
        )
        self.executor = CommandExecutor(self.app_config, log=self.log)
        self.cpid_service = CpidService(self.executor, self.app_config, log=self.log)
        self.pixel10_service = Pixel10Service(self.executor, self.app_config, log=self.log)
        self.device_monitor = DeviceMonitor(
            self.executor, log=self.log, on_status_change=None)

        # --- Qt bridge: services callbacks → Qt signals ---
        self.bridge = QtBridge()
        self.bridge.bind_executor(self.executor)
        self.bridge.bind_device_monitor(self.device_monitor)

        # --- Theme (initial stylesheet only; the change listener is wired
        # after the widgets exist, since it re-paints live widgets) ---
        self.theme = ThemeManager(
            QApplication.instance(), seed=tokens.SEED,
            dark=(self.app_config.theme.lower() == "dark"))
        self.theme.apply()

        # --- Build UI ---
        self._build_menu_bar()
        self._build_central()
        self._build_status_bar()

        # Now that the widgets exist, subscribe them to future theme changes.
        self.theme.on_change(self._on_theme_change)
        # Repaint once with the current scheme so colors are correct on startup.
        self._on_theme_change(self.theme.scheme)

        # Verify tools & start device polling AFTER the first paint, so the
        # window appears immediately instead of blocking on adb shell calls
        # during construction. singleShot(0) runs once the event loop is idle.
        # The tools check must complete BEFORE the monitor starts: the monitor
        # reads executor.cached_paths to locate adb/fastboot, and if it polls
        # before check_tools() populates that cache its first probe silently
        # fails (so the device shows "Disconnected" until the next cycle).
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._check_tools_then_monitor)

        self.bridge.busy_warning.connect(
            lambda: QMessageBox.warning(self, "Busy",
                                        "Another operation is currently running."))

    # =====================================================================
    # UI construction
    # =====================================================================

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()

        # Theme menu
        theme_menu = mb.addMenu("&Theme")
        self.act_toggle = QAction("Toggle &Dark Mode", self)
        self.act_toggle.setShortcut(QKeySequence("Ctrl+T"))
        self.act_toggle.triggered.connect(self.theme.toggle_mode)
        theme_menu.addAction(self.act_toggle)

        # Help menu
        help_menu = mb.addMenu("&Help")
        act_drivers = QAction("&Install Drivers...", self)
        act_drivers.triggered.connect(self._show_install_drivers)
        help_menu.addAction(act_drivers)
        help_menu.addSeparator()
        act_about = QAction("&About", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _build_central(self) -> None:
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Left: navigation rail ---
        self.nav_rail = NavRail()
        root.addWidget(self.nav_rail)

        # --- Middle+Right: splitter (content | console), user-resizable ---
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # --- Content zone: device card on top + stacked views below ---
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(14, 10, 8, 10)
        content_layout.setSpacing(10)

        self.device_card = DeviceCard()
        content_layout.addWidget(self.device_card)
        # Live device state: the monitor (polled in a background thread) emits
        # DeviceInfo through the bridge; route each update to the card. Without
        # this connection the card never refreshes and stays "Disconnected".
        self.bridge.device_status.connect(self.device_card.update_device)

        # Stacked pages driven by the nav rail. Phase 3 adds more.
        self.page_stack = QStackedWidget()
        self.page_adb = AdbView(self.executor, self.app_config)
        self.page_stack.addWidget(self.page_adb)
        self.page_fastboot = FastbootView(self.executor, self.app_config)
        self.page_stack.addWidget(self.page_fastboot)
        self.page_flashing = FlashingView(self.executor, self.app_config)
        self.page_stack.addWidget(self.page_flashing)
        self.page_cpid = CpidView(
            self.executor, self.app_config,
            self.cpid_service, self.pixel10_service, self.log)
        self.page_stack.addWidget(self.page_cpid)
        content_layout.addWidget(self.page_stack, 1)
        splitter.addWidget(content)

        # --- Right: persistent console + progress + stop ---
        console_zone = QWidget()
        console_layout = QVBoxLayout(console_zone)
        console_layout.setContentsMargins(8, 10, 14, 10)
        console_layout.setSpacing(8)

        self.log_view = LogView(title="Command Matrix")
        self.bridge.console_output.connect(self.log_view.append)
        console_layout.addWidget(self.log_view, 1)

        # Inline action row: stop button + progress bar.
        ctrl = QHBoxLayout()
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setProperty("variant", "danger")
        self.btn_stop.clicked.connect(self.executor.stop_current_command)
        ctrl.addWidget(self.btn_stop)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        ctrl.addWidget(self.progress, 1)
        console_layout.addLayout(ctrl)
        splitter.addWidget(console_zone)

        # Weight: content gets most of the width; console ~36%.
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([620, 380])

        # Wire nav rail → page switching. Each destination gets a themed icon.
        self.nav_rail.add_item(icons.icon_for("nav-adb"), "ADB")
        self.nav_rail.add_item(icons.icon_for("nav-fastboot"), "Fastboot")
        self.nav_rail.add_item(icons.icon_for("nav-flashing"), "Flashing")
        self.nav_rail.add_item(icons.icon_for("nav-cpid"), "CPID")
        self.nav_rail.page_changed.connect(self._on_nav_change)
        self.nav_rail.select(0)

    def _build_status_bar(self) -> None:
        sb = QStatusBar(self)
        self.setStatusBar(sb)
        sb.showMessage("Ready")

        # Wire footer/progress signals from the bridge.
        self.bridge.footer_status.connect(
            lambda text, color: sb.showMessage(text))
        self.bridge.progress_set.connect(
            lambda v: self.progress.setValue(int(v * 100)))
        self.bridge.progress_stop.connect(lambda: self.progress.setValue(0))
        self.bridge.command_done.connect(
            lambda: sb.showMessage("Ready") or self.progress.setValue(0))

    # =====================================================================
    # Actions
    # =====================================================================

    def _on_nav_change(self, index: int) -> None:
        """Switch the stacked page to the selected nav destination.

        Switching is instant. We deliberately do NOT animate the incoming page
        with a QGraphicsOpacityEffect: combining a graphics effect with a
        QStackedWidget caches each page's offscreen render, and on Windows the
        previous page's content bleeds through as the new page's background —
        so e.g. clicking Fastboot showed the ADB buttons under the Fastboot
        header. Instant switching is also the M3 nav-rail convention.
        """
        pages = {0: self.page_adb, 1: self.page_fastboot,
                 2: self.page_flashing, 3: self.page_cpid}
        page = pages.get(index)
        if page is None:
            return
        self.page_stack.setCurrentWidget(page)

    def _check_tools_then_monitor(self) -> None:
        """Verify platform-tools exist, then start device monitoring.

        Runs the tools check on a worker thread (it shells out) and only
        starts the DeviceMonitor once the tool paths are cached — otherwise
        the monitor's first probe can't find adb/fastboot and the device
        card stays "Disconnected" for a full poll cycle on startup.
        """
        def _check():
            try:
                self.executor.check_tools()
                self.bridge.console_output.emit(
                    "ADB / Fastboot / Scrcpy ready.\n", "info")
            except Exception as e:
                self.bridge.console_output.emit(
                    f"[tools check failed] {e}\n", "error")
            finally:
                # Start polling only after the cache is populated (or the
                # check failed; the monitor tolerates missing tools).
                self.device_monitor.start()

        threading.Thread(target=_check, daemon=True).start()

    def _resolve_icon_path(self):
        """Locate icon.png — prefer the persistent dir, fall back to resources."""
        from pathlib import Path
        candidates = [
            self.app_config.persistent_dir / "icon.png",
            self.app_config.resources_dir / "icon.png",
        ]
        for p in candidates:
            if Path(p).exists():
                return p
        return None

    # =====================================================================
    # Theme & dialogs
    # =====================================================================

    def _on_theme_change(self, scheme: dict) -> None:
        """Re-paint widgets that QSS can't fully reach.

        Single dispatch point for all theme-aware widgets. Every widget that
        paints its own colors (rather than relying purely on QSS) is refreshed
        here from the active M3 scheme — no hardcoded colors anywhere.
        """
        # Log view: per-level colors + the timestamp-gutter color.
        self.log_view.set_level_colors({
            "info": scheme.get("primary", "#0061e6"),
            "success": scheme.get("on_surface", "#000000"),
            "warn": scheme.get("error", "#98000a"),
            "error": scheme.get("error", "#98000a"),
        })
        self.log_view.set_scheme(scheme)

        # Update the theme toggle menu action text based on current mode.
        if hasattr(self, "act_toggle"):
            if self.theme.dark:
                self.act_toggle.setText("Toggle &Light Mode")
            else:
                self.act_toggle.setText("Toggle &Dark Mode")
        # Device card: connection-state chip (re-applies the current state).
        self.device_card.update_colors(scheme)
        # Flashing view: dismissible safety banner tint.
        self.page_flashing.update_colors(scheme)
        # Persist the new mode.
        self.app_config.theme = "Dark" if self.theme.dark else "Light"
        self.app_config.save()

    def _show_about(self) -> None:
        """Open the rich About dialog (Features / Changelog / Contact)."""
        from .widgets import show_about
        show_about(parent=self, window_icon=self.windowIcon())

    def _show_install_drivers(self) -> None:
        """Open the ADB & Fastboot driver installer dialog."""
        from .widgets import InstallDriversDialog
        dlg = InstallDriversDialog(parent=self, config=self.app_config, log=self.log)
        dlg.exec()

    # =====================================================================
    # Lifecycle
    # =====================================================================

    def closeEvent(self, event) -> None:
        self.device_monitor.stop()
        self.app_config.window_position = (
            f"{self.width()}x{self.height()}+{self.x()}+{self.y()}")
        self.app_config.save()
        if self.executor.current_process:
            try:
                self.executor.current_process.terminate()
            except Exception:
                pass
        super().closeEvent(event)


def launch() -> int:
    """Application entry point."""
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    import sys
    sys.exit(launch())

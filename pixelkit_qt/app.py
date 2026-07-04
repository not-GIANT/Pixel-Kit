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
from pixelkit.services.firmware_service import FirmwareService
from pixelkit.services.device_monitor import DeviceMonitor

from .bridge import QtBridge
from .theme import ThemeManager, tokens, icons
from .views import AdbView, FastbootView, FlashingView, CpidView, FirmwareView
from .widgets import DeviceCard, LogView, NavRail

APP_TITLE = "Pixel Kit"
APP_VERSION = "v3.9 (Qt/M3)"


class MainWindow(QMainWindow):
    """Top-level window — menu bar, device card, action area, log, status bar."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PixelKit-3.9 by GIANT")
        # Minimum size keeps every card visible without maximisation.
        # The actual launch size/position is restored from the saved config
        # below (falls back to 1040×700 centred if no config exists yet).
        self.setMinimumSize(940, 560)

        # --- App resources (config, logger, services) ---
        self.app_config = AppConfig()

        # Window icon — from the bundled icon.png (root or resources/).
        icon_path = self._resolve_icon_path()
        if icon_path:
            self.setWindowIcon(icons.window_icon_from_png(icon_path))

        log_dir = self.app_config.persistent_dir / "logs"
        self.log = PixelKitLogger(
            console_callback=lambda text, tag=None: None,  # placeholder; rewired below
            log_dir=str(log_dir),
        )
        self.executor = CommandExecutor(self.app_config, log=self.log)
        self.cpid_service = CpidService(self.executor, self.app_config, log=self.log)
        self.pixel10_service = Pixel10Service(self.executor, self.app_config, log=self.log)
        self.firmware_service = FirmwareService(self.executor, self.app_config, log=self.log)
        self.device_monitor = DeviceMonitor(
            self.executor, log=self.log, on_status_change=None)

        # --- Qt bridge: services callbacks → Qt signals ---
        self.bridge = QtBridge()
        self.bridge.bind_executor(self.executor)
        self.bridge.bind_device_monitor(self.device_monitor)

        # Now that the bridge exists, rewire the logger's console_callback so
        # that direct log calls (e.g. from CpidService._log, which calls
        # self.log.info/status/error directly instead of going through the
        # executor's on_console_output callback) also appear in the GUI console.
        self.log.console_callback = self.bridge._emit_console

        # --- Theme (initial stylesheet only; the change listener is wired
        # after the widgets exist, since it re-paints live widgets) ---
        self.theme = ThemeManager(
            QApplication.instance(), seed=tokens.SEED,
            dark=(self.app_config.theme.lower() == "dark"))
        self.theme.apply()

        # --- Restore window geometry (size + position) from config.
        # Done BEFORE the UI is built so the initial paint already uses the
        # saved size — this avoids a flicker from resize(1040,700) → saved.
        self._restore_window_state()

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
        content.setMinimumWidth(550)
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
        self.page_firmware = FirmwareView(
            self.executor, self.app_config,
            self.firmware_service, self.log)
        self.page_stack.addWidget(self.page_firmware)
        self.bridge.device_status.connect(self.page_firmware.on_device_status)
        content_layout.addWidget(self.page_stack, 1)
        splitter.addWidget(content)

        # --- Right: persistent console + progress + stop ---
        console_zone = QWidget()
        console_zone.setMinimumWidth(300)
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

        # Keep a reference so closeEvent can persist the splitter position.
        self.splitter = splitter

        # Weight: content gets most of the width; console ~36%.
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # Restore saved splitter sizes (falls back to a good default).
        saved_split = self.app_config.config_data.get("splitter_sizes")
        if saved_split and len(saved_split) == 2:
            splitter.setSizes(saved_split)
        else:
            splitter.setSizes([550, 557])

        # Wire nav rail → page switching. Each destination gets a themed icon.
        self.nav_rail.add_item(icons.icon_for("nav-adb"), "ADB", "nav-adb")
        self.nav_rail.add_item(icons.icon_for("nav-fastboot"), "Fastboot", "nav-fastboot")
        self.nav_rail.add_item(icons.icon_for("nav-flashing"), "Flashing", "nav-flashing")
        self.nav_rail.add_item(icons.icon_for("nav-cpid"), "CPID", "nav-cpid")
        self.nav_rail.add_item(icons.icon_for("nav-firmware"), "Firmware", "nav-firmware")
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
                 2: self.page_flashing, 3: self.page_cpid,
                 4: self.page_firmware}
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
        # Custom-calibrated developer console palettes for maximum contrast and vivid colors.
        is_dark = self.theme.dark
        if is_dark:
            log_colors = {
                "info": "#38BDF8",       # Vibrant Electric Sky Blue (system messages, status headers)
                "success": "#F8FAFC",    # Clean, crisp off-white (standard command stdout)
                "warn": "#FBBF24",       # Bright amber-gold (warnings)
                "error": "#F87171",      # Vivid pastel red-coral (errors)
                "on_surface_variant": "#94A3B8",  # Muted slate-400 (fallback)
            }
        else:
            log_colors = {
                "info": "#0D47A1",       # Deep Cobalt Blue (system messages, status headers)
                "success": "#0F172A",    # Rich Dark Slate/Charcoal (standard command stdout)
                "warn": "#B45309",       # Warm Amber-Brown (warnings)
                "error": "#B91C1C",      # Deep Crimson Red (errors)
                "on_surface_variant": "#475569",  # Slate-600 (fallback)
            }
        self.log_view.set_level_colors(log_colors)
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
        # Firmware view: dismissible safety banner tint.
        self.page_firmware.update_colors(scheme)
        # Refresh the nav rail icons with the new theme colors
        self.nav_rail.update_icons()
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

    def _restore_window_state(self) -> None:
        """Restore window size, position, and validate it is on-screen.

        The saved format is ``WxH+X+Y`` (e.g. ``1040x700+200+100``).
        If no valid saved state exists, the window is set to 1040×700 and
        centred on the primary screen. An off-screen safety check ensures
        we never place the window outside every monitor's bounds (e.g. after
        a monitor is unplugged), falling back to centering in that case.
        """
        import re
        from PySide6.QtGui import QScreen

        pos_str = self.app_config.window_position  # e.g. "1040x700+200+100"
        match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", pos_str.strip())
        if match:
            w, h, x, y = (int(v) for v in match.groups())
            # Clamp to minimum size just in case the saved value predates it.
            w = max(w, self.minimumWidth())
            h = max(h, self.minimumHeight())
            self.resize(w, h)

            # Safety check: at least 100×50 px of the title bar must be
            # visible on some screen so the user can always drag it back.
            from PySide6.QtCore import QRect
            title_rect = QRect(x, y, max(w, 100), 50)
            on_screen = any(
                screen.geometry().intersects(title_rect)
                for screen in QApplication.screens()
            )
            if on_screen:
                self.move(x, y)
            else:
                # Restore size but centre on the primary screen.
                primary = QApplication.primaryScreen()
                if primary:
                    sg = primary.availableGeometry()
                    self.move(
                        sg.x() + (sg.width() - w) // 2,
                        sg.y() + (sg.height() - h) // 2,
                    )
        else:
            # No saved state — default size, centred.
            self.resize(1192, 661)
            primary = QApplication.primaryScreen()
            if primary:
                sg = primary.availableGeometry()
                self.move(
                    sg.x() + (sg.width() - 1192) // 2,
                    sg.y() + (sg.height() - 661) // 2,
                )

    def closeEvent(self, event) -> None:
        self.device_monitor.stop()
        # Persist window geometry.
        self.app_config.window_position = (
            f"{self.width()}x{self.height()}+{self.x()}+{self.y()}")
        # Persist splitter position so the console/content ratio is restored.
        if hasattr(self, "splitter"):
            self.app_config.config_data["splitter_sizes"] = self.splitter.sizes()
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

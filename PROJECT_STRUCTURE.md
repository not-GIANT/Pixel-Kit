# Pixel Kit - Project Structure & Feature Documentation

This document provides a comprehensive overview of the Pixel Kit project layout, its primary features, and recent developments.

---

## 1. Project Directory Structure

```text
PixelKit-v3.8/
├── pixelkit/                      # Core business logic layer (framework-agnostic)
│   ├── config.py                  # Handles persistent configuration settings (pixelkit_config.json)
│   ├── logger.py                  # Core logging wrapper (PixelKitLogger)
│   ├── models/                    # Model-specific logic and device schemas
│   │   └── device.py              # Device data representation model
│   └── services/                  # Automated backend service implementations
│       ├── command_executor.py    # Shells out subprocess commands asynchronously with output buffering
│       ├── device_monitor.py      # Background thread polling connected devices via ADB / Fastboot
│       ├── driver_installer.py    # Driver installation logic (Automatic via Drivers.exe, Manual via DPInst)
│       ├── _driver_helper.py      # Elevated helper script for manual driver installation
│       ├── cpid_service.py        # Automated IMEI/CPID repair sequences for Pixel 7, 8, and 9
│       ├── pixel10_service.py     # CPID sequence specific to Tensor G4 / Pixel 10 devices
│       └── firmware_service.py    # Extracts, validates, and flashes full factory firmware images (ZIPs)
│
├── pixelkit_qt/                   # Material 3 Desktop UI layer (PySide6 / Qt)
│   ├── app.py                     # Main application window, layouts, and menus
│   ├── bridge.py                  # Thread-safe QtBridge connecting core services to Qt signals
│   ├── theme/                     # Material Design 3 style guidelines, themes, and styles
│   │   ├── icons.py               # Generates and caches style-aware icons and colors
│   │   ├── manager.py             # Instantly updates and saves active themes (Light/Dark mode)
│   │   ├── stylesheet.py          # Custom QSS stylesheet templates for Material 3 UI widgets
│   │   ├── tokens.py              # Theme tokens and dynamic seed colors
│   │   └── nav_icons/             # Standalone MD SVG icons (phone_android, bolt, security, etc.)
│   │
│   ├── views/                     # Main panels/pages loaded into the NavRail stack
│   │   ├── adb_view.py            # ADB command actions (Reboot, Sideload, Mirror Screen, etc.)
│   │   ├── fastboot_view.py       # Fastboot actions (Unlock Bootloader, Lock Bootloader, Getvar)
│   │   ├── flashing_view.py       # Partition-specific flashing (31 partitions)
│   │   ├── cpid_view.py           # IMEI / CPID Repair sequence workflow view
│   │   └── firmware_view.py       # Full Factory Firmware ZIP Flashing view
│   │
│   └── widgets/                   # Specialized and reusable Material 3 widgets
│       ├── about_dialog.py        # Rich "About" modal displaying features and changelog
│       ├── device_card.py         # Displays live status of connected devices (ADB/Fastboot/Disconnected)
│       ├── dialogs.py             # Custom warning, error, and info modal dialogs
│       ├── install_drivers_dialog.py # Dialog with options to install ADB/Fastboot drivers
│       ├── log_view.py            # Console output view with timestamping and color levels
│       ├── m3_widgets.py          # Styled Action Cards and layouts
│       ├── nav_rail.py            # Sidebar navigation controller
│       ├── partition_list.py      # Selection layout for partition flashing
│       └── step_indicator.py      # Bullet-list indicator representing repair progress steps
│
├── resources/                     # Bundled system binaries, drivers, and scripts
│   ├── lexipwn                    # Exploit payload binary
│   ├── platform-tools/            # Executable platform tools (adb.exe, fastboot.exe, scrcpy, drivers)
│   │   ├── adb/                   # Bundled standalone ADB binaries
│   │   └── driver/                # Bundled Google USB Drivers with DPInst installers
│   └── imei_list.txt              # local storage for processed IMEIs
│
├── run.py                         # Application main entry point launcher
└── requirements.txt               # Project dependency package requirements
```

---

## 2. Core Features

### 🔌 Automated USB Driver Installation
- **Automatic Path**: Installs bundled drivers with administrative privilege delegation via the official `Drivers.exe` package.
- **Manual Path**: Extracts Google USB Driver files, copies ADB binaries to system folders (`%SystemDrive%\adb`), and installs the INF driver file using Windows DPInst helper.

### 📱 Live Device Monitoring & State Detection
- Runs a background thread monitoring USB connections.
- Detects transition between modes: **Disconnected**, **ADB Mode**, and **Fastboot Mode**.
- Queries device features dynamically (Model, Serial, Android Version, Battery level, Bootloader Lock state).

### 🛠️ ADB & Fastboot Operations Card Grid
- Quick execution of device commands like: `Reboot System`, `Reboot Bootloader`, `Sideload OTA`, `Unlock/Lock Bootloader`, and `Getvar All`.
- Wires high-speed screen mirroring via `scrcpy` using the bundled adb to prevent background server conflicts.

### 🧩 Partition-Specific Flashing
- Displays a searchable, categorized list of 31 partitions.
- Prevents accidental flashes by verifying the active mode (requires Fastboot) and matching product codename.

### 📦 Full Factory Firmware ZIP Flashing
- Verifies integrity of official factory firmware archives (ZIP formats).
- Parses internal `flash-all.bat` or `flash-all.sh` to determine the partition order, slots (e.g., active slot logic), and wipe parameters.
- Feeds flashing console output streams directly into the main interface progress indicator.

### 🔑 IMEI & CPID Repair Workflows
- **Pixel 7, 8, & 9 Series**: 10-step automated IMEI repair sequence utilizing low-level NVRAM synchronization.
- **Pixel 10 Series**: 8-step specialized CPID sequence supporting Tensor G4 SoC architectures (AT interface, modem patch, security key validation).

### 🖥️ Diagnostics & Logging
- The **Command Matrix** console renders command outputs with accurate time markings.
- Level-specific color highlights (Blue for Info, Green for Success, Red for Errors/Warnings).
- Local persistent logging to file directories.

---

## 3. Recent Implementation Milestones

### 🚀 Version 3.9.0 (Current Release)
- **Factory Firmware Flashing View**: Full ZIP installation interface utilizing fastboot flash-all sequence logic.
- **Flashing Safety Checks**: Added device-side codename verification and checks for bootloader lock state before allowing flash operations to execute.
- **Material Design Icons Integration**: High-definition, SVG-based navigation icons that resize and recolor dynamically during light/dark theme switches.
- **Progress Bar Consolidation**: Connected background thread outputs directly to the primary window status bar.
- **Card Layout & Sizing Constraints**: Enforced 2-column card grid layouts for ADB and Fastboot views across all window sizes, and introduced minimum pane width limits to avoid any widget overlaps or cut-offs.

### ⚙️ Version 3.8.0
- **ADB / Fastboot USB Driver Installer**: Added the `InstallDriversDialog` and background `DriverInstaller` service to solve driver-related connection failures.
- **Screen Mirroring Fixes**: Resolved conflicts where screen mirroring dropped due to conflicting host machine ADB versions.
- **Workspace Optimization**: Deleted legacy bundled python runtimes and temporary build directories to save over 150MB of disk storage.

### 🎨 Version 3.6.0
- **Qt/PySide6 Migration**: Complete rewrite of the app interface, moving away from legacy Tkinter and web-view wrappers.
- **Navigation Sidebar**: Added a Material 3 Navigation Rail for instant view transitions.
- **Dynamic Accent Color Engine**: Automatically generates color schemes from a single seed color (#0B57D0) supporting both Light and Dark mode options.

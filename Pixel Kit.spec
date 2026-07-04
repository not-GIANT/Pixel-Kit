# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Pixel Kit (Qt / PySide6 + Material 3).

Bundles the ``pixelkit_qt/`` UI, the shared ``pixelkit/`` services layer, and
the full ``resources/`` tree (bundled CPython runtime, platform-tools, models,
cpid_logic, lexipwn, etc.) into a standalone Windows executable.

Build with:
    pyinstaller "Pixel Kit.spec"
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

datas = []
binaries = []
hiddenimports = []

# --- resources/ : platform-tools, bundled Python runtime, CPID scripts,
#     devinfo models, lexipwn, etc. Everything the app reads at runtime. ---
datas += [('resources', 'resources')]

# --- nav_icons/ : SVG icons for the sidebar navigation rail ---
datas += [('pixelkit_qt/theme/nav_icons', 'pixelkit_qt/theme/nav_icons')]


# --- PySide6 (Qt 6) : the GUI framework. Collect its plugins/translations
#     so Qt plugins (image formats, platform, styles) ship with the build. ---
tmp_ret = collect_all('PySide6')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# --- material_color_utilities : the HCT scheme generator that derives the
#     full M3 palette from SEED at runtime. Pure-Python but dynamically
#     walked, so collect it explicitly. ---
tmp_ret = collect_all('material_color_utilities')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# --- CPID repair scripts are imported dynamically from resources/ at runtime
#     (cpid_service adds resources/ to sys.path then imports cpid_logic), so
#     PyInstaller can't see the dependency statically. Declare it. ---
hiddenimports += collect_submodules('cpid_logic')

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Unrelated heavy frameworks that PyInstaller might otherwise pull in.
        'matplotlib', 'scipy', 'pandas', 'notebook', 'jupyter',
        'jedi', 'black', 'IPython', 'setuptools', 'pip', 'wheel',
        'tensorflow', 'torch',
        # Legacy / alternative Qt bindings — only PySide6 is used.
        'PyQt5', 'PyQt6', 'PySide2',
        # The removed CustomTkinter UI; never imported by the Qt app.
        'customtkinter',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # binaries/datas live in the COLLECT folder
    name='Pixel Kit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                  # no console window on launch
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Pixel Kit',               # output folder: dist/Pixel Kit/
)

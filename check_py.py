try:
    import PySide6
    print('PySide6:', PySide6.__version__)
except Exception as e:
    print('PySide6 missing:', e)
try:
    import PyInstaller
    print('PyInstaller:', PyInstaller.__version__)
except Exception as e:
    print('PyInstaller missing:', e)

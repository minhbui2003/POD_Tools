# -*- mode: python ; coding: utf-8 -*-

extra_binaries = []
extra_datas = []


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=extra_binaries,
    datas=[('assets/Logo_bg.png', 'assets'), ('assets/icon_crawl.png', 'assets'), ('assets/icon_resize.png', 'assets'), ('assets/guid_get_gemini_key.pdf', 'assets'), ('assets/checkmark.svg', 'assets'), ('assets/folder.svg', 'assets')] + extra_datas,
    hiddenimports=['qt_gui.app', 'qt_gui.common', 'qt_gui.crawl_page', 'qt_gui.resize_page', 'qt_gui.styles', 'qt_gui.update_dialog', 'core.collection_scraper', 'core.gossby_scraper', 'core.wanderprints_scraper', 'core.utils', 'core.config', 'core.updater', 'core.platform_utils'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='POD_Tools',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\Logo_bg.ico'],
)

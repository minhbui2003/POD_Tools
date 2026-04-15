# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/Logo_bg.png', 'assets'), ('assets/icon_crawl.png', 'assets'), ('assets/icon_resize.png', 'assets'), ('assets/guid_get_gemini_key.pdf', 'assets')],
    hiddenimports=['gui.tab_crawl', 'gui.tab_resize', 'core.collection_scraper', 'core.gossby_scraper', 'core.wanderprints_scraper', 'core.utils', 'core.config', 'core.updater', 'gui.update_dialog'],
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
    upx=True,
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

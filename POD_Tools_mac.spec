# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/Logo_bg.png', 'assets'),
        ('assets/icon_crawl.png', 'assets'),
        ('assets/icon_resize.png', 'assets'),
        ('assets/guid_get_gemini_key.pdf', 'assets'),
        ('assets/checkmark.svg', 'assets'),
    ],
    hiddenimports=[
        'qt_gui.app',
        'qt_gui.common',
        'qt_gui.crawl_page',
        'qt_gui.resize_page',
        'qt_gui.styles',
        'qt_gui.update_dialog',
        'core.collection_scraper',
        'core.gossby_scraper',
        'core.wanderprints_scraper',
        'core.utils',
        'core.config',
        'core.updater',
        'core.platform_utils',
    ],
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
    [],
    exclude_binaries=True,
    name='POD Tools',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='POD Tools',
)

app = BUNDLE(
    coll,
    name='POD Tools.app',
    icon=None,
    bundle_identifier='com.podsoftware.podtools',
    info_plist={
        'CFBundleName': 'POD Tools',
        'CFBundleDisplayName': 'POD Tools',
        'NSHighResolutionCapable': 'True',
    },
)

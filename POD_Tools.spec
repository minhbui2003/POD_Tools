# -*- mode: python ; coding: utf-8 -*-

import os
import sys

python_root = os.path.dirname(sys.executable)
dll_dir = os.path.join(python_root, "DLLs")
tcl_dir = os.path.join(python_root, "tcl")

extra_binaries = []
for dll_name in ("tcl86t.dll", "tk86t.dll"):
    dll_path = os.path.join(dll_dir, dll_name)
    if os.path.exists(dll_path):
        extra_binaries.append((dll_path, "."))

extra_datas = []
for folder_name in ("tcl8.6", "tk8.6"):
    folder_path = os.path.join(tcl_dir, folder_name)
    if os.path.exists(folder_path):
        extra_datas.append((folder_path, os.path.join("tcl", folder_name)))


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=extra_binaries,
    datas=[('assets/Logo_bg.png', 'assets'), ('assets/icon_crawl.png', 'assets'), ('assets/icon_resize.png', 'assets'), ('assets/guid_get_gemini_key.pdf', 'assets')] + extra_datas,
    hiddenimports=['gui.tab_crawl', 'gui.tab_resize', 'core.collection_scraper', 'core.gossby_scraper', 'core.wanderprints_scraper', 'core.utils', 'core.config', 'core.updater', 'core.platform_utils', 'gui.update_dialog'],
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

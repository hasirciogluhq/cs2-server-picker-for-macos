# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

PKG_DIR = Path(SPECPATH)
ROOT = PKG_DIR.parent
SRC = ROOT / "src"

VERSION = os.environ.get("CS2_PICKER_VERSION", "0.0.0-dev").lstrip("v")

ctk_datas, ctk_binaries, ctk_hidden = collect_all("customtkinter")

a = Analysis(
    [str(SRC / "cs2_picker" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=ctk_binaries,
    datas=ctk_datas,
    hiddenimports=ctk_hidden + ["requests", "urllib3", "certifi"],
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
    name="CS2ServerPicker",
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
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CS2ServerPicker",
)

app = BUNDLE(
    coll,
    name="CS2 Server Picker.app",
    icon=None,
    bundle_identifier="com.cs2serverpicker.macos",
    info_plist={
        "CFBundleName": "CS2 Server Picker",
        "CFBundleDisplayName": "CS2 Server Picker",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "NSHumanReadableCopyright": "GPL-3.0",
    },
)

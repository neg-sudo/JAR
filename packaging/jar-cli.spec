# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the JAR command line binary.

Build from the repository root:

    pyinstaller --clean --noconfirm packaging/jar-cli.spec
"""

import os
import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
sys.path.insert(0, str(ROOT))

ICON = ROOT / "jar" / "assets" / ("jar.ico" if sys.platform == "win32" else "jar.png")

a = Analysis(
    [str(ROOT / "scripts" / "entry_cli.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "jar" / "assets"), "jar/assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The CLI release stays small; the desktop release bundles the GUI stack.
    excludes=["tkinter", "customtkinter", "PIL", "pystray", "send2trash", "pytest"],
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
    name="jar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)

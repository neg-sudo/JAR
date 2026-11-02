# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the JAR desktop binary.

Build from the repository root after installing the GUI extras:

    pip install ".[gui]"
    pyinstaller --clean --noconfirm packaging/jar-desktop.spec
"""

import os
import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
sys.path.insert(0, str(ROOT))

ICON = ROOT / "jar" / "assets" / ("jar.ico" if sys.platform == "win32" else "jar.png")

hiddenimports = ["jar.gui.app"]
datas = [(str(ROOT / "jar" / "assets"), "jar/assets")]

# Bundle optional GUI libraries only when they are installed in the build env.
try:
    from PyInstaller.utils.hooks import collect_all

    for package in ("customtkinter", "pystray", "PIL"):
        try:
            package_datas, package_binaries, package_hidden = collect_all(package)
        except Exception:
            continue
        datas.extend(package_datas)
        hiddenimports.extend(package_hidden)
except Exception:  # pragma: no cover - PyInstaller is a build-time dependency
    pass

a = Analysis(
    [str(ROOT / "scripts" / "entry_gui.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
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
    name="jar-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False if sys.platform == "win32" else True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="JAR.app",
        icon=str(ICON) if ICON.exists() else None,
        bundle_identifier="io.github.neg-sudo.jar",
        info_plist={
            "CFBundleName": "JAR",
            "CFBundleDisplayName": "JAR",
            "CFBundleShortVersionString": "2.0.0",
            "NSHighResolutionCapable": True,
        },
    )

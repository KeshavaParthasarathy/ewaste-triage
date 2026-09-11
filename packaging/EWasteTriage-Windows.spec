# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build graph for the Windows 11 x64 desktop product."""

import os
from pathlib import Path
import re


PRODUCT_NAME = "E-Waste Triage"
PRODUCT_STATIC_ASSETS = (
    "app.css",
    "app.js",
    "index.html",
    "phone.css",
    "phone.html",
    "phone.js",
)
RELEASE_DATA_FILES = (
    ("model/model.onnx", "models/production"),
    ("model/manifest.json", "models/production"),
    ("components.sqlite", "reference"),
    ("labels.json", "release"),
    ("parity-report.json", "release"),
    ("release-manifest.json", "release"),
)
EXCLUDED_MODULES = (
    "scripts",
    "server.app",
    "server.classifier",
    "tests",
    "torch",
    "torchvision",
)
HIDDEN_IMPORTS = (
    "desktop.release_metadata",
    "pillow_heif",
    "psutil",
    "qrcode",
    "webview.platforms.edgechromium",
)


PROJECT_ROOT = Path(SPECPATH).resolve().parent
ENTRYPOINT = PROJECT_ROOT / "desktop/main.py"
STATIC_DIR = PROJECT_ROOT / "server/static"


def required_path(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} must name a build input")
    try:
        return Path(value).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"{name} does not exist: {value}") from error


RELEASE_DIR = required_path("EWASTE_RELEASE_DIR")
ICON_PATH = required_path("EWASTE_ICON_PATH")
BUILD_METADATA = required_path("EWASTE_BUILD_METADATA")
APP_VERSION = os.environ.get("EWASTE_APP_VERSION", "")
if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", APP_VERSION) is None:
    raise SystemExit("EWASTE_APP_VERSION must use X.Y.Z")

datas = [(str(STATIC_DIR / name), "server/static") for name in PRODUCT_STATIC_ASSETS]
datas += [
    (str(RELEASE_DIR / source), destination)
    for source, destination in RELEASE_DATA_FILES
]
datas.append((str(BUILD_METADATA), "."))

a = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=list(HIDDEN_IMPORTS),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(EXCLUDED_MODULES),
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=PRODUCT_NAME,
    icon=str(ICON_PATH),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=PRODUCT_NAME,
)

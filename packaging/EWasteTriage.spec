# -*- mode: python ; coding: utf-8 -*-
"""Product-only PyInstaller contract for the Apple Silicon macOS application."""

import os
from pathlib import Path
import re


PRODUCT_NAME = "E-Waste Triage"
BUNDLE_IDENTIFIER = "com.ewastetriage.desktop"
TARGET_ARCHITECTURE = "arm64"
MINIMUM_MACOS_VERSION = "14.0"
BUNDLE_VERSION_PATTERN = r"[0-9]+\.[0-9]+\.[0-9]+"
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
    "pillow_heif",
    "psutil",
    "qrcode",
    "webview.platforms.cocoa",
)
INFO_PLIST = {
    "CFBundleDisplayName": "E-Waste Triage",
    "CFBundleName": "E-Waste Triage",
    "LSMinimumSystemVersion": "14.0",
    "LSApplicationCategoryType": "public.app-category.utilities",
    "NSCameraUsageDescription": (
        "E-Waste Triage uses the camera only when you choose to capture a device photo."
    ),
    "NSLocalNetworkUsageDescription": (
        "E-Waste Triage connects to your phone on the local network only during a capture session."
    ),
    "NSHighResolutionCapable": True,
}


PROJECT_ROOT = Path(SPECPATH).resolve().parent
ENTRYPOINT = PROJECT_ROOT / "desktop/main.py"
STATIC_DIR = PROJECT_ROOT / "server" / "static"
ENTITLEMENTS = PROJECT_ROOT / "packaging" / "entitlements.plist"


def required_environment_path(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} must name a validated build input")
    try:
        path = Path(value).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"{name} does not exist: {value}") from error
    return path


RELEASE_DIR = required_environment_path("EWASTE_RELEASE_DIR")
ICON_PATH = required_environment_path("EWASTE_ICON_PATH")
BUILD_METADATA = required_environment_path("EWASTE_BUILD_METADATA")
APP_VERSION = os.environ.get("EWASTE_APP_VERSION", "")
if re.fullmatch(BUNDLE_VERSION_PATTERN, APP_VERSION) is None:
    raise SystemExit("EWASTE_APP_VERSION must contain three period-separated integers")

missing_static = [name for name in PRODUCT_STATIC_ASSETS if not (STATIC_DIR / name).is_file()]
if missing_static:
    raise SystemExit(f"final product static assets are not integrated: {missing_static}")
missing_release = [name for name, _ in RELEASE_DATA_FILES if not (RELEASE_DIR / name).is_file()]
if missing_release:
    raise SystemExit(f"validated release stage is incomplete: {missing_release}")

datas = [
    (str(STATIC_DIR / filename), "server/static")
    for filename in PRODUCT_STATIC_ASSETS
]
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
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCHITECTURE,
    codesign_identity=None,
    entitlements_file=str(ENTITLEMENTS),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=PRODUCT_NAME,
)

app = BUNDLE(
    coll,
    name=f"{PRODUCT_NAME}.app",
    icon=str(ICON_PATH),
    bundle_identifier=BUNDLE_IDENTIFIER,
    version=APP_VERSION,
    info_plist=INFO_PLIST,
)

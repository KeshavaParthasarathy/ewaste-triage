#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --version X.Y.Z [--release-dir PATH]" >&2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${PROJECT_ROOT}/.venv/bin/python}"
RELEASE_DIR="${PROJECT_ROOT}/.release-staging/release"
BUILD_BASE="${EWASTE_BUILD_BASE:-${PROJECT_ROOT}/build/macos}"
DIST_DIR="${EWASTE_DIST_DIR:-${PROJECT_ROOT}/dist}"
VERSION=""

while (($#)); do
  case "$1" in
    --version)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      VERSION="$2"
      shift 2
      ;;
    --release-dir)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      RELEASE_DIR="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "error: --version must contain three period-separated integers" >&2
  exit 2
fi
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "error: Python executable is unavailable: ${PYTHON_BIN}" >&2
  exit 1
fi

# This is deliberately the first operation that can inspect or mutate build state.
"${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/verify_macos_bundle.py" \
  --release-dir "${RELEASE_DIR}" \
  --expected-version "${VERSION}" \
  --stage-only

if ! SOURCE_REVISION="$(/usr/bin/git -C "${PROJECT_ROOT}" rev-parse --verify 'HEAD^{commit}' 2>/dev/null)"; then
  echo "error: source tree must have a valid Git commit" >&2
  exit 1
fi
if ! SOURCE_STATUS="$(/usr/bin/git -C "${PROJECT_ROOT}" status --porcelain=v1 --untracked-files=all)"; then
  echo "error: source tree status could not be inspected" >&2
  exit 1
fi
if [[ -n "${SOURCE_STATUS}" ]]; then
  echo "error: source tree must be clean before packaging" >&2
  exit 1
fi

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
  echo "error: macOS packaging requires Darwin" >&2
  exit 1
fi
if ! "${PYTHON_BIN}" -c 'import PyInstaller' >/dev/null 2>&1; then
  echo "error: install the pinned PyInstaller build dependency" >&2
  exit 1
fi

PRODUCT_STATIC_ASSETS=(app.css app.js index.html phone.css phone.html phone.js)
for filename in "${PRODUCT_STATIC_ASSETS[@]}"; do
  if [[ ! -f "${PROJECT_ROOT}/server/static/${filename}" ]]; then
    echo "error: final product asset is not integrated: server/static/${filename}" >&2
    exit 1
  fi
done

BUILD_ROOT="${BUILD_BASE}/${VERSION}"
ICON_PATH="${BUILD_ROOT}/icon/EWasteTriage.icns"
BUILD_METADATA="${BUILD_ROOT}/generated/build-metadata.json"
PYINSTALLER_DIST="${BUILD_ROOT}/pyinstaller-dist"
PYINSTALLER_WORK="${BUILD_ROOT}/pyinstaller-work"
BUILT_APP="${PYINSTALLER_DIST}/E-Waste Triage.app"
FINAL_APP="${DIST_DIR}/E-Waste Triage.app"
DMG_PATH="${DIST_DIR}/E-Waste Triage-${VERSION}-arm64.dmg"
RELEASE_JSON="${DIST_DIR}/E-Waste Triage-${VERSION}-arm64.json"

case "${BUILD_ROOT}" in
  "${BUILD_BASE}"/*) ;;
  *) echo "error: unsafe build directory" >&2; exit 1 ;;
esac
/bin/rm -rf -- "${BUILD_ROOT}"
/bin/mkdir -p "${BUILD_ROOT}/icon" "${BUILD_ROOT}/generated" "${PYINSTALLER_DIST}" "${PYINSTALLER_WORK}"

RELEASE_MANIFEST_SHA256="$(/usr/bin/shasum -a 256 "${RELEASE_DIR}/release-manifest.json" | /usr/bin/awk '{print $1}')"
"${PYTHON_BIN}" - "${BUILD_METADATA}" "${VERSION}" "${SOURCE_REVISION}" "${RELEASE_MANIFEST_SHA256}" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
payload = {
    "schema_version": 1,
    "app_version": sys.argv[2],
    "source_revision": sys.argv[3],
    "release_manifest_sha256": sys.argv[4],
}
with path.open("w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

"${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/render_app_icon.py" \
  --source "${PROJECT_ROOT}/desktop/assets/app-icon.svg" \
  --output "${ICON_PATH}"

export EWASTE_RELEASE_DIR="${RELEASE_DIR}"
export EWASTE_ICON_PATH="${ICON_PATH}"
export EWASTE_BUILD_METADATA="${BUILD_METADATA}"
export EWASTE_APP_VERSION="${VERSION}"
"${PYTHON_BIN}" -m PyInstaller \
  --noconfirm \
  --clean \
  --workpath "${PYINSTALLER_WORK}" \
  --distpath "${PYINSTALLER_DIST}" \
  "${PROJECT_ROOT}/packaging/EWasteTriage.spec"

CURRENT_SOURCE_REVISION="$(/usr/bin/git -C "${PROJECT_ROOT}" rev-parse --verify 'HEAD^{commit}')"
SOURCE_STATUS="$(/usr/bin/git -C "${PROJECT_ROOT}" status --porcelain=v1 --untracked-files=all)"
if [[ "${CURRENT_SOURCE_REVISION}" != "${SOURCE_REVISION}" || -n "${SOURCE_STATUS}" ]]; then
  echo "error: source tree changed while packaging; discarding release outputs" >&2
  exit 1
fi

"${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/verify_macos_bundle.py" \
  --release-dir "${RELEASE_DIR}" \
  --expected-version "${VERSION}" \
  --app "${BUILT_APP}"

/bin/mkdir -p "${DIST_DIR}"
/bin/rm -rf -- "${FINAL_APP}"
/usr/bin/ditto "${BUILT_APP}" "${FINAL_APP}"
"${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/verify_macos_bundle.py" \
  --release-dir "${RELEASE_DIR}" \
  --expected-version "${VERSION}" \
  --app "${FINAL_APP}"

DMG_SOURCE="${BUILD_ROOT}/dmg-source"
/bin/mkdir -p "${DMG_SOURCE}"
/usr/bin/ditto "${FINAL_APP}" "${DMG_SOURCE}/E-Waste Triage.app"
/bin/ln -s /Applications "${DMG_SOURCE}/Applications"
/bin/rm -f -- "${DMG_PATH}" "${RELEASE_JSON}"
/usr/bin/hdiutil create \
  -volname "E-Waste Triage ${VERSION}" \
  -srcfolder "${DMG_SOURCE}" \
  -ov \
  -format UDZO \
  "${DMG_PATH}"

DMG_SHA256="$(/usr/bin/shasum -a 256 "${DMG_PATH}" | /usr/bin/awk '{print $1}')"
"${PYTHON_BIN}" - "${RELEASE_JSON}" "${VERSION}" "${DMG_PATH}" "${DMG_SHA256}" "${SOURCE_REVISION}" "${RELEASE_MANIFEST_SHA256}" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
payload = {
    "schema_version": 1,
    "app_version": sys.argv[2],
    "architecture": "arm64",
    "minimum_macos": "14.0",
    "dmg_filename": Path(sys.argv[3]).name,
    "dmg_sha256": sys.argv[4],
    "source_revision": sys.argv[5],
    "release_manifest_sha256": sys.argv[6],
}
temporary = path.with_suffix(path.suffix + ".tmp")
with temporary.open("w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
temporary.replace(path)
PY

echo "Built ${FINAL_APP}"
echo "Built ${DMG_PATH}"
echo "Wrote ${RELEASE_JSON}"

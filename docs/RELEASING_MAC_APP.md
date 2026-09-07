# Releasing the E-Waste Triage Mac app

This guide is for release administrators. Training datasets, checkpoints, reviewed reference YAML, parity evidence, and staging tools are administrator-only inputs; none are part of the shipped user product. The first release is an unsigned arm64 build for macOS 14 or later. Do not substitute training assets, a new checkpoint, or a reconstructed parity file during packaging.

## Release inputs and host setup

From a clean, reviewed checkout, activate the existing environment:

```sh
source .venv/bin/activate
```

On this Conda/readline host, starting `.venv/bin/pytest` directly crashes. Use the in-memory dummy-`readline` launcher instead; it changes no project file:

```sh
.venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["-q"]))'
```

The currently approved candidate is Trial 7, model ID `t07-new-phone-mouse-efficientnet-b0`: public validation 81.2%, own-device holdout 30/32 (93.75%), ONNX parity 15/15, maximum probability delta `1.9669532775878906e-06`. Select the reviewed assets named in the release record, not a similarly named local candidate:

```sh
MODEL_ID=t07-new-phone-mouse-efficientnet-b0
MODEL_BUNDLE=.release-staging/model-t07-20260906
PARITY_REPORT=.release-staging/parity-t07-20260906.json
test -d "$MODEL_BUNDLE" && test -f "$PARITY_REPORT"
```

The audited closed-schema parity report records 32 valid, non-overlapping holdout samples. The checkout need not contain those holdout image files; the audited report is the release record.

## Prepare immutable inputs

After component hardening, regenerate component schema/version `2`/`2.0.0` from reviewed `reference/` and retain the emitted summary in the release record:

```sh
COMPONENT_DB=.release-staging/components-2.0.0.sqlite
.venv/bin/python scripts/build_component_db.py \
  --source reference --out "$COMPONENT_DB" --print-summary
```

For a candidate that has not already been independently approved, export to a new empty staging directory and give each audited reference image explicitly. This command refuses an existing output directory. It does not overwrite production and its bundle manifest records parity; do not manufacture a separate parity report from its console output.

```sh
.venv/bin/python scripts/export_onnx.py \
  --checkpoint models/experiments/<reviewed-trial>/best.pt \
  --output-dir .release-staging/model-<new-reviewed-id> \
  --reference-image <audited-image-1> \
  --reference-image <audited-image-2> \
  --model-id <new-reviewed-id>
```

Atomically validate and stage only the approved pair. `prepare_release.py` writes a temporary sibling and promotes it only after the closed-schema checks pass:

```sh
export APP_VERSION=0.1.0
RELEASE_DIR=.release-staging/release-$APP_VERSION
.venv/bin/python scripts/prepare_release.py \
  --model-bundle "$MODEL_BUNDLE" \
  --component-db "$COMPONENT_DB" \
  --parity-report "$PARITY_REPORT" \
  --output-dir "$RELEASE_DIR" \
  --app-version "$APP_VERSION"
```

## Build, verify, and smoke-test

Use a clean source checkout. The packaging script verifies the staged release before building, creates the app/DMG/checksum JSON, and verifies the app bundle:

```sh
git status --porcelain=v1
./scripts/build_macos_app.sh --version "$APP_VERSION" --release-dir "$RELEASE_DIR"
.venv/bin/python scripts/verify_macos_bundle.py \
  --release-dir "$RELEASE_DIR" \
  --expected-version "$APP_VERSION" \
  --app "dist/E-Waste Triage.app"
EWASTE_PACKAGED_APP="$PWD/dist/E-Waste Triage.app" \
  .venv/bin/python -c 'import sys, types; sys.modules["readline"] = types.ModuleType("readline"); import pytest; raise SystemExit(pytest.main(["tests/test_packaged_smoke.py", "-q"]))'
```

Independently compare the DMG hash with the generated release JSON before distribution:

```sh
shasum -a 256 "dist/E-Waste Triage-$APP_VERSION-arm64.dmg"
.venv/bin/python - <<'PY'
import json, os
from pathlib import Path
version = os.environ["APP_VERSION"]
record = json.loads(Path(f"dist/E-Waste Triage-{version}-arm64.json").read_text())
print(record["dmg_sha256"])
PY
```

The two printed SHA-256 values must match exactly. Archive the release record, validation output, checksums, source revision, approved model ID, and component version together.

## Rollback, cleanup, and signing boundary

To roll back, select a prior reviewed model bundle and its matching reviewed component database/parity report, run the same `prepare_release.py` command into a new versioned release directory, then rebuild and verify. Never overwrite `models/best.pt` or mutate an already reviewed staged pair.

Remove only exact ignored, version-specific outputs after confirming the version value; do not use broad home-directory or repository cleanup:

```sh
if ! /usr/bin/printf '%s\n' "${APP_VERSION-}" | /usr/bin/grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "APP_VERSION must be an exact X.Y.Z release version" >&2
  exit 1
fi
rm -rf -- "build/macos/$APP_VERSION"
rm -rf -- ".release-staging/release-$APP_VERSION"
rm -f -- "dist/E-Waste Triage-$APP_VERSION-arm64.dmg" \
  "dist/E-Waste Triage-$APP_VERSION-arm64.json"
```

Developer ID signing and notarization are future release steps and are explicitly unavailable in this unsigned milestone. Do not imply Gatekeeper trust, signing, notarization, or TLS-based phone transport before those capabilities exist.

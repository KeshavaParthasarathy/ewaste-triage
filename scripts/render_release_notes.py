#!/usr/bin/env python3
"""Render deterministic, human-readable notes for a verified app release stage."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_macos_bundle import validate_release_stage
from server.model_bundle import load_model_bundle


_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def render_release_notes(release_dir: Path, version: str) -> str:
    """Build notes only from the same verified stage used by packaging."""
    if _VERSION.fullmatch(version) is None:
        raise ValueError("version must contain three period-separated integers")
    release_dir = Path(release_dir)
    release = validate_release_stage(release_dir, expected_version=version)
    model, _artifact = load_model_bundle(release_dir / "model")
    components = release["components"]
    target = release["target"]
    parity = release["parity"]
    metrics = parity["metrics"]
    holdout = parity["holdout"]
    return (
        f"# E-Waste Triage {version}\n\n"
        "Internal Apple Silicon tester release.\n\n"
        "## Release identity\n\n"
        f"- App version: `{version}`\n"
        f"- Model: `{model.model_id}` (`{model.architecture}`, schema `{model.schema_version}`)\n"
        f"- Model artifact SHA-256: `{model.artifact_sha256}`\n"
        f"- Preprocessing: `{model.preprocessing_version}`\n"
        f"- Component references: `{components['version']}` (schema `{components['schema_version']}`)\n"
        f"- Component database SHA-256: `{components['sha256']}`\n"
        f"- Target: Apple Silicon (`{target['architecture']}`), macOS `{target['minimum_macos']}` or later\n\n"
        "## Validation snapshot\n\n"
        f"- ONNX parity: {metrics['top1_matches']}/{metrics['reference_images']} top-1 matches; "
        f"maximum probability delta `{metrics['max_probability_delta']}`.\n"
        f"- Holdout: `{holdout['samples']}` labeled samples; validation passed with no training overlap.\n\n"
        "## Product boundaries\n\n"
        "- Classification, component assessment, and history run locally on the Mac.\n"
        "- Phone capture uses temporary same-network HTTP and is not TLS-encrypted; use it only on a trusted network.\n"
        "- Administrator training tools and training photos are not included in the live app.\n"
        "- This internal build is ad-hoc signed, not Developer ID signed or notarized.\n"
    )


def write_release_notes(release_dir: Path, version: str, output: Path) -> Path:
    """Atomically publish notes so failed validation cannot leave a partial file."""
    text = render_release_notes(release_dir, version)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        write_release_notes(args.release_dir, args.version, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"error: release notes could not be generated: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

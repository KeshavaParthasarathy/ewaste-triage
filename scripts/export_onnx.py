#!/usr/bin/env python3
"""Export a PyTorch checkpoint as a parity-gated ONNX model bundle."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Sequence

import numpy as np
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.classifier import Classifier
from server.imaging import SUPPORTED_PREPROCESSING_VERSION
from server.inference import OnnxClassifier
from server.model_bundle import SUPPORTED_SCHEMA, sha256_file


MAX_PROBABILITY_DELTA = 1e-4


class ParityError(RuntimeError):
    """An exported graph does not match its source checkpoint."""


def _write_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _manifest(
    classifier: Classifier,
    checkpoint: Path,
    artifact: Path,
    metrics: dict,
    model_id: str,
) -> dict:
    return {
        "model_id": model_id,
        "architecture": classifier.arch,
        "classes": list(classifier.classes),
        "preprocessing_version": SUPPORTED_PREPROCESSING_VERSION,
        "confidence_floor": classifier.confidence_floor,
        "artifact_sha256": sha256_file(artifact),
        "schema_version": SUPPORTED_SCHEMA,
        "metrics": {
            "checkpoint_sha256": sha256_file(checkpoint),
            "parity": metrics,
        },
    }


def _measure_parity(
    pytorch_engine: Classifier,
    onnx_engine: OnnxClassifier,
    reference_images: Sequence[Path],
) -> dict:
    top1_matches = 0
    max_probability_delta = 0.0
    for path in reference_images:
        with Image.open(path) as image:
            pytorch_probabilities = pytorch_engine.probabilities(image)
        with Image.open(path) as image:
            onnx_probabilities = onnx_engine.probabilities(image)

        if pytorch_probabilities.shape != onnx_probabilities.shape:
            raise ParityError(
                "probability shape parity failed: "
                f"PyTorch {pytorch_probabilities.shape}, ONNX {onnx_probabilities.shape}"
            )
        if not np.isfinite(pytorch_probabilities).all():
            raise ParityError("PyTorch probabilities contain non-finite values")
        if not np.isfinite(onnx_probabilities).all():
            raise ParityError("ONNX probabilities contain non-finite values")
        top1_matches += int(
            np.argmax(pytorch_probabilities) == np.argmax(onnx_probabilities)
        )
        max_probability_delta = max(
            max_probability_delta,
            float(np.max(np.abs(pytorch_probabilities - onnx_probabilities))),
        )

    count = len(reference_images)
    if top1_matches != count:
        raise ParityError(f"top-1 parity failed: {top1_matches}/{count} images matched")
    if max_probability_delta > MAX_PROBABILITY_DELTA:
        raise ParityError(
            "probability parity failed: maximum absolute delta "
            f"{max_probability_delta:.8f} exceeds {MAX_PROBABILITY_DELTA:.8f}"
        )
    return {
        "reference_images": count,
        "top1_matches": top1_matches,
        "max_probability_delta": max_probability_delta,
    }


def export_checkpoint(
    checkpoint: Path,
    output_dir: Path,
    reference_images: Sequence[Path],
    *,
    model_id: str,
) -> Path:
    """Export, verify, and atomically promote an ONNX model bundle."""
    checkpoint = Path(checkpoint)
    output_dir = Path(output_dir)
    reference_images = tuple(Path(path) for path in reference_images)
    if not reference_images:
        raise ValueError("at least one reference image is required for parity")
    if not isinstance(model_id, str) or not model_id:
        raise ValueError("model_id must be a non-empty string")
    if output_dir.exists():
        raise FileExistsError(f"output bundle already exists: {output_dir}")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}-", suffix=".tmp", dir=output_dir.parent
        )
    )
    try:
        classifier = Classifier(checkpoint)
        artifact = stage / "model.onnx"
        torch.onnx.export(
            classifier.model,
            torch.zeros((1, 3, 224, 224), dtype=torch.float32),
            artifact,
            input_names=["image"],
            output_names=["logits"],
            opset_version=17,
            dynamo=False,
        )

        pending_metrics = {
            "reference_images": 0,
            "top1_matches": 0,
            "max_probability_delta": 1.0,
        }
        _write_manifest(
            stage / "manifest.json",
            _manifest(classifier, checkpoint, artifact, pending_metrics, model_id),
        )
        onnx_engine = OnnxClassifier(stage)
        parity_metrics = _measure_parity(classifier, onnx_engine, reference_images)
        _write_manifest(
            stage / "manifest.json",
            _manifest(classifier, checkpoint, artifact, parity_metrics, model_id),
        )
        os.replace(stage, output_dir)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--reference-image",
        required=True,
        action="append",
        type=Path,
        dest="reference_images",
    )
    parser.add_argument("--model-id", required=True)
    arguments = parser.parse_args()
    bundle = export_checkpoint(
        arguments.checkpoint,
        arguments.output_dir,
        arguments.reference_images,
        model_id=arguments.model_id,
    )
    print(bundle)


if __name__ == "__main__":
    main()

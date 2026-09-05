"""Portable inference interface and ONNX Runtime implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np
import onnxruntime as ort
from PIL import Image

from server.classifier import prediction_from_probabilities
from server.imaging import preprocess_array
from server.model_bundle import load_model_bundle


class InferenceEngine(Protocol):
    """Inference boundary shared by desktop product features."""

    def probabilities(self, image: Image.Image) -> np.ndarray: ...

    def classify(self, image: Image.Image) -> dict: ...


class OnnxClassifier:
    """Classify release images from a validated model bundle."""

    def __init__(self, bundle_dir: Path):
        self.manifest, artifact = load_model_bundle(Path(bundle_dir))
        self.session = ort.InferenceSession(
            str(artifact), providers=["CPUExecutionProvider"]
        )

    def probabilities(self, image: Image.Image) -> np.ndarray:
        logits = self.session.run(
            ["logits"], {"image": preprocess_array(image)}
        )[0][0]
        shifted = logits - logits.max()
        exponentials = np.exp(shifted)
        values = exponentials / exponentials.sum()
        return values.astype(np.float32, copy=False)

    def classify(self, image: Image.Image) -> dict:
        return prediction_from_probabilities(
            self.probabilities(image),
            self.manifest.classes,
            self.manifest.confidence_floor,
        )

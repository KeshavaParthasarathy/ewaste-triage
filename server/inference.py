"""Portable inference interface and ONNX Runtime implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np
import onnxruntime as ort
from PIL import Image

from server.imaging import (
    SUPPORTED_PREPROCESSING_VERSION,
    preprocess_crop_array,
    preprocess_image,
    register_image_formats,
)
from server.model_bundle import ModelBundleError, load_model_bundle
from server.prediction import prediction_from_probabilities


EXPECTED_INPUT_SHAPE = (1, 3, 224, 224)
EXPECTED_TENSOR_TYPE = "tensor(float)"


class InferenceEngine(Protocol):
    """Inference boundary shared by desktop product features."""

    def probabilities(self, image: Image.Image) -> np.ndarray: ...

    def probabilities_preprocessed(self, crop: Image.Image) -> np.ndarray: ...

    def classify(self, image: Image.Image) -> dict: ...


class OnnxClassifier:
    """Classify release images from a validated model bundle."""

    def __init__(self, bundle_dir: Path):
        register_image_formats()
        self.manifest, artifact = load_model_bundle(Path(bundle_dir))
        if self.manifest.preprocessing_version != SUPPORTED_PREPROCESSING_VERSION:
            raise ModelBundleError(
                "unsupported preprocessing version: "
                f"expected {SUPPORTED_PREPROCESSING_VERSION!r}, "
                f"got {self.manifest.preprocessing_version!r}"
            )
        self.session = ort.InferenceSession(
            str(artifact), providers=["CPUExecutionProvider"]
        )
        inputs = self.session.get_inputs()
        if (
            len(inputs) != 1
            or inputs[0].name != "image"
            or inputs[0].type != EXPECTED_TENSOR_TYPE
            or tuple(inputs[0].shape) != EXPECTED_INPUT_SHAPE
        ):
            raise ModelBundleError(
                "ONNX image input must be one tensor(float) named 'image' "
                "with shape (1, 3, 224, 224)"
            )

        outputs = self.session.get_outputs()
        expected_output_shape = (1, len(self.manifest.classes))
        if (
            len(outputs) != 1
            or outputs[0].name != "logits"
            or outputs[0].type != EXPECTED_TENSOR_TYPE
            or tuple(outputs[0].shape) != expected_output_shape
        ):
            raise ModelBundleError(
                "ONNX logits output must be one tensor(float) named 'logits' "
                f"with shape {expected_output_shape} for "
                f"{len(self.manifest.classes)} classes"
            )

    @property
    def arch(self) -> str:
        """Expose the architecture validated by the release manifest."""
        return self.manifest.architecture

    @property
    def classes(self) -> tuple[str, ...]:
        """Expose the canonical classes validated by the release manifest."""
        return self.manifest.classes

    def probabilities(self, image: Image.Image) -> np.ndarray:
        return self.probabilities_preprocessed(preprocess_image(image))

    def probabilities_preprocessed(self, crop: Image.Image) -> np.ndarray:
        logits = self.session.run(
            ["logits"], {"image": preprocess_crop_array(crop)}
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

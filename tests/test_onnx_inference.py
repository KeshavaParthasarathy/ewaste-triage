import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import onnx
import pytest
import torch
import torch.nn as nn
from onnx import TensorProto, helper, numpy_helper
from PIL import Image

import scripts.export_onnx as export_module
from scripts.export_onnx import ParityError, export_checkpoint
from server.classifier import Classifier
from server.inference import OnnxClassifier
from server.model_bundle import ModelBundleError, load_model_bundle


class TinyClassifier(nn.Module):
    """A deterministic export fixture that keeps the ONNX suite lightweight."""

    def __init__(self, n_classes):
        super().__init__()
        self.pool = nn.AdaptiveAvgPool2d((1, 1))
        self.head = nn.Linear(3, n_classes)

    def forward(self, image):
        return self.head(self.pool(image).flatten(1))


@pytest.fixture
def tiny_checkpoint(tmp_path, monkeypatch):
    def build_tiny(architecture, n_classes):
        assert architecture == "test_tiny"
        model = TinyClassifier(n_classes)
        with torch.no_grad():
            model.head.weight.copy_(torch.eye(n_classes, 3))
            model.head.bias.copy_(torch.tensor([0.1, 0.0, -0.1]))
        return model

    monkeypatch.setattr("server.classifier._build", build_tiny)
    model = build_tiny("test_tiny", 3)
    checkpoint = tmp_path / "tiny.pt"
    torch.save(
        {
            "arch": "test_tiny",
            "classes": [
                "0301_computer_mouse",
                "0306_mobile_phone",
                "0401_small_consumer",
            ],
            "state_dict": model.state_dict(),
        },
        checkpoint,
    )
    return checkpoint


@pytest.fixture
def reference_images(tmp_path):
    paths = []
    for name, size, color in (
        ("red", (321, 251), (240, 20, 10)),
        ("green", (251, 321), (10, 230, 20)),
        ("blue", (287, 263), (10, 20, 240)),
    ):
        path = tmp_path / f"{name}.png"
        Image.new("RGB", size, color).save(path)
        paths.append(path)
    return paths


def write_metadata_test_bundle(
    bundle_dir,
    *,
    preprocessing_version="rgb-224-v1",
    input_shape=(1, 3, 224, 224),
    input_type=TensorProto.FLOAT,
    output_width=3,
):
    bundle_dir.mkdir()
    model_input = helper.make_tensor_value_info("image", input_type, input_shape)
    model_output = helper.make_tensor_value_info(
        "logits", TensorProto.FLOAT, (1, output_width)
    )
    logits = numpy_helper.from_array(
        np.zeros((1, output_width), dtype=np.float32), name="constant_logits"
    )
    graph = helper.make_graph(
        [helper.make_node("Constant", [], ["logits"], value=logits)],
        "metadata-test-model",
        [model_input],
        [model_output],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 17)], ir_version=10
    )
    artifact = bundle_dir / "model.onnx"
    onnx.save(model, artifact)
    manifest = {
        "model_id": "metadata-test-model",
        "architecture": "test_tiny",
        "classes": [
            "0301_computer_mouse",
            "0306_mobile_phone",
            "0401_small_consumer",
        ],
        "preprocessing_version": preprocessing_version,
        "confidence_floor": 0.6,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "schema_version": 1,
        "metrics": {},
    }
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest))
    return bundle_dir


def test_exported_onnx_matches_pytorch_top1(tiny_checkpoint, reference_images, tmp_path):
    bundle = export_checkpoint(
        tiny_checkpoint,
        tmp_path / "bundle",
        reference_images,
        model_id="test-model",
    )
    torch_engine = Classifier(tiny_checkpoint)
    onnx_engine = OnnxClassifier(bundle)

    for path in reference_images:
        with Image.open(path) as image:
            torch_probabilities = torch_engine.probabilities(image)
        with Image.open(path) as image:
            onnx_probabilities = onnx_engine.probabilities(image)
        with Image.open(path) as image:
            torch_result = torch_engine.classify(image)
        with Image.open(path) as image:
            onnx_result = onnx_engine.classify(image)

        assert onnx_probabilities.dtype == np.float32
        assert onnx_probabilities == pytest.approx(torch_probabilities, abs=1e-4)
        assert onnx_result["class_name"] == torch_result["class_name"]
        assert onnx_result["confidence"] == pytest.approx(
            torch_result["confidence"], abs=1e-4
        )
        assert set(onnx_result) == {
            "class_name",
            "unu_key",
            "confidence",
            "low_confidence",
            "topk",
        }


def test_export_writes_fixed_opset17_graph_and_loadable_manifest(
    tiny_checkpoint, reference_images, tmp_path
):
    output = tmp_path / "nested" / "bundle"

    bundle = export_checkpoint(
        tiny_checkpoint, output, reference_images, model_id="test-model"
    )

    manifest, artifact = load_model_bundle(bundle)
    graph = onnx.load(artifact)
    model_input = graph.graph.input[0]
    dimensions = [
        dimension.dim_value for dimension in model_input.type.tensor_type.shape.dim
    ]
    assert bundle == output
    assert model_input.name == "image"
    assert graph.graph.output[0].name == "logits"
    assert dimensions == [1, 3, 224, 224]
    assert [(item.domain, item.version) for item in graph.opset_import] == [("", 17)]
    assert manifest.model_id == "test-model"
    assert manifest.architecture == "test_tiny"
    assert manifest.preprocessing_version == "rgb-224-v1"
    assert manifest.metrics["parity"]["reference_images"] == 3
    assert manifest.metrics["parity"]["top1_matches"] == 3
    assert manifest.metrics["parity"]["max_probability_delta"] <= 1e-4
    assert set(json.loads((bundle / "manifest.json").read_text())) == {
        "model_id",
        "architecture",
        "classes",
        "preprocessing_version",
        "confidence_floor",
        "artifact_sha256",
        "schema_version",
        "metrics",
    }


def test_parity_failure_does_not_promote_bundle(
    tiny_checkpoint, reference_images, tmp_path, monkeypatch
):
    real_classifier = export_module.OnnxClassifier

    class WrongOnnxClassifier(real_classifier):
        def probabilities(self, image):
            return np.roll(super().probabilities(image), 1)

    monkeypatch.setattr(export_module, "OnnxClassifier", WrongOnnxClassifier)
    output = tmp_path / "bundle"

    with pytest.raises(ParityError, match="top-1"):
        export_checkpoint(
            tiny_checkpoint, output, reference_images, model_id="bad-model"
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".bundle-*.tmp"))


def test_probability_delta_failure_does_not_promote_bundle(
    tiny_checkpoint, reference_images, tmp_path, monkeypatch
):
    real_classifier = export_module.OnnxClassifier

    class ImpreciseOnnxClassifier(real_classifier):
        def probabilities(self, image):
            values = np.sqrt(super().probabilities(image))
            return (values / values.sum()).astype(np.float32)

    monkeypatch.setattr(export_module, "OnnxClassifier", ImpreciseOnnxClassifier)
    output = tmp_path / "bundle"

    with pytest.raises(ParityError, match="probability parity"):
        export_checkpoint(
            tiny_checkpoint, output, reference_images, model_id="imprecise-model"
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".bundle-*.tmp"))


@pytest.mark.parametrize(
    ("engine_name", "non_finite"),
    [("PyTorch", np.nan), ("ONNX", np.inf)],
)
def test_non_finite_probabilities_do_not_promote_bundle(
    tiny_checkpoint,
    reference_images,
    tmp_path,
    monkeypatch,
    engine_name,
    non_finite,
):
    if engine_name == "PyTorch":
        real_probabilities = Classifier.probabilities

        def non_finite_probabilities(self, image):
            values = real_probabilities(self, image).copy()
            values[0] = non_finite
            return values

        monkeypatch.setattr(Classifier, "probabilities", non_finite_probabilities)
    else:
        real_classifier = export_module.OnnxClassifier

        class NonFiniteOnnxClassifier(real_classifier):
            def probabilities(self, image):
                values = super().probabilities(image).copy()
                values[0] = non_finite
                return values

        monkeypatch.setattr(
            export_module, "OnnxClassifier", NonFiniteOnnxClassifier
        )

    output = tmp_path / "bundle"
    with pytest.raises(ParityError, match=f"{engine_name} probabilities.*non-finite"):
        export_checkpoint(
            tiny_checkpoint, output, reference_images, model_id="non-finite-model"
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".bundle-*.tmp"))


def test_onnx_classifier_rejects_unsupported_preprocessing_version(tmp_path):
    bundle = write_metadata_test_bundle(
        tmp_path / "bundle", preprocessing_version="rgb-999-v9"
    )

    with pytest.raises(ModelBundleError, match="preprocessing version"):
        OnnxClassifier(bundle)


@pytest.mark.parametrize(
    ("input_shape", "input_type"),
    [((1, 3, 256, 256), TensorProto.FLOAT), ((1, 3, 224, 224), TensorProto.DOUBLE)],
)
def test_onnx_classifier_rejects_wrong_image_input_metadata(
    tmp_path, input_shape, input_type
):
    bundle = write_metadata_test_bundle(
        tmp_path / "bundle", input_shape=input_shape, input_type=input_type
    )

    with pytest.raises(ModelBundleError, match="image input"):
        OnnxClassifier(bundle)


def test_onnx_classifier_rejects_output_width_that_disagrees_with_classes(tmp_path):
    bundle = write_metadata_test_bundle(tmp_path / "bundle", output_width=2)

    with pytest.raises(ModelBundleError, match="output.*3 classes"):
        OnnxClassifier(bundle)


def test_export_requires_at_least_one_reference_image(tiny_checkpoint, tmp_path):
    output = tmp_path / "bundle"

    with pytest.raises(ValueError, match="reference image"):
        export_checkpoint(tiny_checkpoint, output, [], model_id="test-model")

    assert not output.exists()


def test_export_script_can_be_invoked_directly_from_outside_repository(tmp_path):
    script = Path(__file__).parents[1] / "scripts" / "export_onnx.py"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--checkpoint" in result.stdout

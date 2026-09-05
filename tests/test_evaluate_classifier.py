import importlib
import json

import numpy as np
import pytest
import torch
import torch.nn as nn
from PIL import Image


def evaluator():
    try:
        module = importlib.import_module("scripts.evaluate_classifier")
    except ModuleNotFoundError:
        pytest.fail("scripts.evaluate_classifier has not been implemented")
    return module


def test_scan_labeled_images_uses_parent_folder_as_ground_truth(tmp_path):
    mouse = tmp_path / "0301_computer_mouse"
    laptop = tmp_path / "0303_laptop"
    mouse.mkdir()
    laptop.mkdir()
    Image.new("RGB", (20, 20), "white").save(mouse / "mouse01_000.jpg")
    Image.new("RGB", (20, 20), "black").save(laptop / "laptop01_000.jpeg")

    samples = evaluator().scan_labeled_images(
        tmp_path,
        ["0301_computer_mouse", "0301_keyboard", "0303_laptop"],
    )

    assert [(sample["path"].name, sample["true_class"], sample["true_index"])
            for sample in samples] == [
        ("mouse01_000.jpg", "0301_computer_mouse", 0),
        ("laptop01_000.jpeg", "0303_laptop", 2),
    ]


def test_scan_labeled_images_rejects_a_class_the_model_does_not_know(tmp_path):
    unknown = tmp_path / "9999_unknown"
    unknown.mkdir()
    Image.new("RGB", (20, 20)).save(unknown / "sample.jpg")

    with pytest.raises(ValueError, match="9999_unknown"):
        evaluator().scan_labeled_images(tmp_path, ["0303_laptop"])


def test_scan_labeled_images_rejects_heic_in_a_mixed_folder(tmp_path):
    laptop = tmp_path / "0303_laptop"
    laptop.mkdir()
    Image.new("RGB", (20, 20)).save(laptop / "sample.jpg")
    (laptop / "sample.heic").write_bytes(b"not decoded because HEIC is unsupported")

    with pytest.raises(ValueError, match=r"sample\.heic.*JPEG"):
        evaluator().scan_labeled_images(tmp_path, ["0303_laptop"])


def test_scan_labeled_images_validates_unknown_folder_before_file_format(tmp_path):
    unknown = tmp_path / "9999_unknown"
    unknown.mkdir()
    (unknown / "sample.heic").write_bytes(b"unsupported image placeholder")

    with pytest.raises(ValueError, match="9999_unknown"):
        evaluator().scan_labeled_images(tmp_path, ["0303_laptop"])


def test_compute_metrics_reports_literal_accuracy_and_confusion_matrix():
    rows = [
        {"true_index": 0, "predicted_index": 0},
        {"true_index": 0, "predicted_index": 1},
        {"true_index": 2, "predicted_index": 2},
    ]

    metrics = evaluator().compute_metrics(rows, ["mouse", "keyboard", "laptop"])

    assert metrics["total"] == 3
    assert metrics["correct"] == 2
    assert metrics["overall_accuracy"] == pytest.approx(2 / 3)
    assert metrics["per_class"]["mouse"]["support"] == 2
    assert metrics["per_class"]["mouse"]["accuracy"] == pytest.approx(0.5)
    assert metrics["per_class"]["keyboard"]["support"] == 0
    assert metrics["per_class"]["keyboard"]["accuracy"] is None
    assert metrics["per_class"]["laptop"]["accuracy"] == pytest.approx(1.0)
    assert metrics["confusion_matrix"] == [
        [1, 1, 0],
        [0, 0, 0],
        [0, 0, 1],
    ]


class TinyCamModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Conv2d(3, 2, kernel_size=1, bias=False)
        self.head = nn.Linear(2, 2, bias=False)

    def forward(self, x):
        x = torch.relu(self.features(x))
        return self.head(x.mean(dim=(2, 3)))


def test_gradcam_returns_a_normalized_map_matching_the_feature_map():
    torch.manual_seed(7)
    model = TinyCamModel().eval()
    image = torch.linspace(0, 1, 3 * 8 * 8).reshape(1, 3, 8, 8)

    cam = evaluator().gradcam(model, model.features, image, class_index=0)

    assert cam.shape == (8, 8)
    assert np.isfinite(cam).all()
    assert float(cam.min()) >= 0.0
    assert float(cam.max()) <= 1.0


def test_overlay_cam_outputs_a_viewable_rgb_image():
    image = Image.new("RGB", (12, 8), (30, 60, 90))
    cam = np.zeros((4, 6), dtype=np.float32)
    cam[:, 3:] = 1.0

    overlay = evaluator().overlay_cam(image, cam)

    assert overlay.mode == "RGB"
    assert overlay.size == image.size
    assert overlay.getpixel((10, 4)) != image.getpixel((10, 4))


def test_write_report_creates_machine_readable_and_visual_outputs(tmp_path):
    source = tmp_path / "source.jpg"
    model_input = tmp_path / "model-input.jpg"
    heatmap = tmp_path / "heatmap.jpg"
    for path, color in ((source, "white"), (model_input, "gray"), (heatmap, "red")):
        Image.new("RGB", (20, 20), color).save(path)
    rows = [{
        "source_path": str(source),
        "true_class": "0303_laptop",
        "true_index": 0,
        "predicted_class": "0301_keyboard",
        "predicted_index": 1,
        "confidence": 0.75,
        "correct": False,
        "topk": [
            {"class_name": "0301_keyboard", "confidence": 0.75},
            {"class_name": "0303_laptop", "confidence": 0.25},
        ],
        "model_input": "images/model-input.jpg",
        "heatmap": "heatmaps/heatmap.jpg",
    }]
    metrics = {
        "total": 1,
        "correct": 0,
        "overall_accuracy": 0.0,
        "macro_f1_present": 0.0,
        "per_class": {
            "0303_laptop": {"support": 1, "correct": 0, "accuracy": 0.0},
            "0301_keyboard": {"support": 0, "correct": 0, "accuracy": None},
        },
        "confusion_matrix": [[0, 1], [0, 0]],
    }
    out = tmp_path / "report"

    evaluator().write_report(
        out,
        rows,
        metrics,
        classes=["0303_laptop", "0301_keyboard"],
        model_info={"checkpoint": "best.pt", "arch": "resnet18"},
    )

    assert (out / "index.html").is_file()
    assert (out / "predictions.csv").is_file()
    assert (out / "summary.json").is_file()
    assert (out / "confusion_matrix.png").is_file()
    summary = json.loads((out / "summary.json").read_text())
    assert summary["metrics"]["overall_accuracy"] == 0.0
    html = (out / "index.html").read_text()
    assert "Model evaluation" in html
    assert "0301_keyboard" in html
    assert "Incorrect" in html


def test_confusion_matrix_reserves_space_for_long_column_labels(tmp_path):
    classes = [
        "0301_computer_mouse",
        "0301_keyboard",
        "0303_laptop",
        "0306_mobile_phone",
        "0401_headphones",
    ]
    output = tmp_path / "matrix.png"

    evaluator()._write_confusion_matrix(
        output,
        classes,
        [[0 for _ in classes] for _ in classes],
    )

    with Image.open(output) as rendered:
        assert rendered.width >= 190 + 140 * len(classes)


def test_confusion_matrix_column_labels_preserve_every_word():
    module = evaluator()

    assert hasattr(module, "_matrix_column_label")
    assert module._matrix_column_label("0301_computer_mouse") == "Computer\nMouse"
    assert module._matrix_column_label("0301_keyboard") == "Keyboard"
    assert module._matrix_column_label("0306_mobile_phone") == "Mobile\nPhone"

"""
Loads the trained checkpoint once and classifies PIL images.

Class folder names must start with a 4-digit UNU-KEY (e.g. "0306_mobile_phone") so the
value chain can join. Anything before the first underscore is treated as the key.
"""
import pathlib
from collections.abc import Sequence

import numpy as np
import torch
import torch.nn as nn
from torchvision import models

from server.imaging import (
    preprocess_crop_array,
    preprocess_image,
    register_image_formats,
)

DEFAULT_CONFIDENCE_FLOOR = 0.60

register_image_formats()


def _build(arch, n_classes):
    if arch == "resnet18":
        m = models.resnet18(); m.fc = nn.Linear(m.fc.in_features, n_classes)
    elif arch == "resnet50":
        m = models.resnet50(); m.fc = nn.Linear(m.fc.in_features, n_classes)
    elif arch == "efficientnet_b0":
        m = models.efficientnet_b0()
        m.classifier = nn.Sequential(nn.Dropout(0.2),
                                     nn.Linear(m.classifier[1].in_features, n_classes))
    elif arch == "mobilenet_v3_small":
        m = models.mobilenet_v3_small()
        m.classifier[3] = nn.Linear(m.classifier[3].in_features, n_classes)
    else:
        raise ValueError(f"unknown arch {arch}")
    return m


def prediction_from_probabilities(probabilities, classes: Sequence[str], confidence_floor):
    """Build the stable prediction response shared by every inference backend."""
    probabilities = np.asarray(probabilities)
    order = np.argsort(-probabilities, kind="stable")[:min(3, len(classes))]
    top_index = int(order[0])
    top = classes[top_index]
    top_confidence = float(probabilities[top_index])
    key = top.split("_")[0]
    return {
        "class_name": top,
        "unu_key": key if (key.isdigit() and len(key) == 4) else None,
        "confidence": round(top_confidence, 4),
        "low_confidence": top_confidence < confidence_floor,
        "topk": [
            {
                "class_name": classes[int(index)],
                "confidence": round(float(probabilities[index]), 4),
            }
            for index in order
        ],
    }


class Classifier:
    def __init__(self, ckpt_path, confidence_floor=DEFAULT_CONFIDENCE_FLOOR):
        ckpt_path = pathlib.Path(ckpt_path)
        if not ckpt_path.exists():
            raise FileNotFoundError(
                f"No model at {ckpt_path}. Train one with scripts/train_classifier.py first."
            )
        # Threading hurts here: measured 152.9 ms/img at 8 threads vs 24.7 ms/img at 1.
        torch.set_num_threads(1)
        ck = torch.load(ckpt_path, map_location="cpu")
        self.classes = ck["classes"]
        self.arch = ck.get("arch", "resnet18")
        self.confidence_floor = confidence_floor
        self.model = _build(self.arch, len(self.classes))
        self.model.load_state_dict(ck["state_dict"])
        self.model.eval()

    def probabilities(self, pil_image):
        return self.probabilities_preprocessed(preprocess_image(pil_image))

    def probabilities_preprocessed(self, crop):
        x = torch.from_numpy(preprocess_crop_array(crop))
        with torch.no_grad():
            prob = torch.softmax(self.model(x), 1)[0]
        return prob.numpy().astype(np.float32, copy=False)

    def classify(self, pil_image):
        return prediction_from_probabilities(
            self.probabilities(pil_image), self.classes, self.confidence_floor
        )

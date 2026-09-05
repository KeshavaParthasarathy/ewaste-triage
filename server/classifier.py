"""
Loads the trained checkpoint once and classifies PIL images.

Class folder names must start with a 4-digit UNU-KEY (e.g. "0306_mobile_phone") so the
value chain can join. Anything before the first underscore is treated as the key.
"""
import pathlib

import torch
import torch.nn as nn
from torchvision import models, transforms

MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
DEFAULT_CONFIDENCE_FLOOR = 0.60


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
        self.tf = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(MEAN, STD),
        ])

    def classify(self, pil_image):
        x = self.tf(pil_image.convert("RGB")).unsqueeze(0)
        with torch.no_grad():
            prob = torch.softmax(self.model(x), 1)[0]
        k = min(3, len(self.classes))
        conf, idx = prob.topk(k)
        conf, idx = conf.tolist(), idx.tolist()
        top = self.classes[idx[0]]
        key = top.split("_")[0]
        return {
            "class_name": top,
            "unu_key": key if (key.isdigit() and len(key) == 4) else None,
            "confidence": round(conf[0], 4),
            "low_confidence": conf[0] < self.confidence_floor,
            "topk": [{"class_name": self.classes[i], "confidence": round(c, 4)}
                     for c, i in zip(conf, idx)],
        }

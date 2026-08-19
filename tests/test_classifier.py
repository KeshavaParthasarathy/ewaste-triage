import pytest
import torch
import torch.nn as nn
from PIL import Image
from torchvision import models

from server.classifier import Classifier


@pytest.fixture
def ckpt(tmp_path):
    m = models.resnet18()
    m.fc = nn.Linear(m.fc.in_features, 3)
    p = tmp_path / "best.pt"
    torch.save({"arch": "resnet18",
                "classes": ["0301_small_it", "0306_mobile_phones", "0401_small_consumer"],
                "state_dict": m.state_dict()}, p)
    return p


def test_classify_returns_a_known_class(ckpt):
    c = Classifier(ckpt)
    r = c.classify(Image.new("RGB", (400, 300), (120, 90, 60)))
    assert r["class_name"] in c.classes
    assert 0.0 <= r["confidence"] <= 1.0
    assert len(r["topk"]) == 3


def test_unu_key_is_parsed_from_the_class_name(ckpt):
    c = Classifier(ckpt)
    r = c.classify(Image.new("RGB", (400, 300)))
    assert r["unu_key"] in {"0301", "0306", "0401"}


def test_low_confidence_is_flagged(ckpt):
    c = Classifier(ckpt, confidence_floor=1.01)
    r = c.classify(Image.new("RGB", (400, 300)))
    assert r["low_confidence"] is True


def test_missing_checkpoint_fails_at_construction(tmp_path):
    with pytest.raises(FileNotFoundError):
        Classifier(tmp_path / "absent.pt")

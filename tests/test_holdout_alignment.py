from PIL import Image
from torchvision import datasets

from scripts.train_classifier import align_holdout_classes


def test_align_holdout_classes_uses_training_class_indices(tmp_path):
    """A partial holdout must not renumber laptop/phone as model classes zero/one."""
    for class_name in ("0303_laptop", "0306_mobile_phone"):
        folder = tmp_path / class_name
        folder.mkdir()
        Image.new("RGB", (20, 20)).save(folder / "sample.jpg")
    holdout = datasets.ImageFolder(tmp_path)
    training_classes = [
        "0301_computer_mouse",
        "0301_keyboard",
        "0303_laptop",
        "0306_mobile_phone",
        "0401_headphones",
    ]

    aligned = align_holdout_classes(holdout, training_classes)

    assert aligned.classes == training_classes
    assert aligned.class_to_idx["0303_laptop"] == 2
    assert aligned.class_to_idx["0306_mobile_phone"] == 3
    assert sorted(aligned.targets) == [2, 3]
    assert sorted(target for _, target in aligned.samples) == [2, 3]

import pathlib

import pytest

import scripts.split_dataset as split_module
from scripts.split_dataset import group_split, write_splits


def test_no_device_appears_in_both_splits():
    files = [(f"cls_a/dev{d}_{i}.jpg", "cls_a", f"dev{d}") for d in range(10) for i in range(5)]
    train, val = group_split(files, val_frac=0.3, seed=0)
    train_devs = {d for _, _, d in train}
    val_devs = {d for _, _, d in val}
    assert train_devs & val_devs == set()


def test_every_file_lands_somewhere():
    files = [(f"cls_a/dev{d}_{i}.jpg", "cls_a", f"dev{d}") for d in range(10) for i in range(5)]
    train, val = group_split(files, val_frac=0.3, seed=0)
    assert len(train) + len(val) == len(files)


def test_each_class_keeps_at_least_one_val_device():
    files = []
    for cls in ("a", "b"):
        for d in range(4):
            files += [(f"{cls}/dev{cls}{d}_{i}.jpg", cls, f"dev{cls}{d}") for i in range(3)]
    train, val = group_split(files, val_frac=0.25, seed=0)
    assert {c for _, c, _ in val} == {"a", "b"}


def test_write_splits_replaces_stale_outputs_on_rerun(tmp_path):
    """Changing a split must not leave old photos in train or validation."""
    src = tmp_path / "raw"
    cls = src / "class_a"
    cls.mkdir(parents=True)
    for name in ("dev1_0.jpg", "dev2_0.jpg", "dev3_0.jpg"):
        (cls / name).write_bytes(name.encode())
    dst = tmp_path / "photos"
    first_train = [("class_a/dev1_0.jpg", "class_a", "dev1")]
    first_val = [("class_a/dev2_0.jpg", "class_a", "dev2")]
    write_splits(src, dst, first_train, first_val)

    second_train = [("class_a/dev3_0.jpg", "class_a", "dev3")]
    second_val = [("class_a/dev1_0.jpg", "class_a", "dev1")]
    write_splits(src, dst, second_train, second_val)

    assert {p.name for p in (dst / "train" / "class_a").iterdir()} == {"dev3_0.jpg"}
    assert {p.name for p in (dst / "val" / "class_a").iterdir()} == {"dev1_0.jpg"}


def test_write_splits_preserves_existing_outputs_when_staging_copy_fails(tmp_path, monkeypatch):
    """A pre-swap copy failure must not delete the last known-good split."""
    src = tmp_path / "raw"
    cls = src / "class_a"
    cls.mkdir(parents=True)
    for name in ("dev1_0.jpg", "dev2_0.jpg"):
        (cls / name).write_bytes(name.encode())
    dst = tmp_path / "photos"
    train = [("class_a/dev1_0.jpg", "class_a", "dev1")]
    val = [("class_a/dev2_0.jpg", "class_a", "dev2")]
    write_splits(src, dst, train, val)

    monkeypatch.setattr(split_module.shutil, "copy2", lambda *_: (_ for _ in ()).throw(OSError("copy failed")))

    with pytest.raises(OSError, match="copy failed"):
        write_splits(src, dst, val, train)

    assert (dst / "train" / "class_a" / "dev1_0.jpg").read_bytes() == b"dev1_0.jpg"
    assert (dst / "val" / "class_a" / "dev2_0.jpg").read_bytes() == b"dev2_0.jpg"


def test_write_splits_rolls_back_only_mutated_outputs_when_swap_fails(tmp_path, monkeypatch):
    """A mid-swap failure must restore train without deleting untouched validation."""
    src = tmp_path / "raw"
    cls = src / "class_a"
    cls.mkdir(parents=True)
    for name in ("dev1_0.jpg", "dev2_0.jpg"):
        (cls / name).write_bytes(name.encode())
    dst = tmp_path / "photos"
    train = [("class_a/dev1_0.jpg", "class_a", "dev1")]
    val = [("class_a/dev2_0.jpg", "class_a", "dev2")]
    write_splits(src, dst, train, val)
    original_replace = pathlib.Path.replace

    def fail_before_val_backup(path, target):
        if path == dst / "val":
            raise OSError("swap failed")
        return original_replace(path, target)

    monkeypatch.setattr(pathlib.Path, "replace", fail_before_val_backup)

    with pytest.raises(OSError, match="swap failed"):
        write_splits(src, dst, val, train)

    assert (dst / "train" / "class_a" / "dev1_0.jpg").read_bytes() == b"dev1_0.jpg"
    assert (dst / "val" / "class_a" / "dev2_0.jpg").read_bytes() == b"dev2_0.jpg"

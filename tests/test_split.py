from scripts.split_dataset import group_split


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

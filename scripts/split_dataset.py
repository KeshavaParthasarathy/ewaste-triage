"""
Device-level train/val split.

Photos are named <device_id>_<n>.jpg inside a per-class folder. Splitting by PHOTO
leaks the same physical device into both sides and produces validation accuracy that
measures memorization rather than generalization. This splits by DEVICE.

    .venv/bin/python -m scripts.split_dataset --src data/photos/raw --dst data/photos
"""
import argparse
import pathlib
import random
import shutil
import tempfile

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def scan(src):
    """Return [(relative_path, class_name, device_id), ...]."""
    out = []
    for cls_dir in sorted(p for p in pathlib.Path(src).iterdir() if p.is_dir()):
        for f in sorted(cls_dir.iterdir()):
            if f.suffix.lower() in IMG_EXT:
                out.append((str(f.relative_to(src)), cls_dir.name, f.stem.split("_")[0]))
    return out


def group_split(files, val_frac=0.25, seed=0):
    """Split by device, keeping at least one validation device per class."""
    rng = random.Random(seed)
    by_class = {}
    for rec in files:
        by_class.setdefault(rec[1], set()).add(rec[2])

    val_devices = set()
    for cls, devices in by_class.items():
        devs = sorted(devices)
        rng.shuffle(devs)
        n = max(1, round(len(devs) * val_frac)) if len(devs) > 1 else 0
        val_devices.update(devs[:n])

    train = [r for r in files if r[2] not in val_devices]
    val = [r for r in files if r[2] in val_devices]
    return train, val


def write_splits(src, dst, train, val):
    """Build clean split directories, then swap them in with rollback support."""
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    stage = pathlib.Path(tempfile.mkdtemp(prefix=".photo-split-", dir=dst))
    splits = {"train": train, "val": val}
    mutations = []
    try:
        for split, recs in splits.items():
            (stage / split).mkdir()
            for rel, cls, _ in recs:
                out = stage / split / cls
                out.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / rel, out / pathlib.Path(rel).name)

        for split in splits:
            final = dst / split
            backup = stage / f"{split}.old"
            mutation = {
                "final": final,
                "backup": backup,
                "backup_created": False,
                "installed": False,
            }
            mutations.append(mutation)
            if final.exists():
                final.replace(backup)
                mutation["backup_created"] = True
            (stage / split).replace(final)
            mutation["installed"] = True
    except Exception:
        for mutation in reversed(mutations):
            final = mutation["final"]
            backup = mutation["backup"]
            if mutation["installed"] and final.exists():
                shutil.rmtree(final)
            if mutation["backup_created"] and backup.exists():
                backup.replace(final)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="folder of <class>/<device_id>_<n>.jpg")
    ap.add_argument("--dst", required=True, help="output root; train/ and val/ are created")
    ap.add_argument("--val-frac", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    src, dst = pathlib.Path(a.src), pathlib.Path(a.dst)
    files = scan(src)
    if not files:
        raise SystemExit(f"no images found under {src}")
    train, val = group_split(files, a.val_frac, a.seed)

    write_splits(src, dst, train, val)

    n_train_dev = len({d for _, _, d in train})
    n_val_dev = len({d for _, _, d in val})
    print(f"train: {len(train)} photos / {n_train_dev} devices")
    print(f"val:   {len(val)} photos / {n_val_dev} devices")
    print("Devices are disjoint across splits — validation measures generalization.")


if __name__ == "__main__":
    main()

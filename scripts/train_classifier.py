"""
Transfer-learning classifier: device photo -> UNU-KEY category.

Starts from an ImageNet-pretrained backbone and retrains only the head (optionally
the last block too). That is what makes ~100 images per class enough instead of ~50,000.

Expected layout (torchvision ImageFolder):

    data/photos/train/0306_mobile_phone/*.jpg
    data/photos/train/0301_small_it/*.jpg
    data/photos/val/0306_mobile_phone/*.jpg
    ...
    data/photos/holdout_own/0306_mobile_phone/*.jpg    <- YOUR phone photos (optional)

The holdout set is the science: train on public dataset images, then measure how much
accuracy drops on photos you took yourself. That gap is domain shift, and reporting it
honestly is worth more than a single inflated benchmark number.

    .venv/bin/python scripts/train_classifier.py --smoke-test        # verify pipeline, no data needed
    .venv/bin/python scripts/train_classifier.py --data-dir data/photos --epochs 15
    .venv/bin/python scripts/train_classifier.py --data-dir data/photos --holdout-dir data/photos/holdout_own
"""
import argparse, json, pathlib, random, shutil, sys, time
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, WeightedRandomSampler
from torchvision import datasets, models, transforms
from sklearn.metrics import classification_report, confusion_matrix

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.imaging import MEAN, STD, normalize_image, preprocess_array


def seed_everything(seed):
    """Seed every RNG used by model initialization, augmentation, and sampling."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def pick_device():
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def build_transforms(train):
    if train:
        # Aggressive augmentation is how you survive a small dataset AND narrow the
        # gap between clean dataset images and messy real phone photos.
        return transforms.Compose([
            transforms.Lambda(normalize_image),
            transforms.RandomResizedCrop(224, scale=(0.6, 1.0)),
            transforms.RandomHorizontalFlip(),
            transforms.RandomRotation(15),
            transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.3, hue=0.05),
            transforms.ToTensor(),
            transforms.Normalize(MEAN, STD),
            transforms.RandomErasing(p=0.25, scale=(0.02, 0.15)),
        ])
    return transforms.Lambda(lambda image: torch.from_numpy(preprocess_array(image))[0])


def build_model(arch, n_classes, unfreeze_blocks):
    if arch == "resnet18":
        m = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
        head_in, head_name = m.fc.in_features, "fc"
    elif arch == "resnet50":
        m = models.resnet50(weights=models.ResNet50_Weights.IMAGENET1K_V2)
        head_in, head_name = m.fc.in_features, "fc"
    elif arch == "efficientnet_b0":
        m = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.IMAGENET1K_V1)
        head_in, head_name = m.classifier[1].in_features, "classifier"
    else:
        sys.exit(f"unknown arch {arch}")

    for p in m.parameters():          # freeze everything the backbone already learned
        p.requires_grad = False

    if head_name == "fc":
        m.fc = nn.Linear(head_in, n_classes)
        if unfreeze_blocks >= 1:      # let the last block adapt to e-waste textures
            for p in m.layer4.parameters():
                p.requires_grad = True
    else:
        m.classifier = nn.Sequential(nn.Dropout(0.2), nn.Linear(head_in, n_classes))
        if unfreeze_blocks >= 1:
            for p in m.features[-2:].parameters():
                p.requires_grad = True
    return m


def make_synthetic(root, n_classes=4, per_class=24):
    """Coloured-noise images so the training loop can be verified before any real photos exist."""
    from PIL import Image
    rng = np.random.default_rng(0)
    if root.exists():
        shutil.rmtree(root)
    for split, n in (("train", per_class), ("val", max(4, per_class // 3))):
        for c in range(n_classes):
            d = root / split / f"synthclass_{c}"
            d.mkdir(parents=True, exist_ok=True)
            base = rng.integers(40, 215, size=3)
            for i in range(n):
                arr = np.clip(base + rng.normal(0, 28, (224, 224, 3)), 0, 255).astype(np.uint8)
                Image.fromarray(arr).save(d / f"{i:03d}.jpg", quality=88)
    return root


@torch.no_grad()
def evaluate(model, loader, device, classes, title):
    model.eval()
    y_true, y_pred, confs = [], [], []
    for x, y in loader:
        logits = model(x.to(device))
        prob = torch.softmax(logits, 1)
        conf, pred = prob.max(1)
        y_true += y.tolist()
        y_pred += pred.cpu().tolist()
        confs += conf.cpu().tolist()
    acc = float(np.mean(np.array(y_true) == np.array(y_pred))) if y_true else float("nan")
    print(f"\n=== {title} ===  n={len(y_true)}  accuracy={acc:.3f}  mean confidence={np.mean(confs):.3f}")
    if y_true:
        present = sorted(set(y_true) | set(y_pred))
        print(classification_report(y_true, y_pred, labels=present,
                                    target_names=[classes[i] for i in present], zero_division=0))
        print("confusion matrix (rows=true, cols=pred):")
        print(confusion_matrix(y_true, y_pred, labels=present))
    return acc


def warn_about_heic(data_dir):
    """torchvision's ImageFolder silently drops .heic. Fail loudly instead."""
    heic = list(pathlib.Path(data_dir).rglob("*.heic")) + list(pathlib.Path(data_dir).rglob("*.HEIC"))
    if heic:
        print(f"\n!! {len(heic)} .heic file(s) found under {data_dir}.")
        print("!! torchvision 0.28 IGNORES these silently — they will NOT be in your dataset.")
        print("!! Fix: set the iPhone camera to 'Most Compatible', or convert:")
        print(f"!!   sips -s format jpeg {data_dir}/**/*.heic --out <same folder>")
        print("!! Example dropped file:", heic[0], "\n")


def align_holdout_classes(dataset, training_classes):
    """Remap a partial ImageFolder holdout onto the trained model's class indices."""
    unknown = [name for name in dataset.classes if name not in training_classes]
    if unknown:
        raise ValueError(f"holdout contains classes absent from training: {unknown}")
    old_to_new = {
        old_idx: training_classes.index(name)
        for name, old_idx in dataset.class_to_idx.items()
    }
    dataset.samples = [(path, old_to_new[target]) for path, target in dataset.samples]
    dataset.imgs = dataset.samples
    dataset.targets = [target for _, target in dataset.samples]
    dataset.classes = list(training_classes)
    dataset.class_to_idx = {name: idx for idx, name in enumerate(training_classes)}
    return dataset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data" / "photos"))
    ap.add_argument("--holdout-dir", default=None, help="your own phone photos, for domain-shift measurement")
    ap.add_argument("--arch", default="resnet18", choices=["resnet18", "resnet50", "efficientnet_b0"])
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--unfreeze", type=int, default=1, help="0=head only, 1=head + last block")
    ap.add_argument("--seed", type=int, default=20260821)
    ap.add_argument("--out", default=None)
    ap.add_argument("--smoke-test", action="store_true")
    a = ap.parse_args()
    seed_everything(a.seed)

    data_dir = pathlib.Path(a.data_dir)
    if a.smoke_test:
        data_dir = make_synthetic(ROOT / "data" / "_smoketest")
        a.epochs = min(a.epochs, 3)
        print(f"SMOKE TEST — synthetic noise images in {data_dir}. Metrics are meaningless by design.\n")
    if a.out is None:
        a.out = str(ROOT / "models" / "smoke-test") if a.smoke_test else str(ROOT / "models")
    if not (data_dir / "train").exists():
        sys.exit(f"No {data_dir/'train'}. See the docstring for the expected folder layout, "
                 f"or run with --smoke-test first.")

    warn_about_heic(data_dir)

    device = pick_device()
    train_ds = datasets.ImageFolder(data_dir / "train", build_transforms(True))
    val_ds = datasets.ImageFolder(data_dir / "val", build_transforms(False))
    classes = train_ds.classes
    print(f"device={device}  arch={a.arch}  seed={a.seed}  classes={len(classes)}  "
          f"train={len(train_ds)}  val={len(val_ds)}")

    counts = np.bincount([y for _, y in train_ds.samples], minlength=len(classes))
    print("per-class train counts:", dict(zip(classes, counts.tolist())))
    thin = [c for c, n in zip(classes, counts) if n < 40]
    if thin:
        print(f"WARNING: under 40 images in {thin} — transfer learning gets unreliable below ~50/class.")

    # Oversample rare classes so the model does not simply learn to predict the common one.
    w = (1.0 / np.maximum(counts, 1))[[y for _, y in train_ds.samples]]
    sampler_generator = torch.Generator().manual_seed(a.seed)
    sampler = WeightedRandomSampler(
        torch.DoubleTensor(w), len(w), replacement=True, generator=sampler_generator
    )
    train_dl = DataLoader(train_ds, batch_size=a.batch_size, sampler=sampler, num_workers=0)
    val_dl = DataLoader(val_ds, batch_size=a.batch_size, num_workers=0)

    model = build_model(a.arch, len(classes), a.unfreeze).to(device)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"training {trainable:,} of {total:,} parameters ({trainable/total:.1%}) — the rest is frozen\n")

    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=a.epochs)
    crit = nn.CrossEntropyLoss(label_smoothing=0.05)

    outdir = pathlib.Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    best, t0 = -1.0, time.time()

    for ep in range(1, a.epochs + 1):
        model.train()
        tot = correct = 0
        run = 0.0
        for x, y in train_dl:
            x, y = x.to(device), y.to(device)
            opt.zero_grad()
            out = model(x)
            loss = crit(out, y)
            loss.backward()
            opt.step()
            run += loss.item() * y.size(0)
            correct += (out.argmax(1) == y).sum().item()
            tot += y.size(0)
        sched.step()

        model.eval()
        vc = vt = 0
        with torch.no_grad():
            for x, y in val_dl:
                x, y = x.to(device), y.to(device)
                vc += (model(x).argmax(1) == y).sum().item()
                vt += y.size(0)
        vacc = vc / max(vt, 1)
        print(f"epoch {ep:2d}/{a.epochs}  train_loss={run/tot:.4f}  train_acc={correct/tot:.3f}  val_acc={vacc:.3f}")

        if vacc > best:
            best = vacc
            run_config = {
                "arch": a.arch,
                "epochs": a.epochs,
                "batch_size": a.batch_size,
                "lr": a.lr,
                "unfreeze": a.unfreeze,
                "seed": a.seed,
            }
            torch.save({"arch": a.arch, "classes": classes, "state_dict": model.state_dict(),
                        "config": run_config, "best_val_accuracy": vacc},
                       outdir / "best.pt")
            (outdir / "classes.json").write_text(json.dumps(classes, indent=2))

    print(f"\nbest val accuracy {best:.3f} in {time.time()-t0:.0f}s -> {outdir/'best.pt'}")

    model.load_state_dict(torch.load(outdir / "best.pt", map_location=device)["state_dict"])
    evaluate(model, val_dl, device, classes, "VAL (same source as training)")

    if a.holdout_dir:
        hd = pathlib.Path(a.holdout_dir)
        if hd.exists():
            h_ds = datasets.ImageFolder(hd, build_transforms(False))
            present_holdout_classes = list(h_ds.classes)
            h_ds = align_holdout_classes(h_ds, classes)
            if present_holdout_classes != classes:
                print(f"\nNOTE: holdout covers only {present_holdout_classes}; "
                      "their labels were aligned to the trained model indices.")
            h_acc = evaluate(model, DataLoader(h_ds, batch_size=a.batch_size), device, classes,
                             "HOLDOUT (your own phone photos)")
            print(f"\nDOMAIN SHIFT: val {best:.3f} -> own photos {h_acc:.3f}  (drop {best-h_acc:+.3f})")
            print("Report this number. A large drop is a real finding about dataset realism, not a failure.")
        else:
            print(f"\nholdout dir {hd} not found — skipped")


if __name__ == "__main__":
    main()

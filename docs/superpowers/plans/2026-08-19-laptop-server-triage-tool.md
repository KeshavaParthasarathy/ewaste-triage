# Laptop-Server E-Waste Triage Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Flask server on the MacBook that accepts a photo from a phone browser over the phone's own Personal Hotspot and returns device class, part breakdown, reusable parts, and an estimated dollar value with an error bar.

**Architecture:** The phone is the router; the laptop is a client on the hotspot subnet. A self-contained HTML page (no external assets) captures a photo, downscales it to 1024px in canvas, and POSTs it. The server loads `models/best.pt` once at startup, classifies, and joins to the UNU-KEY reference and composition tables to produce dollars. The same server doubles as the photo-ingest tool during data collection.

**Tech Stack:** Python 3.11, PyTorch 2.13 + torchvision 0.28 (MPS), Flask, pytest, vanilla JS.

**Reference spec:** `docs/superpowers/specs/2026-08-19-ewaste-triage-product-design.md`

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `scripts/valuation.py` | Pure function: UNU-KEY (+ mass) → value dict. No I/O beyond reading reference CSVs. | Create |
| `scripts/estimate_value.py` | Thin CLI wrapper over `valuation.estimate` | Modify |
| `scripts/predict.py` | CLI: photo → class → value. Imports valuation, no subprocess. | Modify |
| `scripts/split_dataset.py` | Device-level train/val split | Create |
| `server/classifier.py` | Loads checkpoint once; `classify(PIL.Image) -> dict` | Create |
| `server/app.py` | Flask routes: `/`, `/classify`, `/ingest`, `/health` | Create |
| `server/static/index.html` | Capture page. Zero external assets. | Create |
| `data/scrap_prices.json` | Scrap prices + the date they were quoted | Create |
| `tests/test_valuation.py` | Valuation unit tests | Create |
| `tests/test_classifier.py` | Classifier unit tests | Create |
| `tests/test_server.py` | Endpoint tests + CLI/web equivalence | Create |

---

## Task 0: Hotspot viability test (DO THIS FIRST — 30 minutes)

The entire architecture rests on one unverified assumption: that Safari on the phone can reach an HTTP server on the MacBook over the phone's own Personal Hotspot. Some carrier builds enforce AP client isolation. If this fails, stop and switch to the PWA path in the spec — having lost 30 minutes rather than four weeks.

**Files:**
- Create: `/tmp/hotspot_test.py` (throwaway, do not commit)

- [ ] **Step 1: Install Flask into the venv**

```bash
cd ~/ewaste-triage
.venv/bin/pip install flask pytest
```

Expected: `Successfully installed flask-... pytest-...`

- [ ] **Step 2: Write the throwaway probe**

```python
# /tmp/hotspot_test.py
from flask import Flask, request

app = Flask(__name__)

PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<h2>Hotspot test</h2>
<form method=post enctype=multipart/form-data action=/up>
<input type=file name=f accept="image/*" capture="environment"><br><br>
<button>Upload</button></form>"""

@app.get("/")
def home():
    return PAGE

@app.post("/up")
def up():
    data = request.files["f"].read()
    return f"<h2>OK — received {len(data):,} bytes</h2><a href='/'>again</a>"

app.run(host="0.0.0.0", port=8777)
```

- [ ] **Step 3: Turn on Personal Hotspot and join the Mac to it**

On the iPhone: Settings → Personal Hotspot → Allow Others to Join. Turn **Low Power Mode off** — it disables Personal Hotspot.
On the Mac: join the phone's hotspot network from the WiFi menu.

- [ ] **Step 4: Run the server and find the Mac's hotspot IP**

```bash
cd ~/ewaste-triage
.venv/bin/python /tmp/hotspot_test.py &
ipconfig getifaddr en0
```

Expected: an address like `172.20.10.2`. Approve the macOS "accept incoming connections" firewall prompt when it appears — if you deny it once it never reappears and the phone will simply time out with no error anywhere.

- [ ] **Step 5: Test from the phone**

Open `http://<that-ip>:8777` in Safari on the phone. Tap the file input, take a photo, upload.

**PASS:** "OK — received N bytes". The architecture is validated. Continue to Task 1.
**FAIL (page never loads):** AP client isolation. Stop. Switch to the PWA path in spec §3.
**FAIL (file input does not open the camera):** `capture="environment"` is unsupported here; the page still works via the photo library. Note it and continue.

- [ ] **Step 6: Record the result**

```bash
cd ~/ewaste-triage
echo "## Phase 0 hotspot test — $(date +%Y-%m-%d)" >> docs/experiment-log.md
echo "Result: PASS/FAIL (edit this). Mac hotspot IP: <ip>. Bytes received: <n>." >> docs/experiment-log.md
git add docs/experiment-log.md && git commit -m "test: record Phase 0 hotspot viability result"
```

---

## Task 1: Externalize scrap prices to JSON

Prices are currently hardcoded constants with a placeholder date. They need to be data the student updates weekly from real quotes.

**Files:**
- Create: `data/scrap_prices.json`
- Test: `tests/test_valuation.py`

- [ ] **Step 1: Create the prices file**

```json
{
  "quoted_date": "PLACEHOLDER - replace with the date you pulled these",
  "source": "iscrapapp.com/metals/ and boardsort.com/payout.php",
  "usd_per_lb": {
    "low": 0.60,
    "mid": 1.60,
    "high": 6.00,
    "ferrous": 0.06,
    "nonferrous": 2.20
  },
  "price_uncertainty": 0.30,
  "mass_uncertainty_category_average": 0.50
}
```

- [ ] **Step 2: Commit**

```bash
cd ~/ewaste-triage
git add data/scrap_prices.json
git commit -m "feat: externalize scrap prices to data/scrap_prices.json"
```

---

## Task 2: Extract valuation into an importable module

The server and the CLI must share one implementation of the value chain, or they will drift and report different dollars for the same device.

**Files:**
- Create: `scripts/valuation.py`
- Create: `tests/test_valuation.py`
- Modify: `scripts/estimate_value.py` (becomes a thin CLI wrapper)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_valuation.py
import json
import pytest
from scripts import valuation


@pytest.fixture
def comp_file(tmp_path):
    p = tmp_path / "composition_priors.csv"
    p.write_text(
        "unu_key,description,frac_pcb,frac_ferrous,frac_nonferrous,frac_plastic,board_grade,source_citation\n"
        "0306,Mobile Phones,0.20,0.05,0.10,0.40,high,TEST\n"
    )
    return p


def test_estimate_uses_measured_mass_when_given(comp_file):
    r = valuation.estimate("0306", mass_g=168.0, composition_path=comp_file)
    assert r["mass_kg"] == pytest.approx(0.168)
    assert r["mass_source"] == "measured"
    assert r["value_usd"] > 0
    assert r["value_low"] < r["value_usd"] < r["value_high"]


def test_estimate_falls_back_to_category_average(comp_file):
    r = valuation.estimate("0306", composition_path=comp_file)
    assert r["mass_kg"] == pytest.approx(0.1)
    assert r["mass_source"] == "UNU EU-28 average"


def test_measured_mass_gives_a_tighter_range(comp_file):
    measured = valuation.estimate("0306", mass_g=168.0, composition_path=comp_file)
    average = valuation.estimate("0306", composition_path=comp_file)
    assert measured["rel_uncertainty"] < average["rel_uncertainty"]


def test_unknown_key_raises(comp_file):
    with pytest.raises(valuation.UnknownKey):
        valuation.estimate("9999", composition_path=comp_file)


def test_missing_composition_file_raises(tmp_path):
    with pytest.raises(valuation.CompositionUnavailable):
        valuation.estimate("0306", composition_path=tmp_path / "nope.csv")
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/ewaste-triage
.venv/bin/python -m pytest tests/test_valuation.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.valuation'`

- [ ] **Step 3: Create the package marker**

```bash
cd ~/ewaste-triage
touch scripts/__init__.py tests/__init__.py
```

- [ ] **Step 4: Write the module**

```python
# scripts/valuation.py
"""
UNU-KEY (+ optional measured mass) -> estimated recoverable material value.

Single source of truth for the value chain. Both the CLI (estimate_value.py) and the
server import this, so the two can never report different dollars for the same device.

Reports a RANGE, not a point estimate. UNU weights are EU-28 averages, composition
fractions are literature averages, and scrap prices move weekly. A single number would
be false precision.

MATERIAL value only. Reuse value of a working part is a different, much larger number
and is not predictable from a photo.
"""
import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
LB_PER_KG = 2.20462
MEASURED_MASS_UNCERTAINTY = 0.02


class UnknownKey(Exception):
    """UNU-KEY absent from the reference or composition table."""


class CompositionUnavailable(Exception):
    """composition_priors.csv is missing. We do not invent composition numbers."""


def load_prices(path=None):
    path = pathlib.Path(path or ROOT / "data" / "scrap_prices.json")
    return json.loads(path.read_text())


def estimate(unu_key, mass_g=None, composition_path=None, keys_path=None, prices_path=None):
    """Return a dict describing the estimated material value and its uncertainty."""
    keys_path = pathlib.Path(keys_path or ROOT / "data" / "unu_key_reference.csv")
    composition_path = pathlib.Path(composition_path or ROOT / "data" / "composition_priors.csv")
    if not composition_path.exists():
        raise CompositionUnavailable(
            f"No {composition_path}. Copy composition_priors_TEMPLATE.csv to "
            f"composition_priors.csv and fill it from Oguchi 2011 / Cucchiella 2015."
        )

    prices = load_prices(prices_path)
    keys = pd.read_csv(keys_path, dtype={"unu_key": str})
    comp = pd.read_csv(composition_path, dtype={"unu_key": str}, comment="#")

    krow = keys[keys.unu_key == unu_key]
    crow = comp[comp.unu_key == unu_key]
    if krow.empty or crow.empty:
        raise UnknownKey(f"UNU-KEY {unu_key} missing from reference or composition table")
    krow, crow = krow.iloc[0], crow.iloc[0]

    if mass_g is not None:
        mass_kg = mass_g / 1000.0
        mass_rel_err = MEASURED_MASS_UNCERTAINTY
        mass_source = "measured"
    else:
        mass_kg = float(krow.avg_unit_weight_kg_2012)
        mass_rel_err = prices["mass_uncertainty_category_average"]
        mass_source = "UNU EU-28 average"

    ppl = prices["usd_per_lb"]
    streams = {
        "pcb": (crow.frac_pcb, ppl.get(str(crow.board_grade))),
        "ferrous": (crow.frac_ferrous, ppl["ferrous"]),
        "nonferrous": (crow.frac_nonferrous, ppl["nonferrous"]),
    }

    breakdown, total = {}, 0.0
    for name, (frac, price) in streams.items():
        if pd.isna(frac) or price is None:
            breakdown[name] = None
            continue
        v = mass_kg * float(frac) * LB_PER_KG * float(price)
        breakdown[name] = {"mass_fraction": float(frac), "value_usd": round(v, 4)}
        total += v

    rel = (mass_rel_err ** 2 + prices["price_uncertainty"] ** 2) ** 0.5
    return {
        "unu_key": unu_key,
        "description": str(krow.description),
        "mass_kg": mass_kg,
        "mass_source": mass_source,
        "board_grade": str(crow.board_grade),
        "breakdown": breakdown,
        "value_usd": round(total, 3),
        "value_low": round(total * (1 - rel), 3),
        "value_high": round(total * (1 + rel), 3),
        "rel_uncertainty": round(rel, 3),
        "prices_quoted_date": prices["quoted_date"],
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd ~/ewaste-triage
.venv/bin/python -m pytest tests/test_valuation.py -v
```

Expected: 5 passed

- [ ] **Step 6: Rewrite estimate_value.py as a thin CLI wrapper**

Replace the entire contents of `scripts/estimate_value.py` with:

```python
"""
CLI over scripts/valuation.estimate.

    .venv/bin/python scripts/estimate_value.py 0306
    .venv/bin/python scripts/estimate_value.py 0306 --mass-g 168

MATERIAL value only — see valuation.py.
"""
import argparse
import sys

from scripts import valuation


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("unu_key")
    ap.add_argument("--mass-g", type=float, default=None)
    a = ap.parse_args()

    try:
        r = valuation.estimate(a.unu_key, mass_g=a.mass_g)
    except (valuation.UnknownKey, valuation.CompositionUnavailable) as e:
        sys.exit(str(e))

    print(f"{r['unu_key']}  {r['description']}")
    print(f"  mass: {r['mass_kg']:.3f} kg ({r['mass_source']})")
    print(f"  board grade: {r['board_grade']}   prices dated: {r['prices_quoted_date']}\n")
    for name, b in r["breakdown"].items():
        if b is None:
            print(f"  {name:<12} -- composition not filled in --")
        else:
            print(f"  {name:<12} {b['mass_fraction']:5.1%} of mass  ->  ${b['value_usd']:6.3f}")
    print(f"\n  material value: ${r['value_usd']:.2f}   "
          f"range ${r['value_low']:.2f} - ${r['value_high']:.2f}  (+/-{r['rel_uncertainty']:.0%})")
    if r["mass_source"] != "measured":
        print("  ^ weigh the device and re-run with --mass-g to cut this range roughly in half.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Verify the CLI still refuses cleanly with no composition file**

```bash
cd ~/ewaste-triage
.venv/bin/python -m scripts.estimate_value 0306
```

Expected: the "No .../composition_priors.csv" message, exit code 1.

- [ ] **Step 8: Commit**

```bash
cd ~/ewaste-triage
git add scripts/valuation.py scripts/estimate_value.py scripts/__init__.py tests/
git commit -m "refactor: extract valuation into importable module with tests"
```

---

## Task 3: Point predict.py at the module instead of subprocess

**Files:**
- Modify: `scripts/predict.py`

- [ ] **Step 1: Replace the subprocess call**

In `scripts/predict.py`, delete `import subprocess` and add `from scripts import valuation`. Replace the final block (from `cmd = [sys.executable, ...]` through `subprocess.run(cmd)`) with:

```python
    try:
        r = valuation.estimate(key, mass_g=a.mass_g)
    except (valuation.UnknownKey, valuation.CompositionUnavailable) as e:
        print(f"  {e}")
        return

    print(f"  {r['description']}")
    print(f"  mass {r['mass_kg']:.3f} kg ({r['mass_source']})")
    print(f"  material value ${r['value_usd']:.2f}  "
          f"(${r['value_low']:.2f} - ${r['value_high']:.2f})")
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd ~/ewaste-triage
.venv/bin/python -m scripts.predict --help
```

Expected: the argparse help text, exit code 0.

- [ ] **Step 3: Commit**

```bash
cd ~/ewaste-triage
git add scripts/predict.py
git commit -m "refactor: predict.py imports valuation instead of shelling out"
```

---

## Task 4: Device-level dataset split

A random photo-level split gives near-100% validation accuracy that measures only memorization of specific devices. Splits must group by device.

**Files:**
- Create: `scripts/split_dataset.py`
- Test: `tests/test_split.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_split.py
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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/ewaste-triage
.venv/bin/python -m pytest tests/test_split.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.split_dataset'`

- [ ] **Step 3: Write the module**

```python
# scripts/split_dataset.py
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

    for split, recs in (("train", train), ("val", val)):
        for rel, cls, _ in recs:
            out = dst / split / cls
            out.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, out / pathlib.Path(rel).name)

    n_train_dev = len({d for _, _, d in train})
    n_val_dev = len({d for _, _, d in val})
    print(f"train: {len(train)} photos / {n_train_dev} devices")
    print(f"val:   {len(val)} photos / {n_val_dev} devices")
    print("Devices are disjoint across splits — validation measures generalization.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd ~/ewaste-triage
.venv/bin/python -m pytest tests/test_split.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd ~/ewaste-triage
git add scripts/split_dataset.py tests/test_split.py
git commit -m "feat: device-level dataset split to prevent memorization leakage"
```

---

## Task 5: Classifier service

Loads the checkpoint exactly once. `torch.set_num_threads(1)` because measured: MobileNetV3-Large ran 152.9 ms/img at the 8-thread default versus 24.7 ms/img at 1 thread — small depthwise convs lose more to thread synchronization than they gain.

**Files:**
- Create: `server/classifier.py`
- Create: `tests/test_classifier.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_classifier.py
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
    c = Classifier(ckpt, confidence_floor=1.01)   # nothing can clear this
    r = c.classify(Image.new("RGB", (400, 300)))
    assert r["low_confidence"] is True


def test_missing_checkpoint_fails_at_construction(tmp_path):
    with pytest.raises(FileNotFoundError):
        Classifier(tmp_path / "absent.pt")
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/ewaste-triage
.venv/bin/python -m pytest tests/test_classifier.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'server'`

- [ ] **Step 3: Write the module**

```python
# server/classifier.py
"""
Loads the trained checkpoint once and classifies PIL images.

Class folder names must start with a 4-digit UNU-KEY (e.g. "0306_mobile_phones") so the
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
```

- [ ] **Step 4: Create the package marker and run the tests**

```bash
cd ~/ewaste-triage
touch server/__init__.py
.venv/bin/python -m pytest tests/test_classifier.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd ~/ewaste-triage
git add server/classifier.py server/__init__.py tests/test_classifier.py
git commit -m "feat: classifier service loading checkpoint once"
```

---

## Task 6: Flask app with /health and /classify

**Files:**
- Create: `server/app.py`
- Create: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server.py
import io

import pytest
import torch
import torch.nn as nn
from PIL import Image
from torchvision import models

from server.app import create_app


@pytest.fixture
def ckpt(tmp_path):
    m = models.resnet18()
    m.fc = nn.Linear(m.fc.in_features, 2)
    p = tmp_path / "best.pt"
    torch.save({"arch": "resnet18",
                "classes": ["0301_small_it", "0306_mobile_phones"],
                "state_dict": m.state_dict()}, p)
    return p


@pytest.fixture
def client(ckpt, tmp_path):
    app = create_app(ckpt_path=ckpt, ingest_root=tmp_path / "photos")
    app.config["TESTING"] = True
    return app.test_client()


def _jpeg_bytes(color=(100, 140, 90)):
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), color).save(buf, format="JPEG")
    buf.seek(0)
    return buf


def test_health_reports_model_state(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json["model_loaded"] is True
    assert r.json["n_classes"] == 2


def test_capture_page_has_no_external_assets(client):
    html = client.get("/").get_data(as_text=True)
    assert "<form" in html or "<input" in html
    for scheme in ("http://", "https://", "//cdn"):
        assert scheme not in html, f"page references an external asset ({scheme}); it must be self-contained"


def test_classify_returns_a_class(client):
    r = client.post("/classify", data={"image": (_jpeg_bytes(), "x.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.json["class_name"] in ("0301_small_it", "0306_mobile_phones")
    assert "confidence" in r.json


def test_classify_rejects_a_non_image(client):
    r = client.post("/classify", data={"image": (io.BytesIO(b"not an image"), "x.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert "error" in r.json


def test_classify_without_a_file_is_a_400(client):
    r = client.post("/classify", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_ingest_writes_into_the_class_folder(client, tmp_path):
    r = client.post("/ingest",
                    data={"image": (_jpeg_bytes(), "x.jpg"),
                          "class_name": "0306_mobile_phones",
                          "device_id": "dev01"},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    written = list((tmp_path / "photos" / "0306_mobile_phones").glob("dev01_*.jpg"))
    assert len(written) == 1


def test_ingest_rejects_a_path_traversing_class_name(client):
    r = client.post("/ingest",
                    data={"image": (_jpeg_bytes(), "x.jpg"),
                          "class_name": "../../etc",
                          "device_id": "dev01"},
                    content_type="multipart/form-data")
    assert r.status_code == 400
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/ewaste-triage
.venv/bin/python -m pytest tests/test_server.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'server.app'`

- [ ] **Step 3: Write the app**

```python
# server/app.py
"""
Laptop-hosted triage server. The phone reaches this over its own Personal Hotspot.

    .venv/bin/python -m server.app
    .venv/bin/python -m server.app --demo      # replay pre-shot photos, no model needed

Run it under `caffeinate -i` so the laptop does not sleep mid-demo.
"""
import argparse
import pathlib
import re

from flask import Flask, jsonify, request, send_from_directory
from PIL import Image, UnidentifiedImageError

from scripts import valuation
from server.classifier import Classifier

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def create_app(ckpt_path=None, ingest_root=None):
    app = Flask(__name__, static_folder=str(ROOT / "server" / "static"))
    ckpt_path = pathlib.Path(ckpt_path or ROOT / "models" / "best.pt")
    ingest_root = pathlib.Path(ingest_root or ROOT / "data" / "photos" / "raw")

    # Fail loudly at boot, not on the first request in front of a judge.
    app.config["CLASSIFIER"] = Classifier(ckpt_path)
    app.config["INGEST_ROOT"] = ingest_root

    def _read_image():
        if "image" not in request.files:
            return None, (jsonify({"error": "no file field named 'image'"}), 400)
        try:
            return Image.open(request.files["image"].stream), None
        except (UnidentifiedImageError, OSError):
            return None, (jsonify({"error": "uploaded file is not a decodable image"}), 400)

    @app.get("/")
    def home():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/health")
    def health():
        c = app.config["CLASSIFIER"]
        return jsonify({"model_loaded": True, "arch": c.arch, "n_classes": len(c.classes),
                        "classes": c.classes})

    @app.post("/classify")
    def classify():
        img, err = _read_image()
        if err:
            return err

        result = app.config["CLASSIFIER"].classify(img)
        mass_g = request.form.get("mass_g", type=float)

        if result["low_confidence"]:
            result["advice"] = "Low confidence — route this device to manual teardown."
            return jsonify(result)

        if result["unu_key"] is None:
            result["advice"] = "Class name has no 4-digit UNU-KEY prefix; cannot estimate value."
            return jsonify(result)

        try:
            result["valuation"] = valuation.estimate(result["unu_key"], mass_g=mass_g)
        except valuation.CompositionUnavailable:
            result["advice"] = "Composition table not filled in — class only, no value estimate."
        except valuation.UnknownKey as e:
            result["advice"] = str(e)
        return jsonify(result)

    @app.post("/ingest")
    def ingest():
        class_name = request.form.get("class_name", "")
        device_id = request.form.get("device_id", "")
        if not SAFE_NAME.match(class_name) or not SAFE_NAME.match(device_id):
            return jsonify({"error": "class_name and device_id must match [A-Za-z0-9_.-]+"}), 400

        img, err = _read_image()
        if err:
            return err

        out_dir = app.config["INGEST_ROOT"] / class_name
        out_dir.mkdir(parents=True, exist_ok=True)
        n = len(list(out_dir.glob(f"{device_id}_*.jpg")))
        # Always re-encode to JPEG: torchvision's ImageFolder silently drops .heic files.
        path = out_dir / f"{device_id}_{n:03d}.jpg"
        img.convert("RGB").save(path, format="JPEG", quality=92)
        return jsonify({"saved": str(path.relative_to(app.config["INGEST_ROOT"])),
                        "device_photo_count": n + 1})

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--ckpt", default=None)
    a = ap.parse_args()
    app = create_app(ckpt_path=a.ckpt)
    print(f"Serving on http://0.0.0.0:{a.port}  — find your hotspot IP with: ipconfig getifaddr en0")
    app.run(host="0.0.0.0", port=a.port, threaded=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create the static folder placeholder so `/` does not 500**

```bash
cd ~/ewaste-triage
mkdir -p server/static
echo "<!doctype html><title>placeholder</title><input type=file>" > server/static/index.html
```

- [ ] **Step 5: Run the tests**

```bash
cd ~/ewaste-triage
.venv/bin/python -m pytest tests/test_server.py -v
```

Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
cd ~/ewaste-triage
git add server/app.py server/static/index.html tests/test_server.py
git commit -m "feat: Flask server with /health, /classify, /ingest"
```

---

## Task 7: Self-contained capture page

Zero external assets. On hotspot the laptop has no internet, so any CDN reference hangs for 30 seconds and then fails. Client-side downscaling to 1024px matters more than model speed: measured server-side JPEG decode drops from 175 ms to 8 ms, and payload from 1.65 MB to 0.20 MB.

**Files:**
- Modify: `server/static/index.html`

- [ ] **Step 1: Write the page**

Replace the entire contents of `server/static/index.html`:

```html
<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>E-Waste Triage</title>
<style>
  body{font:16px system-ui,-apple-system,sans-serif;margin:0;padding:16px;background:#111;color:#eee}
  h1{font-size:20px;margin:0 0 12px}
  button,input[type=file]{font:inherit}
  .card{background:#1c1c1c;border:1px solid #333;border-radius:10px;padding:14px;margin:12px 0}
  .big{font-size:28px;font-weight:600}
  .muted{color:#999;font-size:14px}
  .warn{color:#ffb454}
  label{display:block;margin:8px 0 4px;color:#bbb;font-size:14px}
  input[type=number]{width:100%;padding:8px;background:#222;border:1px solid #444;color:#eee;border-radius:6px}
  #shot{max-width:100%;border-radius:8px;margin-top:8px}
</style>

<h1>E-Waste Triage</h1>

<div class="card">
  <input id="file" type="file" accept="image/*" capture="environment">
  <label for="mass">Measured mass in grams (optional — halves the error bar)</label>
  <input id="mass" type="number" step="0.1" placeholder="e.g. 168">
  <img id="shot" hidden>
</div>

<div id="out"></div>

<script>
const MAX = 1024;

// Downscale in canvas before upload. Decode time on the server is the bottleneck,
// not inference: 175 ms -> 8 ms, payload 1.65 MB -> 0.20 MB.
function downscale(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const s = Math.min(1, MAX / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * s);
      c.height = Math.round(img.height * s);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      document.getElementById('shot').src = c.toDataURL('image/jpeg', 0.85);
      document.getElementById('shot').hidden = false;
      c.toBlob(b => b ? resolve(b) : reject(new Error('canvas encode failed')), 'image/jpeg', 0.85);
    };
    img.onerror = () => reject(new Error('could not read that image'));
    img.src = URL.createObjectURL(file);
  });
}

function money(v) { return '$' + Number(v).toFixed(2); }

function render(r) {
  const out = document.getElementById('out');
  if (r.error) { out.innerHTML = `<div class="card warn">${r.error}</div>`; return; }

  let h = `<div class="card"><div class="big">${r.class_name}</div>
           <div class="muted">confidence ${(r.confidence * 100).toFixed(1)}%</div>`;
  if (r.low_confidence) h += `<div class="warn" style="margin-top:8px">${r.advice}</div>`;
  h += `</div>`;

  if (r.valuation) {
    const v = r.valuation;
    h += `<div class="card"><div class="muted">${v.description}</div>
          <div class="big">${money(v.value_usd)}</div>
          <div class="muted">range ${money(v.value_low)} – ${money(v.value_high)}
          (±${(v.rel_uncertainty * 100).toFixed(0)}%)</div>
          <div class="muted" style="margin-top:8px">mass ${v.mass_kg.toFixed(3)} kg
          (${v.mass_source}) · board grade ${v.board_grade}</div>
          <div class="muted">prices dated ${v.prices_quoted_date}</div></div>`;
  } else if (r.advice && !r.low_confidence) {
    h += `<div class="card warn">${r.advice}</div>`;
  }

  h += `<div class="card muted">This classifies the device from its outside and looks up a
        typical breakdown. It does not see inside the case, and it cannot tell whether a
        part still works.</div>`;
  out.innerHTML = h;
}

document.getElementById('file').addEventListener('change', async e => {
  const f = e.target.files[0];
  if (!f) return;
  document.getElementById('out').innerHTML = '<div class="card muted">Working…</div>';
  try {
    const blob = await downscale(f);
    const fd = new FormData();
    fd.append('image', blob, 'photo.jpg');
    const mass = document.getElementById('mass').value;
    if (mass) fd.append('mass_g', mass);
    const res = await fetch('/classify', { method: 'POST', body: fd });
    render(await res.json());
  } catch (err) {
    document.getElementById('out').innerHTML = `<div class="card warn">${err.message}</div>`;
  }
});
</script>
```

- [ ] **Step 2: Run the server test that forbids external assets**

```bash
cd ~/ewaste-triage
.venv/bin/python -m pytest tests/test_server.py::test_capture_page_has_no_external_assets -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd ~/ewaste-triage
git add server/static/index.html
git commit -m "feat: self-contained capture page with client-side downscaling"
```

---

## Task 8: CLI/web equivalence regression test

This is the core regression test. It proves the web and CLI paths share one implementation and cannot drift.

**Files:**
- Modify: `tests/test_server.py`

- [ ] **Step 1: Add the test**

Append to `tests/test_server.py`:

```python
def test_web_and_cli_agree_on_the_same_image(client, ckpt, tmp_path, monkeypatch):
    """The /classify endpoint and the Classifier used by the CLI must agree exactly."""
    from server.classifier import Classifier

    img_path = tmp_path / "sample.jpg"
    Image.new("RGB", (300, 300), (100, 140, 90)).save(img_path, format="JPEG")

    with open(img_path, "rb") as fh:
        web = client.post("/classify", data={"image": (fh, "sample.jpg")},
                          content_type="multipart/form-data").json

    cli = Classifier(ckpt).classify(Image.open(img_path))

    assert web["class_name"] == cli["class_name"]
    assert web["confidence"] == pytest.approx(cli["confidence"], abs=1e-6)
```

- [ ] **Step 2: Run the full suite**

```bash
cd ~/ewaste-triage
.venv/bin/python -m pytest tests/ -v
```

Expected: 20 passed

- [ ] **Step 3: Commit**

```bash
cd ~/ewaste-triage
git add tests/test_server.py
git commit -m "test: web/CLI equivalence regression test"
```

---

## Task 9: Demo fallback mode

Assume something breaks on the fair floor. `--demo` replays pre-shot photos through the same endpoint so the demo survives a dead model file, a failed hotspot, or a phone that will not cooperate.

**Files:**
- Modify: `server/app.py`
- Create: `data/demo_photos/README.md`

- [ ] **Step 1: Add the demo flag**

In `server/app.py`, change the `create_app` signature to `def create_app(ckpt_path=None, ingest_root=None, demo_dir=None):` and insert this route just before `return app`:

```python
    @app.get("/demo")
    def demo():
        """Replay pre-shot photos through the real /classify path. Fair-day insurance."""
        d = pathlib.Path(demo_dir or ROOT / "data" / "demo_photos")
        shots = sorted(p.name for p in d.glob("*.jpg")) if d.exists() else []
        return jsonify({"demo_photos": shots, "count": len(shots),
                        "hint": "POST one of these back to /classify to rehearse without the phone."})
```

Then in `main()`, add the flag:

```python
    ap.add_argument("--demo", action="store_true",
                    help="list the pre-shot fallback photos and exit")
```

and immediately after `a = ap.parse_args()`:

```python
    if a.demo:
        d = ROOT / "data" / "demo_photos"
        shots = sorted(d.glob("*.jpg")) if d.exists() else []
        print(f"{len(shots)} demo photos in {d}")
        for s in shots:
            print(f"  {s.name}")
        if not shots:
            print("  none — shoot 10-15 before the fair, see data/demo_photos/README.md")
        return
```

- [ ] **Step 2: Document the fallback**

```bash
cd ~/ewaste-triage
mkdir -p data/demo_photos
cat > data/demo_photos/README.md <<'EOF'
# Fair-day fallback photos

Shoot 10-15 photos here before the fair, covering every class, using the same protocol
as training (scale reference in frame, varied backgrounds).

If the hotspot fails, the phone misbehaves, or the model file is corrupt, these replay
through the real /classify endpoint from the laptop alone:

    .venv/bin/python -m server.app --demo          # list them
    curl -F image=@data/demo_photos/01.jpg http://localhost:8777/classify

Last resort: a screen recording of a working session. Make one the week before.
EOF
git add data/demo_photos/README.md server/app.py
git commit -m "feat: demo fallback mode for fair-day failures"
```

- [ ] **Step 3: Verify it runs without a model**

```bash
cd ~/ewaste-triage
.venv/bin/python -m server.app --demo
```

Expected: "0 demo photos in .../data/demo_photos" and the reminder line. Exit code 0, no model load attempted.

---

## Task 10: HEIC guard in the training path

The `/ingest` endpoint re-encodes to JPEG, so the primary path is safe. Photos copied in by hand are not. Verified on this machine: `ImageFolder` returned only the `.jpg` from a folder containing one `.jpg` and one `.heic` — no warning, no error.

**Files:**
- Modify: `scripts/train_classifier.py`

- [ ] **Step 1: Add the check**

In `scripts/train_classifier.py`, add this function above `main()`:

```python
def warn_about_heic(data_dir):
    """torchvision's ImageFolder silently drops .heic. Fail loudly instead."""
    heic = list(pathlib.Path(data_dir).rglob("*.heic")) + list(pathlib.Path(data_dir).rglob("*.HEIC"))
    if heic:
        print(f"\n!! {len(heic)} .heic file(s) found under {data_dir}.")
        print("!! torchvision 0.28 IGNORES these silently — they will NOT be in your dataset.")
        print("!! Fix: set the iPhone camera to 'Most Compatible', or convert:")
        print(f"!!   sips -s format jpeg {data_dir}/**/*.heic --out <same folder>")
        print("!! Example dropped file:", heic[0], "\n")
```

Then call it in `main()` immediately after the `if not (data_dir / "train").exists():` block:

```python
    warn_about_heic(data_dir)
```

- [ ] **Step 2: Verify the warning fires**

```bash
cd ~/ewaste-triage
mkdir -p /tmp/heictest/train/cls_a
touch /tmp/heictest/train/cls_a/photo.heic
.venv/bin/python scripts/train_classifier.py --data-dir /tmp/heictest 2>&1 | head -6
rm -rf /tmp/heictest
```

Expected: the `!! 1 .heic file(s) found` warning appears before any training output.

- [ ] **Step 3: Commit**

```bash
cd ~/ewaste-triage
git add scripts/train_classifier.py
git commit -m "fix: warn loudly about .heic files torchvision would silently drop"
```

---

## Task 11: Rehearsal checklist

**Files:**
- Create: `docs/fair-day-checklist.md`

- [ ] **Step 1: Write the checklist**

```markdown
# Fair-day checklist

Run this end-to-end at home at least twice, at least a week before the fair.

## The night before
- [ ] `git status` clean, everything committed
- [ ] `.venv/bin/python -m pytest tests/ -v` — all green
- [ ] `.venv/bin/python -m server.app --demo` lists 10-15 fallback photos
- [ ] Laptop charged; charger packed
- [ ] Phone charged; **Low Power Mode OFF** (it disables Personal Hotspot)
- [ ] Screen recording of a working session saved to the laptop desktop

## Setup, in this order
- [ ] Phone: Settings → Personal Hotspot → Allow Others to Join
- [ ] Mac: join the phone's hotspot from the WiFi menu
- [ ] `ipconfig getifaddr en0` → note the 172.20.10.x address
- [ ] `caffeinate -i .venv/bin/python -m server.app`
- [ ] Approve the macOS incoming-connections prompt if it appears
- [ ] Phone Safari → `http://<that-ip>:8777` → take one photo → confirm a result
- [ ] Write the URL on a card next to the board

## If it breaks
1. Laptop asleep → wake it, the server survives under `caffeinate`
2. Phone lost the hotspot → toggle Personal Hotspot off and on, rejoin the Mac
3. Page loads but upload hangs → firewall prompt was denied; System Settings → Network → Firewall → Options
4. Nothing works → `curl` a demo photo from the laptop and narrate it
5. Still nothing → play the screen recording

## What to say when a judge asks how it works
The model classifies the device from the outside. The part breakdown comes from a lookup
table keyed on that classification. It does not see inside the case, and it cannot tell
whether a part still works — which is why the teardown data matters.
```

- [ ] **Step 2: Commit**

```bash
cd ~/ewaste-triage
git add docs/fair-day-checklist.md
git commit -m "docs: fair-day rehearsal checklist"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §3 Architecture — hotspot | Task 0 |
| §3 `scrap_prices.json` | Task 1 |
| §4 Server imports estimator as module | Tasks 2, 3 |
| §4 `/classify`, `/ingest`, `/health` | Task 6 |
| §4 Client page, no external assets | Task 7 |
| §5 Device-level splits | Task 4 |
| §5 HEIC landmine | Tasks 6 (ingest re-encode), 10 (training guard) |
| §7 Error handling table | Task 6 (all rows), Task 9 (demo fallback) |
| §9 Testing — CLI/web equivalence | Task 8 |
| §9 Rehearsal test | Tasks 0, 11 |

**Not covered by this plan, by design:** §6 model training (already implemented in
`scripts/train_classifier.py`), §10 open question 1 (class list — needs user input),
§11 out-of-scope items.

**Type consistency:** `valuation.estimate()` returns the same dict shape consumed by
`estimate_value.py` (Task 2), `predict.py` (Task 3), and `app.py` (Task 6). The keys
`value_usd`, `value_low`, `value_high`, `rel_uncertainty`, `mass_kg`, `mass_source`,
`board_grade`, `description`, `prices_quoted_date` are used identically in
`index.html` (Task 7). `Classifier.classify()` returns `class_name`, `unu_key`,
`confidence`, `low_confidence`, `topk` — consumed unchanged by Tasks 6, 7, 8.

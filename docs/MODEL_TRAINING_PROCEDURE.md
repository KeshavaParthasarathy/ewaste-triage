# Standard Model Training Procedure

This is the repeatable procedure for collecting device photos, building a leakage-safe dataset, training classifier candidates, comparing them, and deciding when to stop. It applies to the five approved classes:

- `0301_computer_mouse`
- `0301_keyboard`
- `0303_laptop`
- `0306_mobile_phone`
- `0401_headphones`

## 1. Non-negotiable rules

1. **Split by physical device, never by individual photo.** A physical object must appear in only one of training, validation, development, or final test data.
2. **Give every physical object a stable device ID.** Examples: `mouse03`, `phone04`, `laptop05`. Device IDs must not contain underscores.
3. **Keep the public validation set fixed during an experiment campaign.** Changing validation images between trials makes scores incomparable.
4. **Treat a repeatedly inspected holdout as development data.** Once its results influence model choices, it is no longer an untouched final test.
5. **Preserve every candidate separately.** Never train directly over `models/best.pt`.
6. **Handle EXIF orientation before resizing or cropping.** The training and visual-evaluation pipelines already call `ImageOps.exif_transpose`. Deployment preprocessing must match them.
7. **Do not promote a model from accuracy alone.** Check macro F1, per-class recall, confidence behavior, device coverage, model size, latency, and known deployment blockers.

## 2. Canonical folder layout

```text
data/photos/
  raw/<class>/<device_id>_<photo_number>.jpg
  train/<class>/*.jpg
  val/<class>/*.jpg
  holdout_own/<class>/<device_id>_<photo_number>.jpg
  experiments/<campaign>/train/<class>/*.jpg
  experiments/<campaign>/val/<class>/*.jpg

models/
  best.pt
  experiments/<trial>/best.pt

reports/
  <campaign>/<trial>/
```

`raw/` is the canonical source for approved training devices. `holdout_own/` contains physically different evaluation devices. Experiment directories preserve fixed splits without changing the main dataset.

## 3. Collect and label new photos

For each physical device:

1. Choose the correct approved class.
2. Assign a new device ID that has never been used for another object.
3. Capture at least 10-20 useful views:
   - front, rear, both sides, top, and bottom;
   - portrait and landscape framing;
   - close, medium, and wider distances;
   - varied lighting and backgrounds;
   - partial occlusion and realistic wear when available.
4. Keep one device entirely in one split. Never photograph the same object into both `raw/` and `holdout_own/`.

Phone collection server for training devices:

```bash
cd ~/ewaste-triage
caffeinate -i .venv/bin/python -m server.app --collect
```

For an evaluation-only device:

```bash
caffeinate -i .venv/bin/python -m server.app --collect \
  --ingest-root data/photos/holdout_own
```

## 4. Intake audit before training

Before moving downloaded files into the dataset:

- confirm every expected file exists;
- open every image with Pillow to confirm it decodes;
- record image dimensions and EXIF orientation;
- compute SHA-256 hashes and reject exact duplicates;
- visually verify the class and physical-device grouping;
- reject accidental screenshots, unrelated objects, or frames where the target is not recognizable;
- rename files to `<device_id>_<three-digit-number>.jpg`.

Preserve the original JPEG bytes and EXIF metadata in `raw/`. Orientation correction belongs in preprocessing, not in ad hoc destructive edits to source data.

Example naming:

```text
data/photos/raw/0306_mobile_phone/phone03_000.jpg
data/photos/raw/0306_mobile_phone/phone03_001.jpg
data/photos/raw/0301_computer_mouse/mouse04_000.jpg
```

## 5. Build a dataset

### First campaign or intentional full resplit

Use the seeded device-level splitter:

```bash
.venv/bin/python -m scripts.split_dataset \
  --src data/photos/raw \
  --dst data/photos \
  --val-frac 0.25 \
  --seed 20260821
```

Only do this when intentionally creating a new baseline. A resplit may change validation membership and invalidate comparisons with earlier trials.

### Incremental campaign with a fixed validation set

Create an isolated copy of the current split, then add only the newly approved training devices to its `train/` folders. Do not rerun the splitter.

```bash
campaign=data/photos/experiments/<campaign-name>
mkdir -p "$campaign"
cp -R data/photos/train "$campaign/train"
cp -R data/photos/val "$campaign/val"
cp data/photos/raw/<class>/<device_id>_*.jpg "$campaign/train/<class>/"
```

Before training, verify:

- the experiment validation manifest exactly matches the frozen source validation manifest;
- no `(class, device_id)` appears in both train and validation;
- no training device appears in `holdout_own/`;
- all five classes exist in both train and validation;
- per-class counts match the intended additions.

## 6. Preflight verification

Use a valid macOS locale for pytest on this machine:

```bash
LC_ALL=C LANG=C LC_CTYPE=C PYTHONPATH=. .venv/bin/pytest -q
.venv/bin/python scripts/train_classifier.py --smoke-test
```

Smoke-test checkpoints are isolated under `models/smoke-test/`; they do not replace
the production checkpoint.

Record the current production checkpoint hash before any experiment:

```bash
LC_ALL=C shasum -a 256 models/best.pt
```

## 7. Run the controlled baseline trial

Start with the strongest previously validated architecture and change one intended variable at a time. The current reference configuration is:

```bash
caffeinate -i .venv/bin/python scripts/train_classifier.py \
  --data-dir data/photos/experiments/<campaign-name> \
  --holdout-dir data/photos/holdout_own \
  --arch efficientnet_b0 \
  --epochs 15 \
  --batch-size 32 \
  --lr 0.001 \
  --unfreeze 1 \
  --seed 20260821 \
  --out models/experiments/<trial-name>
```

Always use a new output directory. The checkpoint selected by the script is the epoch with the best frozen public-validation accuracy.

For later trials, change only one defensible variable, such as:

- head-only tuning with `--unfreeze 0` to reduce overfitting;
- learning rate;
- number of epochs;
- architecture;
- a documented change to approved training data.

Do not make several changes in one trial; otherwise the source of an improvement is unknown.

## 8. Generate a detailed evaluation

For every candidate:

```bash
PYTHONPATH=. .venv/bin/python -m scripts.evaluate_classifier \
  --data-dir data/photos/holdout_own \
  --checkpoint models/experiments/<trial-name>/best.pt \
  --out reports/<campaign-name>/<trial-name>
```

Review all generated artifacts:

- `index.html` for per-photo predictions and Grad-CAM overlays;
- `summary.json` for checkpoint identity and metrics;
- `predictions.csv` for row-level analysis;
- `confusion_matrix.png` for systematic class confusions.

Record at minimum:

- public-validation accuracy;
- own-device accuracy and correct count;
- macro F1 over classes present in the evaluation set;
- per-class support, recall, precision, and F1;
- errors and top-three confidence values;
- coverage and selective accuracy at the confidence threshold;
- checkpoint size and CPU latency;
- training time and configuration;
- SHA-256 checkpoint hash.

Grad-CAM shows image regions that influenced the prediction. It is a diagnostic aid, not a causal explanation.

## 9. Iterative stopping rule

Define the rule before viewing candidate results. The standard practical rule is:

- an improvement must gain at least **2 evaluation photos** or at least **3 macro-F1 percentage points**;
- it must not introduce a major per-class regression;
- reset the plateau counter after a qualifying improvement;
- stop after **two consecutive well-chosen trials** fail the rule;
- run no more than **five new adaptive trials** in one campaign.

When the development set is small or near its ceiling, report exact paired changes and confidence intervals. Do not keep tuning merely to gain one familiar photo.

## 10. Promotion gate

Keep the candidate separate until all of these are true:

1. It passes the practical improvement rule or clearly improves an operational failure mode.
2. Public validation and per-class metrics remain acceptable.
3. Preprocessing is identical in training, evaluation, CLI inference, browser inference, and collection ingest.
4. A new untouched, device-disjoint test set confirms the result.
5. Every class has adequate test support; zero keyboard photos or one phone photo is not release-grade evidence.
6. The UI confidence threshold is evaluated for both coverage and accepted-set accuracy.
7. The full automated test suite passes.

Only then back up the previous production checkpoint, copy the approved candidate to `models/best.pt`, verify its hash, and rerun the UI smoke test.

## 11. Required campaign report

Every training campaign should end with a report containing:

- data provenance and device IDs;
- exact split counts and leakage checks;
- every valid and invalidated trial in chronological order;
- configurations, hashes, training times, model sizes, and latency;
- validation accuracy, development accuracy, macro F1, and per-class metrics;
- improvement versus the prior trial and prior best;
- confidence-gated behavior;
- confusion matrices and representative Grad-CAM errors;
- stopping-rule decision;
- identified data, model, and deployment issues;
- promotion decision and next data-collection priorities.

## 12. Trial log template

```markdown
| Trial | Data change | Architecture | Epochs | LR | Unfreeze | Public val | Own correct | Own accuracy | Macro F1 | Status |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| T00 | Baseline | EfficientNet-B0 | 15 | 0.001 | 1 | 0.000 | 0/0 | 0.000 | 0.000 | Baseline |
```

For each trial, also record the candidate path, SHA-256 hash, failed-photo filenames, top prediction confidence, and why the next trial was or was not justified.

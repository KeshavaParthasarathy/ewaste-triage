# Headphone Incremental Training Campaign - 2026-09-01

## Outcome

The 20 supplied images belong to the existing `0401_headphones` class, not a new
classification category. They contain two physical devices:

- `headphones03`: Bose over-ear headphones, 14 JPEG views from `IMG_6684` through
  `IMG_6697`.
- `headphones04`: JBL over-ear headphones, 6 JPEG views from `IMG_6698` through
  `IMG_6703`.

Both candidate trials reached 10/10 headphone recall on the own-device development
set, but both caused a major laptop regression. The new checkpoints were preserved
for analysis and were not promoted. Trial 7 remains the best observed overall
candidate at 30/32 correct.

## Data intake

All 20 JPEGs decoded successfully, had unique SHA-256 hashes, and had no exact
content-hash match in the existing canonical dataset. The JPEG copies were moved to:

```text
data/photos/raw/0401_headphones/headphones03_000.jpg ... headphones03_013.jpg
data/photos/raw/0401_headphones/headphones04_000.jpg ... headphones04_005.jpg
```

Matching HEIC source versions remain in Downloads and were not added to the dataset,
which prevents the same views from being counted twice.

The isolated experiment dataset is:

```text
data/photos/experiments/incremental-20260901-headphones03-headphones04
```

| Split | Mouse | Keyboard | Laptop | Phone | Headphones | Total |
|---|---:|---:|---:|---:|---:|---:|
| Train | 160 | 150 | 160 | 160 | 181 | 811 |
| Validation | 50 | 50 | 50 | 50 | 50 | 250 |
| Own-device development | 10 | 0 | 11 | 1 | 10 | 32 |

- Train manifest: `876f84eb6d2a19c10c3281c95e84d3633fc7af7d04b4645a53fb296e3dfae5ee`
- Validation manifest: `e79e52b8b7ee302a6550100bf23e31d987031adf83ebb1c93188deed4bc71e8e`
- Train/validation device overlap: 0
- Train/own-device overlap: 0
- Validation files: byte-for-byte identical to the frozen source validation set

## Trial results

Both trials used EfficientNet-B0, ImageNet initialization, batch size 32, 15 epochs,
one unfrozen feature block, seed `20260821`, and the best fixed-validation checkpoint.

| Trial | Learning rate | Best public val | Own correct | Own accuracy | Macro F1 | Mouse | Laptop | Phone | Headphones | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| T7 prior leader | 0.0010 | 81.2% | 30/32 | 93.8% | 88.0% | 9/10 | 10/11 | 1/1 | 10/10 | Remains leader |
| T9 | 0.0010 | 81.6% | 25/32 | 78.1% | 71.5% | 9/10 | 5/11 | 1/1 | 10/10 | Plateau 1 |
| T10 | 0.0003 | 81.6% | 26/32 | 81.2% | 78.1% | 10/10 | 5/11 | 1/1 | 10/10 | Plateau 2; stop |

T9 selected epoch 9 and trained in approximately 275 seconds. T10 also selected
epoch 9; its approximately 1,334-second runtime reflected machine conditions during
that run and is not evidence of a model architecture difference.

Paired exact comparison with T7:

- T7 versus T9: five T7-only correct images, zero T9-only correct, exact p=0.0625.
- T7 versus T10: five T7-only correct images, one T10-only correct, exact p=0.21875.

## Confidence behavior at the 60% floor

| Trial | Accepted | Accepted correct | Selective accuracy | Review queue |
|---|---:|---:|---:|---:|
| T7 | 28/32 | 27/28 | 96.4% | 4 |
| T9 | 24/32 | 24/24 | 100.0% | 8 |
| T10 | 22/32 | 21/22 | 95.5% | 10 |

T10 has one accepted high-confidence error: `laptop02_007.jpg` was predicted as a
keyboard at 65.1% confidence.

## Runtime and checkpoint identity

CPU benchmarks used one thread, 10 warmup passes, and 100 measured classifications.

| Trial | Size | Median | p95 | Throughput | SHA-256 |
|---|---:|---:|---:|---:|---|
| T9 | 15.57 MB | 78.24 ms | 81.24 ms | 12.8 fps | `ac7077da43b722bb0d641b231b0376d2d91776205badc4c67ea4a0d5526c27fc` |
| T10 | 15.57 MB | 77.98 ms | 80.72 ms | 12.8 fps | `569b3a298413af1e054284f179f08f135a78c5d75480d1cc18ebd18793485dd0` |

Candidate paths:

```text
models/experiments/t09-new-headphone-devices-efficientnet-b0/best.pt
models/experiments/t10-new-headphone-devices-efficientnet-b0-lr3e4/best.pt
```

Detailed reports:

```text
outputs/ewaste-iterative-testing-2026-09-01/t09-new-headphone-devices-efficientnet-b0/index.html
outputs/ewaste-iterative-testing-2026-09-01/t10-new-headphone-devices-efficientnet-b0-lr3e4/index.html
```

## Stopping and promotion decision

The standard stopping rule requires at least 2 additional correct development photos
or at least 3 macro-F1 percentage points without a major class regression. T9 and T10
both fell well below T7 and reduced laptop recall from 10/11 to 5/11. These are two
consecutive non-significant attempts, so the campaign stopped.

Neither model should replace production or Trial 7. The new data remains valid training
data, but its narrow wooden-table acquisition context appears to shift class boundaries
without adding enough scene diversity. The next headphone collection should vary room,
surface, lighting, distance, orientation, partial occlusion, and device condition.
Broader keyboard, phone, and laptop device coverage is still more important than adding
more near-duplicate views of the same headphone devices.

## Preflight safety correction

The documented smoke-test command exposed an unsafe default: it wrote its synthetic
checkpoint to `models/best.pt`. Production was restored byte-for-byte from the existing
`models/retrain-20260821` copy:

- production checkpoint SHA-256: `add3a70cb40beb53c9e738f9945aa8ece2753a4073f66f24518d2a15bf98ca89`
- production class map SHA-256: `b35c825eb116fa6951a60a35f3a1177c2fb30f50e98f77d7d90f5f7700909dbd`

The training script now sends default smoke-test artifacts to `models/smoke-test/`.
`tests/test_smoke_output_safety.py` reproduces the original overwrite against sentinel
production files and verifies both sentinels remain unchanged while a real isolated
smoke checkpoint is created.

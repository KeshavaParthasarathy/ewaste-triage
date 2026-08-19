# E-Waste Triage Tool — Product Design

**Date:** 2026-08-19
**Status:** Approved (architecture), class list pending confirmation
**Scope:** The computer-vision branch of the larger e-waste triage science project. The
leaching-validation experiment is out of scope for this document and runs in parallel.

---

## 1. Problem

Sorting e-waste for recovery currently requires either destructive teardown or lab assay.
A non-destructive triage tool would let a person point a phone at a discarded device and
get back: what the device is, what it is made of, which parts are plausibly reusable, and
roughly what the recoverable material is worth.

This document specifies that tool.

## 2. What the tool honestly does

The model is a **device classifier**, not an x-ray. It identifies the device from an
external photo; the part breakdown then comes from a lookup table keyed on that identity.

This distinction is stated on the project board and in the writeup. A polished demo
invites the assumption that the model sees inside the case. It does not, and claiming
otherwise is the fastest way to lose credibility with a judge.

A photo also cannot determine whether a part **works**. The tool predicts reuse
*candidacy* (desirable part type, no visible damage), never reuse *validity*. The gap
between the two is measured during teardown and reported as a result.

## 3. Architecture

```
  iPhone (Personal Hotspot = the network)
      │  photo via <input type="file" accept="image/*" capture="environment">
      │  downscaled to 1024px client-side in canvas before upload
      ▼
  Safari → http://[<mac-global-ipv6>]:8777   (see note below)
      │
      ▼
  MacBook — Flask app (server/app.py)
      ├── loads models/best.pt once at startup
      ├── torch.set_num_threads(1)
      ├── classify → UNU-KEY + confidence
      ├── if confidence < 0.60 → "route to manual teardown"
      └── join → unu_key_reference.csv (mass)
                → composition_priors.csv (fractions)
                → scrap_prices.json (dollars)
      ▼
  JSON response → rendered in the phone browser
```

**Why laptop-hosted rather than cloud or native app:**

- Only path that fits the available effort budget (see §8).
- Zero model-artifact translation — serves the exact `.pt` that was trained and
  reported on. No ONNX or Core ML conversion step that can silently produce confident
  wrong answers.
- Immune to venue WiFi. The phone is the router; packets never leave the room.
- The same server is the data-ingest tool during collection (§5), so it is built once
  and used twice.

**Measured:** 37 ms round trip on this hardware with a 1024px upload
(8.3 ms decode + 27 ms inference).

**Addressing — verified 2026-08-19, and not what was assumed.** This carrier is
IPv6-only (464XLAT). The hotspot provides *no* IPv4 subnet: the Mac receives a
`192.0.0.2/32` CLAT stub and a global IPv6 address. There is no `172.20.10.x`
network. Consequences: the server binds `::` rather than `0.0.0.0`; the address is
read from `ifconfig en0`, not `ipconfig getifaddr en0`; the ~50-character URL is
delivered as a QR code rather than typed; and because the address is carrier-assigned
it may change on reconnect, so the QR is regenerated at every startup. See
`docs/experiment-log.md`.

## 4. Components

Each component has one job and a defined interface.

| Component | File | Responsibility | Depends on |
|---|---|---|---|
| Training | `scripts/train_classifier.py` | photos → `models/best.pt` + `classes.json` | torchvision, MPS |
| CLI inference | `scripts/predict.py` | one photo → class → value | `best.pt`, estimator |
| Value estimator | `scripts/estimate_value.py` | UNU-KEY (+ mass) → dollars ± range | reference CSVs |
| Priors | `scripts/build_priors.py` | ORA dataset → category priors | `openrepair_*.csv` |
| Sensor model | `scripts/baseline_model.py` | non-destructive readings → value/hazard | `device_log.csv` |
| **Server** | `server/app.py` | HTTP: classify + ingest | `best.pt`, estimator |
| **Client page** | `server/static/index.html` | capture, downscale, POST, render | none (no CDN) |

The server imports the estimator as a module rather than shelling out, so there is one
implementation of the value chain and no drift between CLI and web paths.

### Server endpoints

- `GET  /` — the capture page. Self-contained; **no external assets of any kind**
  (no CDN, no Google Fonts). On hotspot the laptop has no internet and any remote asset
  hangs for 30s then fails.
- `POST /classify` — multipart image → `{class, unu_key, confidence, mass_kg,
  value_usd, value_low, value_high, reusable_parts[], low_confidence: bool}`
- `POST /ingest` — multipart image + `class_name` + `device_id` → writes to
  `data/photos/train/<class_name>/<device_id>_<n>.jpg`. Used during collection only.
- `GET  /health` — model loaded, class count, device. For pre-demo rehearsal.

## 5. Data flow and collection protocol

**Classes: 8–12 coarse categories**, not the full 49 UNU-KEYs. Sourcing 49 device types
is not physically possible for one student, and most classes would hold 0–2 examples,
making per-class F1 undefined or noise. The collapse is stated in the writeup as an
explicit scoping decision rather than left for a judge to discover. Coarse classes map to
UNU-KEYs in `data/unu_key_reference.csv`.

**Target:** ≥8 *distinct physical devices* per class, 12–20 photos each. The number of
distinct devices is the variable that matters, not the number of photos.

**Photo protocol:**
- A US quarter (24.26 mm) or ruler in every frame. Without a scale reference, pixels
  cannot convert to area or mass and the value chain breaks. Retrofitting this after
  shooting means reshooting everything.
- Randomized background across devices. Shooting every device of a class on the same
  surface makes surface texture a perfect predictor; the model scores well and collapses
  on anyone else's photo.
- Vary angle and lighting deliberately. The training set should be at least as messy as
  the test conditions.

**Two verified landmines:**

1. **HEIC.** torchvision 0.28.0's `ImageFolder` extension list does not include `.heic`.
   Files are dropped silently — no warning, no error, no exception. Set the iPhone camera
   to "Most Compatible", or register the HEIF opener *and* patch `IMG_EXTENSIONS` before
   importing `ImageFolder`. The `/ingest` endpoint converts to JPEG on arrival, which
   removes this risk on the primary path.
2. **Device-level splits.** Train/val/test split must group by `device_id`, never by
   photo. A random photo-level split on 200 photos of one laptop yields near-100%
   validation accuracy that measures only memorization. This is the first methodological
   question a good judge asks.

## 6. Model

MobileNetV3-Small or EfficientNet-B0, ImageNet-pretrained, backbone frozen except the
final block plus a new head.

Model size is not constrained on this path — the laptop could run ResNet-50 comfortably.
The small backbone is chosen anyway to keep the PWA fallback open without retraining
(6.21 MB as fp32 ONNX versus 44.78 MB for ResNet-18).

**Reported metrics:** macro-F1 (not accuracy — classes are imbalanced), per-class
precision/recall, confusion matrix, and the headline result below.

**The headline experiment — domain shift.** Train on public dataset images, then evaluate
on photos taken with the student's own phone. The accuracy drop is the most defensible
experimental result in this branch, it costs one afternoon, and it is measured *before*
any fine-tuning on own-photos. `train_classifier.py --holdout-dir` already implements
this and prints the delta.

The expected size of that drop is genuinely unknown for e-waste. Published waste-
classification results are wildly inconsistent — one 2025 comparison reports MobileNetV2
at 97.12% and ResNet50 at 65.20% on the same task. This is a reason to measure it, not
to predict it.

## 7. Error handling

| Condition | Behavior |
|---|---|
| Confidence < 0.60 | Return `low_confidence: true`, display "route to manual teardown", log the photo as a candidate for the next training round |
| Class name lacks a 4-digit UNU-KEY prefix | Return the class, omit the value estimate, explain why |
| `composition_priors.csv` absent or unfilled | Return class + mass, omit dollars. The estimator refuses to invent composition numbers |
| Upload is not a decodable image | 400 with a readable message |
| Model file missing at startup | Fail loudly at boot, not on first request |
| Hotspot unreachable / demo failure | `--demo` flag replays 10–15 pre-shot photos through the same endpoint. A screen recording is the last resort |

## 8. Effort budget

Eleven weeks, solo, sharing the window with a physical leaching experiment. At 6–8 h/week
that is roughly 70–90 hours total; leaching takes at least half. **The CV branch has
35–45 hours.**

| Activity | Hours |
|---|---|
| Data collection | 16–24 |
| Training, evaluation, domain-gap experiment | 10–15 |
| Server + client demo layer | 6–10 |

The demo layer gets 6–10 hours and not one more. This constraint selected the
architecture; it was not a compromise made afterward.

## 9. Testing

- `train_classifier.py --smoke-test` — synthetic images verify the training loop with no
  data present. Already passing.
- `baseline_model.py --synthetic 24` — verifies the sensor pipeline. Already passing.
- `estimate_value.py` — must refuse cleanly when composition data is absent. Already
  passing.
- **Server:** `curl -F image=@sample.jpg http://localhost:8777/classify` returns the same
  class and value as `predict.py` on the same file. This equivalence is the core
  regression test — it proves the web and CLI paths share one implementation.
- **Rehearsal test:** full hotspot round trip from the actual phone, run at home, at least
  twice, at least a week before the fair.

## 10. Open questions

1. **Class list.** Which 8–12 categories? Should be driven by what can be physically
   sourced at ~8 distinct devices each, not by the UNU-KEY table. *Pending user input.*
2. **Hotspot viability.** Whether the phone's carrier build permits client-to-laptop HTTP
   over Personal Hotspot. Some builds enforce AP client isolation. This is the single
   assumption the architecture rests on. Resolved by the 30-minute test in Phase 0.
3. **`capture="environment"` over plain HTTP on a LAN IP.** Expected to work — it is not a
   permission-gated feature like `getUserMedia`, which *is* blocked outside a secure
   context — but no spec citation was found and it was not tested on a real device.
   Resolved by the same Phase 0 test.

## 11. Explicitly out of scope

- Native iOS app. The Core ML *export* is done and is a legitimate board result
  ("quantized to 8-bit, 10.7 MB, verified top-1 parity"). Building an app is not:
  macOS 14.6.1 caps Xcode at 16.2, which cannot deploy to a current iPhone, and free
  provisioning certificates expire in 7 days with no on-device renewal.
- Internal PCB component detection. A stretch goal, and the only part that would need a
  bounding-box annotation tool.
- Any hosted free tier on the critical path. Hugging Face paywalled Gradio Spaces in
  July 2026; Render Free is 512 MB against a measured 386 MB just to import torch and
  load a ResNet-18.
- Reuse *validity* prediction. Not possible from a photo. See §2.

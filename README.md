# E-Waste Triage — Phase 1 / Phase 3 working directory

## The honest constraint

No public database contains your Phase 1 feature vector. Weight, magnetic response,
and probe resistance for a specific used device are physical measurements nobody has
published at scale — that absence is exactly what makes the project novel. Online data
cannot replace collection. It can do four other things:

1. tell you what a realistic device mix looks like (so your 15–25 aren't a weird sample)
2. give you a defensible hazard *prior* (pre-2006 = leaded solder era)
3. supply scrap prices for the ground-truth value score
4. let you build and debug the whole model pipeline before any hardware arrives

## Sources actually verified (Aug 2026)

| Source | What you get | Access |
|---|---|---|
| Open Repair Alliance | 305,649 real repair records: category, brand, year_of_manufacture, repair outcome. **No mass field.** CC BY-SA 4.0 | already downloaded → `data/openrepair_v0.3_202507.csv` |
| fccid.io | Free internal teardown photos + PCB shots for any device with a radio, plus certification date | fccid.io, search by the FCC ID on the label |
| iScrapApp / Boardsort | Current $/lb by board grade (low / mid / high grade, RAM, CPUs) — your value ground truth | iscrapapp.com/metals/, boardsort.com/payout.php |
| Oguchi et al. 2011, *Waste Management* 31(9-10):2150-60 | Per-device mass + metal content for 21 EEE types — cite as the literature anchor | via library / Georgia Tech access |
| Kaggle "E-Waste Image Dataset" | ~10 classes of e-waste photos, for the optional image branch | kaggle.com/datasets/akshat103/e-waste-image-dataset |

## The trap to avoid

If you derive `gt_value_usd` from a per-category scrap table *and* feed `device_category`
to the model, the model just relearns the table. LOO-CV will look great and it will mean
nothing — and it is the first thing a sharp judge will ask about. Ground truth must come
from your own teardown: weigh the separated board, apply the $/lb rate for its grade.

## Files

    data/device_log_template.csv   36-col schema: Phase 1 columns, then gt_* Phase 2 columns
    data/openrepair_v0.3_202507.csv  56 MB, 305,649 rows
    data/category_priors.csv       generated: per-category pre-RoHS %, median year, EOL rate
    scripts/build_priors.py        regenerates category_priors.csv
    scripts/baseline_model.py      LOO-CV random forest, value + hazard, permutation importance
    refs/                          the original project plan PDF

## Start here

    cd ~/ewaste-triage
    python3 scripts/baseline_model.py --synthetic 24     # confirms the pipeline runs
    cp data/device_log_template.csv data/device_log.csv  # delete the EX001 example row
    # ...log real devices...
    python3 scripts/baseline_model.py

Environment already checked: Python 3.11.5, pandas 2.0.3, scikit-learn 1.3.0 — nothing to install.

---

## Photo-based part breakdown & value (added)

Two different models, often confused:

- **External photo of a closed device** → identifies *what the device is*. The part
  breakdown then comes from a lookup keyed on that identity. The CNN is a classifier,
  not an x-ray. Say this plainly in the writeup; claiming the model "sees the parts"
  is the one thing that will get picked apart at judging.
- **Internal photo of an opened board** → genuine per-device component detection
  (ICs, electrolytics, connectors, heatsinks, RAM, batteries). This is real CV.

**A photo cannot tell you whether a part works.** It predicts reuse *candidacy*, not
reuse *validity*. Measuring the gap between the two is a legitimate experiment.

**Two dollar values, never mix them:** material/scrap value (cents to a few dollars per
small device) vs. reuse/resale value (10-100x higher, functionality-dependent).

### Value chain implemented here

    photo -> UNU-KEY class -> avg unit mass (data/unu_key_reference.csv, UN Annex 3)
          -> composition fractions (you fill from Oguchi 2011 / Cucchiella 2015)
          -> board grade -> $/lb (iScrapApp, Boardsort) -> value +/- range

Measured mass beats the category average by a wide margin — the error bar roughly halves.

    data/unu_key_reference.csv            49 UNU-KEYs with EU-28 average unit weights
    data/composition_priors_TEMPLATE.csv  fill from literature, then save as composition_priors.csv
    scripts/estimate_value.py             material-value estimate with propagated uncertainty

### Training data (verified Aug 2026)

| Dataset | Contents |
|---|---|
| Roboflow "Balanced E-Waste Dataset" | 7,200 images, 37 classes, tagged with UNU-KEYs — joins directly to the weight table above |
| Roboflow "E-Waste Dataset" | 19,613 images, pretrained model + API |
| FICS-PCB | 31 boards, 77,000+ annotated components — the substantial board-level set |
| Roboflow PCB-Components sets | 29-401 images, 7-16 component classes; small, good for a quick pilot |
| fccid.io | free internal teardown photos, effectively unlimited, unlabelled |

Prior art to cite and beat: arXiv:2409.16496, "Real-Time Detection of Electronic Components
in Waste Printed Circuit Boards: A Transformer-Based Approach."

### Photo protocol (decide before shooting anything)

Put a **US quarter (24.26 mm) or a ruler in every frame**. Without a scale reference you
cannot convert pixels to area to mass, and the whole value chain breaks. Fixed height,
fixed lighting, plain matte background, same orientation.

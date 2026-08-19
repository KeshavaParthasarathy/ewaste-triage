"""
Phase 3 baseline: leave-one-out CV on non-destructive features only.

  python3 scripts/baseline_model.py                      # uses data/device_log.csv
  python3 scripts/baseline_model.py --synthetic 24       # pipeline smoke test, no hardware needed
  python3 scripts/baseline_model.py --use-category       # adds device_category (see WARNING)

WARNING on --use-category: if your ground-truth value came from a per-category
scrap table, adding device_category as a feature lets the model recover that
table and inflates the score. Keep it off unless every gt_value_usd came from
weighing separated components of that specific device.
"""
import argparse, pathlib, sys
import numpy as np, pandas as pd
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.model_selection import LeaveOneOut
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, r2_score, precision_score, recall_score, confusion_matrix

ROOT = pathlib.Path(__file__).resolve().parent.parent
NUM = ["mass_g", "longest_dim_mm", "magnet_response", "magnet_frac", "log_resistance",
       "continuity_flag", "has_battery_door", "has_dc_jack", "has_usb_port",
       "has_screen", "screen_diag_mm", "cable_attached", "age_years"]


def ohm(v):
    """Multimeter 'OL' / open circuit -> a large finite resistance."""
    if isinstance(v, str) and v.strip().upper() in {"OL", "OPEN", "INF", ""}:
        return 1e9
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def featurize(df):
    d = df.copy()
    tested = pd.to_numeric(d.get("magnet_sites_tested"), errors="coerce").replace(0, np.nan)
    d["magnet_frac"] = pd.to_numeric(d.get("magnet_sites_pos"), errors="coerce") / tested
    r = d.get("resistance_ohm_p1", pd.Series(index=d.index)).map(ohm)
    d["log_resistance"] = np.log10(r.clip(lower=1e-3))
    d["age_years"] = 2026 - pd.to_numeric(d.get("year_est"), errors="coerce")
    for c in NUM:
        d[c] = pd.to_numeric(d.get(c), errors="coerce")
    return d


def synth(n, seed=0):
    """Plausible fake devices so the pipeline runs before real logging. NEVER report these."""
    rng = np.random.default_rng(seed)
    cats = ["Battery/charger/adapter", "PC accessory", "Portable radio", "Mobile", "Headphones", "Small kitchen item"]
    rows = []
    for i in range(n):
        cat = cats[i % len(cats)]
        mass = float(np.clip(rng.lognormal(4.9, 0.85), 15, 3000))
        year = int(rng.integers(1998, 2024))
        pcb = mass * rng.uniform(0.04, 0.22)
        batt = int(rng.random() < 0.35)
        # hazard truth: pre-RoHS leaded solder OR a battery inside
        haz = int(year < 2006 or batt)
        rows.append(dict(
            device_id=f"SYN{i:03d}", device_category=cat, mass_g=round(mass, 1),
            longest_dim_mm=round(mass ** 0.42 * rng.uniform(6, 11), 0),
            magnet_response=int(np.clip(rng.normal(1.4 + 0.7 * (mass > 400), 0.8), 0, 3)),
            magnet_sites_pos=int(rng.integers(0, 7)), magnet_sites_tested=6,
            resistance_ohm_p1=float(10 ** rng.uniform(0, 8)), continuity_flag=int(rng.random() < 0.4),
            has_battery_door=batt if rng.random() < 0.7 else 0,
            has_dc_jack=int(rng.random() < 0.5), has_usb_port=int(rng.random() < 0.5),
            has_screen=int(rng.random() < 0.3), screen_diag_mm=0, cable_attached=int(rng.random() < 0.4),
            year_est=year,
            gt_value_usd=round(pcb * rng.uniform(0.004, 0.02) + mass * 0.0009 * rng.uniform(0.6, 1.4), 3),
            gt_hazard_flag=haz,
        ))
    return pd.DataFrame(rows)


def loo(model_fn, X, y):
    pred = np.empty(len(y), dtype=float)
    for tr, te in LeaveOneOut().split(X):
        m = model_fn()
        m.fit(X[tr], y[tr])
        pred[te] = m.predict(X[te])
    return pred


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "device_log.csv"))
    ap.add_argument("--synthetic", type=int, default=0)
    ap.add_argument("--use-category", action="store_true")
    a = ap.parse_args()

    if a.synthetic:
        df = synth(a.synthetic)
        print(f"!! SYNTHETIC DATA ({a.synthetic} fake devices) — pipeline check only, not a result.\n")
    else:
        p = pathlib.Path(a.data)
        if not p.exists():
            sys.exit(f"No {p}. Copy data/device_log_template.csv to device_log.csv and start logging, "
                     f"or run with --synthetic 24 to test the pipeline.")
        df = pd.read_csv(p)

    d = featurize(df)
    feats = list(NUM)
    if a.use_category:
        oh = pd.get_dummies(d["device_category"], prefix="cat").astype(float)
        d = pd.concat([d, oh], axis=1)
        feats += list(oh.columns)
        print("!! device_category included — check for label leakage (see docstring).\n")

    # --- value regression ---
    rv = d.dropna(subset=["gt_value_usd"])
    Xv = rv[feats].fillna(rv[feats].median(numeric_only=True)).fillna(0).to_numpy(float)
    yv = rv["gt_value_usd"].to_numpy(float)
    print(f"VALUE MODEL   n={len(yv)}  features={Xv.shape[1]}")
    if len(yv) >= 5:
        pv = loo(lambda: RandomForestRegressor(n_estimators=400, min_samples_leaf=1, random_state=0), Xv, yv)
        print(f"  LOO-CV   MAE=${mean_absolute_error(yv, pv):.3f}   R2={r2_score(yv, pv):+.3f}")
        print(f"  baseline (always predict mean)  MAE=${mean_absolute_error(yv, np.full_like(yv, yv.mean())):.3f}   R2=+0.000")
    else:
        print("  need >=5 rows")

    # --- hazard classification ---
    rh = d.dropna(subset=["gt_hazard_flag"])
    Xh = rh[feats].fillna(rh[feats].median(numeric_only=True)).fillna(0).to_numpy(float)
    yh = rh["gt_hazard_flag"].astype(int).to_numpy()
    print(f"\nHAZARD MODEL  n={len(yh)}  positives={yh.sum()}  negatives={(yh == 0).sum()}")
    if len(yh) >= 5 and 0 < yh.sum() < len(yh):
        ph = loo(lambda: RandomForestClassifier(n_estimators=400, class_weight="balanced", random_state=0), Xh, yh).astype(int)
        print(f"  LOO-CV   accuracy={(ph == yh).mean():.3f}  "
              f"precision={precision_score(yh, ph, zero_division=0):.3f}  recall={recall_score(yh, ph, zero_division=0):.3f}")
        maj = np.full_like(yh, int(yh.mean() >= 0.5))
        print(f"  baseline (always predict majority)  accuracy={(maj == yh).mean():.3f}")
        print(f"  confusion [[TN FP][FN TP]] = {confusion_matrix(yh, ph).tolist()}")

        clf = RandomForestClassifier(n_estimators=400, class_weight="balanced", random_state=0).fit(Xh, yh)
        imp = permutation_importance(clf, Xh, yh, n_repeats=30, random_state=0)
        print("\n  feature importance (permutation, mean +/- sd):")
        for i in np.argsort(imp.importances_mean)[::-1][:8]:
            print(f"    {feats[i]:<18} {imp.importances_mean[i]:+.4f} +/- {imp.importances_std[i]:.4f}")
        print("\n  NOTE: at n<30 these ranks are unstable. Re-run with several random_state values "
              "and report only the features that stay on top.")
    else:
        print("  need >=5 rows with both hazard classes present")


if __name__ == "__main__":
    main()

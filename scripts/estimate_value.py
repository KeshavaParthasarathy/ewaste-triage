"""
Photo class label -> estimated recoverable MATERIAL value, with an honest error bar.

    python3 scripts/estimate_value.py 0306                 # use UNU average mass
    python3 scripts/estimate_value.py 0306 --mass-g 168    # use your measured mass (much better)

This deliberately reports a RANGE, not a point estimate. Every input is uncertain:
UNU weights are EU-28 averages, composition fractions are literature averages, and
scrap prices move weekly. A single number would be false precision, and a judge will
ask about exactly this.

NOTE: this estimates MATERIAL/scrap value only. Reuse value of a working part is a
different and much larger number, and it is NOT predictable from a photo — see README.
"""
import argparse, pathlib, sys
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent

# $/lb — REPLACE with today's quotes before reporting anything.
# Check iscrapapp.com/metals/ and boardsort.com/payout.php; record the date you pulled them.
PRICES_USD_PER_LB = {"low": 0.60, "mid": 1.60, "high": 6.00, "ferrous": 0.06, "nonferrous": 2.20}
PRICE_DATE = "PLACEHOLDER — not a real quote"
PRICE_UNCERTAINTY = 0.30   # +/- 30%, covers weekly scrap swings and grade misclassification
MASS_UNCERTAINTY = 0.50    # +/- 50% when falling back to a category-average mass
LB_PER_KG = 2.20462


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("unu_key")
    ap.add_argument("--mass-g", type=float, default=None, help="measured mass; skips the category average")
    a = ap.parse_args()

    keys = pd.read_csv(ROOT / "data" / "unu_key_reference.csv", dtype={"unu_key": str})
    comp_path = ROOT / "data" / "composition_priors.csv"
    if not comp_path.exists():
        sys.exit(f"No {comp_path}.\nCopy composition_priors_TEMPLATE.csv to composition_priors.csv and fill it "
                 f"from Oguchi 2011 / Cucchiella 2015 first — this script will not invent composition numbers.")
    comp = pd.read_csv(comp_path, dtype={"unu_key": str}, comment="#")

    k = keys[keys.unu_key == a.unu_key]
    c = comp[comp.unu_key == a.unu_key]
    if k.empty or c.empty:
        sys.exit(f"UNU-KEY {a.unu_key} missing from reference or composition table.")
    k, c = k.iloc[0], c.iloc[0]

    if a.mass_g is not None:
        mass_kg, mass_rel_err, mass_src = a.mass_g / 1000, 0.02, "measured"
    else:
        mass_kg, mass_rel_err, mass_src = k.avg_unit_weight_kg_2012, MASS_UNCERTAINTY, "UNU EU-28 average"

    streams = [("pcb", c.frac_pcb, PRICES_USD_PER_LB.get(str(c.board_grade), 0.0)),
               ("ferrous", c.frac_ferrous, PRICES_USD_PER_LB["ferrous"]),
               ("nonferrous", c.frac_nonferrous, PRICES_USD_PER_LB["nonferrous"])]

    print(f"{a.unu_key}  {k.description}")
    print(f"  mass: {mass_kg:.3f} kg ({mass_src}, +/-{mass_rel_err:.0%})")
    print(f"  board grade: {c.board_grade}   prices dated: {PRICE_DATE}\n")

    total = 0.0
    for name, frac, price in streams:
        if pd.isna(frac) or pd.isna(price):
            print(f"  {name:<12} -- composition not filled in --")
            continue
        v = mass_kg * float(frac) * LB_PER_KG * float(price)
        total += v
        print(f"  {name:<12} {float(frac):5.1%} of mass  ->  ${v:6.3f}")

    rel = (mass_rel_err ** 2 + PRICE_UNCERTAINTY ** 2) ** 0.5
    print(f"\n  material value: ${total:.2f}   range ${total*(1-rel):.2f} - ${total*(1+rel):.2f}  (+/-{rel:.0%})")
    if mass_src != "measured":
        print("  ^ weigh the device and re-run with --mass-g to cut this range roughly in half.")


if __name__ == "__main__":
    main()

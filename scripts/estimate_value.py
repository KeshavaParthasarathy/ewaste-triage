"""
CLI over scripts/valuation.estimate.

    .venv/bin/python -m scripts.estimate_value 0306
    .venv/bin/python -m scripts.estimate_value 0306 --mass-g 168

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

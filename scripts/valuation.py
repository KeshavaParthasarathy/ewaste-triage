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

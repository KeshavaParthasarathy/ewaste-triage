"""
Build category-level priors from the Open Repair Alliance (ORA) dataset.

WHAT THIS IS FOR: sanity-checking your own sample against the real-world
distribution of small electronics, and estimating how likely a given category
is to predate the 2006 RoHS lead-solder ban.

WHAT THIS IS *NOT* FOR: labelling your devices. Ground truth comes from your
own teardown (Phase 2). Using these numbers as labels and then feeding
device_category to the model makes the model a lookup table, not a predictor.

Data: github.com/openrepair/data, CC BY-SA 4.0.
"""
import pandas as pd, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "openrepair_v0.3_202507.csv"
OUT = ROOT / "data" / "category_priors.csv"

df = pd.read_csv(SRC, low_memory=False)
df["year"] = pd.to_numeric(df["year_of_manufacture"], errors="coerce")
df = df[(df["year"].isna()) | ((df["year"] > 1960) & (df["year"] <= 2026))]

g = df.groupby("product_category")
priors = pd.DataFrame({
    "n_records": g.size(),
    "n_with_year": g["year"].count(),
    "median_year": g["year"].median(),
    "frac_pre_rohs_2006": g["year"].apply(lambda s: (s < 2006).mean() if s.notna().any() else float("nan")),
    "frac_end_of_life": g["repair_status"].apply(lambda s: (s == "End of life").mean()),
    "top_brands": g["brand"].apply(lambda s: "; ".join(s.value_counts().head(3).index.astype(str))),
}).sort_values("n_records", ascending=False)

priors.round(3).to_csv(OUT)
print(f"wrote {OUT}  ({len(priors)} categories, {len(df):,} records)\n")
print(priors[["n_records", "n_with_year", "median_year",
              "frac_pre_rohs_2006", "frac_end_of_life"]].head(15).round(3).to_string())

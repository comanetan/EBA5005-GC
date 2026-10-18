# -*- coding: utf-8 -*-
"""
Item 4 of the "other tests" follow-up list (OPTIMISER_METHODOLOGY_REPORT.md Sec. 21):
we have the headline adjusted R^2 (0.9545) for the subzone-FE hedonic (hedonic_value.py,
Sec. 15's fix) but never plotted residuals vs. fitted or ran Moran's I on the model's OWN
residuals the way the Pricing Lead did for theirs (notebooks/04c_hedonic_econometrics.ipynb,
on main). Directly tests whether subzone FE actually fixed the spatial-autocorrelation
problem town FE had, or just reduced it -- the same distinction Sec. 15 was honest about
for the MRT coefficient (5.28% -> 4.55%, still above their ~3% causal benchmark) but never
checked for the residuals themselves.

Method: refit BOTH the current production formula (C(subzone), 167 levels) and the
pre-Sec.15 formula it replaced (C(town), 26 levels) on the IDENTICAL filtered/sampled rows
(same dropna + sample_n=120_000 + seed=0 fit_hedonic() already uses), so the two residual
sets are directly, apples-to-apples comparable -- isolating the FE-granularity effect from
any other change. Residuals are aggregated to block level (mean residual per `query`
block, >=10 sales, demeaned) and tested with the Pricing Lead's own published methodology:
KNN k=8 row-standardised spatial weights, Singapore-centred equirectangular projection,
Moran's I (esda). Benchmarks to compare against (their notebook, block-level OLS
residuals): no town dummies 0.81, WITH town dummies 0.60, spatial-error model (filtered)
-0.03, LightGBM 0.07.

Caveat stated plainly: the Pricing Lead's own `bk["y"]` was a block fixed-effect/residual
series from their own notebook pipeline (`fe`, not fully visible outside that notebook) --
here it is the mean OLS residual per block from THIS pipeline's own hedonic, the standard
quantity for this diagnostic. Not claimed byte-identical to theirs; the before/after
(subzone vs. town, same rows) is this script's real, self-contained comparison, and the
Pricing Lead's numbers are only a rough compass for where "fixed" vs. "not fixed" sits.
"""
import json
import os

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

import block_analysis as ba
from hedonic_value import WTP_ATTRS, CONTROL_ACCESS

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

FORMULA_BASE = ("log_price ~ C(month_s) + C(flat_type) + C(flat_model) + storey_mid + floor_area_sqm"
                " + remaining_lease_yrs + I(remaining_lease_yrs**2) + {fe} + "
                + " + ".join(WTP_ATTRS + CONTROL_ACCESS) + " + C(elite_primary_tier, Treatment('Beyond 2km'))")
FORMULA_SUBZONE = FORMULA_BASE.format(fe="C(subzone)")
FORMULA_TOWN = FORMULA_BASE.format(fe="C(town)")

TRAIN_MONTHS = 36
SAMPLE_N = 120_000
SEED = 0
MIN_SALES_PER_BLOCK = 10
KNN_K = 8


def prepared_sample():
    """Identical filtering to hedonic_value.py::fit_hedonic(as_of=None) -- same dropna
    columns (union of both formulas' needs) and same sample_n/seed draw, so both FE
    variants are fit on the exact same rows."""
    df_all = ba.load_transactions_with_access()
    df = df_all[df_all["flat_type"] != "MULTI-GENERATION"].copy()
    d = df[df["month"] > df["month"].max() - pd.DateOffset(months=TRAIN_MONTHS)]
    if "dist_mrt_exit_km_at_sale" in d.columns:
        d = d.copy()
        d["dist_mrt_exit_km"] = d["dist_mrt_exit_km_at_sale"]
    d = d.dropna(subset=WTP_ATTRS + CONTROL_ACCESS + ["remaining_lease_yrs", "storey_mid", "subzone", "town"])
    if SAMPLE_N and len(d) > SAMPLE_N:
        d = d.sample(SAMPLE_N, random_state=SEED)
    d = d.copy()
    d["month_s"] = d["month"].dt.strftime("%Y-%m")
    return d


def block_level_moran(d, resid, label):
    """Mean residual per block (query, >=10 sales), demeaned, tested with the Pricing
    Lead's own published method: KNN k=8 row-standardised weights, SG-centred equirectangular
    projection, esda Moran's I."""
    import libpysal
    from esda.moran import Moran

    bk = d.assign(_resid=resid).groupby("query", observed=True).agg(
        n=("_resid", "size"), resid=("_resid", "mean"), lat=("lat", "first"), lon=("lon", "first")
    )
    bk = bk[bk["n"] >= MIN_SALES_PER_BLOCK].dropna(subset=["resid", "lat", "lon"])
    bk["resid"] = bk["resid"] - bk["resid"].mean()

    xy = np.c_[(bk["lon"] - 103.8) * 111_320 * np.cos(np.radians(1.35)), (bk["lat"] - 1.35) * 110_574]
    w = libpysal.weights.KNN.from_array(xy, k=KNN_K)
    w.transform = "r"
    mi = Moran(bk["resid"].to_numpy(), w, permutations=999)
    print(f"{label:>28}: n_blocks={len(bk):>5}  Moran's I={mi.I:+.4f}  p_sim={mi.p_sim:.4f}  z={mi.z_sim:+.2f}")
    return {"label": label, "n_blocks": int(len(bk)), "morans_i": float(mi.I),
            "p_sim": float(mi.p_sim), "z_sim": float(mi.z_sim)}


def residual_vs_fitted_summary(model, label):
    """Numeric stand-in for a residuals-vs-fitted plot: binned mean residual by fitted-value
    decile (a flat near-zero mean in every bin is the "no pattern" signature a plot would
    show visually; a trend across bins would flag heteroskedasticity/nonlinearity)."""
    fitted = model.fittedvalues
    resid = model.resid
    deciles = pd.qcut(fitted, 10, labels=False, duplicates="drop")
    tbl = pd.DataFrame({"fitted": fitted, "resid": resid, "decile": deciles}).groupby("decile").agg(
        mean_fitted=("fitted", "mean"), mean_resid=("resid", "mean"), std_resid=("resid", "std"), n=("resid", "size")
    )
    print(f"\n{label} -- residual vs. fitted, by decile of fitted log(price):")
    print(tbl.to_string(float_format=lambda x: f"{x:.4f}"))
    return tbl.reset_index().to_dict(orient="records")


def run():
    d = prepared_sample()
    print(f"Fit sample: {len(d)} rows, {d['query'].nunique()} blocks, {d['subzone'].nunique()} subzones, "
          f"{d['town'].nunique()} towns\n")

    model_subzone = smf.ols(FORMULA_SUBZONE, data=d).fit()
    model_town = smf.ols(FORMULA_TOWN, data=d).fit()
    print(f"subzone-FE (production): adj R^2 = {model_subzone.rsquared_adj:.4f}")
    print(f"town-FE    (pre-Sec.15): adj R^2 = {model_town.rsquared_adj:.4f}\n")

    moran_subzone = block_level_moran(d, model_subzone.resid, "subzone-FE (production)")
    moran_town = block_level_moran(d, model_town.resid, "town-FE (pre-Sec.15)")

    rvf_subzone = residual_vs_fitted_summary(model_subzone, "subzone-FE (production)")
    rvf_town = residual_vs_fitted_summary(model_town, "town-FE (pre-Sec.15)")

    out = {
        "adj_r2": {"subzone_fe": model_subzone.rsquared_adj, "town_fe": model_town.rsquared_adj},
        "morans_i": {"subzone_fe": moran_subzone, "town_fe": moran_town},
        "residual_vs_fitted": {"subzone_fe": rvf_subzone, "town_fe": rvf_town},
        "benchmark_pricing_lead": {
            "ols_no_town_dummies": 0.81, "ols_with_town_dummies": 0.60,
            "spatial_error_filtered": -0.03, "lightgbm": 0.07,
        },
        "knn_k": KNN_K, "min_sales_per_block": MIN_SALES_PER_BLOCK,
        "n_rows": len(d), "n_blocks_total": int(d["query"].nunique()),
    }
    return out


if __name__ == "__main__":
    result = run()
    with open(os.path.join(DATA, "hedonic_residual_diagnostics.json"), "w") as f:
        json.dump(result, f, indent=2)
    print("\nWrote data/hedonic_residual_diagnostics.json")

# -*- coding: utf-8 -*-
"""
Evidence for the profile-granularity decision:
  1. Join every resale transaction to its geocoded block.
  2. Variance decomposition: how much of each accessibility measure varies
     WITHIN towns (invisible to a town-centroid feature) vs BETWEEN towns.
  3. Hedonic regressions: does block-level accessibility explain price
     beyond town fixed effects? (in-sample + out-of-time)
  4. Distance-band price gradient for MRT (non-linear effect).
  5. Granularity comparison: G1 town x flat_type x storey, G2 + MRT band,
     G3 block x flat_type x storey -- cell coverage vs homogeneity.
"""
import os
import re

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../Project, portable across machines
OUT = os.path.join(ROOT, "notebooks", "optimization_lead", "data")

HEDONIC_MRT = "dist_mrt_exit_km_at_sale"  # station must be open in the month of sale
ACCESS_FEATURES = [
    "dist_mrt_exit_km", "dist_primary_school_km", "n_primary_school_1000m", "dist_hawker_km",
    "dist_supermarket_km", "dist_chas_clinic_km", "dist_park_km", "n_bus_stop_400m",
    "dist_childcare_km", "dist_planned_rail_km",
]


def storey_band(s):
    m = re.match(r"(\d+) TO (\d+)", str(s))
    if not m:
        return None
    lo = int(m.group(1))
    return "Low" if lo <= 6 else ("Mid" if lo <= 15 else "High")


def parse_lease(s):
    m = re.match(r"(\d+)\s*years?(?:\s*(\d+)\s*months?)?", str(s))
    if not m:
        return np.nan
    return int(m.group(1)) + (int(m.group(2)) if m.group(2) else 0) / 12


def load_transactions_with_access():
    cache = os.path.join(OUT, "transactions_block_access.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    r = pd.read_csv(os.path.join(ROOT, "Resale flat prices based on registration date from Jan-2017 onwards.csv"))
    r["month"] = pd.to_datetime(r["month"], format="%Y-%m")
    r["query"] = r["block"].astype(str) + " " + r["street_name"]
    r["storey_band"] = r["storey_range"].apply(storey_band)
    r["storey_mid"] = r["storey_range"].str.extract(r"(\d+) TO (\d+)").astype(float).mean(axis=1)
    r["remaining_lease_yrs"] = r["remaining_lease"].apply(parse_lease)
    r["log_price"] = np.log(r["resale_price"])

    b = pd.read_csv(os.path.join(OUT, "block_accessibility.csv"))
    keep = ["query", "lat", "lon", "mrt_band", "year_completed", "max_floor_lvl", "total_dwelling_units",
            "primary_tier", "elite_primary_tier", "childcare_tier", "childcare_band",
            "secondary_tier", "expressway_proximity_band", "nearest_job_node",
            "near_flood_prone_area", "has_carpark_400m", "has_night_parking_400m"] + \
           [c for c in b.columns if c.startswith(("dist_", "n_", "walk_", "mrt_band_walk"))]
    df = r.merge(b[[c for c in keep if c in b.columns]], on="query", how="inner")
    # MRT distance using only stations open in the month of sale (no credit for unopened stations)
    from block_accessibility import mrt_dist_as_of, band
    df["dist_mrt_exit_km_at_sale"] = mrt_dist_as_of(df, df["month"]).values
    df["mrt_band_at_sale"] = band(df["dist_mrt_exit_km_at_sale"]).astype(str)
    dated = {c[len("dist_"):] for c in df.columns if c.startswith("dist_mrt_exit_opened_")}
    if "walk_mrt_exit_base_km" in df.columns and all(f"walk_{c}" in df.columns for c in dated):
        df["walk_mrt_exit_km_at_sale"] = mrt_dist_as_of(df, df["month"], prefix="walk").values
    df.to_parquet(cache, index=False)
    return df


def network_as_of(df, as_of):
    """Copy of df with dist_mrt_exit_km / mrt_band measured on the rail network open on `as_of`
    (backtests: a profile built at a cutoff must not know about stations that opened later)."""
    from block_accessibility import mrt_dist_as_of, band
    d = df.copy()
    d["dist_mrt_exit_km"] = mrt_dist_as_of(d, pd.Timestamp(as_of)).values
    d["mrt_band"] = band(d["dist_mrt_exit_km"]).astype(str)
    return d


def variance_decomposition(df, features, group="town"):
    """Share of each feature's variance that lies WITHIN towns -- the part a
    town-centroid feature cannot see. Computed on unique blocks (not
    transactions) so busy blocks aren't over-weighted."""
    blocks = df.drop_duplicates("query")
    rows = []
    for f in features:
        x = blocks[f]
        total = ((x - x.mean()) ** 2).sum()
        between = blocks.groupby(group)[f].transform("mean")
        between_ss = ((between - x.mean()) ** 2).sum()
        rows.append({"feature": f, "within_town_share": 1 - between_ss / total,
                     "between_town_share": between_ss / total})
    return pd.DataFrame(rows).sort_values("within_town_share", ascending=False)


BASE = ("log_price ~ C(month) + C(flat_type) + C(flat_model) + storey_mid + floor_area_sqm"
        " + remaining_lease_yrs + I(remaining_lease_yrs**2) + C(town)")


def _hfeat():
    return [HEDONIC_MRT if f == "dist_mrt_exit_km" else f for f in ACCESS_FEATURES]


def hedonic_models(df, sample_n=None, seed=0):
    d = df.dropna(subset=_hfeat() + ["remaining_lease_yrs", "storey_mid"]).copy()
    if sample_n and len(d) > sample_n:
        d = d.sample(sample_n, random_state=seed)
    d["month"] = d["month"].dt.strftime("%Y-%m")
    m_a = smf.ols(BASE, data=d).fit()
    m_b = smf.ols(BASE + " + " + " + ".join(_hfeat()), data=d).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(d["query"])[0]})
    return d, m_a, m_b


def coefficient_table(model):
    rows = []
    for f in _hfeat():
        b, se, p = model.params[f], model.bse[f], model.pvalues[f]
        rows.append({"feature": f, "coef_log": b, "pct_effect_per_unit": (np.exp(b) - 1) * 100,
                     "ci_low_pct": (np.exp(b - 1.96 * se) - 1) * 100,
                     "ci_high_pct": (np.exp(b + 1.96 * se) - 1) * 100, "p_value": p})
    t = pd.DataFrame(rows)
    # translate distance effects to "per 100m closer" for readability
    is_dist = t["feature"].str.startswith("dist_")
    t.loc[is_dist, "pct_per_100m_closer"] = (np.exp(-t.loc[is_dist, "coef_log"] * 0.1) - 1) * 100
    return t


def out_of_time_test(df, cutoff="2025-01-01"):
    d = df.dropna(subset=_hfeat() + ["remaining_lease_yrs", "storey_mid"]).copy()
    d["month_s"] = d["month"].dt.strftime("%Y-%m")
    train, test = d[d["month"] < cutoff], d[d["month"] >= cutoff]
    # month effects can't extrapolate to unseen months -> use a linear+quadratic time trend instead
    f_base = ("log_price ~ t + I(t**2) + C(flat_type) + C(flat_model) + storey_mid + floor_area_sqm"
              " + remaining_lease_yrs + I(remaining_lease_yrs**2) + C(town)")
    for x in (train, test):
        x["t"] = (x["month"] - pd.Timestamp("2017-01-01")).dt.days / 365.25
    common_models = set(train["flat_model"]) & set(test["flat_model"])
    test = test[test["flat_model"].isin(common_models)]
    res = {}
    for name, f in [("town_fixed_effects_only", f_base),
                    ("plus_block_accessibility", f_base + " + " + " + ".join(_hfeat()))]:
        m = smf.ols(f, data=train).fit()
        pred = np.exp(m.predict(test))
        res[name] = {"MAPE_pct": float(np.mean(np.abs(pred - test["resale_price"]) / test["resale_price"]) * 100),
                     "RMSE_sgd": float(np.sqrt(np.mean((pred - test["resale_price"]) ** 2))),
                     "n_test": len(test)}
    return pd.DataFrame(res).T


def mrt_distance_gradient(df):
    d = df.dropna(subset=["remaining_lease_yrs", "storey_mid"]).copy()
    d["month"] = d["month"].dt.strftime("%Y-%m")
    d["mrt_dist_band"] = pd.cut(d[HEDONIC_MRT], [-1, 0.2, 0.4, 0.6, 0.8, 1.2, 99],
                                 labels=["<200m", "200-400m", "400-600m", "600-800m", "800-1200m", ">1200m"])
    m = smf.ols(BASE + " + C(mrt_dist_band, Treatment('<200m'))", data=d).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(d["query"])[0]})
    rows = [{"band": "<200m", "pct_vs_<200m": 0.0, "ci_low": 0.0, "ci_high": 0.0,
             "n_txn": int((d["mrt_dist_band"] == "<200m").sum())}]
    for band in ["200-400m", "400-600m", "600-800m", "800-1200m", ">1200m"]:
        k = f"C(mrt_dist_band, Treatment('<200m'))[T.{band}]"
        b, se = m.params[k], m.bse[k]
        rows.append({"band": band, "pct_vs_<200m": (np.exp(b) - 1) * 100,
                     "ci_low": (np.exp(b - 1.96 * se) - 1) * 100, "ci_high": (np.exp(b + 1.96 * se) - 1) * 100,
                     "n_txn": int((d["mrt_dist_band"] == band).sum())})
    return pd.DataFrame(rows)


SCHOOL_TIER_FEATURES = ["dist_mrt_exit_km_at_sale", "dist_hawker_km", "dist_supermarket_km", "dist_chas_clinic_km",
                        "dist_park_km", "n_bus_stop_400m", "dist_planned_rail_km"]


def school_tier_test(df, sample_n=120_000, seed=0):
    """Hedonic with MOE-style tiers instead of linear school distance:
    - elite (SAP/GEP) primary: Within 1km / 1-2km vs Beyond 2km
    - any primary within 1km vs 1-2km (97% of blocks are 'within 1km')
    - childcare: Within 200m / 200-500m vs Beyond 500m (1km/2km tiers are saturated)"""
    d = df.dropna(subset=SCHOOL_TIER_FEATURES + ["remaining_lease_yrs", "storey_mid"]).copy()
    if sample_n and len(d) > sample_n:
        d = d.sample(sample_n, random_state=seed)
    d["month"] = d["month"].dt.strftime("%Y-%m")
    f = (BASE + " + " + " + ".join(SCHOOL_TIER_FEATURES)
         + " + C(elite_primary_tier, Treatment('Beyond 2km')) + C(primary_tier, Treatment('1-2km'))"
         + (" + C(childcare_band, Treatment('Beyond 500m'))" if "childcare_band" in d else ""))
    m = smf.ols(f, data=d).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(d["query"])[0]})
    rows = []
    for k in m.params.index:
        if "tier" in k or "childcare_band" in k:
            b, se = m.params[k], m.bse[k]
            rows.append({"term": k.split("[T.")[0].replace("C(", "").split(",")[0] + " = " + k.split("[T.")[1].rstrip("]"),
                         "pct_effect": (np.exp(b) - 1) * 100, "ci_low": (np.exp(b - 1.96 * se) - 1) * 100,
                         "ci_high": (np.exp(b + 1.96 * se) - 1) * 100, "p_value": m.pvalues[k],
                         "n_txn_in_level": int((d[k.split("[T.")[0].replace("C(", "").split(",")[0]] ==
                                                k.split("[T.")[1].rstrip("]")).sum())})
    mrt = {"pct_per_100m_closer_mrt": (np.exp(-m.params["dist_mrt_exit_km_at_sale"] * 0.1) - 1) * 100}
    return m, pd.DataFrame(rows), mrt


WALK_PAIRS = [("mrt_exit", "MRT exit"), ("hawker", "hawker"), ("supermarket", "supermarket"),
              ("chas_clinic", "CHAS clinic"), ("park", "park"), ("primary_elite", "SAP/GEP primary"),
              ("bus_stop", "bus stop")]


def detour_summary(blocks):
    """Walking vs straight-line: detour ratio = walk / straight (>=1; 1 = perfectly direct)."""
    r = blocks[blocks["residential"] == "Y"]
    rows = []
    for k, label in WALK_PAIRS:
        s, w = r[f"dist_{k}_km"], r[f"walk_{k}_km"]
        ok = (s > 0.05) & w.notna()  # ratio is unstable for amenities right next door
        ratio = (w[ok] / s[ok])
        rows.append({"amenity": label, "median_straight_m": s.median() * 1000, "median_walk_m": w.median() * 1000,
                     "median_detour_ratio": ratio.median(), "p90_detour_ratio": ratio.quantile(0.9),
                     "share_detour_over_1.5x": (ratio > 1.5).mean() * 100})
    return pd.DataFrame(rows)


def band_reclassification(blocks):
    r = blocks[blocks["residential"] == "Y"]
    return pd.crosstab(r["mrt_band"], r["mrt_band_walk"], margins=True)


def walk_vs_straight_hedonic(df, sample_n=120_000, seed=0):
    """Which MRT distance explains price better, holding everything else equal?"""
    others = ["dist_hawker_km", "dist_supermarket_km", "dist_chas_clinic_km", "dist_park_km", "n_bus_stop_400m",
              "dist_planned_rail_km"]
    d = df.dropna(subset=["dist_mrt_exit_km_at_sale", "walk_mrt_exit_km_at_sale", "remaining_lease_yrs",
                          "storey_mid"] + others).copy()
    if sample_n and len(d) > sample_n:
        d = d.sample(sample_n, random_state=seed)
    d["month"] = d["month"].dt.strftime("%Y-%m")
    base = BASE + " + " + " + ".join(others) + " + C(elite_primary_tier, Treatment('Beyond 2km'))"
    res = {}
    for label, term in [("straight-line MRT", "dist_mrt_exit_km_at_sale"),
                        ("walking MRT", "walk_mrt_exit_km_at_sale"),
                        ("both", "dist_mrt_exit_km_at_sale + walk_mrt_exit_km_at_sale")]:
        m = smf.ols(base + " + " + term, data=d).fit()
        row = {"adj_R2": m.rsquared_adj, "AIC": m.aic}
        for v in ["dist_mrt_exit_km_at_sale", "walk_mrt_exit_km_at_sale"]:
            if v in m.params:
                row[f"pct_per_100m_{'straight' if v.startswith('dist') else 'walk'}"] = (np.exp(-m.params[v] * 0.1) - 1) * 100
                row[f"t_{'straight' if v.startswith('dist') else 'walk'}"] = m.tvalues[v]
        res[label] = row
    return pd.DataFrame(res).T


def granularity_comparison(df, months=12, min_txn=3):
    recent = df[df["month"] > df["month"].max() - pd.DateOffset(months=months)]
    recent = recent[recent["flat_type"] != "MULTI-GENERATION"]
    specs = {
        "G1: town x flat_type x storey": ["town", "flat_type", "storey_band"],
        "G2: G1 x MRT band (Near/Mid/Far)": ["town", "flat_type", "storey_band", "mrt_band"],
        "G3: block x flat_type x storey": ["query", "flat_type", "storey_band"],
    }
    rows = []
    for name, keys in specs.items():
        g = recent.groupby(keys, observed=True)
        cells = g.agg(n=("resale_price", "size"), price_cv=("price_psm", lambda s: s.std() / s.mean()),
                      mrt_sd=("dist_mrt_exit_km", "std"))
        usable = cells[cells["n"] >= min_txn]
        rows.append({
            "granularity": name, "cells_total": len(cells), "cells_usable(>=3 txn/12mo)": len(usable),
            "pct_txn_in_usable_cells": usable["n"].sum() / cells["n"].sum() * 100,
            "median_within_cell_psm_CV": usable["price_cv"].median() * 100,
            "median_within_cell_MRT_sd_m": usable["mrt_sd"].median() * 1000,
            "towns_covered": recent.set_index(keys).loc[usable.index].reset_index()["town"].nunique()
                              if "town" in keys else recent[recent["query"].isin(usable.reset_index()["query"])]["town"].nunique(),
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = load_transactions_with_access()
    df["price_psm"] = df["resale_price"] / df["floor_area_sqm"]
    print(f"Transactions joined to blocks: {len(df):,}")

    print("\n=== Variance decomposition (unique blocks) ===")
    print(variance_decomposition(df, ACCESS_FEATURES).round(3).to_string(index=False))

    print("\n=== Granularity comparison (last 12 months) ===")
    print(granularity_comparison(df).round(2).to_string(index=False))

    print("\n=== Hedonic: town FE vs + block accessibility (80k sample) ===")
    d, m_a, m_b = hedonic_models(df, sample_n=80000)
    print(f"Adj R2  town-FE only: {m_a.rsquared_adj:.4f}   + block access: {m_b.rsquared_adj:.4f}")
    print(f"Resid SE (log) town-FE only: {np.sqrt(m_a.mse_resid):.4f}   + block: {np.sqrt(m_b.mse_resid):.4f}")
    print(coefficient_table(m_b).round(3).to_string(index=False))

    print("\n=== Out-of-time (train <2025, test 2025-26) ===")
    print(out_of_time_test(df).round(3))

    print("\n=== MRT distance price gradient (within town) ===")
    print(mrt_distance_gradient(df).round(2).to_string(index=False))

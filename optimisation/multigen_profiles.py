# -*- coding: utf-8 -*-
"""
MULTI-GENERATION flat profiles -- a deliberately SEPARATE, town-level-only table,
not merged into housing_profiles_v2_full.csv.

Why not just drop the exclusion filter everywhere: MULTI-GENERATION flats are
genuinely rare (88 resale transactions nationwide since 2017, vs 100k+ for
4-room alone), concentrated in just 3 towns. housing_profiles_v2.build_profiles_v2()
profiles on a TRAILING-12-MONTH window with a >=3-transaction floor -- applying
that unchanged to multi-gen would return close to zero profiles most months, and
the few it did return would have shrinkage/diversity statistics built on an n too
thin to mean anything (the project's own shrink_k=10 default alone exceeds the
total national annual volume of this flat type).

This table uses the full ~9-year history instead of a trailing window (the only
way to get a usable sample size at all) and is town-level, not block-level, for
the same reason. It is explicitly a supplementary, lower-confidence table for a
caregiving/multi-generational household archetype to query directly (e.g. via
recommender_v2.solve(query, profiles=load_multigen_profiles())) -- it is NOT
merged into the standard candidate pool, so it never silently dilutes the main
712-profile table's reliability.
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from block_analysis import load_transactions_with_access  # noqa: E402
from housing_profiles_v2 import ESSENTIALS  # noqa: E402

OUT = os.path.join(HERE, "data")


def build_multigen_profiles(min_txn=3, write=True):
    tx = load_transactions_with_access()
    mg = tx[tx["flat_type"] == "MULTI-GENERATION"].copy()
    mg["price_psm"] = mg["resale_price"] / mg["floor_area_sqm"]
    for k, (col, thr) in ESSENTIALS.items():
        mg[f"ess_{k}"] = (mg[col] <= thr).astype(int)
    mg["essentials_score"] = mg[[f"ess_{k}" for k in ESSENTIALS]].sum(axis=1)
    mg["elite_1km"] = (mg["elite_primary_tier"] == "Within 1km").astype(int)
    mg["elite_2km"] = mg["elite_primary_tier"].isin(["Within 1km", "1-2km"]).astype(int)

    agg = dict(
        median_price=("resale_price", "median"), price_p25=("resale_price", lambda s: s.quantile(0.25)),
        price_p75=("resale_price", lambda s: s.quantile(0.75)), median_price_psm=("price_psm", "median"),
        median_floor_area=("floor_area_sqm", "median"), median_remaining_lease=("remaining_lease_yrs", "median"),
        txn_count_alltime=("resale_price", "size"), n_blocks=("query", "nunique"),
        essentials_score=("essentials_score", "mean"), share_primary_1km=("ess_primary_school_1km", "mean"),
        share_elite_primary_1km=("elite_1km", "mean"), share_elite_primary_2km=("elite_2km", "mean"),
        dist_mrt_exit_km_p50=("dist_mrt_exit_km", "median"), dist_hawker_km_p50=("dist_hawker_km", "median"),
        dist_supermarket_km_p50=("dist_supermarket_km", "median"), dist_chas_clinic_km_p50=("dist_chas_clinic_km", "median"),
        dist_park_km_p50=("dist_park_km", "median"), first_sale=("month", "min"), last_sale=("month", "max"),
    )
    prof = mg.groupby("town", observed=True).agg(**agg).reset_index()
    prof = prof[prof["txn_count_alltime"] >= min_txn].copy()
    prof["flat_type"] = "MULTI-GENERATION"
    prof["storey_band"] = "Mid"   # not modelled at this sample size -- a placeholder, not a real median
    prof["mrt_band"] = pd.cut(prof["dist_mrt_exit_km_p50"], [-1, 0.4, 0.8, 99], labels=["Near", "Mid", "Far"])
    prof["profile_id"] = (prof["town"].str.replace("/", "-") + "::MULTIGEN::" + prof["town"].str.replace(" ", "")
                          .str.slice(0, 0) + "town_level")  # distinguishable from the block-informed id scheme
    prof["profile_id"] = prof["town"].str.replace("/", "-") + "::MULTIGEN::town_level"
    prof["txn_count_12m"] = 0  # the recommender's availability stub expects this column; see data_quality note
    # no hedonic model was fit for MULTI-GENERATION (training set excludes it, same reason
    # as everywhere else -- too few rows to fit reliably) -- NaN here, fillna(0) in score()
    # means surplus for these rows is driven only by preference tilt, never a mispricing signal.
    prof["hedonic_gap"] = np.nan
    prof["data_quality"] = (f"THIN DATA: town-level, all-time (" +
                            prof["first_sale"].dt.strftime("%Y-%m") + " to " + prof["last_sale"].dt.strftime("%Y-%m") +
                            "), n=" + prof["txn_count_alltime"].astype(str) +
                            " nationwide sales behind this row -- treat as directional only, not a priced estimate.")
    prof = prof.drop(columns=["first_sale", "last_sale"])

    if write:
        prof.to_csv(os.path.join(OUT, "multigen_profiles.csv"), index=False)
    return prof


def ensure_multigen_fcast_rows(towns):
    """recommender_v2.assemble() merges profiles with price_forecast.csv (read from
    DISK, inside assemble() itself) on [town, flat_type, horizon_months] to compute
    price_upper BEFORE solve()'s own fcast_override parameter ever gets applied -- so
    fcast_override alone cannot fix a missing flat_type; the on-disk file needs the
    rows. The stub forecast itself is flat_type-independent (every flat type gets the
    identical 0%-growth / +15% band -- see price_forecast.csv's own _source column),
    so this appends that same universal stub constant for MULTI-GENERATION rather
    than inventing a new number. Idempotent: skips if already present."""
    path = os.path.join(OUT, "price_forecast.csv")
    f = pd.read_csv(path)
    if (f["flat_type"] == "MULTI-GENERATION").any():
        return
    stub = f.iloc[0]
    rows = [{"town": t, "flat_type": "MULTI-GENERATION", "horizon_months": h,
             "growth_factor": stub["growth_factor"], "growth_factor_lower": stub["growth_factor_lower"],
             "growth_factor_upper": stub["growth_factor_upper"], "_source": stub["_source"]}
            for t in towns for h in f["horizon_months"].unique()]
    pd.concat([f, pd.DataFrame(rows)], ignore_index=True).to_csv(path, index=False)


def load_multigen_profiles():
    """Convenience loader for a caregiving/multi-generational household archetype:
    rv2.solve(query, profiles=load_multigen_profiles())."""
    path = os.path.join(OUT, "multigen_profiles.csv")
    prof = pd.read_csv(path) if os.path.exists(path) else build_multigen_profiles()
    ensure_multigen_fcast_rows(prof["town"].unique().tolist())
    return prof


if __name__ == "__main__":
    prof = build_multigen_profiles()
    print(f"{len(prof)} MULTI-GENERATION town-level profiles (of 3 towns with any sales at all)")
    print(prof[["town", "txn_count_alltime", "median_price", "median_remaining_lease",
                "dist_mrt_exit_km_p50", "mrt_band"]].round(2).to_string(index=False))

# -*- coding: utf-8 -*-
"""
Housing profiles v2 -- block-informed.

Decision (evidence in block_analysis.py):
  profile = town x flat_type x storey_band x mrt_band
  mrt_band: Near (<=400m to an operating MRT exit), Mid (400-800m), Far (>800m)

Why not pure block-level profiles: only ~28% of last-12-month transactions
fall in block x flat_type x storey cells with >=3 sales -- too thin to price
or forecast. Why not stay at town level: 79% of MRT-distance variance (and
63-96% for other amenities) is WITHIN towns, and block accessibility lifts
hedonic adj-R2 0.918 -> 0.935 beyond town fixed effects.

Each profile carries the block-level DISTRIBUTION of its accessibility
(p10/p50/p90), not just a point value, plus the constituent blocks, so the
dashboard can drill down from "Tampines 4-Room Mid-floor, Near MRT" to the
actual blocks behind it.
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from block_analysis import load_transactions_with_access, network_as_of  # noqa: E402

OUT = os.path.join(HERE, "data")

DIST_COLS = ["dist_mrt_exit_km", "dist_primary_school_km", "dist_hawker_km", "dist_supermarket_km",
             "dist_chas_clinic_km", "dist_park_km", "dist_childcare_km", "dist_polyclinic_km",
             "dist_bus_stop_km", "dist_planned_rail_km",
             # added 2026-10-08 (see ATTRIBUTE_EXPANSION_CHECKPOINT.md / OPTIMISER_METHODOLOGY_REPORT.md):
             "dist_secondary_school_km", "dist_secondary_elite_km", "dist_carpark_km", "dist_carpark_night_km",
             "dist_flood_prone_km", "dist_expressway_km", "dist_nearest_job_node_km",
             "dist_raffles_place_km", "dist_jurong_lake_district_km", "dist_punggol_digital_district_km",
             "dist_one_north_km", "dist_woodlands_regional_centre_km"]
COUNT_COLS = ["n_primary_school_1000m", "n_bus_stop_400m", "n_hawker_1000m", "n_supermarket_1000m",
              "n_chas_clinic_500m", "n_park_1000m", "n_childcare_500m",
              "n_secondary_school_1000m", "n_secondary_school_2000m", "n_secondary_elite_2000m",
              "n_carpark_400m", "n_carpark_night_400m", "n_flood_prone_300m", "n_flood_prone_500m"]
# booleans/categoricals that don't belong in a median -- aggregated separately below
# ("share_*" = mean of the 0/1 flag over the profile's sales, same convention as essentials_score;
#  "first" for text labels, acceptable since these rarely vary within a town x flat_type x storey x band cell)
SHARE_FLAG_COLS = ["near_flood_prone_area", "has_carpark_400m", "has_night_parking_400m"]
LABEL_COLS = ["secondary_tier", "expressway_proximity_band", "nearest_job_node"]

# "walkable essentials": indicator per block, then averaged over the profile's sales
ESSENTIALS = {"supermarket": ("dist_supermarket_km", 0.5), "hawker": ("dist_hawker_km", 0.8),
              "clinic": ("dist_chas_clinic_km", 0.5), "park": ("dist_park_km", 0.8),
              "primary_school_1km": ("dist_primary_school_km", 1.0)}


def build_profiles_v2(recent_months=12, min_txn=3, as_of=None, write=True, with_hedonic=True):
    """as_of: build profiles using only transactions up to this date (for
    backtesting). With as_of, MRT distance/band use the rail network open on
    that date (no look-ahead to stations that opened later)."""
    df_all = load_transactions_with_access()
    df_all = df_all[df_all["flat_type"] != "MULTI-GENERATION"].copy()
    df = df_all if as_of is None else network_as_of(df_all[df_all["month"] <= pd.Timestamp(as_of)], as_of)
    df["price_psm"] = df["resale_price"] / df["floor_area_sqm"]
    for k, (col, thr) in ESSENTIALS.items():
        df[f"ess_{k}"] = (df[col] <= thr).astype(int)
    df["essentials_score"] = df[[f"ess_{k}" for k in ESSENTIALS]].sum(axis=1)
    df["elite_1km"] = (df["elite_primary_tier"] == "Within 1km").astype(int)
    df["elite_2km"] = df["elite_primary_tier"].isin(["Within 1km", "1-2km"]).astype(int)

    recent = df[df["month"] > df["month"].max() - pd.DateOffset(months=recent_months)]
    keys = ["town", "flat_type", "storey_band", "mrt_band"]

    agg = {
        "median_price": ("resale_price", "median"),
        "price_p25": ("resale_price", lambda s: s.quantile(0.25)),
        "price_p75": ("resale_price", lambda s: s.quantile(0.75)),
        "median_price_psm": ("price_psm", "median"),
        "median_floor_area": ("floor_area_sqm", "median"),
        "median_remaining_lease": ("remaining_lease_yrs", "median"),
        "txn_count_12m": ("resale_price", "size"),
        "n_blocks": ("query", "nunique"),
        "essentials_score": ("essentials_score", "mean"),
        "share_primary_1km": ("ess_primary_school_1km", "mean"),
        "share_elite_primary_1km": ("elite_1km", "mean"),
        "share_elite_primary_2km": ("elite_2km", "mean"),
        "share_supermarket_500m": ("ess_supermarket", "mean"),
        "share_clinic_500m": ("ess_clinic", "mean"),
    }
    for c in DIST_COLS:
        if c in recent.columns:
            agg[f"{c}_p50"] = (c, "median")
    for c in ["dist_mrt_exit_km", "dist_hawker_km", "dist_supermarket_km"]:
        agg[f"{c}_p10"] = (c, lambda s: s.quantile(0.10))
        agg[f"{c}_p90"] = (c, lambda s: s.quantile(0.90))
    for c in COUNT_COLS:
        if c in recent.columns:
            agg[f"{c}_p50"] = (c, "median")
    for c in SHARE_FLAG_COLS:
        if c in recent.columns:
            agg[f"share_{c}"] = (c, "mean")
    for c in LABEL_COLS:
        if c in recent.columns:
            agg[c] = (c, "first")

    prof = recent.groupby(keys, observed=True).agg(**agg).reset_index()
    prof = prof[prof["txn_count_12m"] >= min_txn].copy()
    prof["profile_id"] = (prof["town"].str.replace("/", "-") + "::" + prof["flat_type"].str.replace(" ", "")
                          + "::" + prof["storey_band"] + "::" + prof["mrt_band"].astype(str))

    # exposure for the availability model: dwelling units of this flat type in the profile's blocks
    blocks = pd.read_csv(os.path.join(OUT, "block_accessibility.csv"))
    ft_col = {"2 ROOM": "2room_sold", "3 ROOM": "3room_sold", "4 ROOM": "4room_sold",
              "5 ROOM": "5room_sold", "EXECUTIVE": "exec_sold"}
    block_of = recent[["query", "town", "flat_type", "storey_band", "mrt_band"]].drop_duplicates()
    block_of = block_of.merge(blocks[["query"] + list(ft_col.values())], on="query", how="left")
    block_of["units_of_type"] = block_of.apply(lambda r: r.get(ft_col.get(r["flat_type"], ""), np.nan), axis=1)
    exposure = block_of.groupby(keys, observed=True)["units_of_type"].sum().rename("units_in_profile_blocks")
    prof = prof.merge(exposure.reset_index(), on=keys, how="left")
    prof["annual_turnover_pct"] = prof["txn_count_12m"] / prof["units_in_profile_blocks"].replace(0, np.nan) * 100

    # backwards-compatible aliases used by recommender/stub code
    prof["nearest_mrt_km"] = prof["dist_mrt_exit_km_p50"]
    prof["nearest_school_km"] = prof["dist_primary_school_km_p50"]
    prof["schools_within"] = prof["n_primary_school_1000m_p50"]

    # block drill-down table: which blocks sit behind each profile (dashboard layer)
    drill = recent.groupby(keys + ["query"], observed=True).agg(
        sales_12m=("resale_price", "size"), median_price=("resale_price", "median"),
        dist_mrt_exit_km=("dist_mrt_exit_km", "first"), lat=("lat", "first"), lon=("lon", "first"),
        **({"walk_mrt_exit_km": ("walk_mrt_exit_km", "first")} if "walk_mrt_exit_km" in recent else {}),
        elite_primary_tier=("elite_primary_tier", "first")).reset_index()
    drill = drill.merge(prof[keys + ["profile_id"]], on=keys, how="inner")

    hedonic_coefs = None
    if with_hedonic:
        from hedonic_value import fit_hedonic, predict_value, market_wtp_coefficients
        model, last_month = fit_hedonic(df, as_of=as_of)
        idx, vals = predict_value(model, recent, at_month=last_month)
        recent = recent.loc[idx].assign(hedonic_value=vals)
        hv = recent.groupby(keys, observed=True)["hedonic_value"].median().rename("hedonic_value").reset_index()
        prof = prof.merge(hv, on=keys, how="left")
        # value-for-money: market value of the attributes minus what they actually sell for
        prof["hedonic_gap"] = prof["hedonic_value"] - prof["median_price"]
        hedonic_coefs = market_wtp_coefficients(model)
        prof.attrs["hedonic_r2_adj"] = model.rsquared_adj

    if write:
        prof.to_csv(os.path.join(OUT, "housing_profiles_v2_full.csv"), index=False)
        drill.to_csv(os.path.join(OUT, "profile_block_drilldown.csv"), index=False)
        if hedonic_coefs:
            import json
            with open(os.path.join(OUT, "market_wtp_coefficients.json"), "w") as f:
                json.dump({"log_points_per_km": hedonic_coefs, "as_of": str(as_of or df["month"].max().date()),
                           "note": "Revealed (market) WTP from the interim hedonic; Preference Lead's conjoint "
                                   "WTP replaces/complements this via household multipliers."}, f, indent=2)
    return prof, drill


if __name__ == "__main__":
    prof, drill = build_profiles_v2()
    print(f"v2 profiles: {len(prof)}  | towns {prof['town'].nunique()} | "
          f"bands {prof['mrt_band'].value_counts().to_dict()}")
    print(f"Block drill-down rows: {len(drill)} across {drill['query'].nunique()} blocks")
    print(prof[["profile_id", "median_price", "txn_count_12m", "n_blocks", "dist_mrt_exit_km_p10",
                "dist_mrt_exit_km_p50", "dist_mrt_exit_km_p90", "essentials_score",
                "annual_turnover_pct"]].head(12).round(3).to_string(index=False))

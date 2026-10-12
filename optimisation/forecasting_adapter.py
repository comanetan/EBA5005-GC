# -*- coding: utf-8 -*-
"""
Adapter: Forecasting Lead's real deliverable (comanetan/EBA5005-GC, forecasting branch,
snapshotted into data/external_handovers/) -> this pipeline's price_forecast.csv schema
(town, flat_type, horizon_months, growth_factor, growth_factor_lower, growth_factor_upper).

Real coverage is 4-ROOM ONLY (price_paths_metadata.json: "Supports four-room profiles
only"), all 26 towns. This adapter REPLACES only the 4-ROOM rows of the existing
price_forecast.csv with real values; every other flat type keeps the existing stub --
stated explicitly in the output and printed on every run, not silently left ambiguous.

Growth factor is computed at THEIR OWN profile granularity first (price_paths' monthly
p10/p50/p90 divided by their OWN prices_today at the shared Sep-2026 base month), THEN
crosswalked and aggregated (median) down to this pipeline's (town, flat_type) grain --
deliberately in that order, so two different aggregation steps (pricing's and
forecasting's) are never mixed before dividing one by the other.
"""
import json
import os

import pandas as pd

from profile_crosswalk import add_my_profile_id

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
EXT = os.path.join(DATA, "external_handovers")

HORIZON_TO_STEPS = {6: 6, 12: 12}  # price_paths month index is already "steps ahead of base"


def build_price_forecast(write=True):
    meta = json.load(open(os.path.join(EXT, "price_paths_metadata.json")))
    base_month = pd.Timestamp(meta["base_price_month"])

    paths = pd.read_csv(os.path.join(EXT, "price_paths_forecasting.csv"))
    paths["month_ts"] = pd.to_datetime(paths["month"])
    paths["steps_ahead"] = ((paths["month_ts"].dt.year - base_month.year) * 12
                            + (paths["month_ts"].dt.month - base_month.month))

    base_price = pd.read_csv(os.path.join(EXT, "prices_today_main.csv"))[["profile_id", "price"]] \
        .rename(columns={"price": "price_base"})
    d = paths.merge(base_price, on="profile_id", how="inner")

    rows = []
    for h, steps in HORIZON_TO_STEPS.items():
        sub = d[d["steps_ahead"] == steps].copy()
        sub["growth_factor"] = sub["p50"] / sub["price_base"]
        sub["growth_factor_lower"] = sub["p10"] / sub["price_base"]
        sub["growth_factor_upper"] = sub["p90"] / sub["price_base"]
        sub["horizon_months"] = h
        rows.append(sub)
    d = pd.concat(rows, ignore_index=True)

    d = add_my_profile_id(d)
    d = d.dropna(subset=["my_profile_id"])
    # aggregate away the lease/storey/MRT-band dimensions my (town, flat_type) grain doesn't carry
    agg = d.groupby(["town", "flat_type", "horizon_months"], observed=True).agg(
        growth_factor=("growth_factor", "median"), growth_factor_lower=("growth_factor_lower", "median"),
        growth_factor_upper=("growth_factor_upper", "median"), n_source_profiles=("growth_factor", "size"),
    ).reset_index()
    agg["_source"] = "REAL (Forecasting Lead, regional SARIMAX, validation-selected) -- 4 ROOM only, " \
                     f"base month {meta['base_price_month']}, model {meta['model_version']}"

    existing = pd.read_csv(os.path.join(DATA, "price_forecast.csv"))
    kept = existing[existing["flat_type"] != "4 ROOM"]
    combined = pd.concat([kept, agg[["town", "flat_type", "horizon_months", "growth_factor",
                                     "growth_factor_lower", "growth_factor_upper", "_source"]]],
                         ignore_index=True)

    if write:
        combined.to_csv(os.path.join(DATA, "price_forecast.csv"), index=False)
        agg.to_csv(os.path.join(DATA, "price_forecast_4room_provenance.csv"), index=False)
    return combined, agg


if __name__ == "__main__":
    combined, agg = build_price_forecast()
    n_towns = agg["town"].nunique()
    print(f"4-ROOM real coverage: {n_towns}/26 towns, {len(agg)} rows (2 horizons x towns)")
    print(f"4-ROOM, horizon=12: median growth_factor {agg[agg.horizon_months==12]['growth_factor'].median():.3f} "
          f"(stub was flat 1.00); other flat types unchanged (still stub)")
    print(combined[combined["flat_type"] == "4 ROOM"].head(6).to_string(index=False))

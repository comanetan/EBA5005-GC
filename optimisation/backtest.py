# -*- coding: utf-8 -*-
"""
Task 6 (shared with Forecasting + Pricing & Availability Leads, recommender
side owned here): "Generates shortlists at past dates using only the data
available then." Evaluation: "Share of shortlisted profiles whose realised
price 6-12 months later stayed within budget, vs a naive 'cheapest towns'
baseline."

Walk-forward design: pick a past cutoff date, rebuild `housing_profiles`
and `pricing_today` using only transactions up to that cutoff, run the
recommender, then check the REALISED price 6/12 months after the cutoff
(which we *do* have, since it's historical) against the household's budget.
"""
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../Project, portable across machines
DATA_DIR = os.path.join(ROOT, "notebooks", "optimization_lead", "data")
sys.path.insert(0, os.path.join(ROOT, "notebooks"))


def storey_band(storey_range):
    m = re.match(r"(\d+) TO (\d+)", str(storey_range))
    if not m:
        return None
    lo = int(m.group(1))
    return "Low" if lo <= 6 else ("Mid" if lo <= 15 else "High")


def build_profiles_as_of(raw_df, cutoff_date, lookback_months=12, min_txn=3):
    window_start = cutoff_date - pd.DateOffset(months=lookback_months - 1)
    window = raw_df[(raw_df["month"] >= window_start) & (raw_df["month"] <= cutoff_date)
                     & (raw_df["flat_type"] != "MULTI-GENERATION")]
    grp = window.groupby(["town", "flat_type", "storey_band"]).agg(
        price_today=("resale_price", "median"),
        median_remaining_lease=("remaining_lease_yrs", "median"),
        txn_count_12m=("resale_price", "size"),
    ).reset_index()
    grp = grp[grp["txn_count_12m"] >= min_txn].copy()
    grp["profile_id"] = (grp["town"].str.replace("/", "-") + "::" + grp["flat_type"].str.replace(" ", "")
                          + "::" + grp["storey_band"])
    return grp


def realised_price_after(raw_df, profile_row, cutoff_date, horizon_months):
    target_month = cutoff_date + pd.DateOffset(months=horizon_months)
    window = raw_df[(raw_df["month"] >= target_month - pd.DateOffset(months=1))
                     & (raw_df["month"] <= target_month + pd.DateOffset(months=1))
                     & (raw_df["town"] == profile_row["town"])
                     & (raw_df["flat_type"] == profile_row["flat_type"])
                     & (raw_df["storey_band"] == profile_row["storey_band"])]
    if window.empty:
        return np.nan
    return window["resale_price"].median()


def naive_cheapest_towns_baseline(profiles_asof: pd.DataFrame, k: int, min_lease: int) -> pd.DataFrame:
    """Simplest possible competitor: k cheapest profiles overall, one per
    town, ignoring preferences/availability entirely."""
    elig = profiles_asof[profiles_asof["median_remaining_lease"] >= min_lease].copy()
    elig = elig.sort_values("price_today")
    seen_towns, picked = set(), []
    for _, r in elig.iterrows():
        if r["town"] in seen_towns:
            continue
        picked.append(r)
        seen_towns.add(r["town"])
        if len(picked) == k:
            break
    return pd.DataFrame(picked)


def run_backtest(cutoff_date_str, budget, min_lease_yrs, k, horizon_months=12, flat_types=None):
    from recommender import HouseholdQuery

    raw = pd.read_csv(os.path.join(ROOT, "Resale flat prices based on registration date from Jan-2017 onwards.csv"))
    raw["month"] = pd.to_datetime(raw["month"], format="%Y-%m")
    raw["storey_band"] = raw["storey_range"].apply(storey_band)

    def parse_lease(s):
        m = re.match(r"(\d+)\s*years?(?:\s*(\d+)\s*months?)?", str(s))
        if not m:
            return np.nan
        yrs = int(m.group(1))
        mos = int(m.group(2)) if m.group(2) else 0
        return yrs + mos / 12
    raw["remaining_lease_yrs"] = raw["remaining_lease"].apply(parse_lease)

    cutoff = pd.Timestamp(cutoff_date_str)
    profiles_asof = build_profiles_as_of(raw, cutoff)
    print(f"Backtest cutoff {cutoff.date()}: {len(profiles_asof)} profiles available then")

    # --- recommender shortlist, using only as-of data (write temp stub pricing/forecast) ---
    import data_prep as dp  # noqa: reuse geo features (static, not time-travel-sensitive here)
    geo = dp.build_town_geo_features()
    profiles_asof = profiles_asof.merge(geo, on="town", how="left")

    os.makedirs(os.path.join(DATA_DIR, "backtest_tmp"), exist_ok=True)
    tmp = os.path.join(DATA_DIR, "backtest_tmp")
    # housing_profiles.csv must NOT carry price_today (that's pricing_today.csv's
    # job) -- else the merge in load_candidate_table() collides into
    # price_today_x/price_today_y instead of a plain price_today column
    profiles_asof.drop(columns=["price_today"]).to_csv(os.path.join(tmp, "housing_profiles.csv"), index=False)
    profiles_asof[["profile_id", "price_today"]].assign(price_today_se=lambda d: d["price_today"] * 0.05).to_csv(
        os.path.join(tmp, "pricing_today.csv"), index=False)
    profiles_asof[["profile_id", "txn_count_12m"]].assign(
        expected_wait_months=lambda d: (12 / (d["txn_count_12m"] / 12 / 20).clip(lower=0.02, upper=0.9)).round(1),
        survival_prob_6m=0.3, survival_prob_12m=0.5, hazard_ratio=1.0,
    ).to_csv(os.path.join(tmp, "availability.csv"), index=False)

    combos = profiles_asof[["town", "flat_type"]].drop_duplicates()
    fc_rows = []
    for _, r in combos.iterrows():
        for h, lo, hi in [(6, 0.08, 0.10), (12, 0.12, 0.15)]:
            fc_rows.append({"town": r["town"], "flat_type": r["flat_type"], "horizon_months": h,
                             "growth_factor": 1.0, "growth_factor_lower": 1 - lo, "growth_factor_upper": 1 + hi})
    pd.DataFrame(fc_rows).to_csv(os.path.join(tmp, "price_forecast.csv"), index=False)

    import json
    with open(os.path.join(tmp, "preferences.json"), "w") as f:
        json.dump({"wtp_sgd": {"per_km_closer_to_mrt": 25000, "per_additional_school_within_1km": 8000,
                                "per_year_remaining_lease": 3000,
                                "storey_band_premium": {"Low": 0, "Mid": 12000, "High": 20000},
                                "per_amenity_count": 1500},
                   "price_elasticity_of_choice": -1.2}, f)

    import recommender as rec
    orig_data_dir = rec.DATA_DIR
    rec.DATA_DIR = tmp
    try:
        q = HouseholdQuery(budget=budget, min_lease_yrs=min_lease_yrs, horizon_months=horizon_months, k=k,
                           flat_types=flat_types)
        res = rec.solve_recommender(q)
    finally:
        rec.DATA_DIR = orig_data_dir

    shortlist = res["shortlist"]
    base_pool = profiles_asof if not flat_types else profiles_asof[profiles_asof["flat_type"].isin(flat_types)]
    baseline = naive_cheapest_towns_baseline(base_pool, k=k, min_lease=min_lease_yrs)

    # --- evaluate against REALISED prices ---
    def evaluate(picks, label):
        rows = []
        for _, r in picks.iterrows():
            realised = realised_price_after(raw, r, cutoff, horizon_months)
            rows.append({"profile_id": r["profile_id"], "price_at_cutoff": r["price_today"],
                         "realised_price": realised, "within_budget": (realised <= budget) if pd.notna(realised) else np.nan})
        out = pd.DataFrame(rows)
        out["strategy"] = label
        return out

    rec_eval = evaluate(shortlist, "recommender") if len(shortlist) else pd.DataFrame()
    base_eval = evaluate(baseline, "naive_cheapest_towns") if len(baseline) else pd.DataFrame()
    combined = pd.concat([rec_eval, base_eval], ignore_index=True)
    return combined


if __name__ == "__main__":
    out = run_backtest(cutoff_date_str="2025-01-01", budget=500_000, min_lease_yrs=60, k=5, horizon_months=12)
    print(out.to_string(index=False))
    print("\nShare within budget by strategy:")
    print(out.groupby("strategy")["within_budget"].mean())

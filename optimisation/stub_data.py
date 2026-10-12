# -*- coding: utf-8 -*-
"""
Placeholder generators for the 3 other leads' outputs, matching
INTERFACE_SPEC.md exactly, so the pipeline runs end-to-end from Day 1.
Each function is clearly swappable for the real thing -- same filename,
same schema, no other code changes needed.

Swap-in dates (from the Gantt): pricing/availability ~7-16 Oct, forecasts
14 Oct, preferences ~16 Oct.
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = r"C:\Users\Daniel Loh\Documents\NUS-ISS_EBAC\SPMF\Project"
DATA_DIR = os.path.join(ROOT, "notebooks", "optimization_lead", "data")
os.makedirs(DATA_DIR, exist_ok=True)


def stub_pricing_today(profiles: pd.DataFrame) -> pd.DataFrame:
    """STUB for Pricing & Availability Lead's hedonic model output."""
    df = profiles[["profile_id", "median_price"]].rename(columns={"median_price": "price_today"})
    df["price_today_se"] = df["price_today"] * 0.05
    df["_source"] = "STUB (trailing-12mo median) -- replace with hedonic model fit by 7 Oct"
    return df


def stub_availability(profiles: pd.DataFrame, seed=7) -> pd.DataFrame:
    """STUB for Pricing & Availability Lead's survival-model output.
    Exponential survival calibrated to each profile's observed turnover:
    higher txn_count_12m -> shorter expected wait. This is a *placeholder*
    functional form, not a claim about the true hazard shape (the real
    model will be Kaplan-Meier / Cox PH, per INTERFACE_SPEC.md)."""
    rng = np.random.default_rng(seed)
    df = profiles[["profile_id", "txn_count_12m"]].copy()
    # more transactions/year at this cell -> implied higher per-unit turnover rate
    monthly_rate = (df["txn_count_12m"] / 12 / 20).clip(lower=0.02, upper=0.9)  # /20 ~ typical units per cell
    expected_wait = 1 / monthly_rate
    df["expected_wait_months"] = expected_wait.round(1)
    df["survival_prob_6m"] = (1 - np.exp(-monthly_rate * 6)).round(3)
    df["survival_prob_12m"] = (1 - np.exp(-monthly_rate * 12)).round(3)
    df["hazard_ratio"] = 1.0
    df["_source"] = "STUB (exponential, calibrated to txn_count_12m) -- replace with KM/Cox PH by 16 Oct"
    return df[["profile_id", "expected_wait_months", "survival_prob_6m", "survival_prob_12m", "hazard_ratio", "_source"]]


def stub_price_forecast(profiles: pd.DataFrame) -> pd.DataFrame:
    """STUB for Forecasting Lead's SARIMAX output. Flat growth with bounds
    loosely calibrated to the GARCH annualised-volatility figures already
    computed for Option A (median ~15-20% annualised vol across towns)."""
    combos = profiles[["town", "flat_type"]].drop_duplicates()
    rows = []
    for _, r in combos.iterrows():
        for h, lo_pct, hi_pct in [(6, 0.08, 0.10), (12, 0.12, 0.15)]:
            rows.append({
                "town": r["town"], "flat_type": r["flat_type"], "horizon_months": h,
                "growth_factor": 1.00,
                "growth_factor_lower": round(1 - lo_pct, 3),
                "growth_factor_upper": round(1 + hi_pct, 3),
                "_source": "STUB (flat 0% growth, +/-GARCH-scale band) -- replace with SARIMAX output by 14 Oct",
            })
    return pd.DataFrame(rows)


def stub_preferences() -> dict:
    """STUB for Preference Lead's choice-based conjoint output, expressed in
    WTP (SGD) so the recommender's objective is dollar-denominated throughout."""
    return {
        "wtp_sgd": {
            "per_km_closer_to_mrt": 25000,
            "per_additional_school_within_1km": 8000,
            "per_year_remaining_lease": 3000,
            "storey_band_premium": {"Low": 0, "Mid": 12000, "High": 20000},
            "per_amenity_count": 1500,
        },
        "price_elasticity_of_choice": -1.2,
        "_source": "STUB (lifted from the earlier simulated-conjoint run) -- replace with real choice-based conjoint output by 16 Oct",
    }


def write_all_stubs(profiles: pd.DataFrame):
    stub_pricing_today(profiles).to_csv(os.path.join(DATA_DIR, "pricing_today.csv"), index=False)
    stub_availability(profiles).to_csv(os.path.join(DATA_DIR, "availability.csv"), index=False)
    stub_price_forecast(profiles).to_csv(os.path.join(DATA_DIR, "price_forecast.csv"), index=False)
    with open(os.path.join(DATA_DIR, "preferences.json"), "w") as f:
        json.dump(stub_preferences(), f, indent=2)
    print("Wrote stub files to", DATA_DIR)


if __name__ == "__main__":
    from housing_profiles import build_profiles
    profiles = build_profiles()
    write_all_stubs(profiles)
    for fname in ["pricing_today.csv", "availability.csv", "price_forecast.csv", "preferences.json"]:
        path = os.path.join(DATA_DIR, fname)
        print(f"  {fname}: {os.path.getsize(path):,} bytes")

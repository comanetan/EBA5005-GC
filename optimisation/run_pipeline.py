# -*- coding: utf-8 -*-
"""
Task 2: "Rough pipeline and simple ranking" -- the Day-1 end-to-end version
that runs against placeholder data for everyone else's piece, proving the
tool works before any real model exists. This is deliberately NOT the real
recommender (no MIP, no goal programming) -- just a naive weighted-sum
ranking, so there's an honest baseline to compare Task 3's real formulation
against later.

Also serves as "pipeline ownership": re-running this end-to-end, today,
against whatever mix of real/stub files currently exists in data/, is the
daily smoke test referenced in INTERFACE_SPEC.md.
"""
import os

import pandas as pd

DATA_DIR = r"C:\Users\Daniel Loh\Documents\NUS-ISS_EBAC\SPMF\Project\notebooks\optimization_lead\data"


def rough_rank(budget, min_lease_yrs=60, k=5):
    """Naive version: no MIP, no diversity constraint, no goal programming --
    just sort by a simple weighted score and take the top k. Intentionally
    simple; Task 3 replaces this with the real formulation."""
    profiles = pd.read_csv(os.path.join(DATA_DIR, "housing_profiles.csv"))
    pricing = pd.read_csv(os.path.join(DATA_DIR, "pricing_today.csv"))
    avail = pd.read_csv(os.path.join(DATA_DIR, "availability.csv"))

    df = profiles.merge(pricing, on="profile_id").merge(avail, on="profile_id")
    df = df[(df["price_today"] <= budget) & (df["median_remaining_lease"] >= min_lease_yrs)]

    # simple score: cheaper + closer to MRT + more schools + shorter wait = better
    # (all min-max normalised, equal weights -- a deliberately crude stand-in
    # for Task 3's WTP-dollar-denominated objective)
    def norm(s):
        return (s - s.min()) / (s.max() - s.min() + 1e-9)

    df["score"] = (
        (1 - norm(df["price_today"])) * 0.4
        + (1 - norm(df["nearest_mrt_km"])) * 0.2
        + norm(df["schools_within"].fillna(0)) * 0.2
        + (1 - norm(df["expected_wait_months"])) * 0.2
    )
    return df.sort_values("score", ascending=False).head(k)[
        ["profile_id", "town", "flat_type", "storey_band", "price_today", "nearest_mrt_km",
         "schools_within", "expected_wait_months", "score"]
    ]


def pipeline_health_check():
    """Confirms every file INTERFACE_SPEC.md promises actually exists and is
    readable, and flags which ones are still stubs vs real."""
    expected = ["housing_profiles.csv", "pricing_today.csv", "availability.csv",
                "price_forecast.csv", "preferences.json"]
    report = []
    for fname in expected:
        path = os.path.join(DATA_DIR, fname)
        exists = os.path.exists(path)
        is_stub = None
        if exists and fname.endswith(".csv"):
            df = pd.read_csv(path)
            is_stub = "_source" in df.columns and df["_source"].astype(str).str.contains("STUB").any()
        elif exists and fname.endswith(".json"):
            import json
            d = json.load(open(path))
            is_stub = "STUB" in str(d.get("_source", ""))
        report.append({"file": fname, "exists": exists, "is_stub": is_stub})
    return pd.DataFrame(report)


if __name__ == "__main__":
    print("=== Pipeline health check ===")
    print(pipeline_health_check().to_string(index=False))

    print("\n=== Rough ranking (Task 2 -- naive, pre-MIP) ===")
    result = rough_rank(budget=550_000, min_lease_yrs=60, k=5)
    print(result.to_string(index=False))

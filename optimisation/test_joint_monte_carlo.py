# -*- coding: utf-8 -*-
"""
Follow-up to the Forecasting Lead's multitype integration (OPTIMISER_METHODOLOGY_REPORT.md
Sec. 23-24): wiring run_joint_monte_carlo() into monte_carlo.py (Sec. 24) fixes a specific,
previously-flagged gap -- the stand-in simulator drew each shortlisted profile's price path
INDEPENDENTLY, which cannot be right: profiles in the same region/flat-type segment share
real macro drivers (rates, supply), so a bad month for one Woodlands pick is somewhat more
likely to also be a bad month for a same-region Sembawang pick, not an independent
coincidence. The old engine had no way to represent that.

This script demonstrates the gap directly rather than just asserting it exists: compute
each profile's OWN (marginal) success probability under both engines, the NAIVE
"assume independence" joint probability (just the product of marginals -- what anyone
reading only the marginals would implicitly assume), and the ACTUAL joint probability
(all picks succeed in the SAME scenario_id row at once). For the OLD stand-in simulator,
scenario_id never meant the same thing across two different profiles (each profile's
regime draw is its own independent rng.choice() call) -- so its "actual joint" should land
close to the naive product, confirming it was implicitly independent all along. For the
NEW real engine, scenario_id IS the same shared scenario across every profile in the
shortlist (one scenario batch, applied to all) -- so its actual joint should differ from
the naive product whenever regional growth is correlated, which is exactly the fix.
"""
import json
import os

import numpy as np
import pandas as pd

import recommender_v2 as rv2
import monte_carlo as mc

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
N_SCENARIOS = 2000
SEED = 42


def joint_success_rate(scenarios, budget, wait_col_price, wait_col_avail):
    """P(every profile in the shortlist succeeds SIMULTANEOUSLY, scenario by scenario) --
    requires scenario_id to mean the same draw across profiles, which is only true for the
    real joint engine; computed for both here anyway, specifically to show the old
    engine's version is just the naive independent product in disguise."""
    success = scenarios.assign(
        ok=scenarios[wait_col_avail] & (scenarios[wait_col_price] <= budget)
    )
    per_scenario = success.groupby("scenario_id")["ok"].all()  # True iff ALL profiles ok that scenario
    return per_scenario.mean()


def run():
    q = rv2.HouseholdQuery2(budget=600_000, min_lease_yrs=60, k=5, target_mrt_km=0.4,
                            needs_primary_school=True, target_storey="Mid",
                            multipliers={"mrt": 1.5}, name="young family, transit-reliant")
    res = rv2.solve(q)
    shortlist = res["shortlist"]
    print(f"Shortlist: {len(shortlist)} picks, flat_types={sorted(shortlist['flat_type'].unique())}")

    fcast = pd.read_csv(os.path.join(DATA, "price_forecast_live.csv"))

    # OLD: force every profile through the stand-in simulator (bypass the real engine
    # entirely), exactly what every prior Monte Carlo run in this project actually did.
    old_scenarios = mc._run_stub_monte_carlo(shortlist, fcast, n_scenarios=N_SCENARIOS, seed=SEED)
    # NEW: the blended public entry point -- routes 3/4/5 ROOM (all 5 picks here) through
    # the real joint engine automatically.
    new_scenarios = mc.run_monte_carlo(shortlist, fcast, n_scenarios=N_SCENARIOS, seed=SEED)
    print(f"New engine used for: {sorted(new_scenarios['regime'].unique())}")

    rows = []
    for label, scenarios in [("OLD (independent stand-in)", old_scenarios), ("NEW (real joint engine)", new_scenarios)]:
        summary = mc.summarize_strategies(scenarios, budget=q.budget)
        marginal_product = summary["wait_12m_p_success_within_budget"].prod()
        actual_joint = joint_success_rate(scenarios, q.budget, "wait12_price", "wait12_available")
        rows.append({
            "engine": label,
            "mean_marginal_p_success_wait12m": summary["wait_12m_p_success_within_budget"].mean(),
            "naive_independent_joint_p_all5_succeed": marginal_product,
            "actual_joint_p_all5_succeed": actual_joint,
            "gap_vs_naive_pct_points": (actual_joint - marginal_product) * 100,
        })
        print(f"\n{label}:")
        print(summary[["profile_id", "wait_12m_p_success_within_budget"]].to_string(index=False))
        print(f"  Naive independent product (all 5 succeed): {marginal_product*100:.2f}%")
        print(f"  Actual joint (all 5 succeed, same scenario): {actual_joint*100:.2f}%")

    out = pd.DataFrame(rows)
    print("\n", out.round(4).to_string(index=False))
    out.to_json(os.path.join(DATA, "joint_monte_carlo_test.json"), orient="records", indent=2)
    print("\nWrote data/joint_monte_carlo_test.json")
    return out


if __name__ == "__main__":
    run()

# -*- coding: utf-8 -*-
"""
Task 5a: formalises the recommender's simple deterministic budget rule
("budget >= upper forecast price", a fixed-percentile proxy) into an
explicit SCENARIO-BASED CHANCE CONSTRAINT:

    P(simulated price at household's horizon <= budget) >= 0.90

evaluated directly from Monte Carlo price draws (reusing monte_carlo.py's
`simulate_price`) rather than relying on the forecast's point percentile
bound. This is the standard scenario-approximation to a chance constraint:
a profile is "chance-feasible" if at least 90% of its simulated price
scenarios clear the budget.
"""
import numpy as np
import pandas as pd

from monte_carlo import REGIMES, simulate_price


def price_only_scenarios(df: pd.DataFrame, fcast: pd.DataFrame, horizon_months: int,
                          n_scenarios=500, seed=11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    regime_names = list(REGIMES.keys())
    regime_probs = [REGIMES[r]["prob"] for r in regime_names]
    fcast_idx = fcast.set_index(["town", "flat_type", "horizon_months"])

    rows = []
    for _, row in df.iterrows():
        key = (row["town"], row["flat_type"], horizon_months)
        if key not in fcast_idx.index:
            continue
        f = fcast_idx.loc[key]
        regimes_drawn = rng.choice(regime_names, size=n_scenarios, p=regime_probs)
        prices = np.array([
            simulate_price(row["price_today"], f["growth_factor"], f["growth_factor_lower"],
                            f["growth_factor_upper"], REGIMES[r], rng)
            for r in regimes_drawn
        ])
        rows.append({"profile_id": row["profile_id"], "prices": prices})
    return rows


def chance_feasible_profiles(df: pd.DataFrame, fcast: pd.DataFrame, budget: float,
                              horizon_months: int, alpha=0.90, n_scenarios=500, seed=11) -> pd.DataFrame:
    """Returns df filtered to profiles where P(price <= budget) >= alpha,
    with the empirical probability attached for transparency."""
    scenario_rows = price_only_scenarios(df, fcast, horizon_months, n_scenarios, seed)
    probs = {r["profile_id"]: float(np.mean(r["prices"] <= budget)) for r in scenario_rows}
    out = df.copy()
    out["p_within_budget"] = out["profile_id"].map(probs)
    out["chance_feasible"] = out["p_within_budget"] >= alpha
    # also report the deterministic-rule comparison for the same profiles
    return out


if __name__ == "__main__":
    import os
    from recommender import load_candidate_table, attach_forecast, compute_wtp_value, compute_goal_deviations_sgd, HouseholdQuery

    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    df, fcast, prefs = load_candidate_table()
    df = attach_forecast(df, fcast, horizon_months=12)

    budget = 550_000
    checked = chance_feasible_profiles(df, fcast, budget=budget, horizon_months=12, alpha=0.90, n_scenarios=500)

    deterministic_feasible = (checked["price_upper"] <= budget).sum()
    chance_feasible = checked["chance_feasible"].sum()
    print(f"Budget=${budget:,}, horizon=12mo, alpha=90%")
    print(f"Deterministic rule (price_upper<=budget) feasible: {deterministic_feasible} / {len(checked)}")
    print(f"Chance-constrained (P(price<=budget)>=90%) feasible: {chance_feasible} / {len(checked)}")

    # where do the two rules disagree?
    checked["deterministic_feasible"] = checked["price_upper"] <= budget
    disagree = checked[checked["deterministic_feasible"] != checked["chance_feasible"]]
    print(f"\nProfiles where the two rules disagree: {len(disagree)}")
    if len(disagree):
        print(disagree[["profile_id", "price_today", "price_upper", "p_within_budget",
                         "deterministic_feasible", "chance_feasible"]].head(10).to_string(index=False))

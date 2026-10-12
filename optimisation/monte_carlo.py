# -*- coding: utf-8 -*-
"""
Task 4: Monte Carlo engine -- "simulates buy-now vs wait-6/12-months outcomes
for each shortlisted profile. It draws price paths from SARIMAX under
interest-rate and supply scenarios, and combines them with survival-based
availability."

Runs today on a STAND-IN SIMULATOR (price paths synthesised from the stub
forecast's growth_factor/bounds + 3 macro regimes approximating "interest-rate
and supply scenarios"), clearly swappable for the real SARIMAX scenario
generator once it lands (14 Oct) -- see `simulate_price()`'s docstring for
the swap point.
"""
import os

import numpy as np
import pandas as pd

DATA_DIR = r"C:\Users\Daniel Loh\Documents\NUS-ISS_EBAC\SPMF\Project\notebooks\optimization_lead\data"

# Stand-in macro regimes: (probability, price-growth multiplier on the mean,
# volatility multiplier, availability multiplier). Approximates "interest-rate
# and supply scenarios" until the Forecasting Lead's real regressor-driven
# SARIMAX scenarios (interest rate, MOP-supply, cooling-measure dummies) land.
REGIMES = {
    "low_rate_high_supply": {"prob": 0.25, "growth_shift": -0.02, "vol_mult": 1.1, "avail_mult": 1.15},
    "base": {"prob": 0.50, "growth_shift": 0.00, "vol_mult": 1.0, "avail_mult": 1.0},
    "high_rate_low_supply": {"prob": 0.25, "growth_shift": 0.03, "vol_mult": 1.2, "avail_mult": 0.85},
}


def implied_sigma(lower_factor, upper_factor, z=1.2816):
    """Back out a normal-approx sigma from an ~80% CI (10th-90th pct bounds)."""
    return (upper_factor - lower_factor) / (2 * z)


def simulate_price(price_today, growth_factor, growth_lower, growth_upper, regime, rng):
    """SWAP POINT: once the Forecasting Lead's real SARIMAX scenario paths
    exist, replace this function body with a draw from their simulated
    distribution (e.g. bootstrap residuals from the fitted SARIMAX model)
    instead of this stand-in normal approximation."""
    sigma = implied_sigma(growth_lower, growth_upper) * regime["vol_mult"]
    mean = growth_factor + regime["growth_shift"]
    draw = rng.normal(mean, sigma)
    return price_today * max(draw, 0.5)  # floor to avoid nonsensical negative/near-zero prices


def simulate_availability(survival_prob, regime, rng):
    p = np.clip(survival_prob * regime["avail_mult"], 0, 0.99)
    return rng.random() < p


def run_monte_carlo(shortlist: pd.DataFrame, fcast: pd.DataFrame, n_scenarios=2000, seed=42):
    """For each shortlisted profile, simulate n_scenarios outcomes for
    buy-now / wait-6mo / wait-12mo and return a long-format scenario table
    plus a summary table."""
    rng = np.random.default_rng(seed)
    regime_names = list(REGIMES.keys())
    regime_probs = [REGIMES[r]["prob"] for r in regime_names]

    fcast_idx = fcast.set_index(["town", "flat_type", "horizon_months"])

    scenario_rows = []
    for _, row in shortlist.iterrows():
        key6 = (row["town"], row["flat_type"], 6)
        key12 = (row["town"], row["flat_type"], 12)
        if key6 not in fcast_idx.index or key12 not in fcast_idx.index:
            continue
        f6, f12 = fcast_idx.loc[key6], fcast_idx.loc[key12]

        # "buy now": price is certain (price_today); success = can a matching
        # flat be secured within a realistic house-hunting window (~6 weeks,
        # not "a new transaction lands in calendar month 1" -- a household
        # searches the active listing pool, it doesn't wait for one fresh
        # transaction event, so the window should reflect typical search
        # duration, not the raw transaction-arrival rate over 1 month)
        immediate_rate = -np.log(max(1 - row.get("survival_prob_6m", 0.3), 1e-6)) / 6
        p_immediate = 1 - np.exp(-immediate_rate * 1.5)

        regimes_drawn = rng.choice(regime_names, size=n_scenarios, p=regime_probs)
        for s in range(n_scenarios):
            regime = REGIMES[regimes_drawn[s]]
            price_6m = simulate_price(row["price_today"], f6["growth_factor"],
                                       f6["growth_factor_lower"], f6["growth_factor_upper"], regime, rng)
            price_12m = simulate_price(row["price_today"], f12["growth_factor"],
                                        f12["growth_factor_lower"], f12["growth_factor_upper"], regime, rng)
            avail_6m = simulate_availability(row.get("survival_prob_6m", 0.3), regime, rng)
            avail_12m = simulate_availability(row.get("survival_prob_12m", 0.5), regime, rng)
            avail_now = rng.random() < p_immediate

            scenario_rows.append({
                "profile_id": row["profile_id"], "scenario_id": s, "regime": regimes_drawn[s],
                "buy_now_price": row["price_today"], "buy_now_available": avail_now,
                "wait6_price": price_6m, "wait6_available": avail_6m,
                "wait12_price": price_12m, "wait12_available": avail_12m,
            })

    scenarios = pd.DataFrame(scenario_rows)
    return scenarios


def summarize_strategies(scenarios: pd.DataFrame, budget: float) -> pd.DataFrame:
    rows = []
    for pid, g in scenarios.groupby("profile_id"):
        row = {"profile_id": pid, "n_scenarios": len(g)}
        for strat, price_col, avail_col in [("buy_now", "buy_now_price", "buy_now_available"),
                                              ("wait_6m", "wait6_price", "wait6_available"),
                                              ("wait_12m", "wait12_price", "wait12_available")]:
            success = g[avail_col] & (g[price_col] <= budget)
            row[f"{strat}_p_success_within_budget"] = success.mean()
            row[f"{strat}_expected_price_if_success"] = g.loc[success, price_col].mean() if success.any() else np.nan
            row[f"{strat}_p_over_budget_given_available"] = (g[avail_col] & (g[price_col] > budget)).sum() / max(g[avail_col].sum(), 1)
        rows.append(row)
    summary = pd.DataFrame(rows)

    def best_strategy(r):
        opts = {"buy_now": r["buy_now_p_success_within_budget"],
                "wait_6m": r["wait_6m_p_success_within_budget"],
                "wait_12m": r["wait_12m_p_success_within_budget"]}
        return max(opts, key=opts.get)
    summary["recommended_strategy"] = summary.apply(best_strategy, axis=1)
    return summary


if __name__ == "__main__":
    from recommender import HouseholdQuery, solve_recommender

    q = HouseholdQuery(budget=550_000, min_lease_yrs=60, horizon_months=12, k=5,
                        target_mrt_km=0.5, target_schools_within=5, target_storey="High")
    res = solve_recommender(q)
    print("Shortlist:", len(res["shortlist"]), "profiles")

    fcast = pd.read_csv(os.path.join(DATA_DIR, "price_forecast.csv"))
    scenarios = run_monte_carlo(res["shortlist"], fcast, n_scenarios=2000)
    print("Scenario table:", scenarios.shape)

    summary = summarize_strategies(scenarios, budget=q.budget)
    print(summary[["profile_id", "buy_now_p_success_within_budget", "wait_6m_p_success_within_budget",
                    "wait_12m_p_success_within_budget", "recommended_strategy"]].to_string(index=False))

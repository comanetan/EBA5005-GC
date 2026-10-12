# -*- coding: utf-8 -*-
"""
Task 5b: parametric sensitivity sweeps over budget and minimum lease, giving
the marginal value of each constraint (PPA Day 2, implemented as re-solve
sweeps rather than LP duals since the recommender is a MIP with the diversity
constraint). Includes an automated MONOTONICITY check -- the proposal's own
evaluation criterion: "more budget never makes the result worse."
"""
import numpy as np
import pandas as pd

from recommender import HouseholdQuery, solve_recommender


def budget_sweep(base_query: HouseholdQuery, budgets, verbose=False):
    rows = []
    for b in budgets:
        q = HouseholdQuery(**{**base_query.__dict__, "budget": b})
        res = solve_recommender(q)
        obj = res["shortlist"]["net_objective_value"].sum() if len(res["shortlist"]) else np.nan
        rows.append({
            "budget": b, "status": res["status"], "n_candidates": res["n_candidates"],
            "n_selected": len(res["shortlist"]), "total_objective_value": obj,
            "shortlist_profile_ids": ";".join(res["shortlist"]["profile_id"].tolist()) if len(res["shortlist"]) else "",
        })
        if verbose:
            print(f"  budget=${b:,}: n_selected={rows[-1]['n_selected']}, objective=${obj:,.0f}" if pd.notna(obj) else f"  budget=${b:,}: infeasible")
    return pd.DataFrame(rows)


def lease_sweep(base_query: HouseholdQuery, min_leases, verbose=False):
    rows = []
    for ml in min_leases:
        q = HouseholdQuery(**{**base_query.__dict__, "min_lease_yrs": ml})
        res = solve_recommender(q)
        obj = res["shortlist"]["net_objective_value"].sum() if len(res["shortlist"]) else np.nan
        rows.append({
            "min_lease_yrs": ml, "status": res["status"], "n_candidates": res["n_candidates"],
            "n_selected": len(res["shortlist"]), "total_objective_value": obj,
        })
        if verbose:
            print(f"  min_lease={ml}yrs: n_candidates={rows[-1]['n_candidates']}, objective=${obj:,.0f}" if pd.notna(obj) else f"  min_lease={ml}yrs: infeasible")
    return pd.DataFrame(rows)


def check_monotonicity(sweep_df: pd.DataFrame, value_col: str, param_col: str, direction="increasing"):
    """Returns (is_monotonic, violations_df). For budget: objective should be
    non-decreasing as budget increases. For min_lease: objective should be
    non-increasing as the constraint tightens (min_lease increases)."""
    df = sweep_df.sort_values(param_col).dropna(subset=[value_col]).reset_index(drop=True)
    diffs = df[value_col].diff()
    if direction == "increasing":
        violations = df[diffs < -1e-6]
    else:
        violations = df[diffs > 1e-6]
    return len(violations) == 0, violations


def marginal_value(sweep_df: pd.DataFrame, value_col: str, param_col: str):
    """Shadow-price-like marginal value: d(objective)/d(param), via finite
    differences along the sweep grid."""
    df = sweep_df.sort_values(param_col).dropna(subset=[value_col]).reset_index(drop=True)
    df["marginal_value"] = df[value_col].diff() / df[param_col].diff()
    return df


if __name__ == "__main__":
    base = HouseholdQuery(budget=500_000, min_lease_yrs=60, horizon_months=12, k=5,
                           target_mrt_km=0.5, target_schools_within=5, target_storey="High")

    print("=== Budget sweep ===")
    budgets = list(range(350_000, 900_001, 50_000))
    bsweep = budget_sweep(base, budgets, verbose=True)
    ok, viol = check_monotonicity(bsweep, "total_objective_value", "budget", direction="increasing")
    print(f"\nMonotonicity (objective non-decreasing in budget): {'PASS' if ok else 'FAIL'}")
    if not ok:
        print(viol)

    print("\n=== Min-lease sweep ===")
    leases = list(range(40, 96, 5))
    lsweep = lease_sweep(base, leases, verbose=True)
    ok2, viol2 = check_monotonicity(lsweep, "total_objective_value", "min_lease_yrs", direction="decreasing")
    print(f"\nMonotonicity (objective non-increasing as min_lease tightens): {'PASS' if ok2 else 'FAIL'}")
    if not ok2:
        print(viol2)

    mv = marginal_value(bsweep, "total_objective_value", "budget")
    print("\nMarginal value of budget ($ objective gain per $ of extra budget), by segment:")
    print(mv[["budget", "total_objective_value", "marginal_value"]].to_string(index=False))

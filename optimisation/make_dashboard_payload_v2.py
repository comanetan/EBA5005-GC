# -*- coding: utf-8 -*-
"""
Regenerates data/dashboard_payload_example.json in the CURRENT v2 schema.

The version this replaced was written by the v1 notebook (build_notebook.py)
and never updated: its profile_id ("HOUGANG::2ROOM::Mid") is missing the MRT
band v2 added ("HOUGANG::2ROOM::Mid::Near"), and it only carried the
shortlist, not the sensitivity_results / montecarlo_scenarios INTERFACE_SPEC
section 5 promises the Dashboard consumer. This script builds all three
pieces from the real v2 pipeline (profiles -> solve -> sweep -> Monte Carlo)
for one representative household, nested under the household's own query --
exactly the dashboard_payload.json contract.

n_scenarios is kept small (20, vs. ~3000 in the real notebook run) purely so
this EXAMPLE file stays small; a real per-request payload would use more.
"""
import json
import os

import numpy as np
import pandas as pd

import recommender_v2 as rv2
import sensitivity_v2 as sv2
import empirical_bands as eb
import monte_carlo as mc

DATA = rv2.DATA


def default_converter(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    raise TypeError(f"Not JSON serialisable: {type(o)}")


def build_example_payload():
    base = dict(budget=600_000, min_lease_yrs=60, k=5, flat_types=["3 ROOM", "4 ROOM"],
                target_mrt_km=0.4, needs_primary_school=True, target_storey="Mid", name="example household")
    overrides = rv2.preference_overrides_from_file()
    query = rv2.HouseholdQuery2(**{**base, **overrides})
    res = rv2.solve(query)
    sl = res["shortlist"]

    shortlist_records = [{
        "household_id": query.name, "profile_id": r.profile_id, "town": r.town, "flat_type": r.flat_type,
        "storey_band": r.storey_band, "price_today": r.price_today, "price_upper_forecast": r.price_upper,
        "wtp_surplus": r.surplus, "goal_deviation_total": r.goal_deviation_total, "rank": r.rank,
    } for r in sl.itertuples()]

    tx = __import__("block_analysis").load_transactions_with_access()
    tx = tx[tx["flat_type"] != "MULTI-GENERATION"]
    bands12 = eb.empirical_growth_bands(tx, horizon=12)
    budget_sweep = sv2.sweep(base, "budget", range(450_000, 800_001, 50_000), upper_factors=bands12)
    lease_sweep = sv2.sweep(base, "min_lease_yrs", range(40, 91, 10), upper_factors=bands12)
    sens_rows = []
    for sweep_df, param in [(budget_sweep, "budget"), (lease_sweep, "min_lease_yrs")]:
        for r in sweep_df.itertuples():
            sens_rows.append({
                "swept_param": param, "budget": getattr(r, "budget", base["budget"]),
                "min_lease_yrs": getattr(r, "min_lease_yrs", base["min_lease_yrs"]),
                "objective_value": None if pd.isna(r.objective) else r.objective,
                "n_feasible_profiles": r.n_candidates,
                "shortlist_profile_ids": r.picks.split(";") if r.picks else [],
            })

    bands6 = eb.empirical_growth_bands(tx, horizon=6)
    fc = eb.fcast_for_shortlist(sl, bands6, bands12)
    scenarios = mc.run_monte_carlo(sl, fc, n_scenarios=20, seed=42)
    mc_long = []
    for r in scenarios.itertuples():
        for horizon, price_col, avail_col in [(0, "buy_now_price", "buy_now_available"),
                                               (6, "wait6_price", "wait6_available"),
                                               (12, "wait12_price", "wait12_available")]:
            mc_long.append({"profile_id": r.profile_id, "scenario_id": r.scenario_id, "regime": r.regime,
                            "horizon_months": horizon, "simulated_price": getattr(r, price_col),
                            "matched_available": getattr(r, avail_col)})

    payload = {
        "household_query": {
            "budget": query.budget, "min_lease_yrs": query.min_lease_yrs, "horizon_months": query.horizon_months,
            "k": query.k, "target_mrt_km": query.target_mrt_km, "needs_primary_school": query.needs_primary_school,
            "school_goal": query.school_goal, "target_storey": query.target_storey,
            "target_wait_months": query.target_wait_months, "target_essentials": query.target_essentials,
            "flat_types": query.flat_types, "towns_exclude": query.towns_exclude, "multipliers": query.multipliers,
        },
        "shortlist": shortlist_records,
        "sensitivity_results": sens_rows,
        "montecarlo_scenarios": mc_long,
        "_schema_version": "v2", "_profile_id_format": "{TOWN}::{FLATTYPE}::{StoreyBand}::{MRTBand}",
    }
    return payload


if __name__ == "__main__":
    payload = build_example_payload()
    out_path = os.path.join(DATA, "dashboard_payload_example.json")
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=default_converter)
    print(f"Wrote {out_path}")
    print(f"  shortlist: {len(payload['shortlist'])} rows | sensitivity_results: {len(payload['sensitivity_results'])} rows "
          f"| montecarlo_scenarios: {len(payload['montecarlo_scenarios'])} rows")

# -*- coding: utf-8 -*-
"""
Item 5 of the "other tests" follow-up list (OPTIMISER_METHODOLOGY_REPORT.md Sec. 19):
we've only ever tested ONE fixed preemptive priority order (DEFAULT_PRIORITY =
[dev_mrt, dev_school, dev_storey, dev_wait, dev_essentials]). solve_preemptive()
accepts any ordering of the 5 goals -- how much does the actual recommendation
change across all of them, not just the one shipped as the default?

Exhaustive, not a sample: 5 goals -> 5! = 120 permutations, each needing n+1=6 fresh
0-1 IPs solved (solve_preemptive's own staged construction) -- 720 solves total,
fully tractable (each IP is small/fast, confirmed in sensitivity_v2.py's own grid
sweeps and the GA-vs-CBC benchmark in OPTIMISER_METHODOLOGY_REPORT.md Sec. 7.2).
"""
import itertools
import json
import os

import recommender_v2 as rv2
from backtest_v2 import EXTENDED_ARCHETYPES

HERE = os.path.dirname(os.path.abspath(__file__))

GOALS = list(rv2.DEFAULT_PRIORITY)  # ["dev_mrt", "dev_school", "dev_storey", "dev_wait", "dev_essentials"]

# The report's own running test household, plus every backtest archetype -- so a null
# result on one household (no goal conflict -> order can't matter) isn't mistaken for
# "order never matters": item 1 (Sec. 17) already showed 3/4 archetypes have a real
# weighted-sum-vs-preemptive gap, i.e. genuine goal conflict, which is exactly where
# priority order SHOULD start to matter.
HOUSEHOLDS = {
    "Report test household": dict(budget=750_000, min_lease_yrs=60, k=3, target_mrt_km=0.5,
                                    multipliers={"mrt": 1.5}, needs_primary_school=True),
    **{f"Archetype: {name}": {**a, "k": 5} for name, a in EXTENDED_ARCHETYPES.items()},
}


def run_household(label, params):
    q = rv2.HouseholdQuery2(name=label, **params)
    rw = rv2.solve(q)
    if rw["status"] != "Optimal":
        return None
    ws_picks = tuple(sorted(rw["shortlist"]["profile_id"]))
    ws_objective = rw["objective"]

    rows = []
    for perm in itertools.permutations(GOALS):
        rp = rv2.solve_preemptive(q, priority=list(perm))
        if rp["status"] != "Optimal":
            rows.append({"priority": list(perm), "status": rp["status"], "objective": None, "picks": None})
            continue
        picks = tuple(sorted(rp["shortlist"]["profile_id"]))
        rows.append({
            "priority": list(perm), "status": rp["status"],
            "objective": round(rp["objective"], 2), "picks": list(picks),
            "matches_ws_picks": picks == ws_picks,
            "first_priority": perm[0],
        })
    return {"household": params, "ws_objective": ws_objective, "ws_picks": list(ws_picks), "rows": rows}


def summarise(label, result):
    rows = result["rows"]
    objs = [r["objective"] for r in rows if r["objective"] is not None]
    picksets = {tuple(r["picks"]) for r in rows if r["picks"] is not None}
    default_order = tuple(GOALS)
    default_row = next(r for r in rows if tuple(r["priority"]) == default_order)
    n_match_ws = sum(1 for r in rows if r.get("matches_ws_picks"))
    print(f"=== {label} ===")
    print(f"  Weighted-sum objective={result['ws_objective']:,.2f}  "
          f"Preemptive (default order) objective={default_row['objective']:,.2f}")
    print(f"  Across 120 orderings: objective range [{min(objs):,.2f}, {max(objs):,.2f}] "
          f"(spread ${max(objs)-min(objs):,.2f}), {len(picksets)} distinct pick-set(s), "
          f"{n_match_ws}/120 match weighted-sum exactly")
    return {"label": label, "n_distinct_picksets": len(picksets), "spread": max(objs) - min(objs),
            "n_match_ws": n_match_ws, "obj_min": min(objs), "obj_max": max(objs)}


if __name__ == "__main__":
    all_results = {}
    summaries = []
    for label, params in HOUSEHOLDS.items():
        result = run_household(label, params)
        if result is None:
            print(f"=== {label} === INFEASIBLE, skipped")
            continue
        all_results[label] = result
        summaries.append(summarise(label, result))
        print()

    print("Summary across all households tested (120 orderings each):")
    print(f"{'Household':<34} {'Distinct picksets':>18} {'Objective spread':>18} {'Match WS':>10}")
    for s in summaries:
        print(f"{s['label']:<34} {s['n_distinct_picksets']:>18} {s['spread']:>18,.2f} {s['n_match_ws']:>10}/120")

    with open(os.path.join(HERE, "data", "preemptive_priority_sensitivity.json"), "w") as f:
        json.dump(all_results, f, indent=2)
    print("\nWrote data/preemptive_priority_sensitivity.json")

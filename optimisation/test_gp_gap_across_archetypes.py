# -*- coding: utf-8 -*-
"""
Item 1 of the "other tests" follow-up list (OPTIMISER_METHODOLOGY_REPORT.md Sec. 17):
is the weighted-sum-vs-preemptive GP gap, reported throughout this project on ONE
illustrative household, a general phenomenon or a cherry-picked example?

Runs recommender_v2.solve() (2b) and solve_preemptive() (2c) on all 4 backtest
archetypes (backtest_v2.EXTENDED_ARCHETYPES) at k=5, today's live data, default
preemptive priority order [dev_mrt, dev_school, dev_storey, dev_wait, dev_essentials]
-- the same settings and priority order already shipped as the product default.

Scope note: this tests the CURRENT, fully-corrected pipeline state across households,
not each of the 5 historical data-correction stages re-run per archetype -- there is
no runnable snapshot of this pipeline's code+data at each of those past states (they
were never independently git-tagged), so re-deriving all 5x4=20 combinations isn't
feasible. What IS feasible, and is what this script does, directly answers the
"cherry-picked or general" question for today's state.
"""
import json
import os

import recommender_v2 as rv2
from backtest_v2 import EXTENDED_ARCHETYPES

HERE = os.path.dirname(os.path.abspath(__file__))
K = 5


def run():
    rows = []
    for name, a in EXTENDED_ARCHETYPES.items():
        q = rv2.HouseholdQuery2(k=K, name=name, **a)
        rw = rv2.solve(q)
        rp = rv2.solve_preemptive(q)
        if rw["status"] != "Optimal" or rp["status"] != "Optimal":
            rows.append({"archetype": name, "status_ws": rw["status"], "status_pe": rp["status"],
                         "gap": None, "shared_picks": None})
            continue
        ws_picks = set(rw["shortlist"]["profile_id"])
        pe_picks = set(rp["shortlist"]["profile_id"])
        gap = rw["objective"] - rp["objective"]
        rows.append({
            "archetype": name,
            "status_ws": rw["status"], "status_pe": rp["status"],
            "ws_objective": round(rw["objective"], 2), "pe_objective": round(rp["objective"], 2),
            "gap": round(gap, 2),
            "n_picks": K, "shared_picks": len(ws_picks & pe_picks),
            "ws_picks": sorted(ws_picks), "pe_picks": sorted(pe_picks),
        })
    return rows


if __name__ == "__main__":
    rows = run()
    print(f"{'Archetype':<34} {'WS obj':>12} {'PE obj':>12} {'Gap':>12} {'Shared/5':>9}")
    for r in rows:
        if r["gap"] is None:
            print(f"{r['archetype']:<34} INFEASIBLE (ws={r['status_ws']}, pe={r['status_pe']})")
            continue
        print(f"{r['archetype']:<34} {r['ws_objective']:>12,.2f} {r['pe_objective']:>12,.2f} {r['gap']:>12,.2f} {r['shared_picks']:>9}/{r['n_picks']}")

    gaps = [r["gap"] for r in rows if r["gap"] is not None]
    print()
    print(f"n={len(gaps)} archetypes with a feasible solve")
    print(f"gap: min={min(gaps):,.2f}  median={sorted(gaps)[len(gaps)//2]:,.2f}  max={max(gaps):,.2f}  mean={sum(gaps)/len(gaps):,.2f}")
    n_zero = sum(1 for g in gaps if abs(g) < 1.0)
    print(f"archetypes with ~$0 gap (full agreement): {n_zero}/{len(gaps)}")

    with open(os.path.join(HERE, "data", "gp_gap_across_archetypes.json"), "w") as f:
        json.dump(rows, f, indent=2)
    print("\nWrote data/gp_gap_across_archetypes.json")

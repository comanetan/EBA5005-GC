# -*- coding: utf-8 -*-
"""
Publishes outputs/shortlist.csv -- my deliverable back to the shared pipeline contract
(README.md on main: "household_id, rank, profile_id, ... | Optimisation | to do").

Runs the production recommender (recommender_v2.solve(), the default weighted-sum 0-1 IP,
live=True so today's real pricing/availability/forecast apply) for each of this project's
own named household archetypes (backtest_v2.EXTENDED_ARCHETYPES) -- the same 4 personas
already used throughout the backtest and the Word report, not ad hoc examples.
"""
import os

import pandas as pd

import recommender_v2 as rv2
from backtest_v2 import EXTENDED_ARCHETYPES

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "outputs")

SHORTLIST_COLS = ["household_id", "rank", "profile_id", "town", "flat_type", "storey_band", "mrt_band",
                   "price_today", "expected_wait_months", "surplus", "net_objective_value"]


def build_shortlist(k=5):
    rows = []
    for household_id, a in EXTENDED_ARCHETYPES.items():
        q = rv2.HouseholdQuery2(k=k, name=household_id, **a)
        r = rv2.solve(q)
        if r["shortlist"].empty:
            print(f"  {household_id}: INFEASIBLE, skipped")
            continue
        sl = r["shortlist"].copy()
        sl["household_id"] = household_id
        rows.append(sl[SHORTLIST_COLS])
        print(f"  {household_id}: {len(sl)} picks, objective ${r['objective']:,.2f}")
    out = pd.concat(rows, ignore_index=True)
    os.makedirs(OUT, exist_ok=True)
    out.to_csv(os.path.join(OUT, "shortlist.csv"), index=False)
    return out


if __name__ == "__main__":
    print("Building outputs/shortlist.csv from today's live recommender, "
          f"{len(EXTENDED_ARCHETYPES)} household archetypes:")
    out = build_shortlist()
    print(f"\nWrote outputs/shortlist.csv: {len(out)} rows, {out['household_id'].nunique()} households")
    print(out.round(2).to_string(index=False))

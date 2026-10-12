# -*- coding: utf-8 -*-
"""
Sensitivity analysis for the block-informed recommender (v2):
  - budget & minimum-lease sweeps (+ monotonicity checks, as in v1)
  - MRT preference sweep: how the shortlist's MRT-band mix shifts as the
    household values MRT access more (proposal's GP evaluation criterion:
    "shortlists change sensibly as preferences are varied")
  - "price of insisting on Near-MRT": objective lost by hard-filtering to
    Near/Mid bands -- only expressible now that profiles carry an MRT band
"""
import numpy as np
import pandas as pd

import recommender_v2 as rv2


def _q(base: dict, **over):
    return rv2.HouseholdQuery2(**{**base, **over})


def _summ(res):
    sl = res["shortlist"]
    base = {"n_candidates": res["n_candidates"], "n_feasible_towns": res.get("n_feasible_towns", 0),
            "k_satisfied": res.get("k_satisfied", False)}
    if sl.empty:
        return {"objective": np.nan, **base, "share_near": np.nan,
                "median_pick_mrt_km": np.nan, "mean_pick_price": np.nan, "picks": ""}
    # objective only comparable across runs when the full k was achievable
    return {"objective": res["objective"] if res.get("k_satisfied") else np.nan, **base,
            "share_near": (sl["mrt_band"] == "Near").mean(), "median_pick_mrt_km": sl["dist_mrt_exit_km_p50"].median(),
            "mean_pick_price": sl["price_today"].mean(), "picks": ";".join(sl["profile_id"])}


def sweep(base: dict, param: str, values, profiles=None, upper_factors=None):
    rows = []
    for v in values:
        r = rv2.solve(_q(base, **{param: v}), profiles=profiles, upper_factors=upper_factors)
        rows.append({param: v, **_summ(r)})
    return pd.DataFrame(rows)


def mrt_preference_sweep(base: dict, multipliers=(0.25, 0.5, 1.0, 1.5, 2.0, 3.0), profiles=None, upper_factors=None):
    rows = []
    for m in multipliers:
        mult = {**base.get("multipliers", {}), "mrt": m}
        r = rv2.solve(_q(base, multipliers=mult), profiles=profiles, upper_factors=upper_factors)
        sl = r["shortlist"]
        mix = sl["mrt_band"].value_counts(normalize=True) if not sl.empty else pd.Series(dtype=float)
        rows.append({"mrt_multiplier": m, "share_Near": mix.get("Near", 0), "share_Mid": mix.get("Mid", 0),
                     "share_Far": mix.get("Far", 0), **{k: v for k, v in _summ(r).items() if k != "share_near"}})
    return pd.DataFrame(rows)


def price_of_insisting(base: dict, profiles=None, upper_factors=None):
    rows = []
    for band in [None, "Mid", "Near"]:
        r = rv2.solve(_q(base, max_mrt_band=band), profiles=profiles, upper_factors=upper_factors)
        rows.append({"hard_mrt_filter": band or "none (soft goal only)", **_summ(r)})
    df = pd.DataFrame(rows)
    df["objective_lost_vs_unconstrained"] = df["objective"].iloc[0] - df["objective"]
    df["extra_price_vs_unconstrained"] = df["mean_pick_price"] - df["mean_pick_price"].iloc[0]
    return df


def monotonic(df, value_col, param_col, increasing=True):
    d = df.sort_values(param_col).dropna(subset=[value_col])
    diffs = d[value_col].diff().dropna()
    bad = (diffs < -1e-6) if increasing else (diffs > 1e-6)
    return not bad.any(), d[bad.reindex(d.index, fill_value=False)]


if __name__ == "__main__":
    from block_analysis import load_transactions_with_access
    from empirical_bands import empirical_growth_bands
    tx = load_transactions_with_access(); tx = tx[tx["flat_type"] != "MULTI-GENERATION"]
    bands = empirical_growth_bands(tx)
    base = dict(budget=600_000, min_lease_yrs=60, k=5, flat_types=["3 ROOM", "4 ROOM"], target_mrt_km=0.5,
                multipliers={"mrt": 1.0})
    b = sweep(base, "budget", range(400_000, 900_001, 50_000), upper_factors=bands)
    ok, _ = monotonic(b, "objective", "budget", True)
    print(b[["budget", "objective", "n_candidates", "n_feasible_towns", "k_satisfied", "share_near", "median_pick_mrt_km"]].round(2).to_string(index=False))
    print("budget monotonic:", ok)
    l = sweep(base, "min_lease_yrs", range(40, 96, 5), upper_factors=bands)
    ok2, _ = monotonic(l, "objective", "min_lease_yrs", False)
    print("lease monotonic:", ok2)
    print(mrt_preference_sweep(base, upper_factors=bands).round(3).drop(columns="picks").to_string(index=False))
    print(price_of_insisting(base, upper_factors=bands).round(2).drop(columns="picks").to_string(index=False))

# -*- coding: utf-8 -*-
"""
Walk-forward backtest: v2 (block-informed) vs v1 (town-level) vs naive
"cheapest towns", across multiple cutoffs x household archetypes.

At each cutoff C, profiles AND the hedonic valuation are rebuilt using only
transactions <= C. Each pick is then scored against what actually happened
12 months later (window C+11 .. C+13 months):
  - within_budget      : realised median price of the pick's cell <= budget (proposal's metric)
  - matched_sale_seen  : did any matching sale occur in that window at all?
  - realised_cell_cv   : price dispersion a buyer of that profile actually faced
  - pick_mrt_km        : how close to MRT the pick's blocks actually are
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from block_analysis import load_transactions_with_access, network_as_of  # noqa: E402
from housing_profiles_v2 import build_profiles_v2  # noqa: E402
import recommender_v2 as rv2  # noqa: E402
import backtest as bt1  # noqa: E402

CUTOFFS = ["2023-01-01", "2023-07-01", "2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01"]

ARCHETYPES = {
    "Young couple, transit-reliant": dict(budget=550_000, min_lease_yrs=60, flat_types=["3 ROOM", "4 ROOM"],
                                           target_mrt_km=0.4, multipliers={"mrt": 1.5}),
    "Family, needs primary school": dict(budget=750_000, min_lease_yrs=65, flat_types=["4 ROOM", "5 ROOM"],
                                          target_mrt_km=0.6, needs_primary_school=True),
    "Budget-first, car owner": dict(budget=450_000, min_lease_yrs=55, flat_types=None,
                                     target_mrt_km=1.0, multipliers={"mrt": 0.5}, target_essentials=3.0),
}

# EXTENDED set (2026-10-08): more cutoffs (quarterly instead of semi-annual) and a 4th,
# deliberately different archetype (small flat, low storey, no school need), added purely
# to tighten the backtest's confidence intervals -- same methodology, more observations.
EXTENDED_CUTOFFS = sorted(CUTOFFS + ["2023-04-01", "2023-10-01", "2024-04-01", "2024-10-01", "2025-04-01"])

EXTENDED_ARCHETYPES = {
    **ARCHETYPES,
    "Retiree, downsizing, low storey": dict(budget=500_000, min_lease_yrs=50, flat_types=["2 ROOM", "3 ROOM"],
                                            target_mrt_km=0.8, target_storey="Low", multipliers={"mrt": 0.7}),
}


def wilson_ci(successes, n, z=1.96):
    """95% Wilson score interval for a proportion -- more reliable than the normal
    approximation at the sample sizes this backtest produces (dozens, not thousands
    of picks per strategy)."""
    if n == 0:
        return np.nan, np.nan
    p = successes / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return (centre - half) / denom, (centre + half) / denom


def realised(tx, cutoff, keys_vals, keys):
    lo, hi = cutoff + pd.DateOffset(months=11), cutoff + pd.DateOffset(months=13)
    w = tx[(tx["month"] >= lo) & (tx["month"] <= hi)]
    for k, v in zip(keys, keys_vals):
        w = w[w[k] == v]
    if w.empty:
        return np.nan, np.nan, 0
    return w["resale_price"].median(), w["resale_price"].std() / w["resale_price"].mean() if len(w) > 1 else np.nan, len(w)


def cell_mrt(tx, cutoff, keys_vals, keys):
    w = tx[(tx["month"] <= cutoff) & (tx["month"] > cutoff - pd.DateOffset(months=12))]
    for k, v in zip(keys, keys_vals):
        w = w[w[k] == v]
    return w["dist_mrt_exit_km"].median() if len(w) else np.nan


def run(cutoffs=CUTOFFS, archetypes=ARCHETYPES, k=5, verbose=True):
    tx = load_transactions_with_access()
    tx = tx[tx["flat_type"] != "MULTI-GENERATION"]
    rows = []
    for c in cutoffs:
        C = pd.Timestamp(c)
        txc = network_as_of(tx, C)  # profile membership as defined at the cutoff
        prof_c, _ = build_profiles_v2(as_of=c, write=False)
        for name, a in archetypes.items():
            q = rv2.HouseholdQuery2(k=k, name=name, **a)
            res = rv2.solve(q, profiles=prof_c)
            for _, p in res["shortlist"].iterrows():
                keys = ["town", "flat_type", "lease_band", "storey_band", "mrt_band"]
                vals = [p[x] for x in keys]
                rp, cv, n = realised(txc, C, vals, keys)
                rows.append({"cutoff": c, "household": name, "strategy": "v2_block_informed",
                             "profile": p["profile_id"], "price_at_cutoff": p["price_today"], "realised_price": rp,
                             "realised_cell_cv": cv, "matched_sales_in_window": n,
                             "pick_mrt_km": p["dist_mrt_exit_km_p50"], "budget": a["budget"]})

            out1 = bt1.run_backtest(c, budget=a["budget"], min_lease_yrs=a["min_lease_yrs"], k=k,
                                    horizon_months=12, flat_types=a.get("flat_types"))
            for _, p in out1.iterrows():
                town, ft_nospace, sb = p["profile_id"].split("::")
                ft = ft_nospace.replace("ROOM", " ROOM") if "ROOM" in ft_nospace else ft_nospace
                town = town.replace("-", "/")
                keys = ["town", "flat_type", "storey_band"]
                rp, cv, n = realised(tx, C, [town, ft, sb], keys)
                rows.append({"cutoff": c, "household": name,
                             "strategy": "v1_town_level" if p["strategy"] == "recommender" else "naive_cheapest_towns",
                             "profile": p["profile_id"], "price_at_cutoff": p["price_at_cutoff"], "realised_price": rp,
                             "realised_cell_cv": cv, "matched_sales_in_window": n,
                             "pick_mrt_km": cell_mrt(txc, C, [town, ft, sb], keys), "budget": a["budget"]})
            if verbose:
                print(f"  {c} | {name}: v2 picks={len(res['shortlist'])}, v1/naive rows={len(out1)}", flush=True)

    df = pd.DataFrame(rows)
    df["within_budget"] = np.where(df["realised_price"].notna(), df["realised_price"] <= df["budget"], np.nan)
    df["matched_sale_seen"] = df["matched_sales_in_window"] > 0
    df.to_csv(os.path.join(HERE, "data", "backtest_v2_results.csv"), index=False)
    return df


def run_v2_variant(label, cutoffs=CUTOFFS, archetypes=ARCHETYPES, k=5, use_empirical_bands=True, verbose=True):
    """Re-runs ONLY the v2 recommender under a variant (v1/naive picks don't change)."""
    from empirical_bands import empirical_growth_bands
    tx = load_transactions_with_access()
    tx = tx[tx["flat_type"] != "MULTI-GENERATION"]
    rows = []
    for c in cutoffs:
        C = pd.Timestamp(c)
        txc = network_as_of(tx, C)
        prof_c, _ = build_profiles_v2(as_of=c, write=False)
        bands =empirical_growth_bands(txc, as_of=c) if use_empirical_bands else None
        for name, a in archetypes.items():
            res = rv2.solve(rv2.HouseholdQuery2(k=k, name=name, **a), profiles=prof_c, upper_factors=bands)
            for _, p in res["shortlist"].iterrows():
                keys = ["town", "flat_type", "lease_band", "storey_band", "mrt_band"]
                rp, cv, n = realised(txc, C, [p[x] for x in keys], keys)
                rows.append({"cutoff": c, "household": name, "strategy": label, "profile": p["profile_id"],
                             "price_at_cutoff": p["price_today"], "realised_price": rp, "realised_cell_cv": cv,
                             "matched_sales_in_window": n, "pick_mrt_km": p["dist_mrt_exit_km_p50"],
                             "budget": a["budget"]})
            if verbose:
                print(f"  {c} | {name}: {len(res['shortlist'])} picks", flush=True)
    df = pd.DataFrame(rows)
    df["within_budget"] = np.where(df["realised_price"].notna(), df["realised_price"] <= df["budget"], np.nan)
    df["matched_sale_seen"] = df["matched_sales_in_window"] > 0
    return df


def run_v2_chance_variant(label="v2_chance_constraint", alpha=0.90, cutoffs=CUTOFFS, archetypes=ARCHETYPES, k=5, verbose=True):
    """Same walk-forward backtest as run_v2_variant, but the budget constraint is the
    SCENARIO-BASED CHANCE CONSTRAINT in chance_constraint.py (P(simulated price <= budget) >= alpha,
    evaluated by Monte Carlo) instead of the deterministic empirical-band upper bound. Built in
    recommender_v2.solve() since the start (query.alpha / chance_alpha) but never backtested until
    now -- this is the first historical evidence of whether it's worth using over the empirical band."""
    tx = load_transactions_with_access()
    tx = tx[tx["flat_type"] != "MULTI-GENERATION"]
    rows = []
    for c in cutoffs:
        C = pd.Timestamp(c)
        txc = network_as_of(tx, C)
        prof_c, _ = build_profiles_v2(as_of=c, write=False)
        for name, a in archetypes.items():
            res = rv2.solve(rv2.HouseholdQuery2(k=k, name=name, **a), profiles=prof_c, chance_alpha=alpha)
            for _, p in res["shortlist"].iterrows():
                keys = ["town", "flat_type", "lease_band", "storey_band", "mrt_band"]
                rp, cv, n = realised(txc, C, [p[x] for x in keys], keys)
                rows.append({"cutoff": c, "household": name, "strategy": label, "profile": p["profile_id"],
                             "price_at_cutoff": p["price_today"], "realised_price": rp, "realised_cell_cv": cv,
                             "matched_sales_in_window": n, "pick_mrt_km": p["dist_mrt_exit_km_p50"],
                             "budget": a["budget"]})
            if verbose:
                print(f"  {c} | {name}: {len(res['shortlist'])} picks (chance-constrained, alpha={alpha})", flush=True)
    df = pd.DataFrame(rows)
    df["within_budget"] = np.where(df["realised_price"].notna(), df["realised_price"] <= df["budget"], np.nan)
    df["matched_sale_seen"] = df["matched_sales_in_window"] > 0
    return df


def diversity_score(bt, strategy):
    """How 'characteristically diverse' (proposal's own phrase, Business Objective 1) a strategy's
    shortlists actually are -- NOT just enforced structurally (<=1/town) but measured: the share of
    each shortlist's k picks that land in a distinct town / MRT band / flat type. 1.0 = every pick
    different on that axis; 1/k = all picks identical on that axis."""
    d = bt[bt["strategy"] == strategy].copy()
    parts = d["profile"].str.split("::", expand=True)
    d["town_"], d["flat_"], d["storey_"], d["mrt_"] = parts[0], parts.get(1), parts.get(2), parts.get(3)
    rows = []
    for (cutoff, household), g in d.groupby(["cutoff", "household"]):
        k = len(g)
        if k == 0:
            continue
        rows.append({
            "cutoff": cutoff, "household": household, "k": k,
            "town_diversity": g["town_"].nunique() / k,
            "mrt_band_diversity": g["mrt_"].nunique() / k if g["mrt_"].notna().any() else np.nan,
            "flat_type_diversity": g["flat_"].nunique() / k if g["flat_"].notna().any() else np.nan,
        })
    return pd.DataFrame(rows)


def summarise(df):
    g = df.groupby("strategy")
    out = pd.DataFrame({
        "picks": g.size(),
        "share_within_budget_12m": g["within_budget"].mean(),
        "share_with_matching_sale_seen": g["matched_sale_seen"].mean(),
        "median_realised_price_CV_pct": g["realised_cell_cv"].median() * 100,
        "median_pick_mrt_km": g["pick_mrt_km"].median(),
        "median_realised_vs_cutoff_pct": g.apply(lambda x: ((x["realised_price"] / x["price_at_cutoff"] - 1) * 100).median()),
    })
    ci = g["within_budget"].apply(lambda s: wilson_ci(s.sum(), s.notna().sum()))
    out["within_budget_95ci_lo"] = ci.apply(lambda t: round(t[0], 3) if pd.notna(t[0]) else np.nan)
    out["within_budget_95ci_hi"] = ci.apply(lambda t: round(t[1], 3) if pd.notna(t[1]) else np.nan)
    return out


def availability_calibration(bt, tx, strategy="v2_block_informed_empirical_band"):
    """Was 'no matching sale' predictable? The realised window is months 11-13 after the cutoff (3 months);
    under the Poisson arrival stub, P(no matching sale in 3 months) = exp(-3 * n12/12), where n12 = the
    profile's sales in the 12 months before the cutoff. Compares predicted vs observed by risk bucket."""
    d = bt[bt["strategy"] == strategy].copy()
    band_col = "mrt_band"
    n12, by_cutoff = [], {}
    for _, r in d.iterrows():
        C = pd.Timestamp(r["cutoff"])
        if C not in by_cutoff:
            by_cutoff[C] = network_as_of(tx[tx["month"] <= C], C)
        tx_c = by_cutoff[C]
        town, ft, lease, sb, mb = r["profile"].split("::")
        ft = ft.replace("ROOM", " ROOM") if "ROOM" in ft else ft
        w = tx_c[(tx_c["month"] > C - pd.DateOffset(months=12)) & (tx_c["town"] == town.replace("-", "/"))
                 & (tx_c["flat_type"] == ft) & (tx_c["lease_band"] == lease)
                 & (tx_c["storey_band"] == sb) & (tx_c[band_col].astype(str) == mb)]
        n12.append(len(w))
    d["sales_prev_12m"] = n12
    d["p_no_sale_pred"] = np.exp(-3 * d["sales_prev_12m"] / 12)
    d["no_sale_observed"] = (d["matched_sales_in_window"] == 0).astype(int)
    d["risk_bucket"] = pd.cut(d["p_no_sale_pred"], [-0.01, 0.01, 0.1, 0.3, 1.0],
                              labels=["<1%", "1-10%", "10-30%", ">30%"])
    tab = d.groupby("risk_bucket", observed=True).agg(picks=("profile", "size"),
                                                      mean_predicted=("p_no_sale_pred", "mean"),
                                                      observed_rate=("no_sale_observed", "mean"),
                                                      observed_count=("no_sale_observed", "sum"))
    return d, tab


if __name__ == "__main__":
    res = run()
    print(summarise(res).round(3).to_string())

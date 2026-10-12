# -*- coding: utf-8 -*-
"""
Iteration 2: granularity-aware price-uncertainty bands.

Backtest iteration 1 showed the stub forecast's flat +15% upper band (sized
for town-level volatility) is too narrow for block-informed profiles: their
cells are thinner, so the price a buyer actually faces 12 months later is
noisier (p90 realised change 17.6% vs 13.8% for town-level picks).

Here the band is learnt from history at the SAME granularity the
recommender uses: for every (town x flat_type x storey x MRT band) cell and
month t, ratio = median price in [t+h-1, t+h+1] / median price in [t-1, t+1],
pooled by (flat_type x MRT band). The upper factor at quantile `q` is then a
scenario-based chance constraint: P(price at horizon <= budget) >= q, on the
historical analogue distribution. Uses only data <= as_of.
"""
import numpy as np
import pandas as pd

KEYS = ["town", "flat_type", "storey_band", "mrt_band"]


def empirical_growth_bands(tx, as_of=None, horizon=12, q=0.90, min_obs=30):
    d = tx if as_of is None else tx[tx["month"] <= pd.Timestamp(as_of)]
    m = d.groupby(KEYS + ["month"], observed=True)["resale_price"].agg(["median", "size"]).reset_index()
    # centred 3-month median (matches how the backtest measures realised price)
    m = m.sort_values(KEYS + ["month"])
    pieces = []
    for _, g in m.groupby(KEYS, observed=True):
        s = g.set_index("month")["median"].asfreq("MS")
        s3 = s.rolling(3, center=True, min_periods=1).median()
        ratio = (s3.shift(-horizon) / s3).dropna()
        if len(ratio):
            pieces.append(pd.DataFrame({"flat_type": g["flat_type"].iloc[0], "mrt_band": g["mrt_band"].iloc[0],
                                        "ratio": ratio.values}))
    r = pd.concat(pieces, ignore_index=True)
    r = r[(r["ratio"] > 0.5) & (r["ratio"] < 2.0)]  # drop obvious mis-joins / composition extremes
    out = r.groupby(["flat_type", "mrt_band"], observed=True)["ratio"].agg(
        growth_factor_median="median", growth_factor_upper=lambda x: x.quantile(q),
        growth_factor_lower=lambda x: x.quantile(1 - q), n_obs="size").reset_index()
    pooled = r.groupby("flat_type")["ratio"].quantile(q).rename("pooled_upper")
    out = out.merge(pooled.reset_index(), on="flat_type", how="left")
    out.loc[out["n_obs"] < min_obs, "growth_factor_upper"] = out["pooled_upper"]
    return out.drop(columns="pooled_upper")


def fcast_for_shortlist(shortlist, bands_6m, bands_12m):
    """Adapter for monte_carlo.run_monte_carlo: one forecast row per pick per
    horizon, taken from the empirical band of the pick's (flat_type, MRT band).
    Replaces the stub's flat 0%-growth assumption with the drift and spread
    these cells actually showed historically. (Unique per pick because the
    shortlist has <= 1 profile per town.)"""
    rows = []
    for h, b in [(6, bands_6m), (12, bands_12m)]:
        bb = b.assign(mrt_band=b["mrt_band"].astype(str)).set_index(["flat_type", "mrt_band"])
        for _, p in shortlist.iterrows():
            key = (p["flat_type"], str(p["mrt_band"]))
            if key not in bb.index:
                continue
            r = bb.loc[key]
            rows.append({"town": p["town"], "flat_type": p["flat_type"], "horizon_months": h,
                         "growth_factor": r["growth_factor_median"], "growth_factor_lower": r["growth_factor_lower"],
                         "growth_factor_upper": r["growth_factor_upper"]})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    from block_analysis import load_transactions_with_access
    tx = load_transactions_with_access()
    tx = tx[tx["flat_type"] != "MULTI-GENERATION"]
    for c in [None, "2024-01-01"]:
        b = empirical_growth_bands(tx, as_of=c)
        print(f"as_of={c}:")
        print(b.round(3).to_string(index=False))

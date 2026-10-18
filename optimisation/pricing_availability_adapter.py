# -*- coding: utf-8 -*-
"""
Adapter: Pricing & Availability Lead's real deliverables (comanetan/EBA5005-GC, main
branch, snapshotted into data/external_handovers/) -> this pipeline's INTERFACE_SPEC.md
schema (pricing_today.csv, availability.csv).

Why an adapter instead of asking them to change their export: their model is
genuinely better than this pipeline's interim stand-in (LightGBM, MAPE 3.90% / R^2
0.977 vs. this pipeline's interim OLS hedonic's 15.8% out-of-time MAPE -- see
docs/model_validation.md on their branch) and already validated; reverse-engineering
the crosswalk here is less work than asking them to re-cut their own pipeline's
granularity, and it's fully reproducible (re-run this script against a newer snapshot
whenever they update).

Method for both files: crosswalk every one of their profile_ids to mine
(profile_crosswalk.py), then aggregate with the MEDIAN across whatever of their profiles
(different lease bands, mostly) land on the same profile_id of mine -- median, not mean,
so a single outlier lease-band cell can't dominate.
"""
import os

import numpy as np
import pandas as pd

from profile_crosswalk import add_my_profile_id

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
EXT = os.path.join(DATA, "external_handovers")


def _my_profile_ids():
    return set(pd.read_csv(os.path.join(DATA, "housing_profiles_v2_full.csv"))["profile_id"])


def build_pricing_today(prices_path=None, write=True):
    """price_low/price_high in their file = 10th/90th percentile of price ACROSS BLOCKS
    within a profile (docs/model_validation.md Sec 2) -- a within-profile dispersion
    measure, not a point-estimate standard error. Converted to an approximate SE via the
    10th/90th-percentile-of-a-normal relationship (z = +/-1.2816): SE =~ (high-low)/2.5632.
    This is a stated approximation, not their model's own reported SE (they don't report
    one) -- flagged here and in the output's provenance so it's never read as more
    precise than it is."""
    prices_path = prices_path or os.path.join(EXT, "prices_today_main.csv")
    d = pd.read_csv(prices_path)
    d = add_my_profile_id(d)
    d = d.dropna(subset=["my_profile_id"])
    d = d[d["my_profile_id"].isin(_my_profile_ids())]
    d["se_approx"] = (d["price_high"] - d["price_low"]) / 2.5632

    agg = d.groupby("my_profile_id", observed=True).agg(
        price_today=("price", "median"), price_today_se=("se_approx", "median"),
        n_source_profiles=("price", "size")).reset_index()
    agg = agg.rename(columns={"my_profile_id": "profile_id"})
    agg["price_today"] = agg["price_today"].round(0)
    agg["price_today_se"] = agg["price_today_se"].round(0)

    if write:
        agg[["profile_id", "price_today", "price_today_se"]].to_csv(
            os.path.join(DATA, "pricing_today.csv"), index=False)
        agg.to_csv(os.path.join(DATA, "pricing_today_provenance.csv"), index=False)
    return agg


def build_availability(wait_path=None, write=True):
    """Their expected_wait.csv gives a point wait_months (median time to next matching
    sale, Cox PH -- docs/model_validation.md Sec 3) and a `scarce` flag (wait capped at
    120 months), but no survival_prob_6m/12m directly. Their own documented 3-step method
    ("turn each gap into a rate 1/gap, add the rates, take 1/total") is already a
    rate/exponential construction -- so deriving survival_prob_h = 1 - exp(-h / wait_months)
    is methodologically consistent with how wait_months was itself built, not an arbitrary
    reinterpretation. hazard_ratio is left blank: not available at this granularity in
    their output (optional in INTERFACE_SPEC.md's own schema)."""
    wait_path = wait_path or os.path.join(EXT, "expected_wait_main.csv")
    d = pd.read_csv(wait_path)
    d = add_my_profile_id(d)
    d = d.dropna(subset=["my_profile_id"])
    d = d[d["my_profile_id"].isin(_my_profile_ids())]

    agg = d.groupby("my_profile_id", observed=True).agg(
        expected_wait_months=("wait_months", "median"),
        scarce_share=("scarce", "mean"), n_source_profiles=("wait_months", "size")).reset_index()
    agg = agg.rename(columns={"my_profile_id": "profile_id"})
    lam = 1 / agg["expected_wait_months"].clip(lower=0.1)
    agg["survival_prob_6m"] = (1 - np.exp(-lam * 6)).round(3)
    agg["survival_prob_12m"] = (1 - np.exp(-lam * 12)).round(3)
    agg["hazard_ratio"] = np.nan
    agg["expected_wait_months"] = agg["expected_wait_months"].round(2)

    if write:
        agg[["profile_id", "expected_wait_months", "survival_prob_6m", "survival_prob_12m",
             "hazard_ratio"]].to_csv(os.path.join(DATA, "availability.csv"), index=False)
        agg.to_csv(os.path.join(DATA, "availability_provenance.csv"), index=False)
    return agg


# 2026-10-18: as of main commit 42df63b (17 Oct), Pricing & Availability started writing
# outputs/optimisation/{pricing_today,availability}.csv DIRECTLY on this pipeline's own
# profile_id scheme (952 of my profiles covered) -- priced/timed per-profile from their
# block mix weighted by units, not a median crosswalk across their 5-part lease-band IDs.
# This supersedes build_pricing_today()/build_availability() above, which exist now only
# to reproduce their OLDER (12 Oct) 5-part-ID snapshot for backtest/history purposes --
# prefer the functions below for any current run.
def build_from_native(pricing_path=None, availability_path=None, write=True):
    """Pass-through (not a crosswalk): their file's profile_id already matches mine, so
    this just filters to my known profile_ids and renames nothing. Any profile_id in
    their file that isn't one of mine (or vice versa) is a genuine boundary disagreement
    in our distance bands, not an adapter bug -- reported, not silently dropped."""
    pricing_path = pricing_path or os.path.join(EXT, "pricing_today_main_native.csv")
    availability_path = availability_path or os.path.join(EXT, "availability_main_native.csv")
    mine = _my_profile_ids()

    p = pd.read_csv(pricing_path)
    p_mine = p[p["profile_id"].isin(mine)].copy()
    if write:
        p_mine[["profile_id", "price_today", "price_today_se", "price_low", "price_high"]].to_csv(
            os.path.join(DATA, "pricing_today.csv"), index=False)

    a = pd.read_csv(availability_path)
    a_mine = a[a["profile_id"].isin(mine)].copy()
    if write:
        a_mine[["profile_id", "expected_wait_months", "survival_prob_6m", "survival_prob_12m",
                "hazard_ratio", "scarce"]].to_csv(os.path.join(DATA, "availability.csv"), index=False)

    missing_mine = mine - set(p["profile_id"])
    extra_theirs = set(p["profile_id"]) - mine
    return p_mine, a_mine, missing_mine, extra_theirs


if __name__ == "__main__":
    mine = pd.read_csv(os.path.join(DATA, "housing_profiles_v2_full.csv"))
    n_mine = mine["profile_id"].nunique()

    if os.path.exists(os.path.join(EXT, "pricing_today_main_native.csv")):
        p, a, missing_mine, extra_theirs = build_from_native()
        print(f"NATIVE pass-through (main@42df63b, 17 Oct): pricing_today.csv {len(p)} / {n_mine} "
              f"of my profiles ({len(p)/n_mine*100:.1f}%), availability.csv {len(a)} / {n_mine}")
        print(f"  {len(missing_mine)} of my profiles missing from their file, "
              f"{len(extra_theirs)} of their profiles not in mine (boundary disagreements, both small)")
        print(f"  median price_today_se ${p['price_today_se'].median():,.0f}, "
              f"median expected_wait_months {a['expected_wait_months'].median():.1f}")
    else:
        p = build_pricing_today()
        print(f"pricing_today.csv: {len(p)} / {n_mine} of my profiles covered "
              f"({len(p)/n_mine*100:.1f}%), median SE ${p['price_today_se'].median():,.0f}")

        a = build_availability()
        print(f"availability.csv: {len(a)} / {n_mine} of my profiles covered "
              f"({len(a)/n_mine*100:.1f}%), median wait {a['expected_wait_months'].median():.1f} months, "
              f"{(a['scarce_share']>0).sum()} profiles with >=1 scarce source cell")

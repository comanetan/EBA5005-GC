# -*- coding: utf-8 -*-
"""
Cross-pipeline validation, flagged in INTEGRATION_PROGRESS.md and never run until now: the
Pricing & Availability Lead's own `docs/model_validation.md` says their 2024-12 backtest
snapshot (outputs/backtest/2024-12/optimisation/{pricing_today,availability}.csv, main
commit a5d2f38) was built explicitly to "match Optimisation's 2025-01-01 cutoff" -- i.e.
data through Dec 2024, predicting the state as of Jan 2025, the exact point this pipeline's
own EXTENDED_CUTOFFS already tests. The snapshot sat unused in the shared repo the whole
time.

Format note: their 2024-12 file is a 4-part NATIVE profile_id (TOWN::FLATTYPE::StoreyBand::
MRTBand, e.g. "ANG MO KIO::2ROOM::High::Mid") -- already in this pipeline's own Low/Mid/High
and Near/Mid/Far vocabulary (built on "Optimisation's profile IDs" per their 17 Oct commit),
but one day before lease_band was added to this scheme, so it carries no lease dimension.
This pipeline's own profiles are therefore aggregated UP from the 5-part scheme to the same
4-part grain (median price/count across lease bands) for a fair, like-for-like comparison --
not crosswalked the other way, since their file can't be split by lease band at all.

What this tests: does THEIR Dec-2024 price/availability prediction track what actually
happened 11-13 months later better, worse, or about the same as this pipeline's own
simplest-possible historical reconstruction (trailing-12-month median/count as of the same
cutoff) -- the same baseline every one of this project's own backtests is compared against.
Not a test of the full recommender (that would need their prediction broadcast across
lease bands inside solve() itself, a bigger and riskier change for a one-off validation);
a direct, auditable comparison of the two price/availability inputs against reality.
"""
import json
import os

import numpy as np
import pandas as pd

from block_analysis import load_transactions_with_access

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
EXT = os.path.join(DATA, "external_handovers")

CUTOFF = pd.Timestamp("2025-01-01")  # matches EXTENDED_CUTOFFS; their snapshot = data through 2024-12
LO, HI = CUTOFF + pd.DateOffset(months=11), CUTOFF + pd.DateOffset(months=13)  # same window realised() uses
EXCLUDED_FLAT_TYPES_HISTORICAL = ["MULTI-GENERATION"]  # 2024-12 predates this pipeline's own 2-ROOM/EXECUTIVE removal


def load_theirs():
    p = pd.read_csv(os.path.join(EXT, "pricing_today_2024-12_native.csv"))
    a = pd.read_csv(os.path.join(EXT, "availability_2024-12_native.csv"))
    for d in (p, a):
        parts = d["profile_id"].str.split("::", expand=True)
        d["town"], d["flat_type_ns"], d["storey_band"], d["mrt_band"] = parts[0], parts[1], parts[2], parts[3]
    return p, a


def flat_type_label(ns):
    return {"2ROOM": "2 ROOM", "3ROOM": "3 ROOM", "4ROOM": "4 ROOM", "5ROOM": "5 ROOM",
            "EXECUTIVE": "EXECUTIVE"}.get(ns, ns)


def mine_at_cutoff(tx):
    """This pipeline's own simplest historical reconstruction at the SAME cutoff and grain:
    trailing-12-month median price and txn count per (town, flat_type, storey_band, mrt_band)
    -- deliberately the plain baseline, not the full hedonic/survival model, for a fair
    like-for-like comparison against their file's own grain."""
    known = tx[(tx["month"] <= CUTOFF) & (tx["month"] > CUTOFF - pd.DateOffset(months=12))
               & (~tx["flat_type"].isin(EXCLUDED_FLAT_TYPES_HISTORICAL))]
    g = known.groupby(["town", "flat_type", "storey_band", "mrt_band"], observed=True).agg(
        price_today=("resale_price", "median"), n_12m=("resale_price", "size")).reset_index()
    return g


def realised_at_cutoff(tx):
    w = tx[(tx["month"] >= LO) & (tx["month"] <= HI)]
    g = w.groupby(["town", "flat_type", "storey_band", "mrt_band"], observed=True).agg(
        realised_price=("resale_price", "median"), n_realised=("resale_price", "size")).reset_index()
    return g


def run():
    tx_all = load_transactions_with_access()
    tx = tx_all[~tx_all["flat_type"].isin(EXCLUDED_FLAT_TYPES_HISTORICAL)]

    theirs_p, theirs_a = load_theirs()
    theirs_p["flat_type"] = theirs_p["flat_type_ns"].apply(flat_type_label)
    theirs_a["flat_type"] = theirs_a["flat_type_ns"].apply(flat_type_label)

    mine = mine_at_cutoff(tx)
    realised = realised_at_cutoff(tx)

    keys = ["town", "flat_type", "storey_band", "mrt_band"]
    cells = realised.merge(mine, on=keys, how="inner").merge(
        theirs_p[keys + ["price_today"]].rename(columns={"price_today": "their_price"}), on=keys, how="inner")
    cells = cells[cells["n_realised"] >= 1].copy()  # need at least one realised sale to score against

    cells["my_abs_pct_err"] = (cells["price_today"] - cells["realised_price"]).abs() / cells["realised_price"] * 100
    cells["their_abs_pct_err"] = (cells["their_price"] - cells["realised_price"]).abs() / cells["realised_price"] * 100

    print(f"Overlapping cells scored (>=1 realised sale in [{LO.date()}, {HI.date()}]): {len(cells)}")
    print(f"My own trailing-12mo median:  MAPE {cells['my_abs_pct_err'].median():.2f}% (median), "
          f"{cells['my_abs_pct_err'].mean():.2f}% (mean)")
    print(f"Their Dec-2024 prediction:    MAPE {cells['their_abs_pct_err'].median():.2f}% (median), "
          f"{cells['their_abs_pct_err'].mean():.2f}% (mean)")
    my_better = (cells["my_abs_pct_err"] < cells["their_abs_pct_err"]).mean()
    print(f"Share of cells where my own baseline is closer to realised: {my_better*100:.1f}%")

    # Availability: realised "at least one matching sale" vs their survival_prob_12m prediction,
    # and vs this pipeline's own equivalent stub formula (txn_count_12m -> Poisson rate).
    a_cells = realised.merge(mine, on=keys, how="inner").merge(
        theirs_a[keys + ["survival_prob_12m"]], on=keys, how="inner")
    a_cells["realised_any_sale"] = (a_cells["n_realised"] >= 1).astype(int)
    lam_mine = (a_cells["n_12m"] / 12).clip(lower=1 / 24)
    a_cells["my_survival_prob_12m"] = 1 - np.exp(-lam_mine * 12)

    def brier(pred, obs):
        return float(((pred - obs) ** 2).mean())

    brier_theirs = brier(a_cells["survival_prob_12m"], a_cells["realised_any_sale"])
    brier_mine = brier(a_cells["my_survival_prob_12m"], a_cells["realised_any_sale"])
    print(f"\nAvailability Brier score (lower = better calibrated), n={len(a_cells)} cells:")
    print(f"  Their Dec-2024 survival_prob_12m: {brier_theirs:.4f}")
    print(f"  My own trailing-count stub:       {brier_mine:.4f}")

    out = {
        "cutoff": str(CUTOFF.date()), "window": [str(LO.date()), str(HI.date())],
        "n_price_cells": len(cells),
        "my_price_mape_median": float(cells["my_abs_pct_err"].median()),
        "their_price_mape_median": float(cells["their_abs_pct_err"].median()),
        "my_price_mape_mean": float(cells["my_abs_pct_err"].mean()),
        "their_price_mape_mean": float(cells["their_abs_pct_err"].mean()),
        "share_cells_mine_closer": float(my_better),
        "n_availability_cells": len(a_cells),
        "brier_theirs": brier_theirs, "brier_mine": brier_mine,
    }
    with open(os.path.join(DATA, "cross_validate_pricing_lead_2024-12.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("\nWrote data/cross_validate_pricing_lead_2024-12.json")
    return out


if __name__ == "__main__":
    run()

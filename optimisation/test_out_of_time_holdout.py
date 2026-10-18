# -*- coding: utf-8 -*-
"""
Item 6 of the "other tests" follow-up list (OPTIMISER_METHODOLOGY_REPORT.md Sec. 22, last
of the six): the extended walk-forward backtest's most recent cutoff is 2025-07-01
(backtest_v2.EXTENDED_CUTOFFS). The headline 99.4% [96.9%, 99.9%] reliability figure cited
throughout this report comes entirely from cutoffs the model has, in effect, already been
tuned against during this project's own iteration history. As more real transaction months
have accumulated since, the strongest test of whether that number holds up GOING FORWARD
is a genuinely NEW cutoff never used in any prior iteration -- not just adding more
historical cutoffs to the same already-seen window.

Data-availability check (block_analysis.load_transactions_with_access()): transactions run
2017-01 .. 2026-10, but 2026-10 is a PARTIAL month (212 sales vs. 2,000-2,600 for every
complete month either side -- "today" in this project's timeline is 2026-10-19, so October
is still mid-month). realised() needs the window [cutoff+11mo, cutoff+13mo] fully inside
available data to be unbiased. That rules out touching October:
  - cutoff=2025-08-01 -> window [2026-07, 2026-09], all 3 months complete.      SAFE, primary holdout.
  - cutoff=2025-09-01 -> window [2026-08, 2026-10], includes the partial month. Flagged, not primary.
Both are new -- neither appears in EXTENDED_CUTOFFS (latest: 2025-07-01) -- but only the
first has a fully-observable, unbiased realised window. Both are run; 2025-09-01's results
are reported with the partial-window caveat stated plainly, not silently included as if
equally reliable.

Method: EXACT same methodology as the production headline figure --
backtest_v2.run_v2_variant("v2_block_informed_empirical_band", ...) (empirical growth
bands, the shipped default), same EXTENDED_ARCHETYPES (4 households), same k=5 -- only the
cutoff is new. Also recomputes the EXTENDED_CUTOFFS baseline fresh in this same run (not
copied from the report) so the comparison is apples-to-apples from one script, one process.
"""
import json
import os

import pandas as pd

import backtest_v2 as bt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
LABEL = "v2_block_informed_empirical_band"
K = 5

NEW_CUTOFFS_SAFE = ["2025-08-01"]          # fully-observable realised window
NEW_CUTOFFS_FLAGGED = ["2025-09-01"]       # realised window touches the partial Oct-2026 month


def summarise_by_cutoff(df):
    """Same reliability metric as backtest_v2.summarise(), but broken down per cutoff
    (not just pooled across all of them) -- the small-n price of looking at one cutoff at
    a time, accepted deliberately so a single bad new cutoff can't hide inside a pooled
    average."""
    rows = []
    for cutoff, g in df.groupby("cutoff"):
        n = g["within_budget"].notna().sum()
        succ = g["within_budget"].sum()
        lo, hi = bt.wilson_ci(succ, n)
        rows.append({
            "cutoff": cutoff, "picks": len(g), "n_scored": int(n),
            "share_within_budget_12m": float(g["within_budget"].mean()) if n else None,
            "within_budget_95ci": [round(lo, 3) if pd.notna(lo) else None, round(hi, 3) if pd.notna(hi) else None],
            "share_with_matching_sale_seen": float(g["matched_sale_seen"].mean()),
            "median_realised_cell_cv_pct": float(g["realised_cell_cv"].median() * 100) if g["realised_cell_cv"].notna().any() else None,
        })
    return rows


def run():
    print(f"Recomputing the EXTENDED_CUTOFFS (11) baseline fresh, for an apples-to-apples comparison...")
    df_baseline = bt.run_v2_variant(LABEL, cutoffs=bt.EXTENDED_CUTOFFS, archetypes=bt.EXTENDED_ARCHETYPES, k=K, verbose=False)
    baseline_summary = bt.summarise(df_baseline).loc[LABEL]
    print(f"Baseline (11 cutoffs x 4 archetypes, {df_baseline.shape[0]} picks): "
          f"{baseline_summary['share_within_budget_12m']*100:.1f}% "
          f"[{baseline_summary['within_budget_95ci_lo']*100:.1f}%, {baseline_summary['within_budget_95ci_hi']*100:.1f}%]")

    all_new_cutoffs = NEW_CUTOFFS_SAFE + NEW_CUTOFFS_FLAGGED
    print(f"\nRunning genuinely new holdout cutoffs: {all_new_cutoffs} (never in EXTENDED_CUTOFFS)...")
    df_new = bt.run_v2_variant(LABEL, cutoffs=all_new_cutoffs, archetypes=bt.EXTENDED_ARCHETYPES, k=K, verbose=False)
    new_summary = bt.summarise(df_new).loc[LABEL]
    per_cutoff = summarise_by_cutoff(df_new)
    for row in per_cutoff:
        flag = " [FLAGGED: realised window touches the partial Oct-2026 month]" if row["cutoff"] in NEW_CUTOFFS_FLAGGED else ""
        print(f"  {row['cutoff']}: {row['share_within_budget_12m']*100:.1f}% within budget "
              f"({row['n_scored']} scored / {row['picks']} picks), "
              f"matched_sale_seen={row['share_with_matching_sale_seen']*100:.1f}%{flag}")

    df_new_safe = df_new[df_new["cutoff"].isin(NEW_CUTOFFS_SAFE)]
    safe_summary = bt.summarise(df_new_safe).loc[LABEL]
    print(f"\nSafe-only new holdout (2025-08-01, {df_new_safe.shape[0]} picks): "
          f"{safe_summary['share_within_budget_12m']*100:.1f}% "
          f"[{safe_summary['within_budget_95ci_lo']*100:.1f}%, {safe_summary['within_budget_95ci_hi']*100:.1f}%]")

    df_combined = pd.concat([df_baseline, df_new_safe], ignore_index=True)
    combined_summary = bt.summarise(df_combined).loc[LABEL]
    print(f"\nCombined (11 baseline + 1 new safe holdout = 12 cutoffs x 4 archetypes, "
          f"{df_combined.shape[0]} picks): {combined_summary['share_within_budget_12m']*100:.1f}% "
          f"[{combined_summary['within_budget_95ci_lo']*100:.1f}%, {combined_summary['within_budget_95ci_hi']*100:.1f}%]")

    def s(row):
        return {k: (float(v) if pd.notna(v) else None) for k, v in row.items()}

    return {
        "label": LABEL, "k": K,
        "baseline_extended_11x4": s(baseline_summary),
        "new_holdout_cutoffs_all": s(new_summary),
        "new_holdout_per_cutoff": per_cutoff,
        "new_holdout_safe_only": s(safe_summary),
        "combined_12x4": s(combined_summary),
        "safe_cutoffs": NEW_CUTOFFS_SAFE, "flagged_cutoffs": NEW_CUTOFFS_FLAGGED,
    }


if __name__ == "__main__":
    result = run()
    with open(os.path.join(DATA, "out_of_time_holdout_test.json"), "w") as f:
        json.dump(result, f, indent=2)
    print("\nWrote data/out_of_time_holdout_test.json")

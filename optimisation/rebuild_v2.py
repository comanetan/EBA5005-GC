# -*- coding: utf-8 -*-
"""
Rebuild every v2 artefact after an accessibility change, in dependency order:
  block_accessibility.csv -> transactions_block_access.parquet -> housing_profiles_v2 (+ hedonic,
  market_wtp_coefficients.json, drill-down) -> backtest (iteration 1 + iteration 2 empirical band).
Run: python rebuild_v2.py [--skip-backtest]
"""
import os
import sys
import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA = os.path.join(HERE, "data")

if __name__ == "__main__":
    t0 = time.time()
    import block_accessibility as ba
    blocks, meta = ba.build_block_accessibility()
    print(f"[1] block_accessibility: {len(blocks)} blocks, walk cols "
          f"{sum(c.startswith('walk_') for c in blocks.columns)} ({time.time()-t0:.0f}s)", flush=True)

    cache = os.path.join(DATA, "transactions_block_access.parquet")
    if os.path.exists(cache):
        os.remove(cache)
    from block_analysis import load_transactions_with_access
    tx = load_transactions_with_access()
    print(f"[2] parquet: {len(tx):,} sales; walk_at_sale={'walk_mrt_exit_km_at_sale' in tx} ({time.time()-t0:.0f}s)", flush=True)

    from housing_profiles_v2 import build_profiles_v2
    prof, drill = build_profiles_v2()
    print(f"[3] profiles v2: {len(prof)} | bands {prof['mrt_band'].value_counts().to_dict()} ({time.time()-t0:.0f}s)", flush=True)

    if "--skip-backtest" not in sys.argv:
        import backtest_v2 as bt
        it1 = bt.run(verbose=False)
        it2 = bt.run_v2_variant("v2_block_informed_empirical_band", verbose=False)
        both = pd.concat([it1, it2], ignore_index=True)
        both.to_csv(os.path.join(DATA, "backtest_v2_results_iter2.csv"), index=False)
        print(bt.summarise(both).round(3).to_string())
        d, tab = bt.availability_calibration(both, tx)
        print(tab.round(3).to_string())
        print(f"[4] backtest done ({time.time()-t0:.0f}s)", flush=True)

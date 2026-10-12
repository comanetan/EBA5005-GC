# -*- coding: utf-8 -*-
"""
Compare walking-distance variants against straight-line distance:
  raw OSM network vs OSM + 25m gap connectors.
For each: detour ratios, MRT band reclassification, and whether walking MRT
distance explains resale price better than straight-line (hedonic adj R2 / AIC).
Writes data/walk_variant_comparison.csv.
"""
import importlib
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(DATA, "transactions_block_access.parquet")

VARIANTS = {"OSM raw": "block_walk_distances.csv", "OSM + 25m connectors": "block_walk_distances_connect25m.csv"}


def run_variant(walk_file):
    os.environ["BLOCK_WALK_FILE"] = walk_file
    import block_accessibility as ba
    import block_analysis as ban
    importlib.reload(ba)
    importlib.reload(ban)
    blocks, _ = ba.build_block_accessibility()
    if os.path.exists(CACHE):
        os.remove(CACHE)
    tx = ban.load_transactions_with_access()
    return ban.detour_summary(blocks), ban.band_reclassification(blocks), ban.walk_vs_straight_hedonic(tx)


if __name__ == "__main__":
    rows = []
    for name, f in VARIANTS.items():
        det, bands, hed = run_variant(f)
        print(f"\n=== {name} ===")
        print(det.round(2).to_string(index=False))
        print(bands)
        print(hed.round(4).to_string())
        for _, r in det.iterrows():
            rows.append({"variant": name, "metric": f"median_detour_{r['amenity']}", "value": r["median_detour_ratio"]})
        for lbl, r in hed.iterrows():
            rows.append({"variant": name, "metric": f"adjR2_{lbl}", "value": r["adj_R2"]})
            rows.append({"variant": name, "metric": f"AIC_{lbl}", "value": r["AIC"]})
    pd.DataFrame(rows).to_csv(os.path.join(DATA, "walk_variant_comparison.csv"), index=False)
    # leave the pipeline on the chosen file (block_accessibility.WALK_FILE default: gap-corrected)
    run_variant(VARIANTS["OSM + 25m connectors"])

# -*- coding: utf-8 -*-
"""
Cross-validates the real availability model's expected_wait_months against an
independent, self-collected signal: live 99.co listing turnover, scraped by
scrape_99co.py (Project/notebooks/) across 6 runs, 5 Oct - 17 Oct 2026.

WHY THIS IS A LIMITED, NOT A FULL, VALIDATION
----------------------------------------------
The scrape has only been running ~12 days -- far too short to observe a
6- or 12-month survival outcome directly (the real model's own horizons).
What IS observable in 12 days is relative turnover speed: do flat types /
lease bands the real model expects to wait LONGER for also show up as
listings that stick around LONGER in the live scrape, and vice versa. This
script tests exactly that directional claim via a cell-level correlation,
not an exact-value match -- consistent with every other cross-check in this
project (reported with its own limitations, never oversold).

METHOD
------
1. Filter scraped listings to segment=hdb_sale, sub_category in {3R,4R,5R}
   (matches this pipeline's current flat-type scope).
2. Derive flat_type from sub_category; town from a substring match of
   formatted_address against the pipeline's 26 known town names (HDB street
   names conventionally lead with the town name); lease_band from the "Built:
   YYYY" field via the same <60/60-79/80+ cut block_analysis.py uses, assuming
   a 99-year original lease (true for every sampled listing's lease_type).
3. Restrict to listings first seen at least 5 days before the latest scrape
   run, so every listing included has had a comparable chance to be observed
   disappearing (otherwise a listing first seen yesterday looks artificially
   "still listed" next to one first seen 12 days ago).
4. Aggregate to flat_type x lease_band cells (town dropped for cell size --
   26 towns x 3 x 3 is too sparse at n=3,336 total listings). Per cell:
   empirical "delisted share" = count(still_listed=False) / count(total) --
   a turnover-speed proxy, not a survival estimate.
5. Aggregate the real availability.csv's expected_wait_months to the same
   cells (median across town/storey/mrt bands) and Spearman-correlate the two
   cell-level series: faster turnover (higher delisted share) should pair
   with a SHORTER expected wait (negative correlation).
"""
import os
import re

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SCRAPE_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "data", "scraped_listings"))

TOWNS = ["ANG MO KIO", "BEDOK", "BISHAN", "BUKIT BATOK", "BUKIT MERAH", "BUKIT PANJANG",
         "BUKIT TIMAH", "CENTRAL AREA", "CHOA CHU KANG", "CLEMENTI", "GEYLANG", "HOUGANG",
         "JURONG EAST", "JURONG WEST", "KALLANG/WHAMPOA", "MARINE PARADE", "PASIR RIS",
         "PUNGGOL", "QUEENSTOWN", "SEMBAWANG", "SENGKANG", "SERANGOON", "TAMPINES",
         "TOA PAYOH", "WOODLANDS", "YISHUN"]
# KALLANG/WHAMPOA has no literal "KALLANG/WHAMPOA" street name -- addresses say
# "Kallang" or "Whampoa" directly; matched as two separate substrings below.
TOWN_SUBSTRINGS = {t: [t] for t in TOWNS}
TOWN_SUBSTRINGS["KALLANG/WHAMPOA"] = ["KALLANG", "WHAMPOA"]

SUBCAT_TO_FLATTYPE = {"hdb_3r": "3 ROOM", "hdb_4r": "4 ROOM", "hdb_5r": "5 ROOM"}


def match_town(address):
    if not isinstance(address, str):
        return None
    a = address.upper()
    for town, substrs in TOWN_SUBSTRINGS.items():
        if any(s in a for s in substrs):
            return town
    return None


def lease_band(remaining_lease_yrs):
    yrs = pd.to_numeric(remaining_lease_yrs, errors="coerce")
    return pd.cut(yrs, [-1, 59.999, 79.999, 999], labels=["<60", "60-79", "80+"]).astype(str)


def load_scraped():
    path = os.path.join(SCRAPE_DIR, "listings_master.csv")
    d = pd.read_csv(path, low_memory=False)
    d = d[(d["segment"] == "hdb_sale") & (d["sub_category"].isin(SUBCAT_TO_FLATTYPE))].copy()
    n_raw = len(d)
    d["flat_type"] = d["sub_category"].map(SUBCAT_TO_FLATTYPE)
    d["town"] = d["formatted_address"].apply(match_town)
    n_town_matched = d["town"].notna().sum()

    built_year = d["top"].str.extract(r"Built:\s*(\d{4})").astype(float)[0]
    current_year = 2026
    remaining_lease = 99 - (current_year - built_year)
    d["remaining_lease_est"] = remaining_lease
    d["lease_band"] = lease_band(remaining_lease)
    n_lease_matched = d["lease_band"].isin(["<60", "60-79", "80+"]).sum()

    d["first_seen"] = pd.to_datetime(d["first_seen"], utc=True)
    d["last_seen"] = pd.to_datetime(d["last_seen"], utc=True)
    latest_run = d["last_seen"].max()
    comparable = d[d["first_seen"] <= latest_run - pd.Timedelta(days=5)].copy()

    print(f"Scraped HDB 3/4/5-room listings: {n_raw}")
    print(f"  town matched: {n_town_matched} ({n_town_matched/n_raw:.1%})")
    print(f"  lease_band resolved: {n_lease_matched} ({n_lease_matched/n_raw:.1%})")
    print(f"  first_seen >=5 days before latest run (comparable follow-up): {len(comparable)} "
          f"({len(comparable)/n_raw:.1%})")
    return comparable


def cell_turnover(comparable):
    valid = comparable.dropna(subset=["flat_type", "lease_band"])
    valid = valid[valid["lease_band"].isin(["<60", "60-79", "80+"])]
    g = valid.groupby(["flat_type", "lease_band"], observed=True)
    out = g.agg(n=("listing_id", "size"), n_delisted=("still_listed", lambda s: (~s).sum()))
    out["delisted_share"] = out["n_delisted"] / out["n"]
    return out.reset_index()


def model_expected_wait():
    prof = pd.read_csv(os.path.join(DATA, "housing_profiles_v2_full.csv"))
    avail = pd.read_csv(os.path.join(DATA, "availability.csv"))
    merged = prof.merge(avail, on="profile_id", how="inner")
    merged = merged[merged["flat_type"].isin(SUBCAT_TO_FLATTYPE.values())]
    g = merged.groupby(["flat_type", "lease_band"], observed=True)["expected_wait_months"].median()
    return g.reset_index()


def main():
    comparable = load_scraped()
    turnover = cell_turnover(comparable)
    model = model_expected_wait()

    merged = turnover.merge(model, on=["flat_type", "lease_band"], how="inner")
    merged = merged[merged["n"] >= 15]  # drop cells too thin to say anything
    print(f"\nCells with >=15 comparable listings: {len(merged)}")
    print(merged.to_string(index=False))

    if len(merged) >= 4:
        rho, p = spearmanr(merged["delisted_share"], merged["expected_wait_months"])
        print(f"\nSpearman correlation (delisted_share vs. model expected_wait_months): "
              f"rho={rho:.3f}, p={p:.3f}")
        print("Expected sign: NEGATIVE (faster scraped turnover <-> shorter modelled expected wait).")
    else:
        rho, p = np.nan, np.nan
        print("\nToo few cells to correlate meaningfully.")

    result = {
        "scrape_window_days": 12,
        "n_scraped_hdb_3_4_5_room": int(len(comparable)),
        "cells_compared": merged.to_dict(orient="records"),
        "spearman_rho": None if pd.isna(rho) else round(float(rho), 3),
        "spearman_p": None if pd.isna(p) else round(float(p), 3),
        "_note": "A short-horizon (12-day), cell-level directional cross-check, not a validation of "
                 "the model's 6-/12-month survival horizons, which the scrape has not run long enough "
                 "to observe directly. delisted_share is a turnover-speed proxy (share of listings, "
                 "first seen >=5 days before the latest scrape run, no longer listed by that run), not "
                 "a survival estimate.",
    }
    import json
    with open(os.path.join(DATA, "cross_validate_99co_listings.json"), "w") as f:
        json.dump(result, f, indent=2, default=str)
    print("\nWrote data/cross_validate_99co_listings.json")


if __name__ == "__main__":
    main()

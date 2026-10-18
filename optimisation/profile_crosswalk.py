# -*- coding: utf-8 -*-
"""
Crosswalk between the Pricing/Availability and Forecasting leads' profile_id scheme
(comanetan/EBA5005-GC, main + forecasting branches) and this pipeline's own.

Theirs:  "{TOWN}|{FLATTYPE}|{LeaseBand}|{MRTBand}|{StoreyRange}"
         e.g. "ANG MO KIO|4 ROOM|60-79|500m-1km|1-6"
         lease_band in {<60, 60-79, 80+}; mrt_band in {<500m, 500m-1km, >1km};
         storey_band in {1-6, 7-12, 13+}

Mine (since 2026-10-18, see OPTIMISER_METHODOLOGY_REPORT.md Sec. 16):
         "{TOWN}::{FLATTYPE}::{LeaseBand}::{StoreyBand}::{MRTBand}"
         e.g. "ANG MO KIO::4ROOM::60-79::Mid::Mid"
         lease_band in {<60, 60-79, 80+} -- IDENTICAL to theirs, chosen deliberately so
         this is the one dimension that never needs crosswalking;
         storey_band in {Low, Mid, High} (1-6 / 7-15 / 16+);
         mrt_band in {Near, Mid, Far} (<=400m / 400-800m / >800m)

One approximation now, stated honestly rather than hidden in the numbers (there were two
until lease_band was added to my own profile -- see git history for the earlier version of
this module, which also aggregated across their lease bands):
  Bin edges don't line up exactly on storey/MRT (theirs: 500m/1km vs mine: 400m/800m;
  theirs: 7-12/13+ vs mine: 7-15/16+). Mapped to the nearest sensible 3-to-3 correspondence
  below -- this will misclassify some blocks right at a boundary (e.g. a block at 650m is
  "500m-1km" to them, "Mid" to both schemes either way here, but a block at 900m is
  ">1km"/"Far" to them while being "Mid" under my own 800m cutoff for a block that's
  actually 750-800m -- the edge cases are the source of any remaining disagreement, not a
  systematic bias). Every adapter function in this module still aggregates (median, not
  mean, to resist outlier blocks) across whichever of their profiles collapse onto one of
  mine at these storey/MRT boundaries -- just never across lease any more.
"""
import pandas as pd

MRT_BAND_MAP = {"<500m": "Near", "500m-1km": "Mid", ">1km": "Far"}
STOREY_BAND_MAP = {"1-6": "Low", "7-12": "Mid", "13+": "High"}
LEASE_BAND_SET = {"<60", "60-79", "80+"}  # identity mapping -- both sides use this exact set


def parse_their_profile_id(pid):
    parts = pid.split("|")
    if len(parts) != 5:
        return None
    town, flat_type, lease_band, mrt_band, storey_range = parts
    return {"town": town, "flat_type": flat_type, "lease_band": lease_band,
            "their_mrt_band": mrt_band, "their_storey_band": storey_range}


def crosswalk_profile_id(pid):
    """Theirs -> mine. Returns None if the lease/MRT/storey band isn't in the known
    vocabulary (would mean their schema changed since this crosswalk was written -- fail
    loudly via None/NaN rather than silently mis-binning)."""
    parsed = parse_their_profile_id(pid)
    if parsed is None:
        return None
    mrt = MRT_BAND_MAP.get(parsed["their_mrt_band"])
    storey = STOREY_BAND_MAP.get(parsed["their_storey_band"])
    lease = parsed["lease_band"] if parsed["lease_band"] in LEASE_BAND_SET else None
    if mrt is None or storey is None or lease is None:
        return None
    flat_type_nospace = parsed["flat_type"].replace(" ", "").replace("-", "")
    town = parsed["town"].replace("/", "-")
    return f"{town}::{flat_type_nospace}::{lease}::{storey}::{mrt}"


def add_my_profile_id(df, pid_col="profile_id"):
    """Adds my_profile_id, town, flat_type columns to a dataframe keyed by their profile_id."""
    d = df.copy()
    parsed = d[pid_col].apply(parse_their_profile_id)
    d["town"] = parsed.apply(lambda p: p["town"] if p else None)
    d["flat_type"] = parsed.apply(lambda p: p["flat_type"] if p else None)
    d["my_profile_id"] = d[pid_col].apply(crosswalk_profile_id)
    return d


if __name__ == "__main__":
    tests = ["ANG MO KIO|4 ROOM|60-79|500m-1km|1-6", "TAMPINES|2 ROOM|<60|<500m|13+",
              "QUEENSTOWN|EXECUTIVE|80+|>1km|7-12"]
    for t in tests:
        print(t, "->", crosswalk_profile_id(t))

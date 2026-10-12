# -*- coding: utf-8 -*-
"""
Builds the housing-profile table: the shared unit of analysis for all four
workstreams (per the FINAL proposal's "Define indicative housing profiles").

ASSUMPTION (documented in INTERFACE_SPEC.md for the other leads to confirm):
  profile = (town x flat_type x storey_band), storey_band in {Low, Mid, High}
  matching the Low/Mid/High levels already used in the conjoint design.
This keeps the profile count manageable (~450) for a MIP while preserving
the storey-level price/preference variation the hedonic and conjoint models
both need.
"""
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = r"C:\Users\Daniel Loh\Documents\NUS-ISS_EBAC\SPMF\Project"
OUT_DIR = os.path.join(ROOT, "notebooks", "optimization_lead", "data")
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "notebooks"))

STOREY_BANDS = {
    # storey_range lower bound (int) -> band
}


def storey_band(storey_range):
    m = re.match(r"(\d+) TO (\d+)", str(storey_range))
    if not m:
        return None
    lo = int(m.group(1))
    if lo <= 6:
        return "Low"
    elif lo <= 15:
        return "Mid"
    else:
        return "High"


def parse_lease(s):
    m = re.match(r"(\d+)\s*years?(?:\s*(\d+)\s*months?)?", str(s))
    if not m:
        return np.nan
    yrs = int(m.group(1))
    mos = int(m.group(2)) if m.group(2) else 0
    return yrs + mos / 12


def build_profiles(recent_months=12):
    out_path = os.path.join(OUT_DIR, "housing_profiles.csv")
    if os.path.exists(out_path):
        return pd.read_csv(out_path)

    df = pd.read_csv(os.path.join(ROOT, "Resale flat prices based on registration date from Jan-2017 onwards.csv"))
    df["month"] = pd.to_datetime(df["month"], format="%Y-%m")
    df["storey_band"] = df["storey_range"].apply(storey_band)
    df["remaining_lease_yrs"] = df["remaining_lease"].apply(parse_lease)
    df["price_psm"] = df["resale_price"] / df["floor_area_sqm"]

    cutoff = df["month"].max() - pd.DateOffset(months=recent_months - 1)
    recent = df[(df["month"] >= cutoff) & (df["flat_type"] != "MULTI-GENERATION")]

    grp = recent.groupby(["town", "flat_type", "storey_band"]).agg(
        median_price=("resale_price", "median"),
        median_price_psm=("price_psm", "median"),
        median_floor_area=("floor_area_sqm", "median"),
        median_remaining_lease=("remaining_lease_yrs", "median"),
        txn_count_12m=("resale_price", "size"),
    ).reset_index()

    grp = grp[grp["txn_count_12m"] >= 3].copy()  # drop too-thin profiles
    grp["profile_id"] = (grp["town"].str.replace("/", "-") + "::" + grp["flat_type"].str.replace(" ", "")
                          + "::" + grp["storey_band"])

    import data_prep as dp
    geo = dp.build_town_geo_features()
    grp = grp.merge(geo, on="town", how="left")

    cols = ["profile_id", "town", "flat_type", "storey_band", "median_price", "median_price_psm",
            "median_floor_area", "median_remaining_lease", "txn_count_12m",
            "nearest_mrt_km", "mrt_stations_within", "bus_stops_within", "schools_within",
            "nearest_school_km", "hawker_within", "parks_within", "cc_within", "polyclinic_within"]
    grp = grp[[c for c in cols if c in grp.columns]]
    grp.to_csv(out_path, index=False)
    return grp


if __name__ == "__main__":
    profiles = build_profiles()
    print(f"Housing profiles: {len(profiles)} rows (town x flat_type x storey_band, >=3 txns/12mo)")
    print(f"Towns: {profiles['town'].nunique()}, flat types: {profiles['flat_type'].nunique()}, "
          f"storey bands: {profiles['storey_band'].nunique()}")
    print(profiles.head(10).to_string())
    print("\nPrice range:", profiles["median_price"].min(), "-", profiles["median_price"].max())

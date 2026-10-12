"""Housing profiles as they exist at a date: town x flat type x lease band x MRT band x storey band.

A profile describes flats a buyer could buy at `as_of`: lease band uses remaining lease AT as_of, MRT band uses stations open
AT as_of, and only blocks past their 5-year MOP by then are included. Each block x flat type is split across storey bands
by its historical share of sales (or share of floors if it has never sold)."""
import numpy as np, pandas as pd
import config as C
from . import common as K

STOREY_DEFAULT = {"1-6": 4.0, "7-12": 10.0, "13+": 16.0}

def _floor_shares(max_floor):
    floors = pd.Series(np.arange(1, int(max(max_floor, 1)) + 1), dtype=float)
    return pd.Series(K.band(floors, C.STOREY_BANDS)).value_counts(normalize=True)

def profile_rows(as_of):
    """One row per block x flat type x storey band at `as_of`, with its profile_id and share of the block's sales."""
    s = K.stock().copy()
    s = s[s["flat_type"].isin(K.TYPES) & (s["year_completed"] + 5 <= K.year_frac(as_of))]   # resellable by as_of
    s["lease_start"] = s["address"].map(K.lease_start()).fillna(s["year_completed"])
    s["remaining_lease_yrs"] = (99 - (K.year_frac(as_of) - s["lease_start"])).round(2)
    s["dist_mrt_m"] = s["address"].map(K.mrt_distance_as_of(as_of))
    s["lease_band"] = K.band(s["remaining_lease_yrs"], C.LEASE_BANDS)
    s["mrt_band"] = K.band(s["dist_mrt_m"], C.MRT_BANDS)

    hist = K.sales()
    hist = hist[hist["in_scope"] & (hist["month"] <= as_of)]
    hist = hist.assign(storey_band=K.band(hist["storey_mid"], C.STOREY_BANDS))
    g = hist.groupby(["address", "flat_type", "storey_band"])
    shares = (g.size() / hist.groupby(["address", "flat_type"]).size()).rename("share").reset_index()
    shares = shares.merge(g["storey_mid"].median().rename("storey_mid").reset_index(), on=["address", "flat_type", "storey_band"])
    have = set(map(tuple, shares[["address", "flat_type"]].drop_duplicates().values))
    fb = [(r.address, r.flat_type, sb, sh, min(STOREY_DEFAULT[sb], r.max_floor_lvl))
          for r in s.itertuples() if (r.address, r.flat_type) not in have
          for sb, sh in _floor_shares(r.max_floor_lvl).items()]
    shares = pd.concat([shares, pd.DataFrame(fb, columns=shares.columns)], ignore_index=True)

    rows = s.merge(shares, on=["address", "flat_type"], how="inner")
    rows["profile_id"] = (rows["town"] + "|" + rows["flat_type"] + "|" + rows["lease_band"] + "|"
                          + rows["mrt_band"] + "|" + rows["storey_band"])
    return rows.reset_index(drop=True)

def current_profiles(as_of):
    """Profile table at `as_of`: how many blocks/flats, and recent sales of flats that fall in each profile today."""
    rows = profile_rows(as_of)
    p = (rows.assign(units_share=rows["units"] * rows["share"])
             .groupby(["profile_id", "town", "flat_type", "lease_band", "mrt_band", "storey_band"])
             .agg(n_blocks=("address", "nunique"), units=("units_share", "sum")).reset_index())
    p["units"] = p["units"].round(0).astype(int)

    # Map past sales to the profile their flat belongs to TODAY (same block, flat type, storey band)
    hist = K.sales()
    hist = hist[hist["in_scope"] & (hist["month"] <= as_of)]
    hist = hist.assign(storey_band=K.band(hist["storey_mid"], C.STOREY_BANDS))
    key = rows.set_index(["address", "flat_type", "storey_band"])["profile_id"]
    hist = hist.join(key, on=["address", "flat_type", "storey_band"], rsuffix="_now", how="inner")
    t_end = K.month_index(as_of)
    recent = hist[hist["t"] > t_end - 12]
    p = p.merge(hist.groupby("profile_id_now").size().rename("n_transactions_all"), left_on="profile_id", right_index=True, how="left")
    p = p.merge(recent.groupby("profile_id_now").agg(n_last12=("resale_price", "size"), median_price_last12=("resale_price", "median")),
                left_on="profile_id", right_index=True, how="left")
    p[["n_transactions_all", "n_last12"]] = p[["n_transactions_all", "n_last12"]].fillna(0).astype(int)
    return p.sort_values("profile_id").reset_index(drop=True)

"""Housing profiles as they exist at a date.

Two profile schemes share the same machinery:
  "homefit"      town x flat type x lease band x MRT band x storey band        e.g. "TAMPINES|4 ROOM|80+|<500m|7-12"
                 (this repo's hand-over files: profiles.csv, prices_today.csv, expected_wait.csv)
  "optimisation" town x flat type x storey band x MRT band, no lease band       e.g. "TAMPINES::4ROOM::Mid::Near"
                 (the Optimisation Lead's v2 IDs: storey Low 1-6 / Mid 7-15 / High 16+ by the storey range's lower floor;
                 MRT Near <400m / Mid 400-800m / Far >800m)

A profile describes flats a buyer could buy at `as_of`: lease band uses remaining lease AT as_of, MRT band uses stations open
AT as_of, and only blocks past their 5-year MOP by then are included. Each block x flat type is split across storey bands
by its historical share of sales (or share of floors if it has never sold)."""
import numpy as np, pandas as pd
import config as C
from . import common as K

SCHEMES = {
    "homefit": dict(storey_col="storey_mid", storey=C.STOREY_BANDS, mrt=C.MRT_BANDS, lease=C.LEASE_BANDS,
                    storey_default={"1-6": 4.0, "7-12": 10.0, "13+": 16.0}),
    "optimisation": dict(storey_col="storey_lo", storey=[(0, 7, "Low"), (7, 16, "Mid"), (16, 1e3, "High")],
                         mrt=[(0, 400, "Near"), (400, 800, "Mid"), (800, 1e9, "Far")], lease=None,
                         storey_default={"Low": 4.0, "Mid": 11.0, "High": 18.0}),
}

def make_id(d, scheme):
    if scheme == "optimisation":
        return (d["town"].str.replace("/", "-") + "::" + d["flat_type"].str.replace(" ", "") + "::"
                + d["storey_band"] + "::" + d["mrt_band"])
    return d["town"] + "|" + d["flat_type"] + "|" + d["lease_band"] + "|" + d["mrt_band"] + "|" + d["storey_band"]

def _floor_shares(max_floor, sc):
    floors = pd.Series(np.arange(1, int(max(max_floor, 1)) + 1), dtype=float)
    return pd.Series(K.band(floors, sc["storey"])).value_counts(normalize=True)

def sales_with_band(as_of, scheme="homefit"):
    """In-scope sales up to as_of, with the scheme's storey band."""
    sc = SCHEMES[scheme]
    h = K.sales()
    h = h[h["in_scope"] & (h["month"] <= as_of)]
    return h.assign(storey_band=K.band(h[sc["storey_col"]], sc["storey"]))

def profile_rows(as_of, scheme="homefit"):
    """One row per block x flat type x storey band at `as_of`, with its profile_id and share of the block's sales."""
    sc = SCHEMES[scheme]
    s = K.stock().copy()
    s = s[s["flat_type"].isin(K.TYPES) & (s["year_completed"] + 5 <= K.year_frac(as_of))]   # resellable by as_of
    s["lease_start"] = s["address"].map(K.lease_start()).fillna(s["year_completed"])
    s["remaining_lease_yrs"] = (99 - (K.year_frac(as_of) - s["lease_start"])).round(2)
    s["dist_mrt_m"] = s["address"].map(K.mrt_distance_as_of(as_of))
    s["lease_band"] = K.band(s["remaining_lease_yrs"], C.LEASE_BANDS)
    s["mrt_band"] = K.band(s["dist_mrt_m"], sc["mrt"])

    hist = sales_with_band(as_of, scheme)
    g = hist.groupby(["address", "flat_type", "storey_band"])
    shares = (g.size() / hist.groupby(["address", "flat_type"]).size()).rename("share").reset_index()
    shares = shares.merge(g["storey_mid"].median().rename("storey_mid").reset_index(), on=["address", "flat_type", "storey_band"])
    have = set(map(tuple, shares[["address", "flat_type"]].drop_duplicates().values))
    fb = [(r.address, r.flat_type, sb, sh, min(sc["storey_default"][sb], r.max_floor_lvl))
          for r in s.itertuples() if (r.address, r.flat_type) not in have
          for sb, sh in _floor_shares(r.max_floor_lvl, sc).items()]
    shares = pd.concat([shares, pd.DataFrame(fb, columns=shares.columns)], ignore_index=True)

    rows = s.merge(shares, on=["address", "flat_type"], how="inner")
    rows["profile_id"] = make_id(rows, scheme)
    return rows.reset_index(drop=True)

def sales_by_profile(as_of, rows, scheme="homefit"):
    """Past sales (up to as_of) mapped to the profile their flat belongs to AT as_of (same block, flat type, storey band)."""
    key = rows.set_index(["address", "flat_type", "storey_band"])["profile_id"]
    hist = sales_with_band(as_of, scheme)
    if "profile_id" in hist:
        hist = hist.drop(columns="profile_id")
    return hist.join(key, on=["address", "flat_type", "storey_band"], how="inner")

def recent_sales(as_of, rows, scheme="homefit", months=12):
    """Number of sales per profile in the `months` months up to and including as_of."""
    h = sales_by_profile(as_of, rows, scheme)
    return h[h["t"] > K.month_index(as_of) - months].groupby("profile_id").size()

def current_profiles(as_of, scheme="homefit"):
    """Profile table at `as_of`: how many blocks/flats, and recent sales of flats that fall in each profile today."""
    rows = profile_rows(as_of, scheme)
    cols = ["profile_id", "town", "flat_type"] + (["lease_band"] if scheme == "homefit" else []) + ["mrt_band", "storey_band"]
    p = (rows.assign(units_share=rows["units"] * rows["share"]).groupby(cols)
             .agg(n_blocks=("address", "nunique"), units=("units_share", "sum")).reset_index())
    p["units"] = p["units"].round(0).astype(int)
    hist = sales_by_profile(as_of, rows, scheme)
    recent = hist[hist["t"] > K.month_index(as_of) - 12]
    p = p.merge(hist.groupby("profile_id").size().rename("n_transactions_all"), left_on="profile_id", right_index=True, how="left")
    p = p.merge(recent.groupby("profile_id").agg(n_last12=("resale_price", "size"), median_price_last12=("resale_price", "median")),
                left_on="profile_id", right_index=True, how="left")
    p[["n_transactions_all", "n_last12"]] = p[["n_transactions_all", "n_last12"]].fillna(0).astype(int)
    return p.sort_values("profile_id").reset_index(drop=True)

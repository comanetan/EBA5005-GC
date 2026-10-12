"""Shared loaders and helpers (cached, so repeated as-of calls in a backtest stay fast)."""
from functools import lru_cache
import numpy as np, pandas as pd
import config as C

TYPES = ["2 ROOM", "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE"]
PROP_COLS = {"2room_sold": "2 ROOM", "3room_sold": "3 ROOM", "4room_sold": "4 ROOM", "5room_sold": "5 ROOM", "exec_sold": "EXECUTIVE"}

def month_index(m):
    """'2017-01' -> integer months (works on a string or a Series)."""
    if isinstance(m, str):
        return int(m[:4]) * 12 + int(m[5:7]) - 1
    return m.str[:4].astype(int) * 12 + m.str[5:7].astype(int) - 1

def month_str(i):
    return f"{int(i) // 12}-{int(i) % 12 + 1:02d}"

def year_frac(m):
    return int(m[:4]) + (int(m[5:7]) - 1) / 12

def band(x, bands):
    edges = [b[0] for b in bands] + [bands[-1][1]]
    return pd.cut(pd.Series(x, dtype=float), edges, labels=[b[2] for b in bands], right=False).astype(str).to_numpy()

def latest_complete_month():
    s = sales()
    return s.loc[~s["partial_month"], "month"].max()

@lru_cache(maxsize=None)
def sales():
    """All resale rows with features (step 4 output). Filter by month <= as_of before use."""
    d = pd.read_csv(C.PROCESSED / "resale_features.csv", dtype={"block": str}, low_memory=False)
    d["t"] = month_index(d["month"])
    return d

@lru_cache(maxsize=None)
def blocks():
    return pd.read_csv(C.PROCESSED / "block_features.csv", dtype={"block": str})

@lru_cache(maxsize=None)
def stock():
    """Block x flat type with units sold (HDB Property Information), for geocoded blocks."""
    p = pd.read_csv(C.PROPINFO, dtype={"blk_no": str})
    p = p[p["residential"] == "Y"].copy()
    p["address"] = (p["blk_no"].str.strip().str.upper() + " "
                    + p["street"].str.strip().str.upper().str.replace(r"\s+", " ", regex=True))
    s = (p.melt(id_vars=["address", "year_completed", "max_floor_lvl", "bldg_contract_town"], value_vars=list(PROP_COLS),
                var_name="col", value_name="units")
           .query("units > 0").assign(flat_type=lambda d: d["col"].map(PROP_COLS)).drop(columns="col"))
    b = blocks()[["address", "town", "lat", "lon"]]
    return s.merge(b, on="address", how="inner")          # only blocks with coordinates

@lru_cache(maxsize=None)
def _station_distances():
    """Blocks x MRT stations (metres, nearest exit of each station) and each station's opening date."""
    pts = pd.read_csv(C.AMENITY_POINTS)
    ex = pts[pts["type"] == "mrt_exit"].copy()
    ex["station"] = ex["name"].str.replace(r"\s+Mrt Station$", "", regex=True).str.strip().str.lower()
    op = pd.read_csv(C.MRT_OPENINGS)
    opened = dict(zip(op["station"].str.lower(), pd.to_datetime(op["opened"])))
    b = blocks()
    stations = np.array(sorted(ex["station"].unique()))
    lat1, lon1 = np.radians(b["lat"].to_numpy(float))[:, None], np.radians(b["lon"].to_numpy(float))[:, None]
    D = np.empty((len(b), len(stations)))
    for j, st in enumerate(stations):
        e = ex[ex["station"] == st]
        lat2, lon2 = np.radians(e["lat"].to_numpy(float))[None, :], np.radians(e["lon"].to_numpy(float))[None, :]
        a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
        D[:, j] = (2 * 6_371_000 * np.arcsin(np.sqrt(a))).min(1)
    return b["address"].to_numpy(), D, stations, pd.Series(stations).map(opened).to_numpy()

def mrt_distance_as_of(as_of):
    """Distance from every block to the nearest MRT station open when month `as_of` began."""
    addr, D, stations, opened = _station_distances()
    start = pd.Timestamp(as_of + "-01")
    ok = np.array([pd.isna(o) or o < start for o in opened])
    return pd.Series(D[:, ok].min(1).round(0), index=addr, name="dist_mrt_m")

@lru_cache(maxsize=None)
def lease_start():
    """Lease commencement year per block (from resale records; never-resold blocks fall back to completion year)."""
    return sales().groupby("address")["lease_commence_date"].agg(lambda s: s.mode()[0])

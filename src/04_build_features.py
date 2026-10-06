"""Step 4 (offline, run after step 2): join coordinates, compute location features, assign profile bands.
Outputs:
  data/processed/block_features.csv   one row per block: coordinates + distances/counts + HDB block attributes
  data/processed/resale_features.csv  one row per transaction, model-ready (hedonic, survival, backtest)
  outputs/profiles.csv                shared handover: profile_id + band definitions (+ recent counts)
  outputs/prices_today.csv            PLACEHOLDER for the rough version: median price per profile, last 12 months
  outputs/expected_wait.csv           PLACEHOLDER: 12 / transactions in last 12 months (naive rate)"""
import numpy as np, pandas as pd
import config as C
# Requires step 1b (cleaning) to have run: reads data/interim/resale_clean.csv

R_EARTH = 6_371_000.0

def haversine_matrix(lat1, lon1, lat2, lon2):
    """Distances in metres between every point in set 1 (rows) and set 2 (columns)."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1[:, None], lon1[:, None], lat2[None, :], lon2[None, :]))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * R_EARTH * np.arcsin(np.sqrt(a))

def nearest_and_count(blocks, pts, radius=None, chunk=1500):
    """For each block: distance to nearest point, index of that point, and count within `radius` metres."""
    blat, blon, plat, plon = (blocks["lat"].to_numpy(float), blocks["lon"].to_numpy(float),
                              pts["lat"].to_numpy(float), pts["lon"].to_numpy(float))
    dmin, imin, cnt = np.empty(len(blat)), np.empty(len(blat), int), np.zeros(len(blat), int)
    for s in range(0, len(blat), chunk):
        d = haversine_matrix(blat[s:s + chunk], blon[s:s + chunk], plat, plon)
        imin[s:s + chunk] = d.argmin(1); dmin[s:s + chunk] = d.min(1)
        if radius:
            cnt[s:s + chunk] = (d <= radius).sum(1)
    return dmin, imin, cnt

def band(x, bands):
    out = pd.Series(pd.NA, index=x.index, dtype="object")
    for lo, hi, label in bands:
        out[(x >= lo) & (x < hi)] = label
    return out

def lease_years(s):
    yrs = s.str.extract(r"(\d+)\s*year").astype(float)[0]
    mths = s.str.extract(r"(\d+)\s*month").astype(float)[0].fillna(0)
    return (yrs + mths / 12).round(2)

def mrt_station_points(pts):
    """MRT exits from the LTA file, plus stations missing from it (station point from OneMap), with opening dates."""
    ex = pts[pts["type"] == "mrt_exit"].copy()
    ex["station"] = ex["name"].str.replace(r"\s+Mrt Station$", "", regex=True).str.strip().str.lower()
    op = pd.read_csv(C.MRT_OPENINGS)
    op["station_key"] = op["station"].str.lower()
    extra = op[op["in_exit_file"] == "N"].rename(columns={"station_key": "_s"})
    ex = pd.concat([ex[["station", "lat", "lon"]],
                    pd.DataFrame({"station": extra["_s"], "lat": extra["lat"], "lon": extra["lon"]})], ignore_index=True)
    opened = dict(zip(op["station_key"], pd.to_datetime(op["opened"])))
    ex["opened"] = ex["station"].map(opened)                 # NaT = open before 2017
    return ex

def block_station_distances(b, mrt):
    d = np.empty((len(b), mrt["station"].nunique()))
    stations = np.array(sorted(mrt["station"].unique()))
    blat, blon = b["lat"].to_numpy(float), b["lon"].to_numpy(float)
    for j, st in enumerate(stations):
        e = mrt[mrt["station"] == st]
        d[:, j] = haversine_matrix(blat, blon, e["lat"].to_numpy(float), e["lon"].to_numpy(float)).min(1)
    return d, stations

def mrt_distance_at_sale(b, D, stations, mrt, months):
    """Nearest MRT among stations already open when the sale month began (a station opening mid-month counts next month)."""
    opened = mrt.drop_duplicates("station").set_index("station")["opened"].reindex(stations)
    rows = []
    for m in sorted(months):
        start = pd.Timestamp(m + "-01")
        open_mask = (opened.isna() | (opened < start)).to_numpy()
        dm = D[:, open_mask]
        rows.append(pd.DataFrame({"address": b["address"], "month": m, "dist_mrt_at_sale_m": dm.min(1).round(0),
                                  "nearest_mrt_at_sale": stations[open_mask][dm.argmin(1)]}))
    return pd.concat(rows, ignore_index=True)

def main(geocode_cache=C.GEOCODE_CACHE, processed=C.PROCESSED, outputs=C.OUTPUTS):
    processed.mkdir(parents=True, exist_ok=True); outputs.mkdir(parents=True, exist_ok=True)

    # --- coordinates
    geo = pd.read_csv(geocode_cache, dtype={"key": str, "postal": str})
    blocks_geo = geo[geo["kind"] == "block"].rename(columns={"key": "address"})
    schools_geo = geo[(geo["kind"] == "school") & geo["lat"].notna()]
    addr = pd.read_csv(C.UNIQUE_ADDR, dtype=str).merge(
        blocks_geo[["address", "lat", "lon", "postal", "match_quality"]], on="address", how="left")
    ok = addr["lat"].notna()
    print(f"Blocks with coordinates: {ok.sum():,}/{len(addr):,}  "
          f"(quality: {addr['match_quality'].value_counts(dropna=False).to_dict()})")

    # --- location features per block
    pts = pd.read_csv(C.AMENITY_POINTS)
    b = addr[ok].copy().reset_index(drop=True)
    mrt = mrt_station_points(pts)
    D, stations = block_station_distances(b, mrt)           # blocks x stations, nearest exit of each station
    b["dist_mrt_now_m"] = D.min(1).round(0)                  # today's network (used for profile bands)
    b["nearest_mrt_now"] = stations[D.argmin(1)]
    b["dist_mrt_lrt_m"] = np.minimum(b["dist_mrt_now_m"],
                                     nearest_and_count(b, pts[pts["type"] == "lrt_exit"])[0]).round(0)
    b["dist_hawker_m"] = nearest_and_count(b, pts[pts["type"] == "hawker"])[0].round(0)
    for kind, col in [("chas_clinic", "n_chas_500m"), ("preschool", "n_preschool_500m")]:
        b[col] = nearest_and_count(b, pts[pts["type"] == kind], C.AMENITY_RADIUS_M)[2]
    if (pts["type"] == "park").any():
        b["dist_park_m"] = nearest_and_count(b, pts[pts["type"] == "park"])[0].round(0)
    for kind, label in [("school", "primary"), ("polyclinic", "polyclinic"), ("supermarket", "supermarket")]:
        g = geo[(geo["kind"] == kind) & geo["lat"].notna()]
        if len(g) == 0:
            if kind == "school": print("WARNING: no geocoded schools yet; school features skipped")
            continue
        radius = C.SCHOOL_RADIUS_M if kind == "school" else C.AMENITY_RADIUS_M
        d, _, n = nearest_and_count(b, g, radius)
        b[f"dist_{label}_m"] = d.round(0)
        b[f"n_{label}_{'1km' if kind == 'school' else '500m'}"] = n

    # --- HDB block attributes (units by flat type -> survival exposure; year completed -> MOP supply)
    prop = pd.read_csv(C.PROPINFO, dtype={"blk_no": str})
    prop["address"] = (prop["blk_no"].str.strip().str.upper() + " "
                       + prop["street"].str.strip().str.upper().str.replace(r"\s+", " ", regex=True))
    keep = ["address", "year_completed", "max_floor_lvl", "total_dwelling_units", "market_hawker",
            "1room_sold", "2room_sold", "3room_sold", "4room_sold", "5room_sold", "exec_sold", "multigen_sold"]
    b = b.merge(prop[keep].drop_duplicates("address"), on="address", how="left")
    print(f"Blocks matched to HDB Property Information: {b['year_completed'].notna().sum():,}/{len(b):,}")
    b.to_csv(processed / "block_features.csv", index=False)

    # --- transaction-level features (from the cleaned, validated file made by step 1b)
    df = pd.read_csv(C.RESALE_CLEAN, dtype={"block": str})
    loc_cols = [c for c in b.columns if c.startswith(("dist_", "n_", "nearest_"))] + ["lat", "lon", "year_completed", "max_floor_lvl"]
    df = df.merge(b[["address"] + loc_cols], on="address", how="left")
    df = df.merge(mrt_distance_at_sale(b, D, stations, mrt, df["month"].unique()), on=["address", "month"], how="left")
    df["lease_band"] = band(df["remaining_lease_yrs"], C.LEASE_BANDS)
    df["mrt_band"] = band(df["dist_mrt_now_m"], C.MRT_BANDS)   # profiles describe flats as they are today
    df["storey_band"] = band(df["storey_mid"], C.STOREY_BANDS)
    df["profile_id"] = (df["town"] + "|" + df["flat_type"] + "|" + df["lease_band"].astype(str) + "|"
                        + df["mrt_band"].astype(str) + "|" + df["storey_band"].astype(str))
    df.loc[df["mrt_band"].isna() | ~df["in_scope"], "profile_id"] = pd.NA   # no coordinates yet, or out of scope
    df.to_csv(processed / "resale_features.csv", index=False)
    print(f"Transactions with a profile: {df['profile_id'].notna().sum():,}/{len(df):,}")

    # --- shared handover files
    last12 = sorted(df["month"].unique())[-13:-1]                 # 12 most recent COMPLETE months
    recent = df[df["month"].isin(last12) & df["profile_id"].notna()]
    prof = (df[df["profile_id"].notna()]
              .groupby(["profile_id", "town", "flat_type", "lease_band", "mrt_band", "storey_band"])
              .size().reset_index(name="n_transactions_all"))
    stats = recent.groupby("profile_id").agg(n_last12=("resale_price", "size"),
                                             median_price_last12=("resale_price", "median")).reset_index()
    prof = prof.merge(stats, on="profile_id", how="left").fillna({"n_last12": 0})
    prof.to_csv(outputs / "profiles.csv", index=False)
    # Placeholders for the rough version: written only if the real model output doesn't exist yet
    if not (outputs / "prices_today.csv").exists():
        (prof.dropna(subset=["median_price_last12"])
             .rename(columns={"median_price_last12": "price"})[["profile_id", "price"]]
             .to_csv(outputs / "prices_today.csv", index=False))
    if not (outputs / "expected_wait.csv").exists():
        prof.assign(wait_months=(12 / prof["n_last12"].clip(lower=1)).round(1))[["profile_id", "wait_months"]] \
            .to_csv(outputs / "expected_wait.csv", index=False)
    print(f"{len(prof):,} profiles ({(prof['n_last12'] >= 5).sum():,} with 5+ sales in the last 12 months: "
          f"{last12[0]} to {last12[-1]})")
    return b, df, prof

if __name__ == "__main__":
    main()

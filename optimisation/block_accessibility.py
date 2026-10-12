# -*- coding: utf-8 -*-
"""
Block-level accessibility: true per-block distances from every geocoded HDB
block to every amenity layer, replacing the town-centroid averages.

Distances are great-circle (haversine) via a BallTree -- straight-line, not
walking-network distance. Straight-line understates real walking distance
by roughly 20-40% in HDB estates; treat bands as relative, not absolute,
walking times (documented limitation).

Rail:
  - CURRENT access uses LTA's MRT/LRT station-exit layer (Dec 2025, 190
    operating stations). Exit distance is closer to real walking access than
    a station centroid.
  - FUTURE access uses Master Plan 2019 rail stations NOT in the operating
    exit layer (e.g. Jurong Region Line: Tengah, Tengah Park, Bahar Junction)
    -- kept as a separate feature, never mixed into current access.
"""
import json
import os

import numpy as np
import pandas as pd
from shapely.geometry import shape
from sklearn.neighbors import BallTree

ROOT = r"C:\Users\Daniel Loh\Documents\NUS-ISS_EBAC\SPMF\Project"
GEO = os.path.join(ROOT, "data", "geospatial")
PROC = os.path.join(ROOT, "data", "processed")
OUT = os.path.join(ROOT, "notebooks", "optimization_lead", "data")
os.makedirs(OUT, exist_ok=True)
EARTH_KM = 6371.0


def _geojson_points(fname, filt=None):
    d = json.load(open(os.path.join(GEO, fname), encoding="utf-8"))
    rows = []
    for f in d["features"]:
        if filt and not filt(f["properties"]):
            continue
        g = shape(f["geometry"])
        c = g if g.geom_type == "Point" else g.centroid
        rows.append({"lat": c.y, "lon": c.x, "name": f["properties"].get("NAME") or f["properties"].get("STATION_NA")})
    return pd.DataFrame(rows)


def _postal_points(cache_name):
    d = pd.read_csv(os.path.join(PROC, cache_name))
    d = d[d["status"] == "OK"] if "status" in d.columns else d.dropna(subset=["latitude"])
    return d.rename(columns={"latitude": "lat", "longitude": "lon"})[["lat", "lon"]]


# which walking-distance file to merge (compute_walk_distances.py output; *_connect25m.csv = OSM gaps bridged)
WALK_FILE = os.environ.get("BLOCK_WALK_FILE", "block_walk_distances_connect25m.csv")

# Operating stations missing from LTA's exit layer (last updated 17 Jul 2026),
# found by patch_missing_exits.py via OneMap. Opening dates verified via LTA /
# Land Transport Guru, so sales before opening don't get credited with them.
PATCH_OPENING_DATES = {
    "PUNGGOL COAST MRT STATION": "2024-12-10",
    "HUME MRT STATION": "2025-02-28",
    "KEPPEL MRT STATION": "2026-07-12",
    "CANTONMENT MRT STATION": "2026-07-12",
    "PRINCE EDWARD ROAD MRT STATION": "2026-07-12",
}

# Stations IN the LTA layer that opened during the 2017+ resale window. Interchanges whose
# other line was already running (Woodlands, Caldecott, Stevens, Orchard, Outram Park, Marina Bay,
# MacPherson, Tampines, Expo) are treated as open throughout.
_DTL3 = ["FORT CANNING", "BENCOOLEN", "JALAN BESAR", "BENDEMEER", "GEYLANG BAHRU", "MATTAR", "UBI", "KAKI BUKIT",
         "BEDOK NORTH", "BEDOK RESERVOIR", "TAMPINES WEST", "TAMPINES EAST", "UPPER CHANGI"]
_TEL1 = ["WOODLANDS NORTH", "WOODLANDS SOUTH"]
_TEL2 = ["SPRINGLEAF", "LENTOR", "MAYFLOWER", "BRIGHT HILL", "UPPER THOMSON"]
_TEL3 = ["NAPIER", "ORCHARD BOULEVARD", "GREAT WORLD", "HAVELOCK", "MAXWELL", "SHENTON WAY", "GARDENS BY THE BAY"]
_TEL4 = ["TANJONG RHU", "KATONG PARK", "TANJONG KATONG", "MARINE PARADE", "MARINE TERRACE", "SIGLAP", "BAYSHORE"]
LTA_OPENING_DATES = {f"{s} MRT STATION": d for group, d in [
    (_DTL3, "2017-10-21"), (["CANBERRA"], "2019-11-02"), (_TEL1, "2020-01-31"), (_TEL2, "2021-08-28"),
    (_TEL3, "2022-11-13"), (_TEL4, "2024-06-23")] for s in group}


def load_amenity_layers():
    exits = _geojson_points("LTA_MRT_Station_Exit.geojson")
    # NaT = open for the whole 2017+ window
    exits["opened"] = pd.to_datetime(exits["name"].map(LTA_OPENING_DATES))
    patch_path = os.path.join(GEO, "MRT_exits_patch_onemap.geojson")
    if os.path.exists(patch_path):
        patch = _geojson_points("MRT_exits_patch_onemap.geojson")
        patch["opened"] = pd.to_datetime(patch["name"].map(PATCH_OPENING_DATES))
        exits = pd.concat([exits, patch], ignore_index=True)
    exits["station"] = exits["name"].astype(str)
    mrt_exits = exits[exits["station"].str.contains("MRT")]
    lrt_exits = exits[exits["station"].str.contains("LRT")]

    def norm(s):
        return (s.astype(str).str.upper().str.strip()
                .str.replace(r"\s+(MRT|LRT)?\s*(STATION|INTERCHANGE)$", "", regex=True)
                .str.replace(r"\s+(MRT|LRT)$", "", regex=True)
                .str.replace(r"[^A-Z ]", "", regex=True).str.strip())

    operating = set(norm(exits["station"]))
    mp19 = _geojson_points("MasterPlan2019_Rail_Station_Layer.geojson")
    mp19 = mp19[mp19["name"].notna() & (mp19["name"].astype(str).str.strip() != "<Null>")]
    mp19["norm"] = norm(mp19["name"])
    # "planned" = in the Master Plan but absent from LTA's operating exit layer.
    # Caveat: the exit layer can lag very recent openings, so a handful of
    # just-opened stations may land here too -- treated as future-access only.
    planned = mp19[~mp19["norm"].isin(operating)]

    schools = pd.read_csv(os.path.join(GEO, "General_Information_of_Schools.csv"))
    schools["postal_code"] = schools["postal_code"].astype(str).str.zfill(6)
    sgeo = pd.read_csv(os.path.join(PROC, "schools_geocoded_v2.csv"))
    sgeo["postal_code"] = sgeo["postal_code"].astype(str).str.zfill(6)
    schools = schools.merge(sgeo[sgeo["status"] == "OK"], on="postal_code", how="inner")
    # Only schools that take P1 pupils: PRIMARY, or MIXED LEVEL starting at P1.
    # (Earlier filter "PRIMARY|MIXED" wrongly included 11 secondary/JC schools
    # such as Hwa Chong Institution and Dunman High.)
    primary = schools[schools["mainlevel_code"].str.contains(r"PRIMARY|\(P1", na=False)].rename(
        columns={"latitude": "lat", "longitude": "lon"})
    # Popularity proxy: SAP or GEP primary schools are typically oversubscribed at P1.
    elite = primary[(primary["sap_ind"] == "Yes") | (primary["gifted_ind"] == "Yes")]

    # Secondary schools: same dataset, mainlevel_code "SECONDARY (S1-S5/S4)" or a MIXED LEVEL
    # that starts at S1 (excludes JC-only and P1-S4 mixed levels, which don't take S1 intake).
    secondary = schools[schools["mainlevel_code"].str.contains(r"SECONDARY|\(S1", na=False)].rename(
        columns={"latitude": "lat", "longitude": "lon"})
    # Popularity proxy for secondary: autonomous or IP (Integrated Programme) status --
    # the closest secondary-level analogue to SAP/GEP's P1 oversubscription signal.
    secondary_elite = secondary[(secondary["autonomous_ind"] == "Yes") | (secondary["ip_ind"] == "Yes")]

    layers = {
        "mrt_exit": mrt_exits[["lat", "lon"]],
        "mrt_exit_base": mrt_exits[mrt_exits["opened"].isna()][["lat", "lon"]],  # open throughout 2017+
        "lrt_exit": lrt_exits[["lat", "lon"]],
        "planned_rail": planned[["lat", "lon"]],
        "bus_stop": _geojson_points("LTA_Bus_Stop.geojson")[["lat", "lon"]],
        "primary_school": primary[["lat", "lon"]],
        "primary_elite": elite[["lat", "lon"]],
        "secondary_school": secondary[["lat", "lon"]],
        "secondary_elite": secondary_elite[["lat", "lon"]],
        "hawker": _geojson_points("Hawker_Centres.geojson")[["lat", "lon"]],
        "supermarket": _postal_points("supermarkets_geocoded_v2.csv"),
        "chas_clinic": _geojson_points("CHAS_Clinics.geojson")[["lat", "lon"]],
        "polyclinic": _geojson_points("Vaccination_Polyclinics.geojson")[["lat", "lon"]],
        "park": _geojson_points("Parks.geojson")[["lat", "lon"]],
        "childcare": _postal_points("childcare_postal_geocoded_v2.csv"),
        "community_club": _geojson_points("Community_Clubs.geojson")[["lat", "lon"]],
    }

    # Carparks -- HDB Carpark Information (data.gov.sg d_23f946fa557947f93a8043bbef41dd09),
    # SVY21 x_coord/y_coord reprojected to WGS84 via pyproj (see fetch_extra_attributes.py).
    cp_path = os.path.join(PROC, "hdb_carpark_latlon.csv")
    if os.path.exists(cp_path):
        cp = pd.read_csv(cp_path).rename(columns={"latitude": "lat", "longitude": "lon"})
        layers["carpark"] = cp[["lat", "lon"]]
        layers["carpark_night"] = cp[cp["night_parking"] == "YES"][["lat", "lon"]]

    # Flood-prone road segments -- PUB's published list, free-text locations geocoded via
    # OneMap search (see fetch_extra_attributes.py). Point proxy for a NAMED ROAD/junction
    # with a documented flooding history, not a flood-extent polygon -- treat as a coarse flag.
    fp_path = os.path.join(ROOT, "notebooks", "optimization_lead", "data", "flood_prone_geocoded.csv")
    if os.path.exists(fp_path):
        fp = pd.read_csv(fp_path)
        fp = fp[fp["status"] == "OK"]
        layers["flood_prone"] = fp.rename(columns={"latitude": "lat", "longitude": "lon"})[["lat", "lon"]]

    # Expressway/trunk-road vertices (OSM via osmnx) -- straight-line distance to the
    # nearest sampled point on a motorway/trunk road, a noise/traffic-exposure proxy.
    ex_path = os.path.join(ROOT, "notebooks", "optimization_lead", "data", "expressway_points.csv")
    if os.path.exists(ex_path):
        layers["expressway"] = pd.read_csv(ex_path)

    # Decentralised employment nodes -- geocoded once (see fetch_extra_attributes.py).
    # Kept OUT of the generic nearest-point `layers` loop below: each node is named and
    # reported as its own column, not pooled into one "nearest business district" number.
    jn_path = os.path.join(ROOT, "notebooks", "optimization_lead", "data", "job_nodes.csv")
    job_nodes = pd.read_csv(jn_path) if os.path.exists(jn_path) else pd.DataFrame()
    # stations opened 2017+, one layer per opening date (for as-of distances)
    for d, g in mrt_exits[mrt_exits["opened"].notna()].groupby("opened"):
        layers[f"mrt_exit_opened_{d:%Y%m%d}"] = g[["lat", "lon"]]
    meta = {"n_operating_mrt_stations": mrt_exits["station"].nunique(),
            "n_operating_lrt_stations": lrt_exits["station"].nunique(),
            "patched_stations": sorted(mrt_exits.loc[mrt_exits["station"].isin(PATCH_OPENING_DATES), "station"].unique().tolist()),
            "dated_stations": mrt_exits[mrt_exits["opened"].notna()].groupby("station")["opened"].first()
                              .dt.strftime("%Y-%m-%d").to_dict(),
            "n_primary_schools": len(primary), "n_elite_primary": len(elite),
            "elite_primary_names": sorted(elite["school_name"].tolist()),
            "n_secondary_schools": len(secondary), "n_elite_secondary": len(secondary_elite),
            "elite_secondary_names": sorted(secondary_elite["school_name"].tolist()),
            "planned_station_names": sorted(planned["norm"].unique().tolist()),
            "job_nodes": job_nodes}
    return layers, meta


# radius-count specs: (layer, radius_km) -> column name
RADIUS_COUNTS = [
    ("bus_stop", 0.4), ("primary_school", 1.0), ("primary_school", 2.0), ("primary_elite", 1.0),
    ("primary_elite", 2.0), ("hawker", 1.0), ("supermarket", 1.0), ("chas_clinic", 0.5), ("park", 1.0),
    ("childcare", 0.5), ("childcare", 1.0), ("childcare", 2.0), ("mrt_exit", 0.8),
    ("secondary_school", 1.0), ("secondary_school", 2.0), ("secondary_elite", 2.0),
    ("carpark", 0.4), ("carpark_night", 0.4), ("flood_prone", 0.3), ("flood_prone", 0.5),
]


def tier(n_1km, n_2km):
    """MOE P1 home-school distance categories (straight-line, as MOE uses)."""
    return np.where(n_1km > 0, "Within 1km", np.where(n_2km > 0, "1-2km", "Beyond 2km"))


def mrt_dist_as_of(df, as_of, prefix="dist"):
    """Distance to the nearest MRT exit that was OPEN on `as_of` (scalar or Series of dates).
    prefix="dist" -> straight-line; prefix="walk" -> walking network."""
    cols = sorted(c for c in df.columns if c.startswith(f"{prefix}_mrt_exit_opened_"))
    d = df[f"{prefix}_mrt_exit_base_km"].copy()
    as_of = pd.to_datetime(as_of)
    for c in cols:
        opened = pd.Timestamp(c.replace(f"{prefix}_mrt_exit_opened_", "").replace("_km", ""))
        open_mask = (as_of >= opened) if np.ndim(as_of) else (as_of >= opened)
        d = np.where(open_mask, np.minimum(d, df[c]), d)
    return pd.Series(d, index=df.index)


def band(dist_km):
    return pd.cut(dist_km, [-1, 0.4, 0.8, 99], labels=["Near", "Mid", "Far"])


def build_block_accessibility():
    out_path = os.path.join(OUT, "block_accessibility.csv")

    blocks = pd.read_csv(os.path.join(ROOT, "HDBPropertyInformation.csv"))
    blocks["query"] = blocks["blk_no"].astype(str) + " " + blocks["street"]
    geo = pd.read_csv(os.path.join(PROC, "hdb_blocks_geocoded.csv"))
    blocks = blocks.merge(geo[geo["status"] == "OK"][["query", "latitude", "longitude"]], on="query", how="inner")
    blocks = blocks.rename(columns={"latitude": "lat", "longitude": "lon"})

    layers, meta = load_amenity_layers()
    X = np.radians(blocks[["lat", "lon"]].values)

    for name, pts in layers.items():
        if pts.empty:
            continue
        tree = BallTree(np.radians(pts[["lat", "lon"]].values), metric="haversine")
        dist, _ = tree.query(X, k=1)
        blocks[f"dist_{name}_km"] = dist[:, 0] * EARTH_KM

    for name, r_km in RADIUS_COUNTS:
        if name not in layers or layers[name].empty:
            continue
        tree = BallTree(np.radians(layers[name][["lat", "lon"]].values), metric="haversine")
        blocks[f"n_{name}_{int(r_km*1000)}m"] = tree.query_radius(X, r=r_km / EARTH_KM, count_only=True)

    # Decentralised employment nodes: one named column per node (not pooled), plus the
    # closest of them -- straight-line proxy distance, NOT a real transit travel time (that
    # would need LTA's GTFS feed or an authenticated OneMap routing token, neither available
    # here -- see OPTIMISER_METHODOLOGY_REPORT.md for the caveat).
    job_nodes = meta.get("job_nodes")
    if job_nodes is not None and not job_nodes.empty:
        jn_ok = job_nodes[job_nodes["status"] == "OK"]
        node_cols = []
        for _, n in jn_ok.iterrows():
            tree = BallTree(np.radians([[n["lat"], n["lon"]]]), metric="haversine")
            dist, _ = tree.query(X, k=1)
            col = f"dist_{n['node']}_km"
            blocks[col] = dist[:, 0] * EARTH_KM
            node_cols.append(col)
        if node_cols:
            blocks["dist_nearest_job_node_km"] = blocks[node_cols].min(axis=1)
            blocks["nearest_job_node"] = blocks[node_cols].idxmin(axis=1).str.replace("dist_", "").str.replace("_km", "")

    blocks["dist_rail_exit_km"] = blocks[["dist_mrt_exit_km", "dist_lrt_exit_km"]].min(axis=1)
    blocks["mrt_band"] = band(blocks["dist_mrt_exit_km"])
    blocks["primary_tier"] = tier(blocks["n_primary_school_1000m"], blocks["n_primary_school_2000m"])
    blocks["elite_primary_tier"] = tier(blocks["n_primary_elite_1000m"], blocks["n_primary_elite_2000m"])
    # NOTE: unlike primary school, MOE does not give secondary-school priority by home
    # distance (S1 posting is PSLE-score-based via a separate points system) -- this tier
    # is a walkability convenience label only, not a MOE admission-priority band.
    blocks["secondary_tier"] = tier(blocks["n_secondary_school_1000m"], blocks["n_secondary_school_2000m"])
    blocks["childcare_tier"] = tier(blocks["n_childcare_1000m"], blocks["n_childcare_2000m"])
    # 1km/2km is saturated for childcare (every block has one within 1km) -> finer bands are the informative cut
    blocks["childcare_band"] = pd.cut(blocks["dist_childcare_km"], [-1, 0.2, 0.5, 99],
                                      labels=["Within 200m", "200-500m", "Beyond 500m"]).astype(str)

    if "dist_flood_prone_km" in blocks:
        # <=300m of a PUB-listed flood-prone road/junction. A coarse point-proxy flag (see
        # load_amenity_layers' note), not a flood-risk model -- most PUB-listed locations
        # are private/landed or CBD roads, so this will be False for most HDB blocks.
        blocks["near_flood_prone_area"] = blocks["dist_flood_prone_km"] <= 0.3
    if "dist_expressway_km" in blocks:
        # Straight-line distance to the nearest motorway/trunk-road OSM vertex -- a traffic
        # noise/exposure proxy, not a measured noise level (no public dB dataset covers this).
        blocks["expressway_proximity_band"] = pd.cut(
            blocks["dist_expressway_km"], [-1, 0.15, 0.4, 99],
            labels=["Within 150m (likely audible)", "150-400m", "Beyond 400m"]).astype(str)
    if "dist_carpark_km" in blocks:
        blocks["has_carpark_400m"] = blocks.get("n_carpark_400m", 0) > 0
        blocks["has_night_parking_400m"] = blocks.get("n_carpark_night_400m", 0) > 0

    # walking-network distances, if walk_network.py has produced them
    walk_path = os.path.join(OUT, WALK_FILE)
    if os.path.exists(walk_path):
        blocks = blocks.merge(pd.read_csv(walk_path), on="query", how="left")
        if "walk_mrt_exit_km" in blocks:
            blocks["mrt_band_walk"] = band(blocks["walk_mrt_exit_km"])

    blocks.to_csv(out_path, index=False)
    return blocks, meta


if __name__ == "__main__":
    b, meta = build_block_accessibility()
    print(f"Blocks with accessibility: {len(b)} (residential: {(b['residential']=='Y').sum()})")
    print("Operating MRT stations:", meta["n_operating_mrt_stations"], "| LRT:", meta["n_operating_lrt_stations"])
    print("Planned (not yet operating) stations:", meta["planned_station_names"])
    dcols = [c for c in b.columns if c.startswith("dist_")]
    print(b.loc[b["residential"] == "Y", dcols].describe().T[["mean", "25%", "50%", "75%", "max"]].round(3))
    print(b.loc[b["residential"] == "Y", "mrt_band"].value_counts())

# -*- coding: utf-8 -*-
"""
Extends the Option A/B town-level geo features with the facility layers the
FINAL Option B proposal explicitly lists: Supermarket Licences, CHAS Clinics,
Childcare & Kindergarten Centres (in addition to the MRT/bus/hawker/parks/
schools/polyclinics/community-clubs already built).
"""
import json
import math
import os
import time
import urllib.parse
import urllib.request

import pandas as pd
from shapely.geometry import shape, Point

ROOT = r"C:\Users\Daniel Loh\Documents\NUS-ISS_EBAC\SPMF\Project"
GEO_DIR = os.path.join(ROOT, "data", "geospatial")
PROC = os.path.join(ROOT, "data", "processed")
OUT_DIR = os.path.join(ROOT, "notebooks", "optimization_lead", "data")
os.makedirs(OUT_DIR, exist_ok=True)


def haversine_km(lon1, lat1, lon2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def geocode_by_postal(df, postal_col, cache_name):
    cache_path = os.path.join(PROC, cache_name)
    if os.path.exists(cache_path):
        return pd.read_csv(cache_path)

    lats, lons = [], []
    for i, postal in enumerate(df[postal_col].astype(str).str.extract(r"(\d{6})")[0]):
        if pd.isna(postal):
            lats.append(None); lons.append(None); continue
        try:
            url = ("https://www.onemap.gov.sg/api/common/elastic/search?"
                   + urllib.parse.urlencode({"searchVal": postal, "returnGeom": "Y",
                                              "getAddrDetails": "N", "pageNum": "1"}))
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("found", 0) > 0:
                r = payload["results"][0]
                lats.append(float(r["LATITUDE"])); lons.append(float(r["LONGITUDE"]))
            else:
                lats.append(None); lons.append(None)
        except Exception:
            lats.append(None); lons.append(None)
        if i % 100 == 0:
            print(f"  geocoded {i}/{len(df)} ({cache_name})")
        time.sleep(0.05)
    df = df.copy()
    df["latitude"] = lats
    df["longitude"] = lons
    df.to_csv(cache_path, index=False)
    return df


def load_chas_points():
    d = json.load(open(os.path.join(GEO_DIR, "CHAS_Clinics.geojson"), encoding="utf-8"))
    pts = [shape(f["geometry"]) for f in d["features"]]
    return pts


def count_within(polygon, pts):
    return sum(1 for p in pts if polygon.contains(p))


def nearest_dist_km(centroid, pts):
    if not pts:
        return None
    return min(haversine_km(centroid.x, centroid.y, p.x, p.y) for p in pts)


def build_extended_town_features():
    out_path = os.path.join(OUT_DIR, "hdb_town_geo_features_v2.csv")
    if os.path.exists(out_path):
        return pd.read_csv(out_path)

    # base (already validated) town features from the Option A/B pipeline
    import sys
    sys.path.insert(0, os.path.join(ROOT, "notebooks"))
    import data_prep as dp
    base = dp.build_town_geo_features()

    # planning area polygons, for the spatial join
    pa_geo = json.load(open(os.path.join(GEO_DIR, "MasterPlan2025_Planning_Area_Boundary_NoSea.geojson"), encoding="utf-8"))
    planning_areas = [{"name": f["properties"]["PLN_AREA_N"], "geom": shape(f["geometry"])}
                       for f in pa_geo["features"]]

    # supermarkets: already geocoded earlier this session (64% success, before
    # the rate limit kicked in) -- reuse the cache, don't re-hit the API
    supermarkets = geocode_by_postal(
        pd.read_csv(os.path.join(GEO_DIR, "Supermarkets_NEA.csv")), "postal_code", "supermarkets_geocoded.csv")
    sm_pts = [Point(lon, lat) for lon, lat in zip(supermarkets["longitude"], supermarkets["latitude"])
              if pd.notna(lon) and pd.notna(lat)]
    print(f"Supermarkets geocoded: {len(sm_pts)}/{len(supermarkets)}")

    # Childcare: OneMap rate-limited this session after ~800+ prior lookups
    # (concurrent retry only recovered 97/1703, ~5.7% -- too sparse and too
    # likely to be a non-random subset to aggregate into town counts without
    # introducing bias). Use whatever the fast retry recovered as a
    # low-confidence supplementary signal only; do not treat absence of a
    # count as "no childcare centres" in that town.
    childcare_geo_path = os.path.join(PROC, "childcare_postal_geocoded.csv")
    if os.path.exists(childcare_geo_path):
        childcare_geo = pd.read_csv(childcare_geo_path)
        cc_pts = [Point(lon, lat) for lon, lat in zip(childcare_geo["longitude"], childcare_geo["latitude"])
                  if pd.notna(lon) and pd.notna(lat)]
        print(f"Childcare/Kindergarten geocoded (LOW CONFIDENCE, rate-limited): {len(cc_pts)}/1703")
    else:
        cc_pts = []
        print("Childcare/Kindergarten: no geocoded data available, skipping (counts will be 0 for all towns)")

    chas_pts = load_chas_points()
    print(f"CHAS clinics: {len(chas_pts)}")

    # planning-area level counts for the 3 new layers
    rows = []
    for pa in planning_areas:
        geom = pa["geom"]
        cen = geom.centroid
        rows.append({
            "planning_area": pa["name"],
            "supermarkets_within": count_within(geom, sm_pts),
            "nearest_supermarket_km": round(nearest_dist_km(cen, sm_pts) or 99, 3),
            "chas_clinics_within": count_within(geom, chas_pts),
            "nearest_chas_clinic_km": round(nearest_dist_km(cen, chas_pts) or 99, 3),
            "childcare_within": count_within(geom, cc_pts),
            "nearest_childcare_km": round(nearest_dist_km(cen, cc_pts) or 99, 3),
        })
    new_pa_features = pd.DataFrame(rows)

    # aggregate to the 26 HDB towns via the same crosswalk used in data_prep
    rows2 = []
    geo_idx = new_pa_features.set_index("planning_area")
    num_cols = [c for c in new_pa_features.columns if c != "planning_area"]
    for town, pa_list in dp.TOWN_TO_PA.items():
        sub = geo_idx.loc[[p for p in pa_list if p in geo_idx.index]]
        row = {"town": town}
        for c in num_cols:
            row[c] = sub[c].mean()
        rows2.append(row)
    new_town_features = pd.DataFrame(rows2)

    merged = base.merge(new_town_features, on="town", how="left")
    merged.to_csv(out_path, index=False)
    return merged


if __name__ == "__main__":
    feat = build_extended_town_features()
    print("\nExtended town geo features:", feat.shape)
    cols = ["town", "mrt_stations_within", "nearest_mrt_km", "schools_within",
            "supermarkets_within", "chas_clinics_within", "childcare_within"]
    print(feat[cols].sort_values("town").to_string(index=False))

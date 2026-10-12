# -*- coding: utf-8 -*-
"""
Robust, resumable, area-batched OneMap geocoder.

Root cause of the earlier failures: OneMap *does* rate-limit (HTTP 429), but
the earlier script's bare `except Exception: pass` silently treated a 429
the same as a genuine "not found" -- so concurrent hammering looked like a
~5% success rate instead of what it actually was (mostly 429s). Fixed here:
  - 429 is detected explicitly and retried with exponential backoff, not
    counted as a failure.
  - Paced requests (default 1 worker, small delay) -- empirically ~0.3s
    sequential spacing keeps 429s rare.
  - Checkpoints after every AREA (not just row count), so a long job
    (13k+ HDB blocks) can be killed/resumed without losing completed areas.
  - Already-geocoded addresses are skipped on resume (reads the existing
    checkpoint file first).
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

PROC = r"C:\Users\Daniel Loh\Documents\NUS-ISS_EBAC\SPMF\Project\data\processed"


def geocode_query(query, timeout=8, max_retries=5):
    """query: a postal code OR a free-text address (OneMap's search accepts both)."""
    url = ("https://www.onemap.gov.sg/api/common/elastic/search?"
           + urllib.parse.urlencode({"searchVal": query, "returnGeom": "Y",
                                      "getAddrDetails": "N", "pageNum": "1"}))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    backoff = 1.0
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("found", 0) > 0:
                r = payload["results"][0]
                return float(r["LATITUDE"]), float(r["LONGITUDE"]), "OK"
            return None, None, "NOT_FOUND"
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(backoff)
                backoff = min(backoff * 2, 20)
                continue
            return None, None, f"HTTP_{e.code}"
        except Exception as e:
            return None, None, f"ERROR_{type(e).__name__}"
    return None, None, "GAVE_UP_429"


def geocode_dataframe_by_area(df, query_col, area_col, cache_name, delay=0.25,
                                max_area_seconds=90, max_total_seconds=1800):
    """Geocodes df[query_col], processing one area_col group at a time,
    checkpointing (append-saving) after each area. Resumable: rows whose
    query already appears in the existing cache are skipped."""
    cache_path = os.path.join(PROC, cache_name)
    existing = pd.read_csv(cache_path) if os.path.exists(cache_path) else pd.DataFrame(
        columns=[query_col, "latitude", "longitude", "status"])
    done_queries = set(existing[query_col].astype(str))

    t_start = time.time()
    areas = df[area_col].dropna().unique().tolist()
    print(f"[{cache_name}] {len(df)} rows across {len(areas)} areas, "
          f"{len(done_queries)} already geocoded from a previous run", flush=True)

    all_new = []
    for area in areas:
        if time.time() - t_start > max_total_seconds:
            print(f"[{cache_name}] TOTAL TIME BUDGET HIT ({max_total_seconds}s) -- "
                  f"stopping before area '{area}'. Re-run this function to resume.", flush=True)
            break

        sub = df[df[area_col] == area]
        todo = sub[~sub[query_col].astype(str).isin(done_queries)]
        if todo.empty:
            continue

        t_area = time.time()
        area_results = []
        for _, row in todo.iterrows():
            q = str(row[query_col])
            lat, lon, status = geocode_query(q)
            area_results.append({query_col: q, "latitude": lat, "longitude": lon, "status": status})
            done_queries.add(q)
            time.sleep(delay)
            if time.time() - t_area > max_area_seconds:
                print(f"  [{area}] area time budget hit mid-area, {len(area_results)}/{len(todo)} done this area", flush=True)
                break

        n_ok = sum(1 for r in area_results if r["status"] == "OK")
        print(f"  [{area}] {len(area_results)} geocoded this run, {n_ok} OK "
              f"({n_ok/max(len(area_results),1)*100:.0f}%), {time.time()-t_area:.0f}s", flush=True)
        all_new.extend(area_results)

        # checkpoint after every area
        combined = pd.concat([existing, pd.DataFrame(all_new)], ignore_index=True) if all_new else existing
        combined = combined.drop_duplicates(subset=[query_col], keep="last")
        combined.to_csv(cache_path, index=False)

    total_ok = (pd.read_csv(cache_path)["status"] == "OK").sum() if os.path.exists(cache_path) else 0
    print(f"[{cache_name}] checkpoint saved: {total_ok} total OK so far -> {cache_path}", flush=True)
    return pd.read_csv(cache_path)


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "facilities"

    if target == "facilities":
        GEO_DIR = r"C:\Users\Daniel Loh\Documents\NUS-ISS_EBAC\SPMF\Project\data\geospatial"

        childcare = pd.read_csv(os.path.join(GEO_DIR, "Childcare_Kindergarten_Centres_ECDA.csv"))
        childcare["postal_code"] = childcare["postal_code"].astype(str).str.extract(r"(\d{6})")[0]
        childcare["area"] = childcare["postal_code"].str[:2]  # postal sector as area proxy
        childcare = childcare.dropna(subset=["postal_code"])
        geocode_dataframe_by_area(childcare, "postal_code", "area", "childcare_postal_geocoded_v2.csv",
                                    delay=0.3, max_area_seconds=60, max_total_seconds=900)

        supermarkets = pd.read_csv(os.path.join(GEO_DIR, "Supermarkets_NEA.csv"))
        supermarkets["postal_code"] = supermarkets["postal_code"].astype(str).str.extract(r"(\d{6})")[0]
        supermarkets["area"] = supermarkets["postal_code"].str[:2]
        supermarkets = supermarkets.dropna(subset=["postal_code"])
        geocode_dataframe_by_area(supermarkets, "postal_code", "area", "supermarkets_geocoded_v2.csv",
                                    delay=0.3, max_area_seconds=60, max_total_seconds=300)

    elif target == "schools":
        GEO_DIR = r"C:\Users\Daniel Loh\Documents\NUS-ISS_EBAC\SPMF\Project\data\geospatial"
        schools = pd.read_csv(os.path.join(GEO_DIR, "General_Information_of_Schools.csv"))
        schools["postal_code"] = schools["postal_code"].astype(str).str.zfill(6)
        schools["area"] = schools["postal_code"].str[:2]
        geocode_dataframe_by_area(schools, "postal_code", "area", "schools_geocoded_v2.csv",
                                    delay=0.3, max_area_seconds=60, max_total_seconds=600)

    elif target == "blocks":
        ROOT = r"C:\Users\Daniel Loh\Documents\NUS-ISS_EBAC\SPMF\Project"
        blocks = pd.read_csv(os.path.join(ROOT, "HDBPropertyInformation.csv"))
        blocks["query"] = blocks["blk_no"].astype(str) + " " + blocks["street"]
        geocode_dataframe_by_area(blocks, "query", "bldg_contract_town", "hdb_blocks_geocoded.csv",
                                    delay=0.25, max_area_seconds=180, max_total_seconds=1800)

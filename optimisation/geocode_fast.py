# -*- coding: utf-8 -*-
"""
Faster, more robust OneMap geocoding: concurrent requests (modest pool, so
we don't get rate-limited harder than sequential), short per-request
timeout, incremental checkpoint saves every N rows (so a hang/kill doesn't
lose progress), and a hard overall time budget so it can never hang silently
again. Progress is explicitly flushed every row so it's visible even when
stdout is redirected to a file.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

PROC = r"C:\Users\Daniel Loh\Documents\NUS-ISS_EBAC\SPMF\Project\data\processed"


def geocode_one(postal, timeout=5):
    try:
        url = ("https://www.onemap.gov.sg/api/common/elastic/search?"
               + urllib.parse.urlencode({"searchVal": postal, "returnGeom": "Y",
                                          "getAddrDetails": "N", "pageNum": "1"}))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if payload.get("found", 0) > 0:
            r = payload["results"][0]
            return float(r["LATITUDE"]), float(r["LONGITUDE"])
    except Exception:
        pass
    return None, None


def geocode_batch(postals, cache_name, max_workers=6, checkpoint_every=100, time_budget_sec=240):
    cache_path = os.path.join(PROC, cache_name)
    t0 = time.time()
    results = {}
    postals = list(dict.fromkeys(postals))  # de-dupe, preserve order
    print(f"[{cache_name}] geocoding {len(postals)} unique postal codes, "
          f"{max_workers} workers, {time_budget_sec}s budget", flush=True)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(geocode_one, p): p for p in postals}
        done = 0
        for fut in as_completed(futures):
            postal = futures[fut]
            lat, lon = fut.result()
            results[postal] = (lat, lon)
            done += 1
            if done % 25 == 0 or done == len(postals):
                elapsed = time.time() - t0
                print(f"  [{cache_name}] {done}/{len(postals)} done, {elapsed:.0f}s elapsed, "
                      f"{sum(1 for v in results.values() if v[0] is not None)} geocoded OK", flush=True)
            if done % checkpoint_every == 0:
                pd.DataFrame([{"postal_code": k, "latitude": v[0], "longitude": v[1]} for k, v in results.items()]) \
                  .to_csv(cache_path + ".partial", index=False)
            if time.time() - t0 > time_budget_sec:
                print(f"  [{cache_name}] TIME BUDGET HIT at {done}/{len(postals)} -- stopping, "
                      f"remainder left ungeocoded (None)", flush=True)
                for f in futures:
                    f.cancel()
                break

    out = pd.DataFrame([{"postal_code": k, "latitude": v[0], "longitude": v[1]} for k, v in results.items()])
    out.to_csv(cache_path, index=False)
    if os.path.exists(cache_path + ".partial"):
        os.remove(cache_path + ".partial")
    print(f"[{cache_name}] DONE: {out['latitude'].notna().sum()}/{len(out)} geocoded, "
          f"{time.time()-t0:.0f}s total -> {cache_path}", flush=True)
    return out


if __name__ == "__main__":
    GEO_DIR = r"C:\Users\Daniel Loh\Documents\NUS-ISS_EBAC\SPMF\Project\data\geospatial"

    childcare = pd.read_csv(os.path.join(GEO_DIR, "Childcare_Kindergarten_Centres_ECDA.csv"))
    postals = childcare["postal_code"].astype(str).str.extract(r"(\d{6})")[0].dropna().tolist()
    geocode_batch(postals, "childcare_postal_geocoded.csv", max_workers=6, time_budget_sec=240)

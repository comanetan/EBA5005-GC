"""Step 2 (NEEDS INTERNET, ~45-60 min, safe to stop and re-run: it resumes from the cache).
Geocodes every block address and primary-school postcode with the OneMap Search API.
Output: data/interim/geocode_cache.csv  (key, kind, lat, lon, postal, matched_blk, match_quality)

match_quality:  exact     = OneMap returned the same block number
                expanded  = exact match after expanding abbreviations (AVE -> AVENUE, etc.)
                postcode  = school matched by postcode
                fallback  = no block+street match; took OneMap's top result (check these)
                manual    = corrected by hand after the street-name check
                none      = nothing found (fix by hand)
If OneMap ever returns 401, create a free OneMap account and run:  export ONEMAP_TOKEN=...  then re-run."""
import os, re, time
import pandas as pd, requests
from config import UNIQUE_ADDR, PRIMARY_SCHOOLS, GEOCODE_CACHE, POLYCLINICS, RAW, SUPERMARKETS_GLOB

URL = "https://www.onemap.gov.sg/api/common/elastic/search"
SAVE_EVERY = 50

ABBREV = {"AVE": "AVENUE", "ST": "STREET", "RD": "ROAD", "DR": "DRIVE", "CRES": "CRESCENT", "CL": "CLOSE",
          "PL": "PLACE", "CTRL": "CENTRAL", "CTR": "CENTRE", "NTH": "NORTH", "STH": "SOUTH", "UPP": "UPPER",
          "BT": "BUKIT", "JLN": "JALAN", "LOR": "LORONG", "KG": "KAMPONG", "TG": "TANJONG", "MKT": "MARKET",
          "HTS": "HEIGHTS", "GDNS": "GARDENS", "PK": "PARK", "TER": "TERRACE", "CT": "COURT", "SQ": "SQUARE",
          "BLVD": "BOULEVARD", "ST.": "SAINT", "C'WEALTH": "COMMONWEALTH", "HG": "HOUGANG", "E": "EAST", "W": "WEST"}

session = requests.Session()
if os.getenv("ONEMAP_TOKEN"):
    session.headers["Authorization"] = os.environ["ONEMAP_TOKEN"]

state = {"pause": 0.8, "ok_streak": 0, "throttled": 0}   # adaptive pacing: finds OneMap's sustainable rate

def search(text):
    for attempt in range(6):
        try:
            r = session.get(URL, params={"searchVal": text, "returnGeom": "Y",
                                         "getAddrDetails": "Y", "pageNum": 1}, timeout=20)
            if r.status_code == 429:                    # rate-limited: slow down for good, wait, retry
                state["pause"] = min(state["pause"] * 1.5, 6.0); state["ok_streak"] = 0; state["throttled"] += 1
                print(f"  rate-limited by OneMap -> pausing {state['pause']:.1f}s between calls from now on", flush=True)
                time.sleep(20); continue
            r.raise_for_status()
            state["ok_streak"] += 1
            if state["ok_streak"] >= 100:               # long run of successes: speed up a little
                state["pause"] = max(state["pause"] * 0.9, 0.3); state["ok_streak"] = 0
            time.sleep(state["pause"])
            return r.json().get("results", [])
        except requests.RequestException as e:
            print(f"  network issue ({e.__class__.__name__}), retrying...", flush=True); time.sleep(5 * (attempt + 1))
    return []

def expand(street):
    return " ".join(ABBREV.get(tok, tok) for tok in street.split())

def geocode_block(block, street):
    first = None
    for quality, text in [("exact", f"{block} {street}"), ("expanded", f"{block} {expand(street)}")]:
        res = search(text)
        first = first or res
        same_blk = [r for r in res if r.get("BLK_NO", "").upper() == block.upper()]
        full = expand(street)
        hit = next((r for r in same_blk if f" {full} " in f" {r.get('ADDRESS', '').upper()} "
                    or r.get("ROAD_NAME", "").upper() == full), None)   # same block AND same street
        if hit:
            return hit, quality
    return (first[0], "fallback") if first else (None, "none")

def row(key, kind, hit, quality):
    return {"key": key, "kind": kind, "lat": hit and float(hit["LATITUDE"]), "lon": hit and float(hit["LONGITUDE"]),
            "postal": hit and hit.get("POSTAL"), "matched_blk": hit and hit.get("BLK_NO"),
            "onemap_address": hit and hit.get("ADDRESS"), "match_quality": quality}

def postcode_sources():
    """Postcode-only point datasets: primary schools always; polyclinics / supermarkets if their files exist."""
    out = []
    sch = pd.read_csv(PRIMARY_SCHOOLS, dtype=str)
    out.append(("school", "SCH", sorted(set(sch["postal_code"].dropna().str.zfill(6)))))
    if POLYCLINICS.exists():
        p = pd.read_csv(POLYCLINICS, dtype=str)
        out.append(("polyclinic", "POLY", sorted(set(p["postal_code"].dropna().str.strip().str.zfill(6)))))
    for f in RAW.glob(SUPERMARKETS_GLOB):
        sm = pd.read_csv(f, dtype=str)
        col = next((c for c in sm.columns if "postal" in c.lower()), None)
        if col:
            codes = sm[col].dropna().str.extract(r"(\d{6})")[0].dropna()
            out.append(("supermarket", "SUP", sorted(set(codes))))
        else:
            print(f"WARNING: no postal-code column found in {f.name}; columns are {list(sm.columns)}")
    return out

def main():
    cache = pd.read_csv(GEOCODE_CACHE, dtype=str) if GEOCODE_CACHE.exists() else pd.DataFrame(columns=["key"])
    done, new = set(cache["key"]), []

    def flush():
        nonlocal cache, new
        if new:
            cache = pd.concat([cache, pd.DataFrame(new)], ignore_index=True); new = []
            cache.to_csv(GEOCODE_CACHE, index=False)

    addr = pd.read_csv(UNIQUE_ADDR, dtype=str)
    todo = addr[~addr["address"].isin(done)]
    print(f"Blocks: {len(addr):,} total, {len(addr) - len(todo):,} already cached, {len(todo):,} to go")
    t0 = time.time()
    for i, r in enumerate(todo.itertuples(), 1):
        t1 = time.time()
        hit, q = geocode_block(r.block, r.street_name)
        new.append(row(r.address, "block", hit, q))
        if i <= 5:
            print(f"  [{q}] {r.address} -> {hit and hit.get('ADDRESS')}  ({time.time() - t1:.1f}s)", flush=True)
        if i % SAVE_EVERY == 0:
            flush(); rate = i / (time.time() - t0)
            print(f"  {i:,}/{len(todo):,} blocks  (~{(len(todo) - i) / rate / 60:.0f} min left, pause {state['pause']:.2f}s)", flush=True)
    flush()

    for kind, prefix, codes in postcode_sources():
        todo_p = [c for c in codes if f"{prefix} {c}" not in set(cache["key"])]
        print(f"{kind}: {len(codes)} postcodes, {len(todo_p)} to go", flush=True)
        for c in todo_p:
            res = search(c)
            hit = next((x for x in res if x.get("POSTAL") == c), res[0] if res else None)
            new.append(row(f"{prefix} {c}", kind, hit, "postcode" if hit else "none"))
        flush()

    summary = cache.groupby(["kind", "match_quality"]).size()
    print("\nMatch summary:\n" + summary.to_string())
    print(f"\nSaved {GEOCODE_CACHE}. Check rows with match_quality = fallback or none before step 4.")

if __name__ == "__main__":
    main()

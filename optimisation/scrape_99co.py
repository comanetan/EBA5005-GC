# -*- coding: utf-8 -*-
"""
Scrapes 99.co property search-result pages (HDB + condo, sale + rent),
paginating through every page, and appends each run into a cumulative,
de-duplicated "listings master" table tracking each listing's first-seen /
last-seen dates across repeated runs.

WHY THIS EXISTS
---------------
The HDB resale CSV only contains COMPLETED transactions -- a lagging
indicator. It can't tell the recommender whether a flat matching a given
profile is actually on the market right now, or how long such listings
typically stay up before being taken down (sold / withdrawn). That's exactly
the proposal's 3rd business objective: "indicate how readily each
shortlisted profile comes up for sale." Today that's a Poisson-arrival STUB
in recommender_v2.py, pending the Pricing & Availability Lead's real
Kaplan-Meier / Cox PH model.

Repeated snapshots of what's currently listed let a listing's disappearance
between two runs be treated as a (right-censored) duration observation --
either a provisional stand-in for that model, or a cross-check against it
once delivered.

HOW TO USE
----------
1. Eyeball the SEARCH_URLS below in your own browser first and fix any that
   have moved (99.co's URL slugs change occasionally) -- the script does not
   guess blindly, it paginates whatever URLs you give it.
2. Run it:                      python scrape_99co.py
3. Re-run every few days, ideally for several weeks, to build up duration
   data. Each run is append-only to data/scraped_listings/ and safe to
   re-run -- it never overwrites history, and rebuilds listings_master.csv
   from every run on disk each time.
4. To automate on Windows (optional), Task Scheduler (PowerShell, run the
   script's own folder path through (Get-Location).Path to avoid typos):
     schtasks /create /tn "99co_scrape" /sc daily /st 09:00 /tr "python <full path to this file>"

SIZE / PACING (tuned 2026-10-06, after a real run)
-----------------------------------------------------
Targets TARGET_PER_CATEGORY (2,000) new listings per category, up to
MAX_PAGES_PER_CATEGORY (120) pages as a backstop. A real run's own numbers
set that ceiling: ~27-33 new listings/page even 60 pages deep, so 120 pages
gives comfortable headroom to clear 2,000 on every category that has that
much inventory (one, condo_rent, may simply not -- the staleness check below
stops early rather than hammering a category that's run dry). Expect this to
take tens of minutes; there's no way around that at this volume. If 99.co
starts timing out repeatedly, that's the site pushing back -- scrape_99co_light.py
is the smaller, faster sibling for routine re-runs once this bigger initial
pull is done.

ETHICS / LEGALITY (checked 2026-10-05)
---------------------------------------
- robots.txt does not disallow /singapore/sale/hdb, /singapore/rent/hdb, or
  a page_num query parameter. It DOES disallow some other paths/params
  (mrt-stations, schools, travel-time sub-pages, several filter params) --
  none of which this script touches.
- Requests are rate-limited with randomised delays and a normal browser
  User-Agent; only fields shown on a public search-results card are
  captured (price, size, beds, built year, address if present, listing URL
  if present) -- no login, no contact details, no per-listing detail-page
  crawl. A single deep run like this one is still bounded (it stops once
  each category hits its target or runs dry) rather than an unbounded or
  continuously-running crawl.
- Proceeding is the team's own informed decision for academic purposes
  (as previously agreed) -- re-confirm 99.co's Terms of Use before any
  non-academic reuse.
"""
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from codecs import decode as codecs_decode

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "data", "scraped_listings")
OUT_DIR = os.path.normpath(OUT_DIR)
os.makedirs(OUT_DIR, exist_ok=True)

# ---- what to scrape -------------------------------------------------------
# VERIFY these in your own browser before a big run -- 99.co's slugs do
# shift. Add/remove entries freely; each is scraped independently.
SEARCH_URLS = {
    "hdb_sale": "https://www.99.co/singapore/sale/hdb",
    "hdb_rent": "https://www.99.co/singapore/rent/hdb",
    # Condo URLs are a secondary nice-to-have (cross-check vs. the URA
    # private-property index already in data/private_property/). Confirm
    # the slug below is still correct before enabling -- comment out if not.
    "condo_sale": "https://www.99.co/singapore/sale/condos-apartments",
    "condo_rent": "https://www.99.co/singapore/rent/condos-apartments",
}

# Optional: paste one search URL per line (e.g. per-town filtered searches,
# copied from your browser's address bar) into town_urls.txt next to this
# script, if the generic searches above turn out to be capped at some max
# result count. Each line becomes its own scrape, tagged by its position.
TOWN_URLS_FILE = os.path.join(HERE, "town_urls.txt")

PAGE_PARAM = "page_num"          # query param used for pagination; change here if 99.co uses a different name
TARGET_PER_CATEGORY = 2000       # primary stop condition: quit a category once it has this many NEW listings
MAX_PAGES_PER_CATEGORY = 120     # backstop in case a category can't reach the target (see module docstring for why 120)
NEW_FRACTION_STOP = 0.15         # a page counts as "exhausted" once under 15% of it is new (lenient -- we're pushing deep on purpose)
STOP_AFTER_N_LOW_PAGES = 3       # consecutive "exhausted" pages -> assume this category has genuinely run dry
DELAY_RANGE = (3.0, 6.0)         # seconds between page requests (politeness; widened for this heavier run)
BACKOFF_ON_BLOCK = (45, 90)      # seconds to wait after a 403/429 before giving up that category
INTER_CATEGORY_COOLDOWN = (20, 40)  # seconds to pause between categories, so 4 categories don't read as one long burst

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept-Language": "en-SG,en;q=0.9",
}

PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', re.S)
CHUNK_RE = re.compile(r'(?:^|\n)([0-9a-f]+):(.*?)(?=\n[0-9a-f]+:|\Z)', re.S)


# ---- fetching ---------------------------------------------------------------
def fetch_html(url, retries=3):
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8"), None
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                print(f"    HTTP {e.code} (blocked/rate-limited) on attempt {attempt+1}")
                if attempt < retries - 1:
                    time.sleep(random.uniform(*BACKOFF_ON_BLOCK))
                    continue
                return None, e.code
            print(f"  fetch attempt {attempt+1} failed: HTTP {e.code}")
            time.sleep(2)
        except Exception as e:
            print(f"  fetch attempt {attempt+1} failed: {e}")
            time.sleep(2)
    return None, None


def js_unescape(s):
    return codecs_decode(s, "unicode_escape").encode("latin1").decode("utf-8", errors="ignore")


def extract_rsc_chunks(html):
    pushes = PUSH_RE.findall(html)
    stream = "".join(js_unescape(p) for p in pushes)
    chunks = {}
    for m in CHUNK_RE.finditer(stream):
        chunks[m.group(1)] = m.group(2)
    return chunks


def resolve_value(val, chunks, depth=0):
    if depth > 3 or not isinstance(val, str) or not val.startswith("$"):
        return val
    ref = val[1:]
    raw = chunks.get(ref)
    if raw is None:
        return val
    try:
        parsed = json.loads(raw)
    except Exception:
        return raw
    if isinstance(parsed, dict):
        return {k: resolve_value(v, chunks, depth + 1) for k, v in parsed.items()}
    return resolve_value(parsed, chunks, depth + 1) if isinstance(parsed, str) else parsed


def parse_listings(chunks):
    listings = []
    for cid, raw in chunks.items():
        if '"listing_id"' not in raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if not isinstance(obj, dict) or "listing_id" not in obj:
            continue
        resolved = {k: resolve_value(v, chunks) for k, v in obj.items()}
        listings.append(resolved)
    return listings


def flatten_listing(obj):
    """Flatten a resolved listing dict into one row, WITHOUT a hardcoded field
    whitelist -- whatever keys 99.co's payload actually carries (address,
    lat/lon, url/slug, agent, updated_at, ...) come through automatically.
    A {'value':.., 'formatted_string':..} sub-dict (price, psf, beds, ...)
    becomes two columns: <key>_value (numeric/raw) and <key>_text (display)."""
    row = {}
    for k, v in obj.items():
        if isinstance(v, dict) and ("formatted_string" in v or "value" in v):
            row[f"{k}_value"] = v.get("value")
            row[f"{k}_text"] = v.get("formatted_string", v.get("value"))
        elif isinstance(v, (dict, list)):
            row[k] = json.dumps(v, ensure_ascii=False)
        else:
            row[k] = v
    return row


# ---- pagination ---------------------------------------------------------------
def scrape_search_pages(base_url, segment, max_pages=MAX_PAGES_PER_CATEGORY, target=TARGET_PER_CATEGORY):
    """Pages through base_url until EITHER `target` new listings are collected
    (the usual, intended stop) OR `max_pages` is hit (a backstop) OR
    STOP_AFTER_N_LOW_PAGES consecutive pages each come back under
    NEW_FRACTION_STOP new (the category has genuinely run dry -- no point
    paying for more requests chasing listings that aren't there)."""
    seen_ids, rows = set(), []
    low_streak = 0
    sep = "&" if "?" in base_url else "?"
    for page in range(1, max_pages + 1):
        url = base_url if page == 1 else f"{base_url}{sep}{PAGE_PARAM}={page}"
        print(f"  [{segment}] page {page}: {url}")
        html, err_code = fetch_html(url)
        if html is None:
            if err_code in (403, 429):
                print(f"    gave up after repeated {err_code} -- stopping '{segment}' early (partial results kept)")
            else:
                print("    fetch failed after retries -- stopping this category")
            break
        chunks = extract_rsc_chunks(html)
        listings = parse_listings(chunks)
        new = [l for l in listings if l.get("listing_id") not in seen_ids]
        fraction_new = len(new) / len(listings) if listings else 0
        if fraction_new < NEW_FRACTION_STOP:
            low_streak += 1
            print(f"    only {len(new)}/{len(listings)} new ({fraction_new:.0%}) -- streak {low_streak}/{STOP_AFTER_N_LOW_PAGES}")
            if low_streak >= STOP_AFTER_N_LOW_PAGES:
                print(f"    mostly duplicates now -- this category has run dry at {len(rows)} new listings (target was {target})")
                break
        else:
            low_streak = 0
            print(f"    {len(new)}/{len(listings)} new ({fraction_new:.0%}); {len(rows)+len(new)}/{target} so far")
        for l in new:
            seen_ids.add(l.get("listing_id"))
            r = flatten_listing(l)
            r["segment"] = segment
            r["page"] = page
            rows.append(r)
        if len(rows) >= target:
            print(f"    reached the {target}-listing target for '{segment}'")
            break
        time.sleep(random.uniform(*DELAY_RANGE))
    return pd.DataFrame(rows)


def load_town_urls():
    if not os.path.exists(TOWN_URLS_FILE):
        return {}
    urls = {}
    with open(TOWN_URLS_FILE, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if line and not line.startswith("#"):
                urls[f"town_url_{i}"] = line
    return urls


def run_full_scrape():
    all_segments = dict(SEARCH_URLS)
    all_segments.update(load_town_urls())
    t0 = time.time()
    frames = []
    for i, (segment, url) in enumerate(all_segments.items()):
        if i > 0:
            cooldown = random.uniform(*INTER_CATEGORY_COOLDOWN)
            print(f"  (cooling down {cooldown:.0f}s before '{segment}')")
            time.sleep(cooldown)
        df = scrape_search_pages(url, segment)
        if len(df):
            frames.append(df)
    combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    run_ts = datetime.now(timezone.utc)
    combined["run_ts"] = run_ts.isoformat()
    ts_tag = run_ts.strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(OUT_DIR, f"snapshot_{ts_tag}.csv")
    combined.to_csv(out_path, index=False)
    print(f"\nSaved {len(combined)} listings -> {out_path}  ({time.time()-t0:.0f}s total)")
    if len(combined):
        print("Per segment:", combined.groupby("segment").size().to_dict())
    return combined


# ---- cumulative master table ---------------------------------------------------
def build_master():
    """Rebuilds listings_master.csv from EVERY snapshot_*.csv on disk (idempotent --
    safe to call after any number of runs). One row per listing_id, with
    first_seen / last_seen / times_seen / still_listed (seen in the most recent run)."""
    files = sorted(f for f in os.listdir(OUT_DIR) if f.startswith("snapshot_") and f.endswith(".csv"))
    if not files:
        print("No snapshot_*.csv files found yet -- run the scraper at least once first.")
        return None
    frames = []
    for f in files:
        try:
            d = pd.read_csv(os.path.join(OUT_DIR, f))
        except Exception as e:
            print(f"  skipping unreadable {f}: {e}")
            continue
        if "run_ts" not in d.columns or "listing_id" not in d.columns or not len(d):
            continue
        frames.append(d)
    if not frames:
        print("No usable snapshots yet.")
        return None
    hist = pd.concat(frames, ignore_index=True, sort=False)
    hist["run_ts"] = pd.to_datetime(hist["run_ts"], utc=True, errors="coerce")
    hist = hist.dropna(subset=["run_ts", "listing_id"])
    latest_run = hist["run_ts"].max()

    agg = hist.groupby("listing_id").agg(
        first_seen=("run_ts", "min"), last_seen=("run_ts", "max"), times_seen=("run_ts", "nunique"),
    )
    agg["still_listed"] = agg["last_seen"] >= latest_run
    agg["min_days_listed"] = (agg["last_seen"] - agg["first_seen"]).dt.total_seconds() / 86400
    # for a listing no longer seen, the TRUE disappearance happened sometime between its
    # last_seen run and the next run after that -- min_days_listed is a lower bound, not exact
    last_row = hist.sort_values("run_ts").groupby("listing_id").last()
    descriptive_cols = [c for c in last_row.columns if c not in ("run_ts", "page")]
    master = agg.join(last_row[descriptive_cols])
    master = master.sort_values("first_seen")

    out_path = os.path.join(OUT_DIR, "listings_master.csv")
    master.to_csv(out_path)
    n_runs = hist["run_ts"].nunique()
    print(f"\nlistings_master.csv: {len(master)} unique listings across {n_runs} run(s) "
          f"({files[0]} .. {files[-1]})")
    if n_runs < 3:
        print("NOTE: duration/availability estimates need several runs spread over time "
              "(re-run this script every few days) before min_days_listed / still_listed are informative.")
    return master


if __name__ == "__main__":
    if "--master-only" in sys.argv:
        build_master()
    else:
        run_full_scrape()
        build_master()

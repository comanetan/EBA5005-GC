# -*- coding: utf-8 -*-
"""
Lighter, safer sibling of scrape_99co.py -- same output format and folder
(data/scraped_listings/, same snapshot_<timestamp>.csv + listings_master.csv),
reusing its fetch/parse code directly, but with a pagination driver that
actually stays small and stops cleanly.

WHY THIS EXISTS -- what went wrong with a full scrape_99co.py run
-------------------------------------------------------------------
A real run (2026-10-05) rode the 60-page safety cap on 3 of 4 categories for
~26 minutes and 5,550 listings, because the old stop rule only fires on
TWO FULLY EMPTY pages in a row -- but 99.co's result pages kept returning a
handful of new listings even deep in (6 new out of 36, 4 new out of 36, ...),
so the streak kept resetting and it never actually triggered. That is far
past the "small, non-disruptive academic snapshot" the original script's own
docstring promises, and is almost certainly why the site started timing out
/ failing SSL handshakes on the very last category -- a sign of being
throttled, not a random network blip.

This version fixes both problems instead of just lowering the page cap:
  1. Stops when a page's NEW-listing fraction drops below NEW_FRACTION_STOP
     (not just when it's literally zero) for STOP_AFTER_N_LOW_PAGES pages in
     a row -- catches "mostly duplicates now" pages the old rule missed.
  2. A hard wall-clock budget for the WHOLE run (TIME_BUDGET_SECONDS). Once
     it's spent, the run stops after finishing the current page, no matter
     what the other heuristics think -- a backstop, not just a suggestion.
  3. Two consecutive failed fetches of ANY kind (not just HTTP 403/429) stop
     the ENTIRE run immediately, on the assumption the site has started
     throttling the whole session, not just one category's worth of pages.

Run:  python scrape_99co_light.py
Re-run every few days, same as the original -- see its own docstring for why.
"""
import os
import random
import sys
import time
from datetime import datetime, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# reuse the already-working fetch/parse/master-build code verbatim -- this file only
# changes HOW MUCH is scraped per run and WHEN it stops, not HOW a page is parsed.
from scrape_99co import (  # noqa: E402
    fetch_html, extract_rsc_chunks, parse_listings, flatten_listing,
    load_town_urls, build_master, SEARCH_URLS, OUT_DIR, PAGE_PARAM, DELAY_RANGE,
)

MAX_PAGES_PER_CATEGORY = 6       # was 60 -- ~150-200 listings/category, a few minutes total
NEW_FRACTION_STOP = 0.25         # a page counts as "exhausted" once under 25% of it is new
STOP_AFTER_N_LOW_PAGES = 2       # consecutive "exhausted" pages -> stop this category
TIME_BUDGET_SECONDS = 360        # hard cap for the WHOLE run (6 minutes), regardless of the above


class TimeBudgetExceeded(Exception):
    pass


def scrape_search_pages_light(base_url, segment, t_start, seen_ids):
    """Like scrape_99co.scrape_search_pages, but stops on a fraction-based
    staleness signal and respects a shared wall-clock budget across ALL
    categories (t_start/TIME_BUDGET_SECONDS), not just a per-category page cap."""
    rows = []
    low_streak = 0
    sep = "&" if "?" in base_url else "?"
    consecutive_fetch_failures = 0
    for page in range(1, MAX_PAGES_PER_CATEGORY + 1):
        if time.time() - t_start > TIME_BUDGET_SECONDS:
            print(f"    time budget ({TIME_BUDGET_SECONDS}s) spent -- stopping here, keeping partial results")
            raise TimeBudgetExceeded()
        url = base_url if page == 1 else f"{base_url}{sep}{PAGE_PARAM}={page}"
        print(f"  [{segment}] page {page}: {url}")
        html, err_code = fetch_html(url)
        if html is None:
            consecutive_fetch_failures += 1
            print(f"    fetch failed ({consecutive_fetch_failures} in a row)")
            if consecutive_fetch_failures >= 2:
                print("    2 failures in a row -- the site is likely throttling us now; stopping the WHOLE run")
                raise TimeBudgetExceeded()  # reuse the same escape hatch: stop everything, keep what we have
            time.sleep(random.uniform(*DELAY_RANGE))
            continue
        consecutive_fetch_failures = 0

        chunks = extract_rsc_chunks(html)
        listings = parse_listings(chunks)
        new = [l for l in listings if l.get("listing_id") not in seen_ids]
        fraction_new = len(new) / len(listings) if listings else 0
        if fraction_new < NEW_FRACTION_STOP:
            low_streak += 1
            print(f"    only {len(new)}/{len(listings)} new ({fraction_new:.0%}) -- streak {low_streak}/{STOP_AFTER_N_LOW_PAGES}")
            if low_streak >= STOP_AFTER_N_LOW_PAGES:
                print("    mostly duplicates now -- assuming end of fresh results for this category")
                break
        else:
            low_streak = 0
            print(f"    {len(new)}/{len(listings)} new ({fraction_new:.0%})")
        for l in new:
            seen_ids.add(l.get("listing_id"))
            r = flatten_listing(l)
            r["segment"] = segment
            r["page"] = page
            rows.append(r)
        time.sleep(random.uniform(*DELAY_RANGE))
    return pd.DataFrame(rows)


def run_light_scrape():
    all_segments = dict(SEARCH_URLS)
    all_segments.update(load_town_urls())
    t0 = time.time()
    seen_ids = set()  # shared across categories too, so nothing is double-counted
    frames = []
    try:
        for segment, url in all_segments.items():
            df = scrape_search_pages_light(url, segment, t0, seen_ids)
            if len(df):
                frames.append(df)
    except TimeBudgetExceeded:
        pass  # keep whatever was collected before the budget ran out

    combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    run_ts = datetime.now(timezone.utc)
    combined["run_ts"] = run_ts.isoformat()
    ts_tag = run_ts.strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(OUT_DIR, f"snapshot_{ts_tag}.csv")
    combined.to_csv(out_path, index=False)
    print(f"\nSaved {len(combined)} listings -> {out_path}  ({time.time()-t0:.0f}s total, budget was {TIME_BUDGET_SECONDS}s)")
    if len(combined):
        print("Per segment:", combined.groupby("segment").size().to_dict())
    return combined


if __name__ == "__main__":
    if "--master-only" in sys.argv:
        build_master()
    else:
        run_light_scrape()
        build_master()

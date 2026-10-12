# -*- coding: utf-8 -*-
"""Run anytime to see real geocoding progress across all three jobs.
Usage: python check_geocoding_progress.py"""
import os
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../Project, portable across machines
PROC = os.path.join(ROOT, "data", "processed")
GEO_DIR = os.path.join(ROOT, "data", "geospatial")

TARGETS = [
    ("HDB blocks", "hdb_blocks_geocoded.csv",
     lambda: len(pd.read_csv(os.path.join(ROOT, "HDBPropertyInformation.csv")))),
    ("Childcare/Kindergarten", "childcare_postal_geocoded_v2.csv",
     lambda: pd.read_csv(os.path.join(GEO_DIR, "Childcare_Kindergarten_Centres_ECDA.csv"))["postal_code"]
             .astype(str).str.extract(r"(\d{6})")[0].nunique()),
    ("Supermarkets", "supermarkets_geocoded_v2.csv",
     lambda: pd.read_csv(os.path.join(GEO_DIR, "Supermarkets_NEA.csv"))["postal_code"]
             .astype(str).str.extract(r"(\d{6})")[0].nunique()),
]

print(f"{'Job':<25} {'Done':>8} {'/ Total':>10} {'% Complete':>12}  Status")
print("-" * 80)
for name, fname, total_fn in TARGETS:
    path = os.path.join(PROC, fname)
    total = total_fn()
    if not os.path.exists(path):
        print(f"{name:<25} {0:>8} {total:>10} {'0%':>12}  NOT STARTED")
        continue
    df = pd.read_csv(path)
    done_rows = len(df)
    ok_rows = (df["status"] == "OK").sum() if "status" in df.columns else df["latitude"].notna().sum()
    pct = done_rows / total * 100
    status = "COMPLETE" if done_rows >= total else f"IN PROGRESS ({total - done_rows} queries not yet attempted)"
    print(f"{name:<25} {done_rows:>8} {total:>10} {pct:>11.1f}%  {status}")
    print(f"{'  (of which geocode OK)':<25} {ok_rows:>8}")

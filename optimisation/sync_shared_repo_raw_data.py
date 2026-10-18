# -*- coding: utf-8 -*-
"""
Data-layout portability bridge (2026-10-18): this pipeline's scripts read raw/processed
inputs from THIS WORKSTREAM'S OWN flat `Project/data/...` layout (no raw/ vs interim/
split), never from the team's shared repo's `data/raw/` + `data/interim/` split. The two
layouts are NOT the same shape, so there is no single path-variable swap that fixes this.

What this script actually does: given a checkout of the shared repo (comanetan/EBA5005-GC),
copies the raw/interim files that genuinely ARE the same dataset under a different name or
location into the exact paths this pipeline's scripts expect -- so someone who only has the
shared repo checked out can still run this pipeline's build chain. Every mapping below was
verified byte/row/feature-count identical before being added here (see DATA_LAYOUT.md for
the verification notes) -- nothing is copied on a guess.

What this script deliberately does NOT do: silently invent a mapping for a file whose
shared-repo counterpart is a DIFFERENT dataset (not just a different name) -- e.g.
`PreSchoolsLocation.geojson` and `polyclinics.csv` are real files on `main` with no honest
equivalent among this pipeline's own inputs (see SKIPPED list below and DATA_LAYOUT.md).
Run with --verify-only to check without copying anything.
"""
import argparse
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # .../Project
DEFAULT_SHARED_REPO = os.path.join(os.path.dirname(ROOT), "EBA5005-GC")

# (source path inside the shared repo, destination path inside Project, kind)
# kind controls how two existing files are compared: "csv" compares row count, "geojson"
# compares feature count, "bytes" (pdf etc.) compares raw byte length.
MAPPING = [
    ("data/raw/HDBPropertyInformation.csv", "HDBPropertyInformation.csv", "csv"),
    ("data/raw/ResaleflatpricesbasedonregistrationdatefromJan2017onwards.csv",
     "Resale flat prices based on registration date from Jan-2017 onwards.csv", "csv"),
    ("data/raw/CHASClinics.geojson", os.path.join("data", "geospatial", "CHAS_Clinics.geojson"), "geojson"),
    ("data/raw/Generalinformationofschools.csv",
     os.path.join("data", "geospatial", "General_Information_of_Schools.csv"), "csv"),
    ("data/raw/HawkerCentresGEOJSON.geojson", os.path.join("data", "geospatial", "Hawker_Centres.geojson"), "geojson"),
    ("data/raw/LTAMRTStationExitGEOJSON.geojson",
     os.path.join("data", "geospatial", "LTAMRTStationExitGEOJSON.geojson"), "geojson"),
    ("data/raw/ListofSupermarketLicences.csv", os.path.join("data", "geospatial", "Supermarkets_NEA.csv"), "csv"),
    ("data/raw/Parks.geojson", os.path.join("data", "geospatial", "Parks.geojson"), "geojson"),
    ("data/raw/mrt_station_openings.csv", os.path.join("data", "geospatial", "mrt_station_openings.csv"), "csv"),
    # daniel_add: this pipeline's own earlier raw/interim contributions, already pushed to
    # main under data/{raw,interim}/daniel_add/ with the SAME filenames this pipeline expects.
    ("data/raw/daniel_add/Childcare_Kindergarten_Centres_ECDA.csv",
     os.path.join("data", "geospatial", "Childcare_Kindergarten_Centres_ECDA.csv"), "csv"),
    ("data/raw/daniel_add/Community_Clubs.geojson", os.path.join("data", "geospatial", "Community_Clubs.geojson"), "geojson"),
    ("data/raw/daniel_add/HDBCarparkInformation.csv", os.path.join("data", "geospatial", "HDBCarparkInformation.csv"), "csv"),
    ("data/raw/daniel_add/LTA_Bus_Stop.geojson", os.path.join("data", "geospatial", "LTA_Bus_Stop.geojson"), "geojson"),
    ("data/raw/daniel_add/MasterPlan2019_Rail_Station_Layer.geojson",
     os.path.join("data", "geospatial", "MasterPlan2019_Rail_Station_Layer.geojson"), "geojson"),
    ("data/raw/daniel_add/PUB_Flood_Prone_Areas_2025.pdf", os.path.join("data", "geospatial", "PUB_Flood_Prone_Areas_2025.pdf"), "bytes"),
    ("data/raw/daniel_add/Vaccination_Polyclinics.geojson",
     os.path.join("data", "geospatial", "Vaccination_Polyclinics.geojson"), "geojson"),
    ("data/interim/daniel_add/childcare_postal_geocoded_v2.csv",
     os.path.join("data", "processed", "childcare_postal_geocoded_v2.csv"), "csv"),
    ("data/interim/daniel_add/expressway_points.csv",
     os.path.join("notebooks", "optimization_lead", "data", "expressway_points.csv"), "csv"),
    ("data/interim/daniel_add/flood_prone_geocoded.csv",
     os.path.join("notebooks", "optimization_lead", "data", "flood_prone_geocoded.csv"), "csv"),
    ("data/interim/daniel_add/hdb_carpark_latlon.csv", os.path.join("data", "processed", "hdb_carpark_latlon.csv"), "csv"),
    ("data/interim/daniel_add/job_nodes.csv",
     os.path.join("notebooks", "optimization_lead", "data", "job_nodes.csv"), "csv"),
]

# Real files on `main` with NO honest equivalent in this pipeline -- not copied, see
# DATA_LAYOUT.md for why each one was rejected rather than force-mapped.
SKIPPED = [
    ("data/raw/PreSchoolsLocation.geojson",
     "different dataset (SAP/GEP preschool centre codes) to this pipeline's "
     "Childcare_Kindergarten_Centres_ECDA.csv (ECDA vacancy data); also not currently "
     "read by any script here, so there is nothing to bridge"),
    ("data/raw/polyclinics.csv",
     "their hand-made full 26-polyclinic list vs. this pipeline's "
     "Vaccination_Polyclinics.geojson (8 COVID vaccination sites only, used today for "
     "dist_polyclinic_km) -- their list is probably BETTER for this purpose, but swapping "
     "the source changes every block's polyclinic distance and needs a backtest "
     "re-verification, so it is flagged here, not silently swapped in"),
]

# A true gap: no raw or processed equivalent exists anywhere in the shared repo.
TRUE_GAPS = [
    ("data/processed/hdb_rental_town_flattype_month.csv (read live by recommender_v2.py "
     "for dev_wait's monthly_rent)",
     "built from this pipeline's own 'RentingOutofFlatsfromJan2021.csv' -- the shared repo "
     "has no rental dataset at all (only resale transactions). Needs either this pipeline's "
     "own raw file or a fresh data.gov.sg download of 'Renting Out of Flats' before this "
     "pipeline can be rebuilt from a bare shared-repo checkout."),
]


def _count(path, kind):
    if kind == "csv":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f) - 1  # minus header
    if kind == "geojson":
        return len(json.load(open(path, encoding="utf-8")).get("features", []))
    return os.path.getsize(path)


def sync(shared_repo, verify_only=False):
    print(f"Shared repo: {shared_repo}")
    print(f"Project root: {ROOT}\n")

    copied, verified, mismatched, missing_source = [], [], [], []
    for src_rel, dst_rel, kind in MAPPING:
        src = os.path.join(shared_repo, src_rel)
        dst = os.path.join(ROOT, dst_rel)
        if not os.path.exists(src):
            missing_source.append((src_rel, dst_rel))
            continue
        if os.path.exists(dst):
            try:
                n_src, n_dst = _count(src, kind), _count(dst, kind)
            except Exception as e:
                mismatched.append((src_rel, dst_rel, f"could not compare ({e})"))
                continue
            if n_src == n_dst:
                verified.append((dst_rel, n_dst))
            else:
                mismatched.append((src_rel, dst_rel, f"shared repo has {n_src}, local has {n_dst}"))
        else:
            if verify_only:
                print(f"WOULD COPY  {src_rel}  ->  {dst_rel}")
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
            copied.append((src_rel, dst_rel))

    print(f"{'Would copy' if verify_only else 'Copied'}: {len(copied)}")
    for s, d in copied:
        print(f"  {s}  ->  {d}")
    print(f"\nAlready present & verified identical: {len(verified)}")
    for d, n in verified:
        print(f"  {d} ({n})")
    if mismatched:
        print(f"\nMISMATCHED -- not overwritten, needs a human look: {len(mismatched)}")
        for s, d, msg in mismatched:
            print(f"  {d}: {msg}")
    if missing_source:
        print(f"\nNot found in shared repo (expected path wrong, or repo not up to date): {len(missing_source)}")
        for s, d in missing_source:
            print(f"  {s}")

    print(f"\nSkipped (no honest equivalent, see DATA_LAYOUT.md): {len(SKIPPED)}")
    for s, reason in SKIPPED:
        print(f"  {s}: {reason}")
    print(f"\nTrue gaps (not present in the shared repo in any form): {len(TRUE_GAPS)}")
    for f, reason in TRUE_GAPS:
        print(f"  {f}: {reason}")

    return dict(copied=copied, verified=verified, mismatched=mismatched, missing_source=missing_source)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shared-repo", default=DEFAULT_SHARED_REPO,
                     help="Path to a comanetan/EBA5005-GC checkout (default: sibling EBA5005-GC folder)")
    ap.add_argument("--verify-only", action="store_true", help="Report what would happen, copy nothing")
    args = ap.parse_args()
    sync(args.shared_repo, verify_only=args.verify_only)

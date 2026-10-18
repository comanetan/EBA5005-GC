# Data layout: this pipeline vs. the shared repo (2026-10-18)

This pipeline's scripts read raw/processed inputs from a flat `Project/data/...` layout —
no `raw/` vs `interim/` split. The team's shared repo (`comanetan/EBA5005-GC`) uses a
different shape (`data/raw/`, `data/interim/`), so **there is no single path-variable swap
that makes this pipeline run directly against a bare shared-repo checkout.** This file
records exactly what was checked, what maps cleanly, and what genuinely doesn't — so the
next person doesn't have to re-derive it. `sync_shared_repo_raw_data.py` automates the
mappable part.

## Mappable (21 files, verified identical by row/feature/byte count before being wired in)

**Common raw sources** (both this pipeline and `main` downloaded the same data.gov.sg /
LTA / OneMap datasets independently, under different filenames):

| Shared repo (`data/raw/...`) | This pipeline | Verified |
|---|---|---|
| `HDBPropertyInformation.csv` | `HDBPropertyInformation.csv` | 13,357 rows, identical columns |
| `ResaleflatpricesbasedonregistrationdatefromJan2017onwards.csv` | `Resale flat prices based on registration date from Jan-2017 onwards.csv` | 241,920 rows, identical columns |
| `CHASClinics.geojson` | `data/geospatial/CHAS_Clinics.geojson` | 1,193 features |
| `Generalinformationofschools.csv` | `data/geospatial/General_Information_of_Schools.csv` | 337 rows, identical columns |
| `HawkerCentresGEOJSON.geojson` | `data/geospatial/Hawker_Centres.geojson` | 129 features |
| `LTAMRTStationExitGEOJSON.geojson` | `data/geospatial/LTAMRTStationExitGEOJSON.geojson` | 613 features |
| `ListofSupermarketLicences.csv` | `data/geospatial/Supermarkets_NEA.csv` | 478 rows, identical columns |
| `Parks.geojson` | `data/geospatial/Parks.geojson` | 462 features |
| `mrt_station_openings.csv` | `data/geospatial/mrt_station_openings.csv` | 44 rows, identical columns |

**This workstream's own earlier contributions** (already pushed to `main` under
`data/{raw,interim}/daniel_add/` in an earlier session, with the exact filenames this
pipeline expects — a straight folder-root change, no renaming):

| Shared repo | This pipeline | Verified |
|---|---|---|
| `data/raw/daniel_add/Childcare_Kindergarten_Centres_ECDA.csv` | `data/geospatial/Childcare_Kindergarten_Centres_ECDA.csv` | 1,871 rows |
| `data/raw/daniel_add/Community_Clubs.geojson` | `data/geospatial/Community_Clubs.geojson` | 125 features |
| `data/raw/daniel_add/HDBCarparkInformation.csv` | `data/geospatial/HDBCarparkInformation.csv` | 2,272 rows |
| `data/raw/daniel_add/LTA_Bus_Stop.geojson` | `data/geospatial/LTA_Bus_Stop.geojson` | 5,205 features |
| `data/raw/daniel_add/MasterPlan2019_Rail_Station_Layer.geojson` | `data/geospatial/MasterPlan2019_Rail_Station_Layer.geojson` | 257 features |
| `data/raw/daniel_add/PUB_Flood_Prone_Areas_2025.pdf` | `data/geospatial/PUB_Flood_Prone_Areas_2025.pdf` | 100,269 bytes |
| `data/raw/daniel_add/Vaccination_Polyclinics.geojson` | `data/geospatial/Vaccination_Polyclinics.geojson` | 8 features |
| `data/interim/daniel_add/childcare_postal_geocoded_v2.csv` | `data/processed/childcare_postal_geocoded_v2.csv` | 1,703 rows |
| `data/interim/daniel_add/expressway_points.csv` | `notebooks/optimization_lead/data/expressway_points.csv` | 20,831 rows |
| `data/interim/daniel_add/flood_prone_geocoded.csv` | `notebooks/optimization_lead/data/flood_prone_geocoded.csv` | 36 rows |
| `data/interim/daniel_add/hdb_carpark_latlon.csv` | `data/processed/hdb_carpark_latlon.csv` | 2,272 rows |
| `data/interim/daniel_add/job_nodes.csv` | `notebooks/optimization_lead/data/job_nodes.csv` | 5 rows |

**To (re-)populate a fresh checkout**: `python sync_shared_repo_raw_data.py [--shared-repo PATH] [--verify-only]`.
Tested 2026-10-18 against a simulated empty project directory — all 21 files copy correctly
with matching content (see `OPTIMISER_METHODOLOGY_REPORT.md` for the test description).

## Deliberately NOT mapped (real files on `main`, no honest equivalent here)

- **`data/raw/PreSchoolsLocation.geojson`** — a different dataset (2,290 SAP/GEP preschool
  *centre codes*) from this pipeline's `Childcare_Kindergarten_Centres_ECDA.csv` (ECDA
  childcare *vacancy* data). Also not read by any script in this pipeline today, so there's
  nothing to actually bridge even if the two were comparable.
- **`data/raw/polyclinics.csv`** — their hand-made, full 26-polyclinic list (name + postal
  code) vs. this pipeline's current source for `dist_polyclinic_km`,
  `Vaccination_Polyclinics.geojson` (only 8 COVID-vaccination sites, a real undercount of
  actual polyclinics). **Their list is probably the better source** — but swapping it in
  changes every block's polyclinic distance, which needs a backtest re-verification before
  going live, so this is flagged as a candidate improvement, not executed silently as part
  of a data-layout fix.

## True gap (not present in the shared repo in any form)

- **`data/processed/hdb_rental_town_flattype_month.csv`** — read *live* (not just at build
  time) by `recommender_v2.py::load_inputs()` for the `dev_wait` goal's `monthly_rent`.
  Built from this pipeline's own raw `RentingOutofFlatsfromJan2021.csv`. The shared repo has
  no rental dataset anywhere (`main` only ever downloaded resale transactions, not rentals).
  A fresh checkout needs either this pipeline's own raw file restored, or a new
  `data.gov.sg` download of "Renting Out of Flats" before the pipeline can run end to end.

## What this does and doesn't fix

This closes the gap for someone who has `EBA5005-GC` checked out and wants to reproduce
this pipeline's *inputs*. It does **not** change where this pipeline's own scripts read
from — they still use `Project/data/...` paths (`ROOT`-relative, portable across machines,
just not across repo layouts) — and it does not attempt to restructure this workstream's
own files into a `raw/`/`interim/` split to match `main`'s convention, since that would be
a much larger, higher-risk refactor for a benefit (matching a convention) that doesn't
change any output.

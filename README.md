# SG HomeFit: EBA5005 Group 2

Prescriptive recommender for HDB resale buyers. Proposal: `docs/EBA5005_Group2.pdf`.

## Folder layout
```
data/raw/         downloads, never edited (see "Data sources" below)
data/interim/     intermediate files made by the pipeline (address list, geocode cache, amenity points)
data/processed/   model-ready tables (block_features.csv, resale_features.csv)
outputs/          shared handover files between workstreams (formats below)
src/              pipeline scripts, run in order 01 → 07
src/homefit/      model code shared by steps 4, 6, 7 and the backtest (profiles, hedonic, survival)
notebooks/        01_raw_eda (data understanding) · 02_processed_eda (location vs price) · 03_survival (availability analysis) · 03b_survival_diagnostics (PH tests, residuals, model comparison, rolling backtest) · 04_hedonic (pricing model, SHAP, backtest) · 04b_hedonic_validation (validation designs, tuning, ablation, conformal intervals, index check) · 04c_hedonic_econometrics (semi-log hedonic regression, implicit prices, specification tests, spatial-error/lag models, new-MRT-station difference-in-differences) · 05_supplementary_eda (MOP supply, resale rate by age, time-series checks, affordability, spatial clustering)
docs/             proposal and report material
```

## Getting started (teammates)
1. VS Code → Command Palette (⇧⌘P) → **Git: Clone** → paste the repo URL → open the folder, then open `SG-HomeFit.code-workspace`.
2. **Terminal → Run Task → "0 · Set up Python environment"**, then **"Install modelling libraries"**.
3. Rebuild the local data (about 2 minutes, no internet needed): run tasks **1, 1b, 3, 4, 4b, 5** in order.
   Skip task 2: the geocode cache is already in the repo, so geocoding has nothing left to do.
   Tasks 6 and 7 (models, ~3 min) are optional: their outputs are already committed in `outputs/`.
4. Notebooks in `notebooks/` are saved with their outputs, so you can read them without re-running.

**Team rules:** pull before you start, push when you stop (Source Control panel). Edit only your own files and notebooks;
shared files (`src/config.py`, profile bands, handover formats) change only after the team agrees.

## First-time setup (VS Code)
1. Open `SG-HomeFit.code-workspace` (File → Open Workspace from File…). Install the recommended extensions if prompted.
2. **Terminal → Run Task… → "0 · Set up Python environment"**, which creates `.venv` and installs `requirements.txt`.
3. When VS Code asks, select `.venv` as the Python interpreter.
4. Modelling libraries (LightGBM, SHAP, lifelines, statsmodels, PuLP, Streamlit): `.venv/bin/pip install -r requirements-models.txt`

## Data build: Terminal → Run Task…
| Task | Needs internet | Time | Output |
|---|---|---|---|
| 1 · Unique addresses | no | seconds | `data/interim/unique_addresses.csv` (9,755 blocks), `primary_schools.csv` (182) |
| 1b · Clean + validate resale data | no | seconds | `data/interim/resale_clean.csv` (all rows, with flags), `docs/validation_report.md` |
| 2 · Geocode with OneMap | **yes** | ~45–60 min, resumable | `data/interim/geocode_cache.csv` |
| 3 · Amenity points | no | seconds | `data/interim/amenity_points.csv` |
| 4 · Build features + profiles | no | ~2 min | `data/processed/*.csv`, `outputs/profiles.csv` (profiles that exist today, from current stock) |
| 4b · Validate features | no | seconds | `docs/validation_report_features.md`; fails if prices/waits don't cover every profile |
| 5 · Price index | no | ~1 min | `outputs/price_index_v0.csv` (flat controls) and `price_index_v1.csv` (+ location, once step 4 has run): time-dummy hedonic index by region × flat type, Jan 2017 = 100 |
| 6 · Hedonic prices | no | ~2 min | `outputs/prices_today.csv` (LightGBM), `docs/hedonic_validation.csv`; add a month (e.g. `2023-06`) for a backtest run |
| 7 · Expected wait | no | ~1 min | `outputs/expected_wait.csv` (Cox survival); add a month for a backtest run |

Step 2 can be stopped and re-run at any time; it picks up where it left off. After adding polyclinics or a supermarket file, re-run step 2: it only geocodes the new postcodes, then re-run steps 3 and 4. Afterwards, check rows in
`geocode_cache.csv` where `match_quality` is `fallback` or `none` and fix them by hand before step 4.

## Handover file formats (the pipeline "contract")
Everyone writes their output in exactly these columns, keyed by `profile_id`. The Optimisation Lead owns this list.
| File | Columns | Owner | Status |
|---|---|---|---|
| `outputs/profiles.csv` | profile_id, town, flat_type, lease_band, mrt_band, storey_band, n_blocks, units, n_transactions_all, n_last12, median_price_last12 | shared | **built** by step 4: 1,828 profiles that exist today (blocks past MOP) |
| `outputs/prices_today.csv` | profile_id, price, price_low, price_high | Pricing & Availability | **model**: LightGBM hedonic, step 6 (low/high = 10th–90th percentile across the profile's blocks) |
| `outputs/expected_wait.csv` | profile_id, wait_months, wait_p10, wait_p90, scarce | Pricing & Availability | **model**: Cox survival, calibrated by flat type and blended with recent sales, step 7 (scarce = capped at 120 months) |
| `outputs/optimisation/pricing_today.csv` | profile_id, price_today, price_today_se, price_low, price_high | Pricing & Availability → Optimisation | same model on the Optimisation Lead's IDs (`TOWN::4ROOM::60-79::Mid::Near`, with lease band), step 6 |
| `outputs/optimisation/availability.csv` | profile_id, expected_wait_months, survival_prob_6m, survival_prob_12m, hazard_ratio, scarce | Pricing & Availability → Optimisation | same model on the Optimisation Lead's IDs, step 7 |
| `outputs/price_index_v1.csv` | month, region, flat_type, index, n_sales, median_price | Pricing & Availability → Forecasting | **use this**: flat + location controls (MRT at time of sale, amenities). `price_index_v0.csv` = flat controls only |
| `outputs/price_paths.csv` | profile_id, month, p10, p50, p90 | Forecasting | to do |
| `outputs/weights.json` | {attribute: {level: WTP_$}} | Preference | to do |
| `outputs/shortlist.csv` | household_id, rank, profile_id, … | Optimisation | to do |

`profile_id` = `TOWN|FLAT_TYPE|LEASE_BAND|MRT_BAND|STOREY_BAND`, e.g. `TAMPINES|4 ROOM|80+|<500m|7-12`.
Bands are defined once in `src/config.py`; change them there only, then re-run step 4.

## Models and the backtest interface
Every model function takes `as_of` ("YYYY-MM") and uses only sales up to that month: lease band and MRT band are worked out
as of that date, and only blocks past their 5-year MOP by then count as stock. So the whole chain can be re-run in the past.
```python
import sys; sys.path.insert(0, "src")
from homefit import profiles, hedonic, survival
prof   = profiles.current_profiles("2023-06")            # profiles that existed in Jun 2023
model  = hedonic.fit("2023-06"); prices, _ = hedonic.price_profiles(model, "2023-06")
cox    = survival.fit("2023-06"); waits, _ = survival.profile_waits(cox, "2023-06")
```
From the terminal: `python src/06_hedonic_prices.py 2023-06` and `python src/07_expected_wait.py 2023-06` write
`outputs/backtest/2023-06/prices.csv` and `expected_wait.csv` (~1 min together). Validation results: `docs/model_validation.md`.
Notebook 03 documents the survival analysis; `src/homefit/survival.py` is the production version used by step 7.

## Data sources (downloaded 3 Oct 2026, raw files unchanged)
| File | Source | Rows |
|---|---|---|
| ResaleflatpricesbasedonregistrationdatefromJan2017onwards.csv | data.gov.sg (HDB) | 241,920 (Jan 2017 – Oct 2026; Oct 2026 partial) |
| HDBPropertyInformation.csv | data.gov.sg (HDB) | 13,357 blocks |
| Generalinformationofschools.csv | data.gov.sg (MOE) | 337 schools (182 primary incl. mixed P1–S4) |
| LTAMRTStationExitGEOJSON.geojson | data.gov.sg (LTA) | 613 exits (541 MRT, 72 LRT) |
| HawkerCentresGEOJSON.geojson | data.gov.sg (NEA) | 129 (123 existing used) |
| CHASClinics.geojson | data.gov.sg (MOH) | 1,193 |
| PreSchoolsLocation.geojson | data.gov.sg (ECDA) | 2,290 |
| mrt_station_openings.csv | hand-made from LTA/Wikipedia opening dates + OneMap | 44 stations opened since 2017 (5 missing from the LTA exit file added with coordinates) |
| polyclinics.csv | hand-made (SingHealth / NHGP / NUP clinic lists) | **to fill**: name, postal_code |
| *supermarket*.csv (optional) | data.gov.sg (SFA licensed supermarkets) | not yet downloaded |
| Parks*.geojson (optional) | data.gov.sg (NParks "Parks") | not yet downloaded |
| Block coordinates | OneMap Search API (SLA) | generated by step 2 |

Still to collect: MAS SORA (Forecasting), cooling-measure dates (Forecasting), conjoint responses (Preference).

## Geocoding quality (3 Oct 2026)
9,755 / 9,755 blocks geocoded. 9,749 exact block + street matches; 6 corrected by hand where OneMap returned the same block number on a different street (e.g. Jln Batu → Jln Gali Batu). LTA's exit file lists 7 stations by code (e.g. DT4 = Hume); names are mapped in `config.py`, checked against exit coordinates.

## Known limitations to state in the report
- MRT distance is time-aware: `dist_mrt_at_sale_m` only counts stations open when the sale month began (use it in the hedonic model); profile bands use the network open at the profile date (`homefit.common.mrt_distance_as_of`). Circle Line Stage 6 (Keppel, Cantonment, Prince Edward Road) opened 12 Jul 2026, verified against LTA's May 2026 release.
- Oct 2026 is a partial month; step 4 uses the 12 most recent *complete* months for recent statistics.

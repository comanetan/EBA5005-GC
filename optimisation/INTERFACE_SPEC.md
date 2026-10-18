# Optimisation Lead — handover file formats & pipeline structure
**Task 1 deliverable. Due 1 Oct 2026. Audience: all four leads.**

> ## ⚠ v2 UPDATE (4 Oct 2026) — profile definition changed. Please read this box first.
> Every HDB block is now geocoded (13,356/13,357). Evidence (see
> `Optimisation_Lead_Pipeline_v2_BlockLevel.ipynb`): 79% of MRT-distance variance is *within* towns, and
> block accessibility explains price beyond town effects. So the shared unit of analysis is now:
>
> **`profile = town × flat_type × storey_band × mrt_band`**, `mrt_band ∈ {Near ≤400m, Mid 400–800m, Far >800m}`
> measured to the nearest **operating** MRT exit (LTA exit layer). **712 profiles.**
>
> `profile_id` format: `"{TOWN}::{FLATTYPE}::{StoreyBand}::{MRTBand}"`, e.g. `"TAMPINES::4ROOM::Mid::Near"`.
>
> What this means for each lead:
> - **Pricing & Availability** — `pricing_today.csv` and `availability.csv` keyed by the v2 `profile_id`.
>   `data/transactions_block_access.parquet` already joins every sale to its block's accessibility;
>   `housing_profiles_v2_full.csv` has `units_in_profile_blocks` = exposure for the survival model.
> - **Forecasting** — no schema change (`price_forecast.csv` stays by town × flat_type). But please report
>   interval **coverage at v2 granularity**: finer cells move more than town-level. `empirical_bands.py`
>   (p90 ≈ +16–21%/12m) is the benchmark your intervals should beat.
> - **Preference** — `preferences.json` gains `household_multiplier` per attribute (1.0 = values it like the
>   market). Market (revealed) rates are in `market_wtp_coefficients.json`; conjoint WTP ÷ market rate = multiplier.
> - **Dashboard** — `profile_block_drilldown.csv` lists the actual blocks (address, lat/lon, sales) behind each profile.
>
> v1 files (town-level, 322 profiles) are kept for comparison; v1 sections below remain accurate for v1 only.
>
> **v2.1 accessibility update** (same `profile_id` format):
> - **Rail is date-aware.** 5 operating stations missing from LTA's exit layer were patched (Punggol Coast, Hume,
>   Keppel, Cantonment, Prince Edward Rd). For any **historical** model use `dist_mrt_exit_km_at_sale` /
>   `mrt_band_at_sale` in the parquet (stations count only after opening, 40 dated stations); `dist_mrt_exit_km`
>   is today's network and is what profiles and recommendations use.
> - **School access = MOE P1 tiers** (straight-line: `Within 1km` / `1-2km` / `Beyond 2km`): `primary_tier`
>   (any of 182 P1 schools) and `elite_primary_tier` (20 SAP/GEP schools). Profiles carry
>   `share_elite_primary_1km` / `share_elite_primary_2km`. Childcare: `childcare_band` (200m / 500m).
> - **Preference Lead:** please estimate school WTP **per tier** (`elite_primary_within_1km`, `elite_primary_1_2km`,
>   both already in `market_wtp_coefficients.json`), not per school count — `per_additional_school_within_1km`
>   below is superseded.
> - **Walking distances** (`walk_*_km`, OSM network) are available per block for display; they are not the model
>   input (OSM gaps; they did not explain price better than straight-line).
>
> **v2.2 new attributes** (2026-10-08, same `profile_id` format, same 712 profiles): 6 new attribute groups
> added to `block_accessibility.csv` → `housing_profiles_v2_full.csv`. **Descriptive/filterable only**,
> usable today via `profiles=` filtering or the web app's search tab — with ONE exception (expressway,
> see v2.3 below), since pricing the others would need a hedonic re-fit with real evidence that the
> coefficient is trustworthy (see `OPTIMISER_METHODOLOGY_REPORT.md` §9 — 3 of 4 tested candidates were
> explicitly REJECTED for a bad or confounded sign, not just "not done yet").
> - **Secondary school** — `dist_secondary_school_km_p50`, `dist_secondary_elite_km_p50` (autonomous/IP
>   status, the S1-level analogue of SAP/GEP), `secondary_tier`. Same source as primary school
>   (`General_Information_of_Schools.csv`, MOE). **Not a MOE admission-priority band** — S1 posting is
>   PSLE-score-based, not home-distance-based, unlike P1. **Tested for pricing and rejected** (§9):
>   counterintuitive positive sign, same cause as primary school's exclusion.
> - **Carpark** — `dist_carpark_km_p50`, `dist_carpark_night_km_p50`, `share_has_carpark_400m`,
>   `share_has_night_parking_400m`. Source: data.gov.sg `HDB Carpark Information`
>   (dataset `d_23f946fa557947f93a8043bbef41dd09`), SVY21 → WGS84 via pyproj. **Tested for pricing and
>   rejected** (§9): not statistically significant (p=0.26).
> - **Flood-prone flag** — `dist_flood_prone_km_p50`, `share_near_flood_prone_area` (≤300m). Source: PUB's
>   published 36-location list (`List-of-Flood-Prone-Areas-as-at-Apr-2025.pdf`), free-text locations
>   geocoded via OneMap search. **Point proxy for a named road/junction, not a flood-extent polygon** — only
>   175/10,795 residential blocks are within 300m of one (most listed locations are private/landed/CBD
>   roads, not HDB estates); treat as a coarse flag, not a risk model. **Tested for pricing and REJECTED**
>   (§9): the coefficient is significant but confounded (flagged blocks cluster in prime central estates) —
>   do not price this in even though it looks significant.
> - **Expressway/noise proxy** — `dist_expressway_km_p50`, `expressway_proximity_band`. Source: OSM
>   motorway/trunk/motorway_link/trunk_link ways for all of Singapore (20,831 sampled vertices via
>   `osmnx.features_from_place`). **Straight-line distance to the nearest road vertex, not a measured dB
>   noise level** — no public noise dataset covers this.
> - **Decentralised employment nodes** — `dist_{node}_km_p50` for 5 named nodes (`raffles_place`,
>   `jurong_lake_district`, `punggol_digital_district`, `one_north`, `woodlands_regional_centre`), plus
>   `dist_nearest_job_node_km_p50` / `nearest_job_node`. Geocoded via OneMap search. **Straight-line distance
>   to a fixed point, explicitly NOT real transit travel time** — true PT travel time would need LTA's GTFS
>   feed or an authenticated OneMap routing token (neither available/set up); don't present this as "commute
>   time" without that caveat.
> - **MULTI-GENERATION flat type** — deliberately kept OUT of the main 712-profile table (only 88
>   transactions nationwide since 2017, 3 towns only — too thin for the trailing-12-month / block-level /
>   shrink_k=10 machinery). Instead: `multigen_profiles.py` builds a separate town-level, all-time-window
>   table (`data/multigen_profiles.csv`, 3 rows) with an explicit `data_quality` caveat column, queryable via
>   `multigen_profiles.load_multigen_profiles()` + `recommender_v2.solve(query, profiles=...)`. No hedonic
>   value gap for this flat type (`hedonic_gap` is NaN by design — no model was fit on 88 rows).
>
> **v2.3 expressway priced in as a GOAL** (2026-10-10, see OPTIMISER_METHODOLOGY_REPORT.md §9): of the 4
> v2.2 attributes tested as hedonic regressors, only `dist_expressway_km` passed both the within-town-variance
> and sign/significance checks (+0.94%/km, p<0.0001, correctly signed as a disamenity). Added to
> `hedonic_value.WTP_ATTRS` → `market_wtp_coefficients.json["dist_expressway_km"]`. Wired into
> `recommender_v2.HouseholdQuery2` as `target_expressway_km` (default `None` = inactive) — a MINIMUM-distance
> goal (mirror of `target_mrt_km`'s maximum-distance goal), producing `dev_expressway` in the shortlist and
> `goal_deviation_total`. Exposed in the web app's Final Recommender tab. Backtest re-run after this change:
> 98.8% within-budget reliability, unchanged from the pre-change baseline.
>
> **v2.6 Pricing & Availability now native to this pipeline's profile IDs** (2026-10-18, see
> OPTIMISER_METHODOLOGY_REPORT.md §12): as of `main` commit `42df63b` (17 Oct), the Pricing & Availability
> Lead writes `outputs/optimisation/pricing_today.csv` / `availability.csv` directly on this pipeline's own
> `profile_id` — no crosswalk needed. `pricing_availability_adapter.py` gained `build_from_native()`, a
> pass-through that supersedes the crosswalk functions below for current runs (kept for historical/backtest
> reproduction only). Coverage: **99.7% of profiles (706/708)**, up from 96.2% (681/708). Checked against
> Forecasting's own documented caveat ("do not independently sample [price_paths.csv] rows for Monte
> Carlo"): `monte_carlo.py`/`chance_constraint.py` only ever use the summary `growth_factor` columns, never
> the row-level quantile table — no change needed. Also published `outputs/shortlist.csv`
> (`build_shortlist.py`), this pipeline's own deliverable on the team's shared handover contract.
>
> **v2.5 MRT premium corrected for spatial bias** (2026-10-18, see OPTIMISER_METHODOLOGY_REPORT.md §11): the
> Pricing & Availability Lead's `notebooks/04c_hedonic_econometrics.ipynb` (main branch) found a naive
> town-FE hedonic overstates the MRT premium ~2x vs. their spatially-corrected/causal (DiD on 11 real new
> stations) estimate. Checked directly: this pipeline's own `dist_mrt_exit_km` coefficient implied the
> identical inflated number (5.28% per halving) as their comparable naive specification. `hedonic_value.py`
> now applies their recommended ~3% benchmark as a correction factor (`MRT_SPATIAL_CORRECTION`) to the
> **exported WTP rate** (preference tilt, `dev_mrt`, GP calculator default) — not to the hedonic's own price
> predictions, which is a separate, not-yet-done fix. Backtest re-verified: 96.6% [93.1-98.3%], statistically
> unchanged from 97.6% [94.5-99.0%] before.
>
> **v2.4 real adapters for Pricing/Availability and Forecasting** (2026-10-12, see OPTIMISER_METHODOLOGY_REPORT.md
> §10): `pricing_today.csv` / `availability.csv` / `price_forecast_live.csv` are no longer stubs — built by
> `pricing_availability_adapter.py` / `forecasting_adapter.py` from the other leads' REAL branches (`main` /
> `forecasting` in comanetan/EBA5005-GC), via a profile_id crosswalk (`profile_crosswalk.py`, their 5-part
> `TOWN|FLATTYPE|LeaseBand|MRTBand|StoreyRange` scheme → this pipeline's 4-part one). **96.2% of profiles
> (681/708) now have real pricing/availability**; forecasting real coverage is **4-ROOM only, all 26 towns**
> (their model's own stated scope), every other flat type still on the stub.
> - **Opt-in by design, not automatic everywhere**: real data is only substituted when `assemble()` infers
>   `live=True` (i.e. `profiles=None` was passed, meaning "today"). Any explicit historical `profiles`
>   snapshot (the backtest, multigen) gets `live=False` automatically — real data can never leak into a
>   historical cutoff. Verified: backtest reliability unchanged (98.8%) after wiring this in.
> - **The hedonic "bargain" signal is suppressed, not recalculated naively, for real-priced profiles.**
>   `hedonic_value` was fit against this pipeline's own `median_price`, not the Pricing Lead's real,
>   lease-band-blended `price_today` — the two disagree by a median 2.5% but up to ±50-80% at the tails.
>   Comparing them would mostly measure model disagreement, not real mispricing, so `shrunk_value_gap` is
>   set to $0 (not fabricated) for every real-priced profile until the hedonic is re-fit against the real
>   price as its target — flagged as the top follow-up item, see §10's "what's still needed" list.
> - Run `python pricing_availability_adapter.py && python forecasting_adapter.py` to refresh against a
>   newer snapshot of the other branches (re-download via `data/external_handovers/`, see the scripts).

This is the contract the recommender is built against. If your module's real
output doesn't match a schema below, either the schema changes (tell the
Optimisation Lead before 2 Oct) or your adapter changes — don't let the
recommender guess.

## 0. The shared unit of analysis: a "housing profile"

**Assumption (not yet confirmed with Pricing/Forecasting leads — flag ASAP if
you've defined this differently):**

> `profile = (town × flat_type × storey_band)`, `storey_band ∈ {Low, Mid, High}`
> (Low = 01–06, Mid = 07–15, High = 16+), matching the storey levels already
> used in the conjoint design.

Built from the last 12 months of HDB resale transactions, dropping any
town/flat_type/storey_band cell with fewer than 3 transactions (too thin to
price reliably). Current count: **322 profiles** across 26 towns × 6 flat
types (MULTI-GENERATION excluded — too rare) × 3 storey bands.

`profile_id` format: `"{TOWN}::{FLATTYPE}::{StoreyBand}"`, e.g.
`"TAMPINES::4ROOM::Mid"`. This id is the join key across every file below.

File: `data/housing_profiles.csv`
| column | type | meaning |
|---|---|---|
| profile_id | str | join key |
| town | str | HDB town (26 standard towns) |
| flat_type | str | `2 ROOM`...`EXECUTIVE` |
| storey_band | str | Low / Mid / High |
| median_price | float | trailing-12mo median resale price, SGD (placeholder "price today" until the hedonic model lands) |
| median_price_psm | float | trailing-12mo median $/sqm |
| median_floor_area | float | sqm |
| median_remaining_lease | float | years |
| txn_count_12m | int | liquidity / sample-size signal |
| nearest_mrt_km, mrt_stations_within, bus_stops_within | float/int | town-level (not block-level) accessibility |
| schools_within, nearest_school_km | float/int | town-level primary-school proximity |
| hawker_within, parks_within, cc_within, polyclinic_within | int | town-level amenity counts |
| supermarkets_within, chas_clinics_within, childcare_within | int | town-level amenity counts (added for FINAL proposal's amenity list) |

**Known limitation**: all locational/amenity features are **town-level
averages**, not block-level. A true block-level join (OneMap geocode per
block) is a stretch goal, not a Day-1 dependency — the recommender works
fine on town-level features and we upgrade later if time allows.

## 1. Pricing & Availability Lead → `pricing_today.csv`
| column | type | meaning |
|---|---|---|
| profile_id | str | join key |
| price_today | float | hedonic model's fitted/predicted price for this profile, SGD |
| price_today_se | float | standard error of the hedonic estimate (used for a simple uncertainty band until the real interval exists) |

**Stub until ready**: `median_price` from `housing_profiles.csv`, `price_today_se` = 5% of price.

## 2. Pricing & Availability Lead → `availability.csv`
| column | type | meaning |
|---|---|---|
| profile_id | str | join key |
| expected_wait_months | float | Kaplan-Meier median time-to-next-resale for this profile's (town, flat_type) cohort |
| survival_prob_6m | float | P(a matching flat transacts within 6 months) |
| survival_prob_12m | float | P(a matching flat transacts within 12 months) |
| hazard_ratio | float | Cox PH hazard ratio vs. baseline (optional, for interpretation only) |

**Stub until ready**: exponential survival with rate calibrated to each
profile's `txn_count_12m` (higher turnover -> shorter expected wait).

## 3. Forecasting Lead → `price_forecast.csv`
Forecasts are **by region and flat type** (coarser than profile-level,
per the proposal) and applied as a growth multiplier on top of `price_today`.
"Region" = town for now (document says region; we don't have a region
crosswalk yet, so town is the working granularity until told otherwise).

| column | type | meaning |
|---|---|---|
| town | str | join key (joins to profile via town) |
| flat_type | str | join key |
| horizon_months | int | 6 or 12 |
| growth_factor | float | E[price_t+h / price_t] |
| growth_factor_lower | float | lower bound of the SARIMAX prediction interval (e.g. 10th pct) |
| growth_factor_upper | float | upper bound of the SARIMAX prediction interval (e.g. 90th pct) |

**Stub until ready (14 Oct)**: flat growth_factor = 1.00 with ±8%/±12%
bounds at 6/12 months, loosely calibrated to the GARCH volatility figures
already computed for Option A.

## 4. Preference Lead → `preferences.json`
Default (population-level) preference weights from the choice-based conjoint,
expressed as **willingness-to-pay in SGD** (so the recommender's objective
is dollar-denominated throughout) plus the raw elasticity/part-worths for
reference.

```json
{
  "wtp_sgd": {
    "per_km_closer_to_mrt": 25000,
    "per_additional_school_within_1km": 8000,
    "per_year_remaining_lease": 3000,
    "storey_band_premium": {"Low": 0, "Mid": 12000, "High": 20000},
    "per_amenity_count": 1500
  },
  "price_elasticity_of_choice": -1.2,
  "part_worths": { "...": "as estimated by conjoint_analysis.py" }
}
```

**Stub until ready**: the dict above, lifted from the Option B notebook's
earlier simulated-conjoint run, clearly marked as placeholder.

## 5. Optimisation Lead → outputs (what the dashboard/backtest consume)

`shortlist.csv` — one row per selected profile for a given household query:
`household_id, profile_id, town, flat_type, storey_band, price_today,
price_upper_forecast, wtp_surplus, goal_deviation_total, rank`

`sensitivity_results.csv` — one row per (budget, min_lease) grid point:
`budget, min_lease_yrs, objective_value, n_feasible_profiles, shortlist_profile_ids`

`montecarlo_scenarios.csv` — one row per (profile_id, scenario, horizon):
`profile_id, scenario_id, horizon_months, simulated_price, matched_available`

`dashboard_payload.json` — the above three, nested under a household query,
plus the household's input parameters, for the what-if dashboard to render.
Current example (v2 schema, 4-part profile_id): `data/dashboard_payload_example.json`,
regenerated by `python make_dashboard_payload_v2.py`.

## 6. Pipeline ownership
The Optimisation Lead keeps `run_pipeline.py` executable end-to-end **every
day** from 2 Oct onward, against whatever mix of real and stub files exists
at that moment. Each lead swaps in their real file by replacing the
corresponding CSV/JSON in `data/` — same filename, same schema. Check-ins:
9, 14, 16 Oct. Pipeline freeze: 19 Oct (inputs frozen; only re-runs after that).

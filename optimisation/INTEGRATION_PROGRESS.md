# Integration Progress Report — Optimisation Workstream

**As of:** 18 Oct 2026 · **Branch:** `optimisation` (8 commits, up to date with `origin/optimisation`)
**Compiled from:** `git log`/`git show` against `origin/main` and `origin/forecasting`, this branch's adapter scripts, and `README.md` / `docs/model_validation.md` on `main`.

Legend: 🟢 delivered & wired in · 🟡 delivered, not yet wired in (action is on me) · 🔴 not delivered — blocking ask · ⚪ my own deliverable, owed to the team

---

## 1. Pricing & Availability Lead (Tan Xue Min Comane) — 🟡 mostly delivered, I need to re-pull

**Good news first:** as of `main` commit `42df63b` (**17 Oct**, 6 days *after* the snapshot I built my adapter against), Pricing & Availability started writing output **directly in my own profile-ID scheme** — I no longer need my crosswalk adapter for these two files.

| What | File (on `main`) | Columns | Status |
|---|---|---|---|
| Price per profile | `outputs/optimisation/pricing_today.csv` | `profile_id, price_today, price_today_se, price_low, price_high` | 🟢 exists, native to my IDs |
| Availability per profile | `outputs/optimisation/availability.csv` | `profile_id, expected_wait_months, survival_prob_6m, survival_prob_12m, hazard_ratio, scarce` | 🟢 exists, native to my IDs |
| Backtest versions | `outputs/backtest/<as_of>/optimisation/{pricing_today,availability}.csv` | same columns | 🟢 exists for `2023-06`; `docs/model_validation.md` says "matches Optimisation's 2025-01-01 cutoff" — **confirm with them whether a `2024-12` backtest snapshot is also cut** |

**Coverage, per their own `docs/model_validation.md` §3b:** 952 of my profiles exist in their file; 713 have ≥3 sales in the last 12 months against my own count of 712 — essentially full agreement. Any profile_id missing from their file is a genuine boundary case (our distance bands disagree at the edge), not a gap.

**Done (18 Oct):**
1. ✅ `pricing_availability_adapter.py` now has `build_from_native()`, a pass-through (not a crosswalk) that reads `outputs/optimisation/{pricing_today,availability}.csv` straight off the 17 Oct `main` snapshot. Re-ran it: coverage went from **682/708 (96.2%, 12 Oct crosswalk)** to **706/708 (99.7%, 17 Oct native)**. The old crosswalk functions are kept in the file for historical/backtest reproduction only.
2. ✅ Resolved: `price_today_se` in their new file is documented as `price × 0.052` (hold-out log-RMSE on unseen blocks) — a different definition from my old adapter's percentile-based approximation. Audited every consumer; see the resolution table below — no live computation actually uses this column.

**One optional ask, not blocking:** their hedonic is fit against a different price basis than mine, which is why I currently suppress my own "bargain" signal (`shrunk_value_gap`) to $0 for every real-priced profile (see Finding 2 in `OPTIMISER_METHODOLOGY_REPORT.md`). If they're willing to share **block-level predicted price** (not just the profile aggregate), I could re-fit my own hedonic against their target and re-enable that signal instead of suppressing it. Not urgent — flagging for later.

**Checked again (19–20 Oct):** no new commits on `main` since 17 Oct (`209c94b`). Two things found while checking, both now acted on or logged:
1. ✅ **Re-ran the crosswalk adapter** against the current (post-scope-alignment) 1,013-profile universe — `pricing_today.csv`/`availability.csv` were one day stale (18 Oct, still built against the pre-2-ROOM/EXECUTIVE-removal 1,184 profiles). Refreshed coverage: **958/1,013 (94.6%)** for both files, median price SE $30,431, median wait 1.0 months.
2. ✅ **Done (20 Oct):** `outputs/backtest/2024-12/optimisation/{pricing_today,availability}.csv` — their own 2024-12 backtest snapshot, cross-validated against realised 2025-2026 outcomes on 656 overlapping cells (4-part native grain, aggregated up from this pipeline's own 5-part profiles since their file predates lease_band). Their price prediction beat this pipeline's own trailing-12-month-median baseline in 66.8% of cells (4.89% vs. 6.21% median MAPE); their availability model also had a better Brier score (0.0024 vs. 0.0035). Independent, external confirmation that their model earns its keep over the naive baseline. See `OPTIMISER_METHODOLOGY_REPORT.md` §25.

---

## 2. Forecasting Lead — 🟢 mostly delivered, wired in (19 Oct)

**Updated 19 Oct.** Three new commits on `forecasting` today expanded real coverage from 4-ROOM only to **3-ROOM, 4-ROOM and 5-ROOM, all 26 towns** (`MULTITYPE_HANDOVER.md`). **2-ROOM and EXECUTIVE are now explicitly out of scope on their side** ("the API rejects them") — rather than leave those two running on the flat stub indefinitely with no path to a real forecast, this pipeline's own flat-type universe was aligned to match: **2-ROOM and EXECUTIVE removed entirely** (`housing_profiles_v2.py`, `backtest_v2.py`, `backtest.py` — see `OPTIMISER_METHODOLOGY_REPORT.md` §23 for every touchpoint). Profile count **1,184 → 1,013**.

| File | Columns | Coverage |
|---|---|---|
| `forecasting/evidence/multitype/price_forecast.csv` | `town, flat_type, horizon_months, growth_factor, growth_factor_lower, growth_factor_upper` | **3/4/5-ROOM, all 26 towns** — already pre-aggregated to this pipeline's own grain, no crosswalk needed this time |
| `forecasting/evidence/multitype/price_paths_metadata.json` | base month (2026-09), model version, coverage | — |

`forecasting_adapter.py` rewritten against this (`build_price_forecast()`) — real coverage confirmed 26/26 towns × 3 types × 2 horizons, median `growth_factor` 1.0201 (6mo) / 1.0405 (12mo) vs. the stub's flat 1.00. Written to `price_forecast_live.csv` only (the live/production path) — deliberately **not** `price_forecast.csv` (the backtest's stub-only, time-invariant file), since their multitype model has one current snapshot, not dated as-of-cutoff snapshots, and using it for a historical cutoff would be look-ahead bias. Full rebuild + re-verification against both the extended backtest and a live-path isolation test — not assumed safe, see §23.

**What's left:**
1. ⚪ Low priority, unchanged from before: MAS SORA rate series and cooling-measure dates still "to collect" on their side per their `NEXT_STAGE.md`-equivalent notes. Doesn't block today.
2. ✅ **Re-checked (19 Oct):** their own `MULTITYPE_HANDOVER.md` flags *"`fcast_override` alone does not recompute deterministic `price_upper`."* Confirmed in `recommender_v2.py`: `assemble()` computes `price_upper` from `load_inputs()`'s forecast file before `_prepare()` ever sees `fcast_override` — so the fix is architectural (write the real file, as already done), not a code change to `_prepare()`/`assemble()`. No action needed beyond what §23 already did.
3. ⚪ New, low priority: their handover flags **PuLP 4 removes `PULP_CBC_CMD`**, used throughout this pipeline's solver calls. Worth pinning the PuLP version before any environment upgrade; not urgent today.
4. ✅ **Done (19 Oct):** their flagged Monte Carlo gap — *"replacing marginal forecast CSVs alone does not replace the existing Monte Carlo engine"* — closed. `run_joint_monte_carlo()` vendored (`external_forecasting_pkg/forecasting/`) and wired into `monte_carlo.py::run_monte_carlo()` as the primary engine for 3/4/5-ROOM, stand-in simulator kept as fallback for 1-ROOM. Verified the fix is real, not cosmetic: the old engine's actual joint success probability matched its naive independent product almost exactly (confirming it was implicitly independent); the new engine's sits 6.5 points above its own naive product (genuine, measured cross-profile correlation). See `OPTIMISER_METHODOLOGY_REPORT.md` §24.

---

## 3. Preference Lead — 🟡 landed 22 Oct, partially wired (see below)

**No branch exists for this workstream** (`git branch -a` shows only `main`, `forecasting`, `optimisation`). `main`'s own hand-over table lists `outputs/weights.json` as **"to do"**, and my own pipeline's stub carries the note `"STUB … replace with real choice-based conjoint output by 16 Oct"` — **two days overdue** as of today.

This is the single biggest open gap. The good news: the exact contract is already built and tested end-to-end against a stub — I need **one file**, not a code change.

### Exact file needed

**Path:** `preferences.json` (same filename, drop it in `optimisation/data/`)
**Format:** JSON, single object, UTF-8, extension `.json` (not `.csv` — this is a nested structure, a flat table won't carry the `storey_band_premium` sub-object)

```json
{
  "wtp_sgd": {
    "per_km_closer_to_mrt": <number, SGD>,
    "per_additional_school_within_1km": <number, SGD>,
    "per_year_remaining_lease": <number, SGD>,
    "storey_band_premium": {"Low": <number>, "Mid": <number>, "High": <number>},
    "per_amenity_count": <number, SGD>
  },
  "price_elasticity_of_choice": <number, negative>,
  "_source": "<model/method description>"
}
```

Current stub values (what every number is currently defaulting to, for scale):
`per_km_closer_to_mrt: 25000` · `per_additional_school_within_1km: 8000` · `per_year_remaining_lease: 3000` · `storey_band_premium: {Low: 0, Mid: 12000, High: 20000}` · `per_amenity_count: 1500` · `price_elasticity_of_choice: -1.2`.

### Field-by-field spec — what each number means to my model

| Field | Units | How I use it |
|---|---|---|
| `per_km_closer_to_mrt` | SGD, per km | Converted to a multiplier on the market's own fitted $/km-to-MRT rate (currently **$33,100/km**, post spatial-bias correction — see §11 of the Word report) via `wtp / market_rate`. If your conjoint design can anchor against **~3% price effect per halving of MRT distance** rather than a naive ~5-6%, that's the figure the Pricing Lead's spatial econometrics notebook recommends handing you — worth aligning your instrument to it. |
| `per_additional_school_within_1km` | SGD, flat amount | Passed through directly as a $ override on the school goal (currently approximated — my school goal is tier-based: "within 1km" vs "within 2km" vs "any", not count-based like this field; flag if your conjoint can be elicited tier-wise instead, it'd map more cleanly) |
| `storey_band_premium` | SGD, 3 levels (Low/Mid/High) | I average the Low→Mid and Mid→High steps into one $/band step |
| `per_amenity_count` | SGD, flat amount | Direct pass-through, used for the "essentials score" goal (hawker/clinic/supermarket/park counts) |
| `per_year_remaining_lease` | SGD, per year | **Not wired yet** on my side — lease is currently a hard eligibility floor (`min_lease_yrs`), not a priced preference. Send it anyway; I'll wire it once this lands. |
| `price_elasticity_of_choice` | unitless, negative | Not currently consumed — reserved for a future softmax/logit choice-share step if we add one |

**Where this plugs in, so you can see it's not vaporware:** `optimisation/recommender_v2.py::preference_overrides_from_file()` already reads this exact schema and converts it into the recommender's internal weights — tested against the stub above. Drop in the real file at `optimisation/data/preferences.json` and re-run; **no code change needed on my end** unless your real field names differ from the stub (in which case, tell me the names and I'll extend the mapping, same function).

**If the full conjoint isn't ready in time:** even partial coverage helps — e.g. just `per_km_closer_to_mrt` and `storey_band_premium` would already replace two of my five stubbed weights with real numbers.

**Checked again (19–20 Oct):** still no branch, no `preferences.json`. Two things found while checking, neither changes the blocking status:
- `Project/Conjoint/` has a real, usable **survey design** (`HDB_Conjoint_Design.xlsx` — 6 attributes, 8 tasks + 1 holdout × 3 alternatives) and a worked **demo analysis** on 200 *synthetic* respondents (`HDB_Conjoint_Demo_Results.xlsx`, and a later `...with_holdout_simulator_elasticity-v2 (1).xlsx` — same underlying synthetic fit, confirmed by matching every coefficient to full floating-point precision, just with extra holdout/simulator/elasticity tabs layered on top). Neither is real respondent data; both are explicitly template/demo material per the file's own README. Useful as a methodology reference for whoever runs the real survey, not usable as a stand-in.
- A clarification was drafted for `per_year_remaining_lease` specifically: the recommender currently has no priced lease-preference term at all (lease is a hard `min_lease_yrs` floor only — see `recommender_v2.py` lines 104–107). If their conjoint tests lease as discrete levels (like the demo's 50/70/85/95-year bands), a single averaged $/year rate is what's needed, not the raw per-level breakdown.

### ✅ Delivered (22 Oct) — `HDB_Conjoint_Results_noEA_200_with_holdout_simulator_elasticity (2).xlsx`

The real file landed in `Project/Conjoint/`. **200 respondents, but mixed: 36 real + 164 synthetic** (per the companion design file's own filename) — a genuine advance on the all-synthetic demo, not yet a fully-real survey. MNL with part-worths, McFadden pseudo R²=0.301, holdout hit rate 38% (chance=33%). Four segments: Retirees (n=26), Upgraders with cash (n=56), Young DINKs (n=48), Young family with primary school kids (n=70).

Parsed into `data/preferences.json` (exact schema above) and `data/conjoint_wtp.json` (full aggregate + per-segment breakdown, for the report). `per_km_closer_to_mrt` and `per_year_remaining_lease` are an OLS fit of the file's 4 bucketed distance/lease levels — the conjoint tests discrete levels, not a continuous slope, so this is a summary of a (slightly non-monotonic, noisy) step relationship, documented as such in the json's own `_source` field.

Ran through `preference_overrides_from_file()` unchanged — no code change needed, as designed:
- **mrt multiplier: 3.14×** market (household $102,333/km vs. market $32,564/km) — not wired into any default; the live web app already lets the household set its own MRT weight directly, so this would double-apply. Recorded as a substantiation point instead (see `OPTIMISER_METHODOLOGY_REPORT.md` §28): the one archetype with a clean, *statistically solid* segment match (Young DINKs, all 3 distance levels significant) implies **7.62×**, well above this project's own hand-picked 1.5× for "Young couple, transit-reliant" — if anything, the hand-picked value is conservative. The other 3 archetypes' matching segments are too noisy (n=26-70, mostly non-significant point estimates) to responsibly override a deliberately-chosen value.
- **`w_school_sgd`: not overridden.** The live default already prices the school goal from the hedonic's own ~3%-of-price market rate, which scales with price — a flat $69,000 conjoint figure would be a downgrade for cheap/expensive profiles alike. Kept as a reported comparison only (conjoint aggregate $69,000; Family-segment-specific, both levels significant, $201,000 — both land close to the hedonic market rate at this pipeline's ref price, a reassuring stated-vs-revealed cross-check).
- **`storey_step_sgd`: adopted as the new module default ($41,500/band, up from the $15,000 placeholder)** — no existing market-based fallback existed for this one, so real data replaces a guess outright. `recommender_v2.py`'s `DEFAULT_STOREY_STEP_SGD` now reads this live from `preferences.json`.
- **`per_amenity_count`: left alone.** This conjoint doesn't test a walkable-essentials attribute at all; `w_essential_sgd` keeps its $8,000 placeholder rather than being overwritten by an unrelated number.
- **`per_year_remaining_lease` ($5,070/year): still not wired into the objective** — lease remains a hard floor only, exactly as flagged above. Now surfaces live in `/api/meta`'s `market_rate_lease_per_year` (was a hardcoded `3000`) so the GP tab's default at least reflects the real figure.

**Re-verified:** full `rebuild_v2.py` run (storey default change only touches the objective, not profile-building) — extended backtest (11 cutoffs × 4 archetypes) moved **97.7% → 98.2%** reliability (CIs overlap, [94.9%, 99.4%] vs. [94.3%, 99.1%] — not significant), `matched_sale_seen` 81.7% → 78.0%. Canonical live example (budget $600k, 60yr lease, MRT 0.4km, school required, k=5) dropped from $44,380 → $20,534 net objective, decomposed cleanly: $44,380 → $27,786 from the pricing refresh alone (below, item 1 — real prices tightened budget feasibility, 103→94 candidates), → $20,534 from the storey recalibration alone (candidates unchanged; several of this household's picks sit outside its Mid-storey target, and the real cost of that mismatch is higher than the old $15,000 placeholder assumed).

**Status: 🟡 landed, partially wired — no longer the blocking gap**, though still worth tracking: (a) the file is 82% synthetic by respondent count, so treat segment-specific numbers (n=26-70) with real caution; (b) `per_amenity_count` and a priced lease term remain genuinely untested/unmodelled; (c) a fully-real re-run of this survey, if the team does one, should simply overwrite `preferences.json` and re-run — no code changes needed, same as this pass.

---

## 4. What I owe the team

| File | Owner | Status |
|---|---|---|
| `outputs/shortlist.csv` | Optimisation (me) | ✅ **Published 18 Oct.** `build_shortlist.py` runs the production recommender (`solve()`, default weighted-sum 0-1 IP, live pricing/availability/forecast) for the project's own 4 named household archetypes (`backtest_v2.EXTENDED_ARCHETYPES` — young couple, family needing a school, budget-first, retiree) and writes `household_id, rank, profile_id, town, flat_type, storey_band, mrt_band, price_today, expected_wait_months, surplus, net_objective_value` for all 20 picks. **Note:** still running on stub `preferences.json` — re-run `python build_shortlist.py` once the Preference Lead's real file lands, since the picks themselves will change. |

---

## 5. Summary — action items by owner

| Owner | Ask | Deadline status | Blocking? |
|---|---|---|---|
| **Preference Lead** | `preferences.json`, schema above | ✅ **Delivered 22 Oct** (real conjoint, 36 real + 164 synthetic respondents) — see §3 above for what got wired in and what's still a placeholder | No longer — `storey_step_sgd` and the lease rate now run on real data; `w_essential_sgd` and the mrt multiplier default still don't (see §3) |
| **Forecasting Lead** | `price_paths.csv` for 2/3/5-ROOM + EXECUTIVE | no committed date | 🟡 Partial — ~80% of profiles have no real forecast |
| **Pricing & Availability Lead** | Nothing new — optional block-level prices if they're willing | — | No — already delivered, I just need to re-pull `main` |
| **Me (Optimisation)** | ✅ Done 18 Oct: re-wired adapter to `outputs/optimisation/*.csv` (96.2% → 99.7% coverage); confirmed Monte Carlo/chance-constraint don't violate Forecasting's "no joint sampling" caveat; published `outputs/shortlist.csv` (20 picks, 4 archetypes) | done | — |

## 6. Three self-identified follow-ups — all closed (18 Oct, see OPTIMISER_METHODOLOGY_REPORT.md §13-14)

| # | Item | Resolution |
|---|---|---|
| 1 | `price_today_se` definition mismatch | Audited every consumer (`recommender_v2.py`, `recommender.py`, `shrink_k`) — the column is read but **never used in any live computation**; the "uncertainty band" it was meant for is actually implemented via `price_low`/`price_high` → `growth_factor_upper` instead. No live bug; correct new definition (`price × 0.052`, hold-out log-RMSE) now recorded in `INTERFACE_SPEC.md`. |
| 2 | Data-layout portability | Inventoried every file this pipeline reads outside its own `data/` folder, verified byte/row/feature-count against the shared repo's equivalents. **21 files bridgeable** (9 common downloads under different names + 12 of this pipeline's own earlier `daniel_add` contributions, already on `main`) → `sync_shared_repo_raw_data.py` + `DATA_LAYOUT.md`, tested against both the real shared-repo checkout (0 copies needed, all verified identical) and a simulated empty project directory (all 21 copied correctly). **2 correctly rejected** as genuinely different datasets, **1 true gap** recorded (rental data, nowhere in the shared repo). |
| 3 | Hedonic re-fit against the real price basis | A literal transaction-level re-fit isn't possible without the Pricing Lead's block-level predictions (not available). Built a profile-level log-log recalibration instead (`hedonic_value.py::fit_price_calibration()`/`apply_price_calibration()`, R²=0.934 on the 706-profile overlap), with a 3-sigma clip on the result after discovering a handful of thin-sample profiles would otherwise produce 60-100%+ spurious "bargain" signals. `shrunk_value_gap` is no longer forced to $0 for real-priced profiles. **Re-verified against the full walk-forward backtest: 96.6% [93.1%, 98.3%] reliability, identical to before** — this code path only runs when `live=True`, never during a backtest. ✅ Done. |

## 7. Three more follow-ups, requested after the above (18 Oct, see OPTIMISER_METHODOLOGY_REPORT.md §15)

| # | Item | Resolution |
|---|---|---|
| 4 | MRT spatial bias in `predict_value()` itself (not just the exported WTP rate) | `hedonic_value.FORMULA` switched from `C(town)` to `C(subzone)` (167 subzones with HDB stock, via a new `block_accessibility.py::assign_subzone()` geopandas point-in-polygon join, 100% block coverage). **Adjusted R² 0.9372 → 0.9545; implied MRT-halving effect 5.28% → 4.55%** — a genuine, substantial improvement, honestly reported as *partial*: still above the Pricing Lead's ~3% causal benchmark, since subzone FE is a coarser proxy than their spatial-error/DiD methods. `MRT_SPATIAL_CORRECTION` (still applied to the exported WTP rate only) recalibrated to `3.0/4.55≈0.659`. Full `rebuild_v2.py` run + re-verified: backtest reliability **96.5% [93.0%, 98.3%]**, statistically identical to 96.6% [93.1%, 98.3%] before. Calibration (#3 above) re-fit too, R² improved 0.934→0.942. ✅ Done. |
| 5 | Polyclinic data source (8-site COVID-vaccination subset vs. the Pricing Lead's real 27-polyclinic list) | Checked first: `dist_polyclinic_km` feeds no WTP coefficient, no `essentials_score` term, and no web app field today, so this was zero-decision-logic-risk, not something needing a backtest gate. Geocoded the Pricing Lead's real `polyclinics.csv` via OneMap's public search endpoint (`geocode_polyclinics.py`) — **27/27 resolved**. Wired into `block_accessibility.py` in place of the vaccination-site file. Block-level `dist_polyclinic_km` mean fell 3.11km → 1.14km (more points = closer nearest one, as expected). ✅ Done — recommend wiring this attribute into a real goal/WTP term as a separate future item, now that the source is correct. |

**Downstream note**: both fixes landed in the same `rebuild_v2.py` run as the already-reinstated bargain signal (#3), so this report's own "Live Recommender Output" and "Weighted-Sum vs. Preemptive" worked examples moved again — tracked in full in the Word report v2 (§13–§15) and `OPTIMISER_METHODOLOGY_REPORT.md` §15, not silently overwritten.

## 8. Lease-band dimension added — full scope (18 Oct, see OPTIMISER_METHODOLOGY_REPORT.md §16)

| Item | Resolution |
|---|---|
| Lease-band dimension (previously only a hard `min_lease_yrs` floor, never a profile axis) | `profile_id` grew from 4-part to 5-part (`TOWN::FLATTYPE::LeaseBand::StoreyBand::MRTBand`), using the Pricing Lead's own `<60`/`60-79`/`80+` bands exactly — an identity mapping, never crosswalked. Profile count **708 → 1,184**. `profile_crosswalk.py` now preserves lease band instead of discarding it; `pricing_availability_adapter.py`'s crosswalk-based functions are the primary path again (the 17 Oct native pass-through's 4-part file can't match a 5-part ID any more) — coverage 99.7% → 94.5% (1,119/1,184), a real trade-off (thinner cells, real lease splits) reported honestly, not hidden. Calibration fit improved: R² 0.942 → 0.960. **Re-verified against the full extended backtest: reliability 96.5% → 99.4% [96.9%, 99.9%]** — a genuine improvement, alongside an honest cost (`matched_sale_seen` fell to 81.4%). Grepped every hardcoded profile_id string-split in the codebase and fixed two real breakages (`backtest_v2.py`, 3 spots; `technique_comparison.py`, 2 spots) that would otherwise have crashed or silently mis-joined. Webapp backend + frontend updated to return/display `lease_band`. ✅ Done. |

**What this changes for other leads**: nothing required of them — this is purely an internal profile-granularity change on my own side, using their already-published lease bands. `outputs/shortlist.csv` and the Word/slide-deck live examples have moved again as a result (same pattern as #4/#5 above), tracked in full rather than silently overwritten.

## 9. Pricing & Availability Lead added lease band to their native export (22 Oct, see OPTIMISER_METHODOLOGY_REPORT.md §27)

| Item | Resolution |
|---|---|
| `main` commit `35ab9bb` (22 Oct): their `outputs/optimisation/{pricing_today,availability}.csv` now carry a 5-part, lease-band-aware `profile_id` (`TOWN::FLATTYPE::LeaseBand::StoreyBand::MRTBand`), matching this pipeline's own scheme since item #8 above. This is exactly what un-sticks the native pass-through path (`pricing_availability_adapter.py::build_from_native()`), unusable since 17 Oct because of the 4-part/5-part mismatch that same day — not a bug to fix, a scheme mismatch that resolved itself once they caught up. | Re-pulled their native files (1,829 rows, matching their own commit message) into `data/external_handovers/{pricing_today,availability}_main_native.csv`, re-ran `build_from_native()`. **Coverage: 958/1,013 (94.6%, crosswalk) → 1,006/1,013 (99.3%, native pass-through)** — exactly their claimed 1,006/1,013. Re-ran `build_price_calibration.py` and the R² bootstrap against the refreshed `pricing_today.csv`: R² 0.9601→0.9591 (n 1,119→1,006), 95% CI [0.9416, 0.9696] — still stable, no change to that substantiation test's conclusion. The canonical live example (§25) and extended-backtest reliability moved as a result; see §3 above and OPTIMISER_METHODOLOGY_REPORT.md §27 for the full before/after decomposition (this item isolated from the same-day Preference Lead integration). `build_pricing_today()`/`build_availability()` (the crosswalk path) are kept in the file for historical/backtest reproduction only — the backtest itself never reads live pricing regardless (`live=False` always), so this change affects only the live recommender and the calibration fit, not backtest reliability directly. ✅ Done. |

## 10. Self-initiated: independent 99.co listing-turnover cross-check (22 Oct, see OPTIMISER_METHODOLOGY_REPORT.md §29)

| Item | Resolution |
|---|---|
| scrape_99co.py (`Project/notebooks/`, running since 5 Oct, 6 runs / 3,336 HDB 3-4-5-room sale listings by 17 Oct) was built before the real availability model landed, specifically as an independent check on it once it did. Not previously analysed against the real model. | Built `cross_validate_99co_listings.py`: matched scraped listings to town (62.9%, substring match on address), flat_type (direct from sub_category) and lease_band (99.9%, derived from "Built: YYYY"), restricted to listings with >=5 days of comparable follow-up (78.0%), aggregated to flat_type x lease_band (9 cells, n>=15 each). Correlated each cell's empirical "delisted share" (a 12-day turnover-speed proxy, not a survival estimate -- the scrape hasn't run long enough to observe a 6-/12-month outcome directly) against the real model's own `expected_wait_months`. **Spearman rho=-0.350, p=0.356 (n=9)** -- the expected sign (faster live turnover <-> shorter modelled wait), not statistically significant at this cell count. Directionally consistent, not an independent confirmation of the model's long-horizon calibration; reported as exactly that, no more. ✅ Done -- recommend re-running after a longer accumulation period (the scrape is still running) for a proper Kaplan-Meier-based comparison instead of a single turnover share. |

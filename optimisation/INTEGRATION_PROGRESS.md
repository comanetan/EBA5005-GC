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
2. ⚠️ Still open: `price_today_se` in their new file is documented as `price × 0.052` (hold-out log-RMSE on unseen blocks) — a different definition from my old adapter's percentile-based approximation. Need to re-check `shrink_k` / anywhere I treat `price_today_se` as a profile-mean SE against this new definition.

**One optional ask, not blocking:** their hedonic is fit against a different price basis than mine, which is why I currently suppress my own "bargain" signal (`shrunk_value_gap`) to $0 for every real-priced profile (see Finding 2 in `OPTIMISER_METHODOLOGY_REPORT.md`). If they're willing to share **block-level predicted price** (not just the profile aggregate), I could re-fit my own hedonic against their target and re-enable that signal instead of suppressing it. Not urgent — flagging for later.

---

## 2. Forecasting Lead — 🟡 delivered, narrower than I need

**What exists** (`forecasting` branch, last updated **12 Oct** — no newer commits, so my snapshot is current):

| File | Columns | Coverage |
|---|---|---|
| `outputs/price_paths.csv` | `profile_id, month, p10, p50, p90` (SGD) | **4-ROOM only**, regions North / North-East / East / West / Central |
| `outputs/price_paths_metadata.json` | base month, model version, source hash, coverage/exclusions | — |

I already wrote `forecasting_adapter.py` against this and it's live: it replaces the 4-ROOM rows of `price_forecast.csv` and leaves every other flat type on the flat 1.00 stub.

**What I still need from them:**
1. 🔴 **The same `price_paths.csv` for 2-ROOM, 3-ROOM, 5-ROOM, and EXECUTIVE.** Right now ~80% of my 708 profiles (everything that isn't 4-ROOM) still forecast zero growth. If full coverage isn't realistic by their deadline, even a single blended "all other flat types" series would beat the flat stub.
2. ✅ **Checked (18 Oct):** their `REGIONAL_HANDOVER.md` warns **"do not independently sample these rows for Monte Carlo… joint simulation remains unimplemented."** Verified `monte_carlo.py`/`chance_constraint.py` don't do this — both only ever use the summary `growth_factor`/`growth_factor_lower`/`growth_factor_upper` columns to parameterise their own per-profile normal approximation (`simulate_price()`); neither loads or draws from their row-level `price_paths.csv` quantile table at all. Clean — no fix needed.
3. ⚪ Low priority, from their `NEXT_STAGE.md`: MAS SORA rate series and cooling-measure dates are still "to collect" on their side. Doesn't block me today — their current ARIMA(0,1,1)-on-location-index model doesn't need them — but if they add an interest-rate regressor later, my `growth_factor` columns will change meaning and I'll need to re-validate the backtest.

---

## 3. Preference Lead — 🔴 not started, blocking

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

---

## 4. What I owe the team

| File | Owner | Status |
|---|---|---|
| `outputs/shortlist.csv` | Optimisation (me) | ✅ **Published 18 Oct.** `build_shortlist.py` runs the production recommender (`solve()`, default weighted-sum 0-1 IP, live pricing/availability/forecast) for the project's own 4 named household archetypes (`backtest_v2.EXTENDED_ARCHETYPES` — young couple, family needing a school, budget-first, retiree) and writes `household_id, rank, profile_id, town, flat_type, storey_band, mrt_band, price_today, expected_wait_months, surplus, net_objective_value` for all 20 picks. **Note:** still running on stub `preferences.json` — re-run `python build_shortlist.py` once the Preference Lead's real file lands, since the picks themselves will change. |

---

## 5. Summary — action items by owner

| Owner | Ask | Deadline status | Blocking? |
|---|---|---|---|
| **Preference Lead** | `preferences.json`, schema above | 2 days overdue (was 16 Oct) | 🔴 Yes — every recommendation today runs on stub weights |
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

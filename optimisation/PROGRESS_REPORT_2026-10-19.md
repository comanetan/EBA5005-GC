# SG HomeFit — Optimisation Workstream: Progress Report

**Period:** Monday 13 October 2026 → Monday 19 October 2026
**Author:** Daniel Loh Guo Juin (A0149952R), Optimisation Lead
**Branch:** `optimisation` — 13 commits this period, up to date with `origin/optimisation`
**Compiled from:** `git log` on `optimisation`/`main`/`forecasting`, `INTEGRATION_PROGRESS.md`, `OTHER_TESTS_LOG.md`, `OPTIMISER_METHODOLOGY_REPORT.md`

---

## 1. Executive summary

As of last Monday, the optimisation branch had a working pipeline, recommender, backtest and web app, with real Pricing/Availability and Forecasting data already wired in via adapters. This week's work fell into three threads:

1. **A UI overhaul** (17 Oct) — replaced dense inline explanations with contextual pop-ups, fixed layout/icon issues, renamed "Deviation" to "Shortfall" per earlier feedback.
2. **Three real bugs found and fixed by reviewing teammates' branches**, not assumed safe: an MRT-premium spatial bias (~2× overstated), a native-schema update from the Pricing Lead that needed re-wiring, and a profile-granularity gap (no lease-band dimension) — each investigated, fixed, and **re-verified against the full walk-forward backtest** rather than taken on faith.
3. **A methodology rigor pass** — the three core optimisation techniques (LP, GP, 0-1 IP) documented down to decision variables and constraints with their full trial-and-error history, then **three further substantiation tests** run against specific claims (does a finding generalise across households, is a reported R² fragile, does a design choice actually matter) — all now in the Word report, a 19-slide deck, and a tracked log.

**Headline numbers, then vs. now:**

| Metric | 13 Oct | 19 Oct |
|---|---|---|
| Profiles | 708 (4-part: town × flat type × storey × MRT) | **1,184** (5-part, +lease band) |
| Pricing/availability coverage | 96.2% (crosswalked) | **94.5%** (1,119/1,184, lease-preserving crosswalk — see §3 below for why this isn't a regression) |
| Backtest reliability (extended 11×4) | 97.6% [94.5%, 99.0%] | **99.4% [96.9%, 99.9%]** |
| Hedonic adjusted R² | 0.937 (town FE) | **0.9545** (subzone FE) |
| Hedonic-to-real-price calibration R² | n/a (bargain signal suppressed to $0) | **0.960** [bootstrap 95% CI 0.9457–0.9694] |

---

## 2. Where the Optimisation workstream is at, in detail

### 2a. Real-data integration fixes (17–18 Oct)

- **MRT spatial bias, found and partially fixed.** Reading the Pricing Lead's own spatial-econometrics notebook (routine branch review, not requested) showed a town-fixed-effects hedonic — this pipeline's own specification — overstates the MRT premium by roughly 2× (5.28% vs. their causally-identified ~3%). Fixed in two layers: the *exported* WTP rate used for preference-tilt/goal-penalty got a corrected multiplier ($58,500/km → $33,200/km), and the hedonic model's own price predictions switched from town to **subzone** fixed effects (a new geopandas point-in-polygon join, 167 subzones, 100% block coverage) — closing a third of the gap directly in the model (adj. R² 0.937→0.9545, bias 5.28%→4.55%), honestly reported as *partial*, not fully solved.
- **Pricing & Availability Lead's 17 Oct update, re-wired.** They started writing pricing/availability directly on our profile scheme — adapter updated, coverage rose 96.2%→99.7% at the time.
- **Lease-band dimension added** (their data showed lease was a real price driver we weren't modelling). Profile scheme grew from 4-part to 5-part; this *reduced* raw coverage to 94.5% because their native (lease-collapsed) file can no longer match a 5-part ID — so the adapter went back to crosswalking their original lease-split export, which is thinner per cell but real. Net effect: backtest reliability rose 96.5%→**99.4%**, honestly reported alongside the real cost (the share of picks with a matching realised sale fell to 81.4%).
- **Polyclinic attribute corrected** (8-site COVID-vaccination subset → the Pricing Lead's real 27-polyclinic list, geocoded via OneMap, 27/27 resolved). Checked first that this attribute drives no live decision today, so no backtest re-verification was needed.
- Every fix above was followed by a **full `rebuild_v2.py` run and a fresh walk-forward backtest**, not assumed safe — numbers in the table above are measured, not projected.

### 2b. Reporting and presentation (18–19 Oct)

- **`OPTIMISER_METHODOLOGY_REPORT.md`** grew to §19 — every fix above has its own dated section with before/after numbers.
- **Word report v2** (`SG_HomeFit_Project_Implementation_Report_v2.docx`) now documents all three core optimisation techniques to the level of actual decision variables, objective functions and constraints, their full trial-and-error history, and the three substantiation tests below.
- **Slide deck** expanded from 8 to **19 slides** (both the web-based deck and a native PowerPoint export, `SG_HomeFit_Optimisation_Pipeline_v2.pptx`) — added a cover, agenda, and an 11-slide methodology deep dive mirroring the report.
- **End-to-end validation**: ran the full pipeline from raw data forward, confirmed byte-identical reproducibility, smoke-tested every solver code path, and started the local web app — all 6 API endpoints confirmed working live.

### 2c. Substantiating the findings, not just reporting them (18–19 Oct)

Six further tests were identified to strengthen specific claims; **three are done**, tracked in `OTHER_TESTS_LOG.md`:

1. **Does the GP weighted-sum-vs-preemptive divergence generalise, or was it one cherry-picked household?** Tested across all 4 backtest archetypes: 3/4 show a real gap ($23K–$125K); the household used throughout the report is structurally closest to the one with the *largest* gap, not a small one. The one $0-gap case is itself confirming evidence (every goal simultaneously satisfiable there). Bonus finding: a second divergence mechanism where preemptive gets forced into a negative-surplus "clean" shortlist, rejecting a cheap, profitable shortfall weighted-sum would take.
2. **Is the calibration's R²=0.960 a fragile point estimate?** Bootstrapped (2,000 resamples): 95% CI [0.9457, 0.9694], point estimate sits almost exactly on the bootstrap mean. Stable, not lucky.
3. **Does the preemptive priority order itself matter?** Tested all 120 permutations of the 5-goal order, again across all 4 archetypes. 3/5 households are completely order-invariant; the other 2 swing by **$82K–$88K** purely by priority order — bigger than the GP-mode gap itself. Mechanistically explained: prioritising MRT first (the shipped default) gives the best outcome in both order-sensitive cases, because MRT carries the largest fitted dollar rate.

---

## 3. What's left (on my own side)

| Item | Status |
|---|---|
| IP scaling/stress test at 1,000+ candidates | Not started |
| Residual diagnostics (incl. Moran's I) on the subzone-FE hedonic specifically | Not started |
| Out-of-time holdout beyond the current latest cutoff (2025-07) | Not started |
| `price_today_se`'s definition mismatch, data-layout portability, hedonic basis mismatch | ✅ Closed — see `INTEGRATION_PROGRESS.md` §6 |
| Re-run `build_shortlist.py` once Preference Lead's real file lands | Blocked on them (see §4) |
| Wire the (now-correct) polyclinic attribute into an actual goal/WTP term | Not started, low priority |

---

## 4. What's needed from the rest of the team

| Owner | Ask | Status as of today | Blocking? |
|---|---|---|---|
| **Preference Lead** | `preferences.json` — exact schema already documented in `INTEGRATION_PROGRESS.md` §3, and already wired into `recommender_v2.py` so dropping in the real file needs **no code change** on my end | **No branch exists yet. 3 days past the stub's own 16 Oct target date.** Checked again this morning — still nothing on `main`/`forecasting`/any branch. | 🔴 Yes — every live recommendation today runs on stub conjoint weights |
| **Forecasting Lead** | Real `price_paths.csv` coverage for 2/3/5-ROOM + EXECUTIVE (currently 4-ROOM only, ~80% of profiles still on the flat stub) | No committed date; checked this morning, no new commits since 12 Oct | 🟡 Partial |
| **Pricing & Availability Lead** | Nothing blocking. Optional: block-level (not just profile-level) real price predictions, which would let the hedonic-to-real-price calibration (§2c, item 2) become a literal re-fit instead of a calibration | Checked this morning, no new commits since 17 Oct | No |

No change in asks since the last integration check — confirmed by re-checking `main` and `forecasting` this morning before writing this report, not assumed stale.

---

*Full technical detail behind every claim above: `OPTIMISER_METHODOLOGY_REPORT.md`, `INTEGRATION_PROGRESS.md`, `OTHER_TESTS_LOG.md`, `DATA_LAYOUT.md` (all in this folder).*

# Other tests / EDA for better substantiation — tracking log

**Purpose:** on 2026-10-18, after documenting the three core optimisation techniques in
depth (`OPTIMISER_METHODOLOGY_REPORT.md` §13–§16), six further tests/EDA ideas were
proposed to strengthen the evidence behind specific claims. This file tracks each one —
done or not — with its result, so none gets lost across the conversation. Full write-ups
live in `OPTIMISER_METHODOLOGY_REPORT.md`; this file is the short, standalone index.

| # | Item | Status |
|---|---|---|
| 1 | Statistical significance test on the GP trial-and-error table — does the preemptive-vs-weighted-sum divergence generalise across households, or is it one cherry-picked example? | ✅ **Done, 2026-10-18** — see below |
| 2 | Bootstrap CI on the 0.960 hedonic-to-real-price calibration R² | ✅ **Done, 2026-10-18** — see below |
| 3 | Scaling/stress test on the 0-1 IP at a much larger candidate pool (1,000s, not 10s–100s) | ✅ **Done, 2026-10-19** — see below |
| 4 | Residual diagnostics (incl. Moran's I) on the subzone-FE hedonic specifically | ✅ **Done, 2026-10-19** — see below |
| 5 | Sensitivity of the preemptive priority *order* itself (not just which household) | ✅ **Done, 2026-10-19** — see below |
| 6 | Out-of-time holdout beyond the current latest cutoff (2025-07) | ✅ **Done, 2026-10-19** — see below |

---

## 1. Does the GP divergence generalise, or is it one cherry-picked household? ✅

**Done 2026-10-18.** Full write-up: `OPTIMISER_METHODOLOGY_REPORT.md` §17. Also added to
the Word report v2 (`make_report_part6.js`, new subsection under Goal Programming's
Trial & Error). Script: `test_gp_gap_across_archetypes.py` → `data/gp_gap_across_archetypes.json`.

**Scope note:** the ideal test (re-run the full 5-stage historical correction sequence
across all 4 archetypes, 20 combinations) isn't feasible — the 5 historical data states
were never independently git-tagged as runnable snapshots. What was run instead: today's
final, fully-corrected pipeline, across all 4 backtest archetypes (`backtest_v2.EXTENDED_ARCHETYPES`),
at k=5, default priority order (MRT ≫ School ≫ Storey ≫ Wait ≫ Essentials).

**Result:**

| Archetype | Weighted-sum | Preemptive | Gap | Shared picks |
|---|---|---|---|---|
| Young couple, transit-reliant | −$13,286.90 | −$36,366.10 | $23,079.20 | 3/5 |
| Family, needs primary school | $115,270.25 | −$10,212.79 | **$125,483.04** | 1/5 |
| Budget-first, car owner | $27,069.65 | −$745.64 | $27,815.29 | 1/5 |
| Retiree, downsizing, low storey | $151,468.19 | $151,468.19 | **$0.00** | 5/5 |

**Conclusion:** generalises — 3/4 archetypes show a real, substantial gap ($23K–$125K),
not an artefact of the one household used throughout the report (which is structurally
closest to "Family, needs primary school," the archetype with the *largest* gap of the
four). The one $0-gap case is itself confirming evidence: that household's constraints are
loose enough that every goal is simultaneously satisfiable, consistent with every other
finding in this project that the gap only exists when a real trade-off exists.

**Bonus finding, not originally asked for:** checking *why* "Budget-first, car owner"
diverges revealed a second mechanism distinct from "preemptive sacrifices surplus to fix a
shortfall." Weighted-sum's own picks carry small, deliberate deviations ($480/$1,072/$630
`dev_mrt`, $2,909 `dev_essentials`) because the extra surplus is worth more than the cost —
net $27,069.65. Preemptive picks a completely different, zero-deviation-everywhere set
whose own surplus is *lower* — net −$745.64. Preemptive isn't trading surplus for a fix; it
is structurally forbidden from ever accepting a cheap, profitable shortfall at all, even on
the lowest-priority goal.

---

## 2. Is the calibration's R²=0.960 a fragile point estimate? ✅

**Done 2026-10-18.** Full write-up: `OPTIMISER_METHODOLOGY_REPORT.md` §18. Also added to
the Word report v2 (`make_report_part6.js`, new subsection under the IP section's Trial &
Error table). Script: `bootstrap_calibration_r2.py` → `data/calibration_r2_bootstrap.json`.

**What was run:** resampled the 1,119-profile overlap with replacement (same n each time),
refit the identical log-log OLS `hedonic_value.py::fit_price_calibration()` uses, 2,000
times, and looked at the empirical spread instead of trusting the one sample already cited
throughout the report.

| Quantity | Point estimate | Bootstrap (2,000 resamples) |
|---|---|---|
| R² | 0.9601 | mean 0.9604, std 0.0063, 95% CI **[0.9457, 0.9694]** |
| β (slope) | 1.0238 | mean 1.0237, std 0.0064 |
| Full min/max across all 2,000 resamples | — | [0.9345, 0.9730] |

**Conclusion:** stable, not fragile. The point estimate sits almost exactly on the
bootstrap mean, the 95% CI is under 2.4 percentage points wide, and even the most extreme
of 2,000 resamples never dropped below 0.9345. The 0.960 figure cited throughout this
report would survive drawing a different sample of profiles from the same population.

---

## 5. Does the preemptive priority order itself actually matter? ✅

**Done 2026-10-19.** Full write-up: `OPTIMISER_METHODOLOGY_REPORT.md` §19. Also added to
the Word report v2 (`make_report_part6.js`, new subsection right after item 1's
generalisation test, under Goal Programming's Trial & Error). Script:
`test_preemptive_priority_sensitivity.py` → `data/preemptive_priority_sensitivity.json`.

**What was run:** all 5! = 120 permutations of the 5-goal priority order, on the report's
own test household **and** all 4 backtest archetypes (not just one household — same
cherry-picking concern item 1 was built to rule out).

| Household | Distinct pick-sets (of 120) | Objective spread | Match weighted-sum |
|---|---|---|---|
| Report test household | 1 | $0.00 | 0/120 |
| Young couple, transit-reliant | **11** | **$87,935.10** | 0/120 |
| Family, needs primary school | **19** | **$82,761.57** | 0/120 |
| Budget-first, car owner | 1 | $0.00 | 0/120 |
| Retiree, downsizing, low storey | 1 | $0.00 | 120/120 |

**Conclusion: order matters conditionally, exactly as theory predicts.** 3/5 households are
completely order-invariant — every goal reads $0 simultaneously on one dominant pick-set,
so there's nothing for processing order to arbitrate. The other 2 — the exact households
item 1 already flagged as having a real goal conflict — are genuinely order-sensitive,
with the objective swinging by $87,935 and $82,761 purely by priority order, **larger than
the GP-mode gap itself** for these households. Grouping by which goal is ranked #1 shows
**MRT-first consistently gives the best average outcome in both order-sensitive
households** — mechanistically explained, not just correlated: MRT carries the largest
fitted dollar rate (~$33,200/km), so deprioritising it lets the solver lock in cheaper
goals first and get trapped into an expensive MRT shortfall it can no longer undo. The
shipped default (MRT first) already matches this empirically best choice — originally
picked because the proposal names transit access first, not because of this test; this
test is independent confirmation it's also the economically sound choice.

---

## 3. Does the 0.000% integrality gap survive 1,000s of candidates? ✅

**Done 2026-10-19.** Full write-up: `OPTIMISER_METHODOLOGY_REPORT.md` §20. Script:
`test_ip_scaling.py` → `data/ip_scaling_test.json`.

**What was run:** the real ~1,184-candidate pool, shuffled once then synthetically expanded
(same-town duplicates, ±3% jitter on `net_objective_value`) up to 20,000 rows, solved both
as the real binary IP and its LP relaxation using `_build_ip()` — a faithful copy of
`recommender_v2.py::solve()`'s own PuLP construction (cardinality + ≤1/town) — at
n_candidates ∈ {50, 200, 500, 1,000, 2,000, 5,000, 10,000, 20,000}.

| n_candidates | 50 | 500 | 5,000 | 20,000 |
|---|---|---|---|---|
| IP solve time | 53.6 ms | 81.5 ms | 107.0 ms | 538.8 ms |
| Integrality gap | 0.000% | 0.000% | 0.000% | 0.000% |

**Conclusion:** both headline findings survive a 400× scale-up cleanly. The integrality gap
stays exactly 0.000% at every scale — confirming §7.1's explanation (a totally-unimodular
partition-matroid structure) is structural, not a small-instance coincidence. CBC's solve
time stays trivial (sub-second even at 20,000 candidates) and grows far sub-linearly,
consistent with the real combinatorial driver being the fixed number of towns (26), not
the candidate count. A future block-level recommender needs no different solver or
formulation.

---

## 4. Did subzone FE actually fix the hedonic's spatial autocorrelation, or just reduce it? ✅

**Done 2026-10-19.** Full write-up: `OPTIMISER_METHODOLOGY_REPORT.md` §21. Script:
`test_hedonic_residual_diagnostics.py` → `data/hedonic_residual_diagnostics.json`.

**What was run:** refit both the production `C(subzone)` formula and the pre-§15
`C(town)` formula it replaced on the identical 76,852-row sample, aggregated residuals to
block level (mean residual per block, ≥10 sales, 2,667 blocks), tested with the Pricing
Lead's own published method — KNN k=8 row-standardised weights, SG-centred equirectangular
projection, Moran's I (999 permutations).

| Model | Adj. R² | Moran's I | p |
|---|---|---|---|
| Town-FE (pre-§15) | 0.9369 | **+0.5918** | 0.001 |
| Subzone-FE (production) | 0.9545 | **+0.3590** | 0.001 |
| *Pricing Lead benchmark: OLS + town dummies* | — | *+0.60* | — |
| *Pricing Lead benchmark: spatial-error (filtered)* | — | *−0.03* | — |

**Conclusion: a real but partial fix**, same honesty pattern already applied to the MRT
coefficient in §15. Moran's I fell ~39% (0.59→0.36) switching town→subzone FE — and this
pipeline's own town-FE number lands almost exactly on the Pricing Lead's independently
measured "OLS + town dummies" benchmark (0.60), reassuring cross-pipeline consistency. But
0.36 is still hugely significant (z=+38.81, p=0.001) and far from the spatial-error
model's fully-filtered −0.03. Subzone FE is a genuine improvement, not a solved problem —
exactly what §15 already said about the MRT coefficient, now confirmed for the residuals
directly instead of inferred from one number.

**Refreshed 2026-10-20** after the flat-type scope alignment (§23): re-run on the
2-ROOM/EXECUTIVE-free transaction set (69,712 rows, 2,478 scored blocks). Subzone-FE adj.
R² 0.9481, Moran's I +0.3512; town-FE adj. R² 0.9270, Moran's I +0.5918 (unchanged). Same
~40.6% reduction, same conclusion — numbers moved slightly with the smaller sample, the
finding didn't.

---

## 6. Does 99.4% reliability hold on a cutoff never used in this project's own iteration history? ✅

**Done 2026-10-19.** Full write-up: `OPTIMISER_METHODOLOGY_REPORT.md` §22. Script:
`test_out_of_time_holdout.py` → `data/out_of_time_holdout_test.json`.

**Data-availability check:** transactions run 2017-01→2026-10, but 2026-10 is a *partial*
month (212 sales vs. 2,000+ for every complete month either side — "today" is 2026-10-19).
`realised()`'s 3-month scoring window must sit entirely inside complete months to be
unbiased, so **2025-08-01** is the newest cutoff with a fully-clean window — the real
ceiling on how far "out-of-time" this test can honestly go right now. 2025-09-01 was also
run but flagged (its window touches the partial month).

**What was run:** the exact production methodology (`run_v2_variant("v2_block_informed_empirical_band", ...)`,
same 4 archetypes, k=5) — recomputed the 11-cutoff baseline fresh (not copied from the
report) for a true apples-to-apples comparison, then ran the new cutoffs.

| Sample | Picks | Reliability | 95% CI | Matched-sale-seen |
|---|---|---|---|---|
| Baseline (re-verified, 11×4) | 220 | 99.4% | [96.9%, 99.9%] | 81.4% |
| New holdout, 2025-08-01 (safe) | 20 (13 scored) | 92.3% | [66.7%, 98.6%] | 65.0% |
| Combined (12×4) | 240 | 99.0% | [96.3%, 99.7%] | 80.0% |

**Conclusion: a genuinely mixed result, reported as such.** Pooled with history, reliability
barely moves (99.4%→99.0%) — nothing changed on that view. But the single genuinely new
cutoff on its own is weaker and noisier: 92.3% within-budget, matched-sale-seen fell to
65.0% (below the already-flagged 81.4% average), and only 13 of 20 picks had any realised
sale to score against at all. The gap is **not statistically significant** given how wide
the small-sample CI is (the two 95% intervals overlap at [96.9%, 98.6%]) — but it's a real,
visible signal that any one new quarter is thinner and noisier than the pooled headline
number alone would suggest. This is the right way for a holdout test to end: not a clean
pass/fail, but a precise picture of where confidence is earned by volume (the pooled 11+
cutoffs) and where it's still thin (any single new quarter) — a caveat worth carrying into
every future reliability claim rather than treating 99.4% as self-renewing.

**Refreshed 2026-10-20** after the flat-type scope alignment (§23): baseline now 98.3%
[95.2%, 99.4%], 218 picks (consistent with §23's own fresh backtest). New holdout cutoff
(2025-08-01): 92.3% [66.7%, 98.6%], 13 of 18 picks scored, matched-sale-seen 72.2%.
Combined (12×4): 97.9% [94.7%, 99.2%]. Same conclusion — the single new cutoff remains
statistically indistinguishable from the (now-98.3%) baseline.

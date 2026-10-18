# Other tests / EDA for better substantiation — tracking log

**Purpose:** on 2026-10-18, after documenting the three core optimisation techniques in
depth (`OPTIMISER_METHODOLOGY_REPORT.md` §13–§16), six further tests/EDA ideas were
proposed to strengthen the evidence behind specific claims. This file tracks each one —
done or not — with its result, so none gets lost across the conversation. Full write-ups
live in `OPTIMISER_METHODOLOGY_REPORT.md`; this file is the short, standalone index.

| # | Item | Status |
|---|---|---|
| 1 | Statistical significance test on the GP trial-and-error table — does the preemptive-vs-weighted-sum divergence generalise across households, or is it one cherry-picked example? | ✅ **Done, 2026-10-18** — see below |
| 2 | Bootstrap CI on the 0.960 hedonic-to-real-price calibration R² | ⬜ Not started |
| 3 | Scaling/stress test on the 0-1 IP at a much larger candidate pool (1,000s, not 10s–100s) | ⬜ Not started |
| 4 | Residual diagnostics (incl. Moran's I) on the subzone-FE hedonic specifically | ⬜ Not started |
| 5 | Sensitivity of the preemptive priority *order* itself (not just which household) | ⬜ Not started |
| 6 | Out-of-time holdout beyond the current latest cutoff (2025-07) | ⬜ Not started |

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

## 2–6. Not yet started

Kept here verbatim so the next session can pick straight back up without re-deriving scope:

- **2 — Bootstrap CI on calibration R²:** resample the 1,119-profile overlap with
  replacement (~500 iterations), refit `hedonic_value.fit_price_calibration()` each time,
  report the R² distribution — not just the single point estimate of 0.960.
- **3 — IP scaling/stress test:** the LP-relaxation and GA benchmarks (§7.1–7.2) only ever
  ran on realistic household-sized candidate pools (11–52 profiles). Test what happens at
  1,000+ candidates (e.g. simulating block-level rather than profile-level granularity) —
  does the 0.000% integrality gap hold, does CBC's solve time stay trivial.
- **4 — Residual diagnostics on the subzone-FE hedonic:** we have the headline adjusted R²
  (0.9545) but haven't plotted residuals vs. fitted or run Moran's I on the subzone-FE
  model's own residuals, the way the Pricing Lead did for theirs. Would directly test
  whether subzone FE actually fixed the spatial autocorrelation problem or just reduced it.
- **5 — Sensitivity of the preemptive priority order:** we've only ever tested one fixed
  order (MRT ≫ School ≫ Storey ≫ Wait ≫ Essentials). `sensitivity_v2.py` already has the
  grid-sweep machinery; point it at all priority permutations (or a representative sample)
  and measure how much the recommendation changes.
- **6 — Out-of-time holdout beyond 2025-07:** the extended backtest's most recent cutoff is
  2025-07. As more real transaction months accumulate, re-running on a genuinely new,
  never-before-tested cutoff (not just adding more historical cutoffs) is the strongest
  test of whether 99.4% reliability holds up going forward.

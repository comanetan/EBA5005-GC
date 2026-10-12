# SG HomeFit Optimiser — Methodology Report

**Purpose:** trace every technique used in the [SG HomeFit Optimiser](https://claude.ai/artifact/KjCLZbJXDZ7H2StsooGupf) and in the project's production recommender (`recommender_v2.py`) back to its source in the EBA5005 syllabus, and record how each was validated before being shipped. This detail is kept out of the tool's own UI by design — the tool is for using the method, this document is for citing it.

**Sources referenced:**
- `Coursework/Product & Pricing Analytics/Day 2 - Product and Price Optimisation/2.1L DS for PP Opt - Math Programming 2026 S2.pdf` — linear programming, integer programming, LP relaxation, sensitivity analysis (shadow price, reduced cost), corner-point/graphical solution method.
- `Coursework/Analytics for Commercial Excellence/Day 3 - Goal Programming & Queuing Model/Goal Programming/1.1L Salesforce (Goal Programming) 2026 S2.pdf` — goal programming, deviational variables, preemptive priorities, goal vs. economic constraints.

---

## 1. Coverage summary

| Syllabus concept | Lecture source | Where it is used | How |
|---|---|---|---|
| Decision variables | Math Programming, p.7 | Both lectures' definition ("values that can be changed to optimise the objective function") | Every tab |
| Objective function, maximise/minimise | Math Programming, p.6–10 | `recommender_v2.py:238`; Tool Tab 1 & 3 | Direct |
| Economic / resource constraints (≤, ≥, =, linear) | Math Programming, p.9, 11; GP, p.12 | `recommender_v2.py:239–252`; Tool Tab 1 & 2 | Direct |
| 0-1 Integer Programming | Math Programming, p.25 | `recommender_v2.py:236` (`cat="Binary"`) | Direct — this *is* the lecture's "0-1 IP" pattern |
| Corner-point / graphical LP solution | Math Programming, p.22–23 | Tool Tab 1 (`runLP()`) | Enumerates every pairwise constraint-line intersection, keeps the feasible ones, evaluates Z at each — the same method taught for 2 decision variables |
| Shadow price | Math Programming, p.34, 43–46 | Tool Tab 1 | Solved exactly from the 2 constraints binding at the optimum (a 2×2 linear system for the dual variables), not approximated |
| Reduced cost | Math Programming, p.34–41 | Tool Tab 1 | `reduced_cost_j = c_j − Σ(shadow_price_i · a_ij)` over the binding constraints, the standard LP formula |
| LP relaxation (binary → continuous) | Math Programming, p.24–27 | `technique_comparison.experiment_lp_relaxation()` (§7.1) | Empirically measured, not just noted: integrality gap = 0.000% in every instance tested — the recommender's selection constraint is a totally-unimodular partition-matroid structure, so rounding was never needed, which is now a measured fact rather than an assumption |
| Goal Programming — target values, goal constraints | GP, p.11–16 | `recommender_v2.py`'s `dev_mrt`/`dev_school`/`dev_storey`/`dev_wait`/`dev_essentials` terms; Tool Tab 2 | See §2 — reduced form vs. literal form |
| Deviational variables d⁺/d⁻ | GP, p.13, 16 | Tool Tab 2 (`runGP()`), shown explicitly | Direct, literal |
| Preemptive priorities P₁ ≫ P₂ | GP, p.10, 19–21 | Tool Tab 2 (2-variable demo) **and** `recommender_v2.solve_preemptive()` (§7.3 — the full k-of-n selection IP, a real production mode) | Direct, literal — solved sequentially exactly as the lecture's worked example, generalised from 2 variables to a genuine shortlist selection |
| Sensitivity analysis ("tweaking one input, investigating the effect on the model") | Math Programming, p.29–30 | `sensitivity_v2.py` (`sweep()`, `mrt_preference_sweep()`, `price_of_insisting()`) | Direct — this is the lecture's own definition, applied as a grid sweep rather than a one-line Excel Solver report |

---

## 2. One deliberate gap: how `recommender_v2.py` differs from the textbook GP form

The lecture's goal programming (GP, p.13–16) writes every goal as an explicit constraint with its own pair of auxiliary variables:

```
X1 + d1- - d1+ = t1
minimise  P1·d1- + P2·d2-
```

`recommender_v2.py` achieves the same effect — only the "min goal" deviation (d⁻) is ever costly, and at least one of d⁺/d⁻ is always zero — but folds it directly into the objective as a one-sided penalty term instead of adding the auxiliary variables and equality rows:

```python
d["dev_mrt"] = d["price_today"] * beta_mrt * m_mrt * (d["dist_mrt_exit_km_p50"] - query.target_mrt_km).clip(lower=0)
```

This is the **reduced form** of a "≤" goal constraint: since over-achievement (getting *closer* than the target) is free and never penalised, `clip(lower=0)` is mathematically identical to minimising d⁻ while leaving d⁺ unconstrained and costless — exactly the behaviour the lecture specifies for a "min goal" (GP, p.15: *"the less the better: d⁻ desirable"*). The simplification removes 5 extra decision variables and 5 extra constraint rows per profile without changing the optimum.

The project also uses **weighted (Archimedean) goal programming** — every deviation priced in actual dollars and summed into one objective — rather than the lecture's **preemptive (lexicographic) priorities** P₁ ≫ P₂. Both are standard GP variants; the project's choice was made so the whole objective stays dollar-denominated throughout (consistent with the proposal's requirement that the recommender return a dollar-comparable surplus). Tool **Tab 2** demonstrates the literal preemptive form with explicit d⁺/d⁻ variables, since that form doesn't appear anywhere else in the codebase.

**Why this distinction matters for the report:** an examiner comparing `recommender_v2.py` against the GP lecture slide-by-slide would correctly observe that no `d1+`/`d1-` variables exist in the Python source. This section exists so that observation is already answered: the technique is present as a reduced form, by design, not omitted.

---

## 3. Gap that was closed: shadow price / reduced cost

Before this round of work, **no module in the project computed a shadow price or reduced cost** — a sizeable share of the Math Programming lecture (pages 29–47, roughly a quarter of the deck) had no counterpart anywhere in the pipeline. `sensitivity_v2.py` covers the lecture's *other* definition of sensitivity analysis (grid-sweep, p.29–30) but not the Excel-Solver-style dual-value report.

Tool **Tab 1** closes this gap: it is a from-scratch implementation of the corner-point method plus an exact 2×2 dual solve for shadow price and reduced cost, built specifically because nothing else in the project demonstrated it.

---

## 4. Validation

Both calculators' solving logic were checked against the lecture's own worked numeric examples before anything was shipped, by running the exact JavaScript functions under Node.js with the lecture's input values substituted in.

**Goal Programming** (`runGP()`, inputs = GP lecture p.17: a=2, b=3, C=640, t1=200, t2=120, Goal 1 priority):

| | Lecture (p.26–27) | Tool output |
|---|---|---|
| X1 | 200 | 200 |
| X2 | 80 | 80 |
| d1⁻ | 0 | 0 |
| d2⁻ | 40 | 40 |
| Z | 40 | 40 |

**Linear Programming** (`runLP()`, inputs = Math Programming lecture p.16: price 60/50, cost 48/35, demand 100/150, capacity 5/4/1000, component 1 0.4/0.7/130, component 2 0.6/0.3/90):

| | Lecture (p.23) | Tool output |
|---|---|---|
| X1 | 80 | 80 |
| X2 | 140 | 140 |
| Z | $3,060 | $3,060 |
| Shadow price, Component 1 | $18 (p.21/45–46) | $18 |
| Shadow price, Component 2 | $8 (p.21/45–46) | $8 |

Both reproduce the lecture's answers exactly. The HDB-specific defaults shown in the published tool (viewing-time allocation, stretch-budget allocation) run through the identical, now-validated functions — only the input labels and numbers changed, not the solving logic.

**Applied tab**: cross-checked by hand against a known-answer synthetic case (8 profiles, k=3, budget $650,000) — 56 feasible 3-of-8 combinations generated, correct subset selected as optimal, matching a manual check of the top candidates by net objective.

---

## 5. What's novel, beyond the syllabus

`technique_comparison.py` adds two further prescriptive techniques not covered in either lecture:
- An **epsilon-constraint multi-objective solve** (`solve_pareto_point()`), tracing the actual surplus-vs-compromise Pareto frontier instead of the single point the weighted-sum objective returns. This is the standard alternative to weighted-sum scalarisation in multi-objective optimisation, included because it directly answers the proposal's business objective 2 ("quantify what relaxing a requirement would be worth") with a full curve rather than one number. As of §7.5 it is also a live, selectable web app feature, not only a standalone experiment.
- A **genetic algorithm** (`solve_ga()`, §7.2), benchmarked against the exact IP solver on the identical selection problem. Included for breadth/completeness (it is the standard fallback technique when a candidate pool is too large to branch-and-bound exactly) rather than because it appears in this module's own syllabus — the measured result (§7.2) is that it is unnecessary at this problem's current scale, which is itself the useful finding.

---

## 6. Two capabilities that existed but had never been backtested

`recommender_v2.solve()` has supported a **scenario-based chance constraint** (`chance_constraint.py`, `query.alpha`) since early in the project — `P(simulated price <= budget) >= alpha`, evaluated by Monte Carlo rather than the deterministic empirical-band upper bound used by default — but it had never been run through the walk-forward backtest, so its real-world performance was unknown. `backtest_v2.run_v2_chance_variant()` closes that gap (2026-10-08):

| Strategy | Within budget, 12m later | Median pick MRT (km) |
|---|---|---|
| v2, stub ±15% band | 94.2% | 0.578 |
| **v2, scenario chance constraint (α=0.90)** | **95.4%** | **0.569** |
| v2, empirical growth-band (current default) | **98.8%** | 0.587 |

**Reading it.** The chance constraint beats the naive stub (95.4% vs 94.2%) and even picks marginally closer to the household's MRT target than the empirical band — but the simpler empirical-band approach already in production is still the most reliable of the three. The more "textbook-sophisticated" stochastic method does not beat the simpler empirical one here, most likely because the Monte Carlo regime-mixture model's volatility assumptions are calibrated more loosely than the empirical band's direct read of realised historical dispersion. **Decision: keep the empirical band as the default**; the chance constraint remains available (`alpha=` on `HouseholdQuery2`) as a documented, now-validated alternative rather than an unvalidated one.

**Diversity**, the proposal's own phrase ("a short, ranked and *characteristically diverse* list"), was enforced structurally (≤1 profile per town) but never measured. `backtest_v2.diversity_score()` adds a direct measurement — the share of a shortlist's k picks landing in a distinct town / MRT band / flat type:

| Strategy | Town diversity | MRT-band diversity | Flat-type diversity |
|---|---|---|---|
| naive cheapest-towns | 1.00 | n/a (no MRT band) | 0.20 |
| v1, town-level | 1.00 | n/a | 0.24 |
| v2, block-informed | 1.00 | 0.42 | 0.36 |
| v2, empirical band | 1.00 | 0.43 | 0.33 |
| v2, chance constraint | 1.00 | 0.43 | 0.36 |

**Reading it.** Town diversity is 1.0 everywhere because it's a hard constraint for every strategy. The more interesting result is unconstrained: v2's flat-type diversity (0.33–0.36) is **meaningfully higher than v1's (0.24) or the naive baseline's (0.20)**, even though nothing explicitly forces flat-type variety — it falls out of the richer surplus/deviation objective naturally picking different flat types across different towns, rather than the naive strategy's tendency to pick the same cheap flat type everywhere. This is the first direct, measured evidence for the proposal's "characteristically diverse" claim, rather than an assumption resting on the town constraint alone.

**Update (2026-10-08, extended sample — see §7.4): these two findings were re-run on roughly double the data (11 cutoffs instead of 6, a 4th household archetype added) specifically to check whether the above held up with tighter confidence intervals. Short answer: yes for the headline ordering, but the diversity gap is smaller than the original small sample suggested — see §7.4 for the corrected numbers.**

---

## 7. Further rigor pass (2026-10-08): closing every item on the "what's left" list

Having a complete deliverable (§1–6) raised a natural second question: not "what technique is missing" (nothing proposal-named is), but "what's under-tested in what already exists, and what's built-but-siloed." Four items were identified and closed in this pass.

### 7.1 Is the 0-1 IP's integer-ness actually load-bearing? (LP relaxation / integrality gap)

The recommender has always solved the true binary IP (never rounds an LP relaxation) — but nobody had checked *how much* work that integrality requirement is actually doing. `technique_comparison.experiment_lp_relaxation()` solves the identical candidate set and objective both ways (CBC's branch-and-bound on the binary IP vs. the same problem with `x_i` relaxed to continuous [0,1]) across all 3 original archetypes x k∈{3,5,8}:

| household | k | integer objective | LP relaxation objective | gap | fractional vars at LP optimum |
|---|---|---|---|---|---|
| Young couple, transit-reliant | 3 / 5 | -48,354 / -135,403 | identical | 0.000% | 0 |
| Family, needs primary school | 3 / 5 / 8 | 64,673 / 73,250 / 26,666 | identical | 0.000% | 0 |
| Budget-first, car owner | 3 / 5 / 8 | 28,284 / 29,633 / 8,497 | identical | 0.000% | 0 |

**Reading it.** The gap is exactly zero in all 8 instances tested, and the LP relaxation's own optimum is already 100% integral (0 fractional variables) — CBC's branch-and-bound is *confirming* optimality, not doing real integer search. This is explained by the constraint structure: "exactly k total, ≤1 per town" is a partition-matroid-plus-cardinality system, whose constraint matrix is totally unimodular, which guarantees an integral LP optimum. Practically this changes nothing (the recommender still always solves the real IP, by design) but it is useful, measured evidence that the model scales safely — a much larger candidate pool would not suddenly require expensive branching, because there essentially isn't any to do.

### 7.2 Exact solver vs. a metaheuristic (genetic algorithm) — is CBC overkill?

Not a technique from this module's own syllabus, included for breadth since it's the standard fallback when an exact solver is too slow. `technique_comparison.solve_ga()` implements a real GA (town-keyed chromosome, uniform crossover + repair, mutation, 60 individuals x 80 generations) for the identical selection problem, benchmarked against CBC:

| household | candidates | exact objective | exact time | GA objective | GA time | GA gap vs exact |
|---|---|---|---|---|---|---|
| Young couple, transit-reliant | 11 | -135,403 | 44ms | -135,403 | 224ms | 0.00% |
| Family, needs primary school | 52 | 73,250 | 77ms | 73,250 | 238ms | 0.00% |
| Budget-first, car owner | 25 | 29,633 | 68ms | 29,633 | 243ms | 0.00% |

**Reading it.** The GA finds the exact same optimum every time, but takes ~4x longer than CBC to do it. At this candidate-pool size (hundreds, not millions) there is no practical case for a metaheuristic — confirmed with a number rather than assumed. A GA would only earn its keep if the candidate pool grew by orders of magnitude (e.g. scoring every individual HDB unit rather than town x flat-type x storey x MRT-band profiles).

### 7.3 A literal preemptive production mode (not just the calculator demo)

§2 noted the production recommender uses weighted-sum (Archimedean) GP, with the lecture's literal preemptive (lexicographic) form demonstrated only in the standalone 2-variable calculator. `recommender_v2.solve_preemptive()` closes that gap: a genuine lexicographic solve on the full k-of-n selection IP, not just 2 variables — priority order `[dev_mrt, dev_school, dev_storey, dev_wait, dev_essentials]` by default, each stage minimising one goal's total shortlist deviation subject to every higher-priority goal already being locked at its own optimum, with surplus as the final tiebreaker.

Tested against the weighted-sum mode on the same household (budget $750k, k=3, MRT weight 1.5x, needs primary school):

| mode | net objective | towns picked | dev_mrt | dev_school | dev_storey | dev_wait |
|---|---|---|---|---|---|---|
| weighted-sum (production default) | 80,915 | Jurong West, Choa Chu Kang, Hougang | — | — | — | — |
| preemptive (MRT ≫ school ≫ storey ≫ wait ≫ essentials) | 28,460 | Bedok, Hougang, Pasir Ris | $0 | $0 | $30,000 | $0 |

**Reading it.** The two modes genuinely disagree on which 3 towns to recommend — preemptive mode gives up $52k of net objective (mostly surplus) specifically to drive MRT/school/wait deviation to exactly $0, something weighted-sum mode does not guarantee (it will trade a large enough surplus gain against a small enough high-priority shortfall). This is the intended behaviour difference between the two GP variants and is now a selectable **production mode**, not just a teaching example — exposed in the web app (§7.5) as `mode: "preemptive"` with a user-orderable priority list.

### 7.4 Extended backtest: more cutoffs, a 4th archetype, and real confidence intervals

The original backtest (§6) used 6 cutoffs x 3 archetypes (18 cells, ~90 picks/strategy). To check whether its conclusions survive more data, cutoffs were densified to 11 (quarterly instead of semi-annual, 2023-01 through 2025-07) and a 4th, deliberately different archetype added (retiree, downsizing, 2-3 room, low-storey preference) — 44 cells, 220 picks per strategy, with 95% Wilson confidence intervals on the budget-reliability rate:

| strategy | within budget, 12m later | 95% CI | median pick MRT (km) |
|---|---|---|---|
| naive cheapest-towns | 100.0% | [98.1%, 100%] | 0.709 |
| v1, town-level | 100.0% | [98.3%, 100%] | 0.803 |
| v2, stub ±15% band | 94.3% | [90.3%, 96.7%] | 0.580 |
| v2, scenario chance constraint (α=0.90) | 95.2% | [91.5%, 97.4%] | 0.578 |
| **v2, empirical growth-band (default)** | **97.6%** | **[94.5%, 99.0%]** | 0.585 |

**Reading it.** The ranking is unchanged (empirical band > chance constraint > stub), and the naive/v1 baselines' near-100% reliability is explained the same way as before (narrow, town-level picks are easy to keep under budget, at the cost of the MRT-distance and diversity shown below). At this larger sample the empirical band's and the chance constraint's confidence intervals **overlap** (94.5–99.0% vs 91.5–97.4%) — the earlier small-sample finding that empirical clearly beats chance-constraint is directionally confirmed but should be stated more cautiously: empirical band remains the best point estimate and the safer default, but 220 picks per strategy is not yet enough to call the empirical-vs-chance gap statistically decisive. More cutoffs over time would sharpen this further.

Diversity, re-measured on the same extended sample:

| strategy | town diversity | MRT-band diversity | flat-type diversity |
|---|---|---|---|
| naive cheapest-towns | 1.00 | n/a | 0.200 |
| v1, town-level | 1.00 | n/a | 0.282 |
| v2, empirical band | 1.00 | 0.409 | 0.305 |
| v2, stub band | 1.00 | 0.432 | 0.318 |
| v2, chance constraint | 1.00 | 0.436 | 0.318 |

**Reading it — a genuine correction to §6's claim.** v2's flat-type diversity (0.30–0.32) is still clearly above the naive baseline (0.20), but is now only modestly above v1's (0.282), not the roughly 50%-larger gap the original 6-cutoff sample suggested (0.24 vs 0.33–0.36). The honest statement with more data: **v2 is measurably more diverse than a naive cheapest-towns strategy, and somewhat more diverse than the existing town-level model — but the v1-vs-v2 part of that gap is smaller than first reported**, which is exactly why re-running a backtest finding against more data, rather than reporting the first result, matters.

### 7.5 Wired into the live web app, not left as standalone scripts

Three of the above are now live, selectable features in `webapp/backend/main.py` / `webapp/frontend/index.html`, not just validation scripts:

- **`/api/recommend`** now defaults every solve to the empirical growth-band (§6's validated best default, computed once at server startup) instead of the stub band it silently used before this pass; accepts `mode: "weighted" | "preemptive"` (§7.3) with an optional caller-supplied `priority` order; accepts an optional `chance_alpha` (§6) to opt into the scenario chance constraint instead of the empirical band.
- **`/api/pareto`** (new) — a live, parameterised version of `technique_comparison.solve_pareto_point()`'s epsilon-constraint frontier (§5), returning the full surplus-vs-compromise curve for a household instead of one scalarised point, rendered in the frontend as a new "Trade-off Frontier" tab.
- The frontend's Final Recommender tab gained a goal-programming mode selector, a 5-slot priority-order picker (shown only in preemptive mode), and a chance-constraint alpha field, with the preemptive mode's per-goal stage values displayed alongside the shortlist.

---

## 8. Six new house attributes, sourced and geocoded (2026-10-08)

A follow-up to the "what other attributes might a household want" brainstorm: for each candidate attribute, real public data was located, geocoded where needed, and wired all the way through `block_accessibility.py` → `housing_profiles_v2_full.csv` (verified: all 712 profiles populated, zero nulls) → the web app's search filters. **None of these are priced into the recommender's surplus/deviation objective yet** — see "What's intentionally not done" below.

| Attribute | Source | New columns | Honesty caveat |
|---|---|---|---|
| Secondary school proximity | `General_Information_of_Schools.csv` (MOE) — same file as primary school, filtered on `mainlevel_code` | `dist_secondary_school_km_p50`, `dist_secondary_elite_km_p50`, `secondary_tier` | Not a MOE priority band — S1 posting is PSLE-score-based, unlike P1's distance-based tiers |
| Carpark access | data.gov.sg `HDB Carpark Information` (`d_23f946fa557947f93a8043bbef41dd09`), SVY21→WGS84 via pyproj | `dist_carpark_km_p50`, `share_has_carpark_400m`, `share_has_night_parking_400m` | None — direct measurement |
| Flood-prone flag | PUB's published 36-location list, OneMap-geocoded | `dist_flood_prone_km_p50`, `share_near_flood_prone_area` | Point proxy for a named road, not a flood-extent polygon; only 175/10,795 blocks within 300m (most listed locations aren't HDB estates) |
| Expressway/noise proxy | OSM motorway/trunk ways (20,831 vertices via `osmnx.features_from_place`) | `dist_expressway_km_p50`, `expressway_proximity_band` | Straight-line distance to road geometry, not a measured dB level |
| Decentralised job nodes | OneMap-geocoded (Raffles Place, Jurong East, Punggol Coast, one-north, Woodlands Regional Centre) | `dist_{node}_km_p50` ×5, `dist_nearest_job_node_km_p50`, `nearest_job_node` | Straight-line distance, explicitly NOT real transit travel time (needs LTA GTFS or an OneMap routing token, neither available) |
| MULTI-GENERATION flat type | Existing resale transaction data, previously filtered out everywhere | Separate table: `multigen_profiles.py` → `data/multigen_profiles.csv` | Only 88 transactions nationwide since 2017 (3 towns) — too thin for the standard pipeline, so built as a town-level, all-time-window table with an explicit `data_quality` column, kept OUT of the main 712-profile table rather than silently diluting it |

**MULTI-GENERATION, verified end-to-end**: `recommender_v2.solve(HouseholdQuery2(flat_types=["MULTI-GENERATION"], budget=1_000_000, k=2), profiles=multigen_profiles.load_multigen_profiles())` → `Optimal`, picks Tampines and Yishun, correctly shows a **large `dev_wait` deviation** (thin/illiquid market → long expected wait under the Poisson stub) and **zero surplus** (no hedonic model was fit on 88 rows, so `hedonic_gap` is NaN→0 by design rather than a fabricated number). This is a genuinely informative result, not a stub returning nonsense.

**A non-obvious bug found and fixed while wiring this in**: `recommender_v2.assemble()` merges the profile table with `price_forecast.csv` (read from disk) to compute `price_upper` *before* `solve()`'s own `fcast_override` parameter is ever applied — so `fcast_override` alone cannot supply a missing flat_type; every multigen row silently read as budget-infeasible until the on-disk forecast file itself got MULTI-GENERATION rows (`multigen_profiles.ensure_multigen_fcast_rows()`, using the exact same flat-type-independent stub constant — growth_factor=1.0, upper=1.15 — every other flat type already gets, confirmed by reading the stub's own `_source` column rather than inventing a number).

**What's intentionally not done (flagged for the user, not an oversight):**
- **Unit orientation / west-sun exposure** — not attempted. No public dataset with pre-computed block orientation was found; would need block footprint geometry + a geometric azimuth calculation, its own research spike before starting.
- **Real PT travel time** (vs. the straight-line job-node proxy above) — would need LTA's GTFS feed or an authenticated OneMap routing token (registration requires credentials this session does not have and should not create without asking first).

---

## 9. Pricing the new attributes: a hedonic re-fit, tested one at a time (2026-10-10)

The 6 new attributes in §8 were descriptive/filterable only. This section tests each one as a candidate new regressor in the interim hedonic model (`hedonic_value.py`), using the exact same two-step discipline the project already used to decide primary-school distance's fate (§ in `block_analysis.py`'s variance-decomposition method, and the documented "counterintuitive sign → exclude" precedent): **(1)** check how much of the attribute's variance is *within*-town (town fixed effects can only be beaten by a signal with real within-town variation), **(2)** fit it and check the sign/significance are both economically sensible before trusting the number.

**Step 1 — variance decomposition** (`block_analysis.variance_decomposition()`, unique blocks):

| Attribute | Within-town share |
|---|---|
| `dist_carpark_km` | 97.4% |
| `near_flood_prone_area` | 94.4% |
| `dist_secondary_school_km` | 80.3% |
| `dist_expressway_km` | 25.6% |
| `dist_nearest_job_node_km` | 10.4% |

`dist_nearest_job_node_km` is ruled out immediately: 89.6% of its variance is *between* towns, meaning it's almost redundant with the town fixed effects already in the model — any coefficient fit on the remaining 10% would be unstable and not worth reporting. The other four went on to step 2.

**Step 2 — fit and check sign/significance** (36-month training window, same formula as production, 77,947 rows):

| Attribute | Coefficient | % per km | p-value | Verdict |
|---|---|---|---|---|
| `dist_secondary_school_km` | +0.0205 | +2.07% | <0.0001 | **Rejected** — same counterintuitive positive sign as primary school (farther = pricier), same likely cause (collinearity with older/denser estates) |
| `dist_carpark_km` | -0.0073 | -0.72% | 0.263 | **Rejected** — not significant (carparks sit within ~80m of nearly every HDB block; too little price-relevant variation) |
| `near_flood_prone_area` | +0.0254 | +2.57% | <0.0001 | **Rejected — confounded.** Checked directly: the 175 flagged blocks sit disproportionately in Bukit Merah/Queenstown/Kallang-Whampoa (mean 0.55km to MRT vs 0.71km for all residential blocks) — prime, central, mature estates. The coefficient is picking up unmodelled prime-location value, not a flood-risk discount; pricing it in would tell a household the model rewards living somewhere with a documented flood history, which is backwards. |
| `dist_expressway_km` | **+0.0094** | **+0.94%** | **<0.0001** | **Accepted** — significant AND correctly signed: farther from an expressway is pricier, the expected disamenity direction. |

**Only `dist_expressway_km` passed both tests.** Added to `hedonic_value.WTP_ATTRS` and re-fit: adjusted R² moved from 0.9372 to 0.9373 (negligible, as expected — one more weak-ish but genuine control). Re-running the walk-forward backtest (`run_v2_variant`, empirical band) confirms **no regression**: 98.8% within-budget reliability, identical to the pre-change baseline.

**Wired in as a GOAL, not a tilt multiplier.** Every existing `ATTR_COLS` attribute (MRT, hawker, supermarket, clinic, park) uses a "closer is better" multiplier convention — `multipliers={"mrt": 1.5}` means "I value proximity 1.5x the market." Expressway proximity is a *disamenity* (closer is worse), so the same multiplier framing would be backwards to explain to a user even though the underlying formula is mathematically sign-agnostic. Instead, `recommender_v2.HouseholdQuery2` gained `target_expressway_km` (default `None` = goal inactive), mirroring `target_mrt_km`'s goal-deviation pattern but inverted — a **minimum**-distance goal (`dev_expressway = price × β × (target − dist).clip(lower=0)`, β from the real fitted coefficient) instead of `dev_mrt`'s **maximum**-distance goal. Verified end-to-end: a household with `target_expressway_km=0.3` gets a real, correctly-directional dollar penalty (`$810` for a Pasir Ris pick 93m from an expressway, `$0` for picks already past 300m) — exposed in the web app as an optional field on the Final Recommender tab.

**Why this section matters for the report**: it demonstrates the attribute pipeline doesn't just add data, it tests whether that data is *trustworthy enough to act on* — and 3 of 4 candidates were correctly rejected with a documented, falsifiable reason rather than assumed to be safe.

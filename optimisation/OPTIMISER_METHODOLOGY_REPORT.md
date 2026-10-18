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

## 10. Real adapters for Pricing & Availability and Forecasting (2026-10-12)

The Pricing & Availability Lead's and Forecasting Lead's real deliverables exist (on `main` and `forecasting` in the team's shared repo) and are genuinely strong — a LightGBM hedonic (MAPE 3.90%, R²=0.977, vs. this pipeline's own interim OLS hedonic's 15.8% MAPE) and a validation-selected regional SARIMAX forecast — but neither's file format matched `INTERFACE_SPEC.md`. Rather than ask them to re-cut their own pipeline's granularity, three adapter scripts were built to convert their real output into this pipeline's schema, reproducibly (re-run against a newer snapshot any time).

**The profile_id crosswalk** (`profile_crosswalk.py`): theirs is `TOWN|FLATTYPE|LeaseBand|MRTBand|StoreyRange` (5 parts; lease band `<60`/`60-79`/`80+`; MRT band `<500m`/`500m-1km`/`>1km`; storey `1-6`/`7-12`/`13+`), mine is `TOWN::FLATTYPE::StoreyBand::MRTBand` (4 parts, no lease dimension; MRT `Near≤400m`/`Mid 400-800m`/`Far>800m`; storey `Low 1-6`/`Mid 7-15`/`High 16+`). Bin edges don't align exactly (their 500m/1km vs. my 400m/800m; their 7-12/13+ vs. my 7-15/16+) — mapped to the nearest sensible 3-to-3 correspondence, an acknowledged approximation at the boundaries. Their extra lease-band dimension has no equivalent in my profile at all; every adapter aggregates with the **median** (not mean, to resist outlier cells) across whichever of their profiles collapse onto one of mine. **Coverage after crosswalk: 681 of my 708 profiles (96.2%)** get real data; the rest fall back to this pipeline's existing stub, per-profile, not all-or-nothing.

**`pricing_availability_adapter.py`** → `pricing_today.csv`, `availability.csv`:
- Their `price_low`/`price_high` are the 10th/90th percentile of price *across blocks within a profile* (a dispersion measure, not a point-estimate SE) — converted to an approximate SE via the 10th/90th-percentile-of-normal relationship (÷2.5632), stated as an approximation, not their model's own reported uncertainty (they don't report one).
- Their `expected_wait.csv` gives a point `wait_months` (Cox PH) and a `scarce` flag, no `survival_prob_6m/12m` directly. Their own documented method ("turn each gap into a rate 1/gap, add the rates, take 1/total") is already a rate/exponential construction, so deriving `survival_prob_h = 1 - exp(-h/wait_months)` is methodologically consistent with how `wait_months` was itself built, not an arbitrary reinterpretation.

**`forecasting_adapter.py`** → blends into `price_forecast_live.csv`: their real coverage is **4-ROOM only, all 26 towns** (`price_paths_metadata.json`: "Supports four-room profiles only") — growth factors computed at their own profile grain first (month-by-month p10/p50/p90 ÷ their own Sep-2026 base price, same profile_id scheme), *then* crosswalked and aggregated, so two different aggregation steps are never mixed before dividing one by the other. Every other flat type keeps the existing stub, stated explicitly in the output (`_source` column) rather than silently implied as fully real.

**Two correctness issues found and fixed while wiring this in, not after:**
1. **Look-ahead bias risk.** Applying today's real pricing/availability/forecast unconditionally would leak into the walk-forward backtest's historical cutoffs. Fixed by gating every real-data substitution behind a `live` flag, inferred automatically from whether `profiles` was explicitly passed to `assemble()` (`profiles=None` → today, live-safe to use real data; an explicit historical snapshot → `live=False`, real data never touches it). The stub-only `price_forecast.csv` is kept untouched for this reason; the real/stub blend lives in a separate `price_forecast_live.csv`. **Verified**: re-ran the backtest after wiring this in — 98.8% reliability, byte-identical to the pre-adapter numbers, confirming zero leakage.
2. **Hedonic-basis mismatch.** `shrunk_value_gap` (the "is this a bargain" signal) is `hedonic_value − price_today`. `hedonic_value` was fit to predict *this pipeline's own* `median_price` — not the Pricing Lead's real, lease-band-blended `price_today`. Checked empirically: the two price bases agree on average (median gap 2.5%) but disagree sharply at the tails (std 13.2%, range −47% to +80%), almost certainly because their price blends across 3 lease bands this pipeline's profile doesn't carry at all. Comparing the two would mostly measure model disagreement, not genuine mispricing. **Fix**: the bargain signal is suppressed (set to $0, not fabricated) for every profile using real pricing, until the hedonic model is properly re-fit with their price as the target — the same conservative treatment already used for MULTI-GENERATION profiles (§8) that have no hedonic fit at all. Surplus for real-priced profiles currently comes from preference tilt only.

**What's still needed from the other leads, concretely** (not a vague "send more data" ask):
- **Preference**: nothing exists on any branch yet — the one workstream genuinely not started, not just mismatched.
- ~~**A richer hedonic re-fit**, once there's bandwidth~~ — **done, 2026-10-18, see §14**: a literal re-fit against their price wasn't possible (no block-level data from them), so a profile-level calibration was built instead (R²=0.934), re-enabling the bargain signal with a statistical outlier guard.
- **Forecast coverage beyond 4-ROOM**, if the regional SARIMAX extends to it — currently the single largest real-data gap (4 of 5 flat types still run on the flat stub for forecasting). *(Still open as of 18 Oct.)*
- **A lease-band dimension**, or confirmation it's safe to keep aggregating it away — this pipeline's profile has never carried remaining lease as a axis beyond a hard minimum-lease filter; the Pricing Lead's data suggests it's a meaningfully large price driver (their profile splits on it explicitly). *(Still open as of 18 Oct.)*
- ~~**Portable file paths**: every script in this pipeline still hardcodes the author's own machine path~~ — **done** (fixed across 18 scripts before this section was last touched; this line was stale, left over from before that fix — corrected 2026-10-18).

---

## 11. Correcting the MRT premium for spatial bias (2026-10-18)

A routine check of the team's other branches surfaced `notebooks/04c_hedonic_econometrics.ipynb` (Pricing & Availability Lead, `main` branch) — a rigorous econometric companion to their production LightGBM model: spatial diagnostics (Moran's I, Lagrange-multiplier tests), spatial-error/spatial-lag models, and a causal difference-in-differences study on 11 real MRT stations opened 2019–2024.

**Finding**: a hedonic fit with only town (and month) fixed effects — this pipeline's own specification class — overstates the MRT premium by roughly 2×, because nearby blocks share unmeasured neighbourhood quality that a town-level fixed effect cannot separate from true MRT proximity.

| Specification | Effect of halving MRT distance |
|---|---|
| OLS, town dummies only (directly comparable to this pipeline's spec) | 5.28% |
| Spatial-error model (controls for neighbourhood quality) | 2.7–3.5% |
| Causal: difference-in-differences on real station openings, 95% CI 2.0–3.7% | 2.8% |
| **Their recommended benchmark** ("the spatially robust figure to hand to the Preference Lead") | **~3%** |

**Checked directly against this pipeline's own coefficient** before acting on it: `market_wtp_coefficients.json`'s fitted `dist_mrt_exit_km` coefficient implied **exactly 5.28%** for the identical halving comparison — the same number as their "town dummies only" row, confirming this pipeline's hedonic carries the identical bias, not a coincidentally similar one.

**Fix**: `hedonic_value.py` now applies a documented correction factor (`MRT_SPATIAL_CORRECTION = 3.0/5.28 ≈ 0.568`, the ratio between their recommended benchmark and the naive estimate directly comparable to this model's own) to the **exported WTP rate** used for preference-tilt and the `dev_mrt` goal penalty. Verified: the corrected coefficient now implies 2.97% for the same halving check. The GP calculator's default "$/km closer to MRT" rate dropped from ~$58,500 to ~$33,100 accordingly.

**Scope — what this does and does not fix**: the correction is applied only where the MRT rate is used as a $-weight (preference tilt, `dev_mrt`, the GP calculator default, `preference_overrides_from_file()`'s multiplier denominator). It is **not** applied to the hedonic model's own price predictions (`predict_value()`), which still use the uncorrected coefficient — those predictions only feed the bargain-gap signal for the ~0.3% of profiles still on stub pricing (99.7% now use real LightGBM prices as of §12's update, unaffected either way), a much smaller blast radius than the $-weight used on every live recommendation. A proper fix would re-fit this pipeline's own hedonic with a spatial term; borrowing a ratio from a different (sales-level vs. block-level) model is a pragmatic, clearly-labelled interim correction, not a substitute for that.

**Re-verified after the change**: backtest reliability 96.6% [93.1%, 98.3%] on the 11-cutoff extended sample, vs. 97.6% [94.5%, 99.0%] before — confidence intervals overlap substantially, not a statistically meaningful regression (expected: this coefficient changes *which* profiles look attractive, not the budget-feasibility check that drives reliability).

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

---

## 12. Pricing & Availability's native-schema update, and following through on the integration progress report (2026-10-18)

One day after §11, the Pricing & Availability Lead pushed a second, independent update (`main` commit `42df63b`, 17 Oct): their availability model was recalibrated — Cox survival rates blended per flat type with an empirical-Bayes adjustment from each profile's last-12-month sales, out-of-sample Spearman 0.916 vs. 0.752 for Cox alone — and, the part that matters here, they started writing `outputs/optimisation/pricing_today.csv` and `availability.csv` **already keyed on this pipeline's own `profile_id`**, priced and timed per-profile from their real block mix rather than a median crosswalk across lease bands (`docs/model_validation.md` §3b on `main`: 952 of this pipeline's profiles covered, vs. 712/713 on each side agreeing on sales-count — essentially full agreement).

**Fix**: `pricing_availability_adapter.py` gained `build_from_native()`, a pass-through (not a crosswalk) that reads their file directly and filters to this pipeline's known profile IDs. The older `profile_crosswalk.py`-based functions (§10) are kept only for reproducing their 12 Oct snapshot for historical/backtest comparison. Coverage rose from **96.2% (681/708, crosswalk) to 99.7% (706/708, native)**.

**Checked against Forecasting's own documented caveat before relying on this further**: `forecasting/REGIONAL_HANDOVER.md` (Forecasting Lead) warns "do not independently sample these rows for Monte Carlo… joint simulation remains unimplemented" about their `price_paths.csv` quantile rows. Verified `monte_carlo.py` and `chance_constraint.py` never load or sample that file's rows at all — both only use the summary `growth_factor`/`growth_factor_lower`/`growth_factor_upper` columns to parameterise their own per-profile normal approximation (`simulate_price()`). No change needed; recorded here as a checked, not assumed, fact.

**Published back to the team's own handover contract**: `outputs/shortlist.csv` (`build_shortlist.py`) — 20 picks across the project's 4 standard household archetypes (`backtest_v2.EXTENDED_ARCHETYPES`), from today's live recommender. Still running on the stub `preferences.json`; scheduled to be re-run once the Preference Lead's real file lands (see `INTEGRATION_PROGRESS.md`).

**What changed downstream, and why it's reported rather than quietly patched over**: every number in this report and the Word report (v2) computed with `profiles=None` (today's real data, i.e. `live=True`) moved by some amount — the Live Recommender Output example, and most visibly the Weighted-Sum vs. Preemptive comparison, whose test household (budget $750k, k=3, MRT weight 1.5×, needing a primary school) now has every goal fully satisfiable: both GP modes return the identical three picks at $0 total deviation, a **$0 gap**, down from $4,469 (after §11's MRT fix) and originally $52,455 (v1 draft). This is correct GP behaviour, not a bug — preemptive and weighted-sum can only disagree when something forces a trade-off, and today's better availability coverage relaxed the one that used to exist for this household. The Word report's Weighted-Sum vs. Preemptive section now demonstrates the same genuine disagreement on a tighter household instead (budget $600k, k=3, MRT weight 2.0×, target MRT 0.3km), where a real $69,546.38 gap and zero shared picks still exist for an inspectable reason.

**Backtest numbers are unaffected by any of this.** Every backtest call passes an explicit historical `profiles` snapshot, which `assemble()` auto-infers as `live=False` and therefore never reads `pricing_today.csv` / `availability.csv` at all — confirmed by reading the gating logic directly (`recommender_v2.py::assemble()`, `load_inputs()`), not assumed. The 96.6% reliability figure, the 0.000% LP-relaxation gap, and the diversity/GA-comparison numbers all still stand as reported in §11 and earlier.

---

## 13. Closing three self-identified follow-ups from the integration progress report (2026-10-18)

Three items were flagged in `INTEGRATION_PROGRESS.md` as open, actionable-by-me follow-ups. All three are closed as of this section.

**(a) `price_today_se` definition mismatch — audited, found to be currently inert.** The Pricing Lead's native file defines `price_today_se` as `price × 0.052` (hold-out log-RMSE on unseen blocks — a single-flat prediction error), different from the old crosswalk adapter's percentile-based approximation and the original stub's flat 5%. Audited every consumer in the codebase (`recommender_v2.py`, the legacy `recommender.py`, `shrink_k`, the GP calculator, the web app, the frontend): `price_today_se` is read into memory in `_load_real_pricing()` but **never merged into the working dataframe or used in any computation** in the live v2 path — `assemble()` only pulls `price_today` across. `shrink_k` shrinks on `txn_count_12m`, not on any price SE, at all. The "simple uncertainty band" this column was originally meant for (per `INTERFACE_SPEC.md`) ended up implemented a different way instead — `price_low`/`price_high` → `growth_factor_upper` → `price_upper` in the hard budget-feasibility constraint. Conclusion: the definition change is currently a no-op on any live output, not a live bug — documented precisely in `INTERFACE_SPEC.md` so a future feature that *does* wire this column in starts from the correct definition.

**(b) Data-layout portability — bridged for the files that are honestly the same dataset, documented for the ones that aren't.** This pipeline reads from its own flat `Project/data/...` layout, never the shared repo's `data/raw`/`data/interim` split, so there is no single path-variable fix. Instead: inventoried every file this pipeline reads from outside its own `data/` folder (grep for `ROOT`-relative paths across all scripts), checked each candidate shared-repo file byte/row/feature-count against this pipeline's own copy before treating it as equivalent, and built `sync_shared_repo_raw_data.py` + `DATA_LAYOUT.md` from the result. **21 files verified identical** (9 common raw downloads under different filenames, 12 of this pipeline's own earlier `daniel_add` contributions already on `main` under the exact filenames expected here) and wired into an automated sync script. **2 files correctly rejected** as genuinely different datasets despite superficially similar names (`PreSchoolsLocation.geojson`, `polyclinics.csv` — the latter flagged as a probably-better future data source for `dist_polyclinic_km`, not silently swapped in). **1 true gap** recorded: `hdb_rental_town_flattype_month.csv` (read live for `dev_wait`'s `monthly_rent`) has no equivalent anywhere in the shared repo at all. Tested the sync script twice: once against the real shared-repo checkout on this machine (0 copies needed, all 21 already present and verified identical — a correctness check in itself), and once against a simulated empty project directory (all 21 copied correctly, spot-checked one file's content post-copy).

**(c) Hedonic re-fit against the real price basis — done, with a measured result, not assumed.** See §14 for the full write-up.

---

## 14. Re-enabling the bargain signal: a profile-level calibration, not a literal re-fit

Since the Pricing Lead's real data went live, `shrunk_value_gap` (the "is this a bargain?" half of every profile's surplus) has been forced to $0 for every real-priced profile — because `hedonic_value` was fit against this pipeline's own transaction prices, not their LightGBM `price_today`, and comparing the two raw mostly measured model disagreement, not genuine mispricing.

**Why a literal re-fit isn't possible today**: re-fitting the attribute regression (`hedonic_value.py::fit_hedonic()`) against their price as the target needs a per-TRANSACTION or per-BLOCK label. The Pricing Lead's real deliverable is a profile-level aggregate (`pricing_today.csv`) — one number per `profile_id`, not per block. Re-fitting a transaction-level OLS against a profile-level average would mean assigning every transaction in a profile the identical target price, collapsing all within-profile variation the regression needs to identify attribute coefficients. Not done; flagged in `INTEGRATION_PROGRESS.md` as an optional future ask (their block-level predictions, if they're willing to share them).

**What was done instead**: a profile-level calibration using what both sides actually have in common — `hedonic_value` and `price_today`, both at profile grain, on the 706-profile overlap. `hedonic_value.py::fit_price_calibration()` fits `log(price_today) = alpha + beta*log(hedonic_value)` by OLS:

| alpha | beta | R² | n | resid_std (log) |
|---|---|---|---|---|
| 0.524 | 0.958 | **0.934** | 706 | 0.089 |

A strong fit (R²=0.934) — most of the systematic difference between the two models is a smooth, correctable basis shift, not noise. `apply_price_calibration()` maps every profile's `hedonic_value` onto `price_today`'s basis via this fit (generalises to stub-priced profiles too, not just the 706 it was fit on), and `recommender_v2.py::score()` now uses `calibrated_value - price_today` instead of forcing $0 for every real-priced profile — artifact: `build_price_calibration.py` → `data/hedonic_price_calibration.json`, re-run whenever `pricing_today.csv` refreshes.

**A real problem found and fixed before calling this done**: the first version (calibration alone, no guard) produced a $202,262.88 "bargain" signal on `CENTRAL AREA::4ROOM::High::Mid` — traced to `hedonic_value=$1,276,675` vs. `price_today=$658,000` on a profile with only 2 blocks / 6 transactions on this pipeline's side. Checked across all 706 profiles: 10 (1.4%) sit beyond 3 calibration-residual standard deviations, 4 (0.6%) beyond 4 — a genuine, small tail, mostly (not exclusively) the thinnest-sample profiles, where this pipeline's and the Pricing Lead's profile likely draw from different block compositions under the same nominal `profile_id`. **Fix**: `apply_price_calibration(..., clip_sigma=3.0)` clips the calibrated value to within 3 residual standard deviations (~±31%) of `price_today` in log space before it's used — a tail guard grounded in the calibration's own measured uncertainty, not an arbitrary cutoff. Touches 10/706 (1.4%) of profiles; the other 98.6% pass through uncapped. Reduced the worst case from $202,263 to $118,784 (still larger than typical because HDB prices are six figures — 31% of $572,000 is genuinely a six-figure number, not a bug).

**Checked the resulting signal's scale isn't a new distortion**: compared against the ORIGINAL (pre-real-data, stub-era) `shrunk_value_gap` across all 708 profiles — median absolute $15,688, std $28,808, range −$142,470 to +$68,827. The calibrated-and-capped version's scale (median $8,876, std ~$29,544 on the 220-candidate live example) is consistent with this, not larger — confirming the fix restores the objective's originally-designed scale on the real-price basis, rather than introducing a new one.

**Re-verified against the full walk-forward backtest, not assumed safe**: `run_v2_variant()`, 11 cutoffs × 4 archetypes extended set — **96.6% [93.1%, 98.3%] reliability, identical to the pre-change figure, median pick MRT 0.61km.** Expected and confirmed: every backtest call passes an explicit historical `profiles` snapshot, `assemble()` infers `live=False`, `price_is_real` is never set, and this entire code path is never exercised during a backtest — the change is scoped to live (`profiles=None`) requests only, exactly like the MRT correction (§11) and the native pricing pass-through (§12) before it.

---

## 15. Two more follow-ups: a real spatial re-fit, and a corrected polyclinic source (2026-10-18)

### 15a. The MRT spatial-bias fix, finished — `predict_value()` itself, not just the exported rate

§11 fixed the MRT premium used for preference-tilt and `dev_mrt`, but explicitly left `predict_value()`'s own price predictions on the biased town-FE coefficient, "pending a proper spatial re-fit." That re-fit is done.

**What was built**: `block_accessibility.py::assign_subzone()` — a geopandas point-in-polygon join of every block's lat/lon against `MasterPlan2019_Subzone_Boundary_NoSea.geojson` (332 subzones island-wide, 167 with HDB stock). 100% coverage, 13,356/13,356 blocks matched, no manual fallback needed. `hedonic_value.FORMULA` now uses `C(subzone)` in place of `C(town)` — a finer, still purely fixed-effects geographic control (subzone nests inside town) that needs no new spatial-econometrics machinery.

**Measured effect**:

| | Town FE (old) | Subzone FE (new) |
|---|---|---|
| Adjusted R² | 0.9372 | **0.9545** |
| Implied effect of halving MRT distance | 5.28% | **4.55%** |
| Pricing Lead's causally-identified benchmark | — | ~3% (unchanged) |

A genuine, substantial improvement — closes about a third of the gap to the ~3% benchmark, and does it as a real change to `predict_value()`'s own output, not a post-hoc multiplier. **Stated honestly, not oversold**: 4.55% is still above ~3%. Subzone FE (median ~3km²) is a coarser proxy for neighbourhood quality than the Pricing Lead's spatial-error model or their causal difference-in-differences design — some within-subzone confound (e.g. newer blocks clustering nearer an MRT entrance within the same subzone) survives. `MRT_SPATIAL_CORRECTION` (the multiplier still applied to the *exported* WTP rate only) was recalibrated to the new, smaller residual gap: `3.0 / 4.55 ≈ 0.659`, up from `3.0 / 5.28 ≈ 0.568`.

**Full rebuild + re-verification, not assumed safe**: ran `rebuild_v2.py` end to end (block accessibility → transaction-block cache → profiles + hedonic + `market_wtp_coefficients.json` → backtest). Profile count and band split unchanged (708; Near 243 / Mid 243 / Far 222 — subzone is an internal regression control, not a profile dimension, so it can't change profile counts). Backtest reliability on the small 6-cutoff × 3-archetype sample: 97.6% [91.5%, 99.3%] — identical to the historical baseline. On the extended 11×4 sample: **96.5% [93.0%, 98.3%]**, statistically identical to the pre-change 96.6% [93.1%, 98.3%]. `build_price_calibration.py` was re-run against the refreshed `hedonic_value` column: R² actually *improved* slightly (0.934 → 0.942, resid_std 0.089 → 0.084) — a more accurate hedonic agrees even more closely with the Pricing Lead's real price, as expected.

**Downstream effect on this report's live examples** (both use `profiles=None`, i.e. real data): the "Live Recommender Output" example's objective moved to $331,842.95 (picks: Toa Payoh / Queenstown / Ang Mo Kio) — a large jump from the $41,242.67 quoted after §12, because that number predates §14's calibration fix landing in the live path (§12 was written when `shrunk_value_gap` was still $0 for every real-priced profile; §14 re-enabled it days later, same day as this section). More interestingly, with the bargain signal now genuinely active, **weighted-sum and preemptive diverge again on the same original test household** — $155,112.19 gap, zero picks shared — because preemptive's strict goal-priority ordering now sacrifices a materially large bargain signal to drive every goal to exactly $0, a trade-off that didn't exist when the signal was flat $0 for everyone. The full arc on this one household, tracked rather than silently overwritten: $52,455 (v1 draft) → $4,469 (§11, MRT correction) → $0 (§12, native pricing update, before the bargain signal was reinstated) → **$155,112 (§14+§15, bargain signal reinstated with a now better-calibrated hedonic)**. The tighter household introduced in §12's write-up (budget $600k, k=3, MRT weight 2.0×) still diverges for a different, complementary reason — tight storey/essentials/school trade-offs under a real budget constraint — gap now $105,726.25 (was $69,546.38), zero picks shared, every preemptive pick paying a flat $15,000 storey penalty to hold `dev_mrt` at exactly $0.

### 15b. Polyclinic source corrected — real list, not a COVID-vaccination subset

`dist_polyclinic_km` (a descriptive profile attribute — **checked and confirmed it feeds no WTP coefficient, no `essentials_score` term, and no web app field today**, so this was a pure data-quality fix with zero decision-logic blast radius, not something needing a backtest gate) was sourced from `Vaccination_Polyclinics.geojson`, 8 COVID-vaccination sites — a real undercount of Singapore's 17 polyclinics (plus 10 "SHP" community health posts in the Pricing Lead's own list, 27 points total). Geocoded the Pricing Lead's real `polyclinics.csv` (name + postal code, 27 rows) via OneMap's public search endpoint — `geocode_polyclinics.py`, **27/27 resolved, 0 failures** — and wired the result into `block_accessibility.py` in place of the vaccination-site file. Effect on the raw feature: block-level `dist_polyclinic_km` mean fell from 3.11km to 1.14km (median 2.66km → 1.05km) — expected, given more than 3× as many points. No other file changed; no re-fit or re-verification needed, since nothing reads this column for pricing or recommendation decisions today. Flagged for whoever eventually wires `dist_polyclinic_km` into a real goal or WTP term in the future: use the corrected source, already in place.

---

## 16. Adding a lease-band dimension to the profile (2026-10-18)

This pipeline's profile had never carried remaining lease as an axis — only a hard `min_lease_yrs` eligibility floor — even though the Pricing Lead's own profile splits explicitly on it (`<60`/`60-79`/`80+` years) and their data suggested it was a meaningfully large price driver being aggregated away.

**What changed**: `profile_id` grew from 4-part (`TOWN::FLATTYPE::StoreyBand::MRTBand`) to 5-part (`TOWN::FLATTYPE::LeaseBand::StoreyBand::MRTBand`), using the Pricing Lead's own `<60`/`60-79`/`80+` bands exactly rather than inventing a new cut — deliberately, so lease becomes the one profile dimension that never needs crosswalking (an identity mapping either way).

| | Before | After |
|---|---|---|
| Profile count | 708 | **1,184** |
| Pricing/availability coverage | 99.7% (706/708, native pass-through) | 94.5% (1,119/1,184, lease-preserving crosswalk) |
| Calibration fit (hedonic vs. real price) | R²=0.942 | **R²=0.960** |
| Backtest reliability (extended 11×4) | 96.5% [93.0%, 98.3%] | **99.4% [96.9%, 99.9%]** |

**A real, measured improvement with an honest cost.** Reliability rose because price estimates are now drawn from a lease-homogeneous population — closer to what a similar flat will actually sell for. Coverage fell because the Pricing Lead's native (lease-collapsed) 17 Oct hand-over file — the thing that drove 99.7% coverage a day earlier — can no longer match a 5-part `profile_id` at all; `pricing_availability_adapter.py` went back to crosswalking their original 5-part export instead, which carries real lease splits but thinner cells per split. The backtest's own `matched_sale_seen` rate makes the trade-off visible directly: **81.4%**, down from the low-90s before — finer cells price better but are more often too thin to find a matching realised sale inside the narrow 3-month validation window. Reported as a real trade-off, not hidden behind the headline reliability number.

**Every touchpoint found by grepping, not assumed safe.** `block_analysis.py` gained `lease_band()` (same bands as the Pricing Lead) computed once inside `load_transactions_with_access()`, shared by every consumer rather than recomputed per-script. `housing_profiles_v2.py`'s profile groupby and `profile_id` construction both updated. `profile_crosswalk.py`'s `crosswalk_profile_id()` now preserves lease band instead of discarding it (previously the ONE dimension every adapter function aggregated away — no longer true). `pricing_availability_adapter.py`'s crosswalk-based functions (kept since §12 only for historical/backtest reproduction) are the primary path once more, now a *better* use of the crosswalk than before: lease is an identity mapping, so only storey/MRT boundary differences remain to resolve. Grepping for every hardcoded profile_id string-split across the codebase caught two real breakages in `backtest_v2.py` (`availability_calibration()`'s profile unpack, three realised-match key lists across `run()`/`run_v2_variant()`/`run_v2_chance_variant()`) and two more in `technique_comparison.py` — fixed, not left as landmines. The FastAPI backend and frontend now return and display `lease_band` alongside `storey_band`/`mrt_band` in the shortlist, trade-off-frontier and profile-search views.

**Re-verified against the full walk-forward backtest, both samples.** Small 6-cutoff × 3-archetype sample: 100.0% [94.7%, 100%] (up from 97.6% [91.5%, 99.3%]). Extended 11×4 sample: **99.4% [96.9%, 99.9%]**, up from 96.5% [93.0%, 98.3%] — point estimates don't overlap cleanly with the *old* 95% CI's lower edge, a genuine signal, not noise. Re-fit the hedonic-to-real-price calibration against the new profiles too: R² rose again, 0.942 → 0.960, resid_std tightened 0.084 → 0.068 — both sides of the comparison are now lease-homogeneous, so they agree even more.

**Downstream on this report's live examples** (both use `profiles=None`, real data, so both moved again): Live Recommender Output now returns 351 candidates (up from 220, more profiles to filter from), objective $84,188.10, top pick Geylang · 4-Room · 60-79-year lease · Low · Mid MRT band. The Weighted-Sum vs. Preemptive gap on the report's running test household: $52,455 (v1 draft) → $4,469 (§11) → $0 (§12) → $155,112.19 (§13+§14) → **$50,362.25** (today), zero picks shared each time the gap reopens — tracked through every cause, not just the final number.

---

## 17. Is the GP divergence finding general, or one cherry-picked household? (2026-10-18)

Every number in §13–§16 above for the "Weighted-Sum vs. Preemptive" gap comes from **one illustrative household** (budget $750k, k=3, MRT weight 1.5×, needs primary school), re-tested across five data states. That raises a fair question this project holds itself to answering, not assuming away: does this household's story generalise, or is it a cherry-picked example that happens to make a good before/after narrative?

**What was tested, and what wasn't.** The ideal test would re-run the full five-stage history across all 4 backtest archetypes (`backtest_v2.EXTENDED_ARCHETYPES`) — 20 combinations. That isn't feasible: the five historical data states (v1 draft, post-MRT-fix, post-native-pricing, post-calibration, post-lease-band) were never independently git-tagged as runnable snapshots — each was a step in one continuously-edited pipeline, not a preserved checkpoint. What **is** feasible, and directly answers the "general or cherry-picked" question, is run **today's final, fully-corrected pipeline** across all 4 archetypes (`test_gp_gap_across_archetypes.py`), at `k=5` (the backtest's own convention) with the shipped default priority order (MRT ≫ School ≫ Storey ≫ Wait ≫ Essentials).

| Archetype | Weighted-sum objective | Preemptive objective | Gap | Shared picks |
|---|---|---|---|---|
| Young couple, transit-reliant | −$13,286.90 | −$36,366.10 | **$23,079.20** | 3/5 |
| Family, needs primary school | $115,270.25 | −$10,212.79 | **$125,483.04** | 1/5 |
| Budget-first, car owner | $27,069.65 | −$745.64 | **$27,815.29** | 1/5 |
| Retiree, downsizing, low storey | $151,468.19 | $151,468.19 | **$0.00** | 5/5 |

**Reading it — the finding generalises, with one genuinely informative exception.** 3 of 4 archetypes show a real, substantial gap ($23K–$125K) — this is not an artefact of the one household used throughout the report; the project's own "Family, needs primary school" archetype (budget $750k, needs primary school) is structurally the closest to that household, and shows the largest gap of all four, $125,483.04. The one archetype with a **$0 gap** (Retiree, downsizing, low storey) is itself the expected, correct behaviour: this household's constraints are loose enough that every goal is simultaneously satisfiable, so there is nothing for the two GP modes to disagree about — consistent with §13–§16's own repeated finding that the gap only exists when a real trade-off exists.

**A second, subtler mechanism found while checking *why* each gap exists — not every divergence is "preemptive sacrifices surplus for a shortfall."** Pulling the goal-deviation breakdown for "Budget-first, car owner":

- **Weighted-sum's own picks** carry small, deliberate deviations — `dev_mrt` of $480, $1,072 and $630 on three picks, and a $2,909 `dev_essentials` on a fourth — accepted because the extra surplus on those specific profiles is worth more than the shortfall costs. Net: **$27,069.65**.
- **Preemptive's picks** are a *completely different set*, chosen so that **every** goal reads exactly $0 on every pick. But that "clean" set's own surplus is lower — net: **−$745.64**.

Preemptive isn't sacrificing surplus to fix a shortfall here; it is structurally forbidden from ever accepting a cheap, profitable shortfall at all, even essentials — the lowest-priority goal — because the lexicographic method locks every higher stage to its own optimum before surplus is ever considered. That is a different, and arguably more revealing, illustration of the lecture's own preemptive-vs-weighted-sum distinction than the report's original household showed on its own.

**Conclusion:** the divergence is a real, general property of these two GP modes on this recommender — not a coincidence of one test household — and the exception (zero gap when nothing conflicts) is itself confirming evidence, not a contradiction. Script and raw output: `test_gp_gap_across_archetypes.py` → `data/gp_gap_across_archetypes.json`.

---

## 18. Is the calibration's R²=0.960 a fragile point estimate? (2026-10-18)

The hedonic-to-real-price calibration (§13, re-fit in §15 and §16) has been reported throughout this report as a single number — R²=0.960 on the 1,119-profile overlap between `hedonic_value` and the Pricing Lead's real `price_today`. A single R² from one fit on one sample is exactly the kind of number that *looks* precise but could in principle be a lucky draw — checked rather than assumed.

**What was run**: `bootstrap_calibration_r2.py` resamples the 1,119-profile overlap **with replacement** (same n each time), refits the identical log-log OLS `hedonic_value.py::fit_price_calibration()` uses, and repeats **2,000 times** — reporting the empirical distribution of R² instead of trusting the one sample already in the report.

| Quantity | Point estimate (full sample) | Bootstrap (2,000 resamples) |
|---|---|---|
| R² | 0.9601 | mean 0.9604, std 0.0063, **95% CI [0.9457, 0.9694]** |
| β (slope) | 1.0238 | mean 1.0237, std 0.0064 |
| Full min/max across all 2,000 resamples | — | [0.9345, 0.9730] |

**Reading it.** The point estimate sits almost exactly on the bootstrap mean (0.9601 vs. 0.9604) — no sign the original fit got a lucky sample. The 95% confidence interval is under 2.4 percentage points wide, and even the most extreme of 2,000 resamples never dropped below 0.9345. β (the slope relating `log(hedonic_value)` to `log(price_today)`) is similarly tight around 1.02, consistent with the two models' prices scaling together almost 1-for-1 once the intercept shift is accounted for. **Conclusion: 0.960 is a stable property of the fit, not a fragile point estimate** — the calibration genuinely explains ~96% of the variance in the real price from this pipeline's own hedonic estimate, and that conclusion would survive drawing a different 1,119-profile sample from the same population. Script and raw output: `bootstrap_calibration_r2.py` → `data/calibration_r2_bootstrap.json`.

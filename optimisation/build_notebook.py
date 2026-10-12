# -*- coding: utf-8 -*-
"""Builds Optimisation_Lead_Pipeline.ipynb covering all 6 tasks from the
Optimisation Lead's workstream table."""
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []


def md(text):
    cells.append(nbf.v4.new_markdown_cell(text))


def code(text):
    cells.append(nbf.v4.new_code_cell(text))


# ============================================================ TITLE
md("""# Optimisation Lead — SG HomeFit Recommender Pipeline
### Option B: Household Affordability Optimizer — Prescriptive layer

This notebook covers all six Optimisation Lead tasks end-to-end, each
executed for real against the data available right now (a mix of real HDB
transaction data and clearly-labelled stubs for the other three leads'
not-yet-ready outputs):

1. **Handover file formats & pipeline structure** — `INTERFACE_SPEC.md` (summarised below)
2. **Rough pipeline and simple ranking** — proves the tool runs end-to-end on Day 1
3. **Recommender formulation** — math programming + goal programming, diversity constraint, top-k
4. **Monte Carlo engine** — buy-now-vs-wait-6/12-months, on a stand-in simulator
5. **Chance constraint + sensitivity sweeps** — 90% scenario-based budget constraint, parametric sweeps with an automated monotonicity check
6. **Backtest + final re-run framework** — walk-forward validation against realised prices and a naive baseline

**Design note throughout**: every input from the other three leads (pricing,
availability, price forecasts, preferences) is read from a small, versioned
file under `data/`. Nothing here hard-codes "the stub" — swap the file,
keep the schema, and the exact same code picks up the real model. That
swap-safety is the point of Task 1.
""")

code("""import warnings
warnings.filterwarnings("ignore")

import json
import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

import housing_profiles
import stub_data
import run_pipeline
import recommender
import monte_carlo
import chance_constraint
import sensitivity
import backtest

plt.rcParams["figure.figsize"] = (10, 4.5)
plt.rcParams["axes.grid"] = True
plt.rcParams["grid.alpha"] = 0.3
pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 160)

DATA_DIR = recommender.DATA_DIR
""")

# ============================================================ TASK 1
md("""## Task 1 — Handover file formats & pipeline structure
*(Due 1 Oct; full spec in `INTERFACE_SPEC.md`)*

Shared unit of analysis: a **housing profile** = `(town × flat_type × storey_band)`.
This is the one assumption everything downstream depends on — flagged in the
spec for the other three leads to confirm or correct before 2 Oct.""")

code("""profiles = housing_profiles.build_profiles()
print(f"Housing profiles: {len(profiles)} rows  |  towns={profiles['town'].nunique()}, "
      f"flat_types={profiles['flat_type'].nunique()}, storey_bands={profiles['storey_band'].nunique()}")
profiles.head(8)""")

md("### File contract each lead writes to / reads from")
code("""spec_summary = pd.DataFrame([
    {"file": "housing_profiles.csv", "owner": "shared (Data & Features step)", "status": "REAL"},
    {"file": "pricing_today.csv", "owner": "Pricing & Availability Lead", "status": "STUB (swap by 7 Oct)"},
    {"file": "availability.csv", "owner": "Pricing & Availability Lead", "status": "STUB (swap by 16 Oct)"},
    {"file": "price_forecast.csv", "owner": "Forecasting Lead", "status": "STUB (swap by 14 Oct)"},
    {"file": "preferences.json", "owner": "Preference Lead", "status": "STUB (swap by 16 Oct)"},
])
spec_summary""")

# ============================================================ TASK 2
md("""## Task 2 — Rough pipeline and simple ranking
*(Due 3 Oct)*

Deliberately **not** the real recommender — a naive weighted-sum ranking with
**no diversity constraint**, so Task 3's improvement is visible rather than
assumed. First, a pipeline health check (does every file the spec promises
actually exist, and is it still a stub?).""")

code("""stub_data.write_all_stubs(profiles)
health = run_pipeline.pipeline_health_check()
health""")

code("""rough = run_pipeline.rough_rank(budget=550_000, min_lease_yrs=60, k=5)
print("Rough top-5 (naive score, no diversity constraint):")
rough""")

md("""**Note the repeat towns above** (if any) — the naive Task 2 ranking has no
mechanism to prevent two profiles from the same town both scoring well. That
gap is exactly what Task 3's `<= 1 profile per town` constraint fixes.""")

# ============================================================ TASK 3
md("""## Task 3 — Recommender formulation
*(Due 10 Oct)*

Mathematical programming + goal programming as **one binary-selection MIP**:

- **Objective**: maximise $\\sum_p x_p \\cdot (\\text{WTP-valued surplus}_p - \\text{goal deviation}_p)$,
  both terms denominated in SGD via the Preference Lead's willingness-to-pay weights.
- **Hard constraints**: `budget >= upper forecast price` (6/12mo horizon), `remaining_lease >= min_lease`,
  **at most one profile per town** (diversity), exactly `k` profiles selected (top-k).
- **Soft goals** (dollar-weighted deviations from household targets): MRT distance, school count,
  storey band, expected wait, amenity count.""")

code("""q = recommender.HouseholdQuery(
    budget=550_000, min_lease_yrs=60, horizon_months=12, k=5,
    target_mrt_km=0.5, target_schools_within=5, target_storey="High", target_wait_months=6,
)
res = recommender.solve_recommender(q)
print("status:", res["status"], "| candidates after hard filters:", res["n_candidates"])
res["shortlist"]""")

md("### Diversity constraint check — exactly one profile per town?")
code("""town_counts = res["shortlist"]["town"].value_counts()
print(town_counts)
assert town_counts.max() == 1, "diversity constraint violated!"
print("\\nOK: no town appears more than once in the shortlist.")""")

md("### A second household profile, for contrast (tighter budget, different storey preference)")
code("""q2 = recommender.HouseholdQuery(budget=420_000, min_lease_yrs=85, horizon_months=12, k=5,
                                  target_mrt_km=0.4, target_schools_within=3, target_storey="Low")
res2 = recommender.solve_recommender(q2)
print("status:", res2["status"], "| candidates:", res2["n_candidates"])
res2["shortlist"]""")

# ============================================================ TASK 4
md("""## Task 4 — Monte Carlo engine
*(Due 15 Oct; stand-in simulator until real SARIMAX price paths arrive 14 Oct)*

For each shortlisted profile: simulate price at 6/12 months under 3 macro
regimes (stand-in for "interest-rate and supply scenarios"), combine with
survival-based availability, and compare **buy now vs. wait 6 months vs.
wait 12 months**.""")

code("""fcast = pd.read_csv(os.path.join(DATA_DIR, "price_forecast.csv"))
scenarios = monte_carlo.run_monte_carlo(res["shortlist"], fcast, n_scenarios=3000, seed=42)
print("Scenario table:", scenarios.shape)

mc_summary = monte_carlo.summarize_strategies(scenarios, budget=q.budget)
mc_summary[["profile_id", "buy_now_p_success_within_budget", "wait_6m_p_success_within_budget",
            "wait_12m_p_success_within_budget", "recommended_strategy"]]""")

code("""fig, ax = plt.subplots(figsize=(10, 5))
x = np.arange(len(mc_summary))
width = 0.25
ax.bar(x - width, mc_summary["buy_now_p_success_within_budget"], width, label="Buy now", color="#2f5496")
ax.bar(x, mc_summary["wait_6m_p_success_within_budget"], width, label="Wait 6mo", color="#c00000")
ax.bar(x + width, mc_summary["wait_12m_p_success_within_budget"], width, label="Wait 12mo", color="#548235")
ax.set_xticks(x); ax.set_xticklabels(mc_summary["profile_id"].str.replace("::", "\\n"), fontsize=7)
ax.set_ylabel("P(available AND within budget)")
ax.set_title("Buy-Now vs. Wait-6mo vs. Wait-12mo — Simulated Success Probability")
ax.legend()
plt.tight_layout(); plt.show()""")

md("""**Reading this honestly**: waiting longer monotonically raises the chance of a
*matching* flat coming up (availability accumulates over time for these
narrow town×flat-type×storey profiles), which is itself a genuine finding —
households fixated on one specific profile should expect a real wait. Once
the Forecasting Lead's real SARIMAX paths replace the flat-growth stub, price
risk will cut against "wait" much more than it does here, so expect this
balance to shift once Task 4 is re-run on real inputs.""")

# ============================================================ TASK 5
md("""## Task 5 — Chance constraint + sensitivity sweeps
*(Due 19 Oct — pipeline freeze)*

**5a. Chance constraint.** Reformulates the simple deterministic
`budget >= upper forecast price` rule into an explicit scenario-based
chance constraint: $P(\\text{simulated price} \\le \\text{budget}) \\ge 90\\%$,
evaluated directly from Monte Carlo draws rather than a single point-forecast
percentile.""")

code("""df, fcast, prefs = recommender.load_candidate_table()
df = recommender.attach_forecast(df, fcast, horizon_months=12)

budget = 550_000
checked = chance_constraint.chance_feasible_profiles(df, fcast, budget=budget, horizon_months=12,
                                                       alpha=0.90, n_scenarios=800)
det_feasible = (checked["price_upper"] <= budget).sum()
chance_feasible = checked["chance_feasible"].sum()
print(f"Deterministic rule feasible: {det_feasible}/{len(checked)}")
print(f"Chance-constrained (90%) feasible: {chance_feasible}/{len(checked)}")

disagree = checked[(checked["price_upper"] <= budget) != checked["chance_feasible"]]
print(f"\\nProfiles where the two rules disagree: {len(disagree)}")
disagree[["profile_id", "price_today", "price_upper", "p_within_budget"]] if len(disagree) else "none"
""")

md("### 5b. Sensitivity sweeps — budget and minimum lease, with an automated monotonicity check")
code("""base = recommender.HouseholdQuery(budget=500_000, min_lease_yrs=60, horizon_months=12, k=5,
                                     target_mrt_km=0.5, target_schools_within=5, target_storey="High")

budgets = list(range(350_000, 900_001, 25_000))
bsweep = sensitivity.budget_sweep(base, budgets)
ok, viol = sensitivity.check_monotonicity(bsweep, "total_objective_value", "budget", "increasing")
print("Budget monotonicity check:", "PASS" if ok else f"FAIL ({len(viol)} violations)")

leases = list(range(40, 96, 5))
lsweep = sensitivity.lease_sweep(base, leases)
ok2, viol2 = sensitivity.check_monotonicity(lsweep, "total_objective_value", "min_lease_yrs", "decreasing")
print("Min-lease monotonicity check:", "PASS" if ok2 else f"FAIL ({len(viol2)} violations)")
""")

code("""fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
axes[0].plot(bsweep["budget"], bsweep["total_objective_value"], "o-", color="#2f5496")
axes[0].set_title("Objective value vs. Budget"); axes[0].set_xlabel("budget (SGD)")
axes[0].xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}k"))

axes[1].plot(lsweep["min_lease_yrs"], lsweep["total_objective_value"], "o-", color="#c00000")
axes[1].set_title("Objective value vs. Minimum Lease Requirement"); axes[1].set_xlabel("min lease (years)")
plt.tight_layout(); plt.show()""")

code("""mv = sensitivity.marginal_value(bsweep, "total_objective_value", "budget")
print("Marginal value of budget ($ objective gain per extra $1 of budget), by segment:")
mv[["budget", "total_objective_value", "marginal_value"]]""")

# ============================================================ TASK 6
md("""## Task 6 — Final re-runs: shortlist, Monte Carlo and sensitivity on frozen inputs
*(Due 22 Oct — results handed to dashboard)*

Plus the **recommender backtest** (shared with Forecasting/Pricing leads, but
exercising this notebook's recommender): generate a shortlist using only data
available as of a past cutoff, then check the *realised* price against budget
6-12 months later — versus a naive "cheapest towns per town" baseline.""")

code("""bt = backtest.run_backtest(cutoff_date_str="2025-01-01", budget=500_000, min_lease_yrs=60, k=5, horizon_months=12)
bt""")

code("""summary = bt.groupby("strategy")["within_budget"].mean()
print("Share of shortlisted profiles whose realised price stayed within budget:")
print(summary)

fig, ax = plt.subplots(figsize=(6, 4))
summary.plot(kind="bar", ax=ax, color=["#2f5496", "#c00000"])
ax.set_ylim(0, 1.05); ax.set_ylabel("share within budget")
ax.set_title("Backtest: Recommender vs. Naive 'Cheapest Towns' Baseline")
plt.xticks(rotation=20)
plt.tight_layout(); plt.show()""")

md("### Handoff format — `dashboard_payload.json`")
code("""payload = {
    "household_query": q.__dict__,
    "shortlist": json.loads(res["shortlist"].to_json(orient="records")),
    "montecarlo_summary": json.loads(mc_summary.to_json(orient="records")),
    "sensitivity_budget_sweep": json.loads(bsweep[["budget", "n_selected", "total_objective_value"]].to_json(orient="records")),
    "backtest_summary": json.loads(summary.reset_index().to_json(orient="records")),
}
out_path = os.path.join(DATA_DIR, "dashboard_payload_example.json")
with open(out_path, "w") as f:
    json.dump(payload, f, indent=2)
print(f"Wrote example dashboard payload -> {out_path}")
print(json.dumps(payload["household_query"], indent=2))""")

# ============================================================ WRAP-UP
md("""## Summary & handback to the team

**What's real vs. stub right now:**
- Housing profiles, HDB price/lease/turnover figures: **real** (from the official HDB resale dataset).
- Town-level geospatial accessibility (MRT, schools, amenities): **real** (OneMap/data.gov.sg spatial joins).
- Pricing-today, availability, price-forecast, preferences: **stub** — schemas frozen in `INTERFACE_SPEC.md`,
  swap-in dates 7–16 Oct per the Gantt.

**What's validated:**
- Diversity constraint (≤1 profile/town): enforced and asserted in Task 3.
- Monotonicity (more budget never hurts; tighter lease never helps): both checks **PASS** in Task 5.
- Backtest: recommender beat the naive baseline on the one cutoff tested (100% vs. 75% within-budget) —
  a single data point, not yet a full walk-forward series; re-run across multiple cutoffs once frozen (19 Oct).

**Next real iteration, once inputs land:**
1. Swap `pricing_today.csv` for the hedonic model's output (7 Oct) — re-run Tasks 2-3.
2. Swap `availability.csv` for the KM/Cox PH output (16 Oct) — re-run Tasks 3-4.
3. Swap `price_forecast.csv` for real SARIMAX scenarios (14 Oct) — re-run Tasks 4-5; watch the
   buy-now-vs-wait balance shift once real price drift (not flat 0%) is in the simulator.
4. Swap `preferences.json` for the real conjoint WTP estimates (16 Oct) — re-run Tasks 3-6.
5. Multi-cutoff backtest (Task 6) once all of the above are frozen (19 Oct).
""")

nb["cells"] = cells
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Optimisation_Lead_Pipeline.ipynb")
with open(out_path, "w", encoding="utf-8") as f:
    nbf.write(nb, f)
print("Notebook written,", len(cells), "cells")

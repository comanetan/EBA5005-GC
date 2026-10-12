# Daniel's Optimisation / Prescription pipeline

The recommender: given a household's budget, requirements and preferences, returns a
short, ranked, characteristically diverse shortlist of housing profiles — plus two
working interactive tools to explore it.

## Start here

- **[INTERFACE_SPEC.md](INTERFACE_SPEC.md)** — the exact file formats this pipeline
  expects from Pricing & Availability, Forecasting and Preference (and what it
  currently stubs in their place). Read the `v2 UPDATE` box at the top first — the
  shared join key (`profile_id`) and schemas have moved since the original 1 Oct spec.
- **[OPTIMISER_METHODOLOGY_REPORT.md](OPTIMISER_METHODOLOGY_REPORT.md)** — every
  technique used, its source in the course syllabus, and how each was validated
  (worked-example reproduction, backtests, significance tests). This is the
  citation trail; cross-check it rather than the code if you need slide numbers.
- **[OPTIMISER_USER_GUIDE.md](OPTIMISER_USER_GUIDE.md)** — how to use the interactive
  calculator.

## Raw/interim data

This pipeline reads the shared `data/raw/` and `data/interim/` at the repo root (resale
transactions, HDB property info, schools, CHAS clinics, hawker centres, parks, MRT exits,
`mrt_station_openings.csv`), plus `data/raw/daniel_add/` and `data/interim/daniel_add/`
for sources that pipeline needed but weren't already shared (carpark info, flood-prone
areas, bus stops, planned rail, community clubs, childcare, polyclinics — see the README
in each `daniel_add/` folder for exactly what and why).

**Partially fixed, one layer of the limitation remains**: every script's `ROOT`/`GEO`/
`PROC`/`DATA_DIR` constants (2026-10-12) are now derived from the script's own file
location (`os.path.dirname(os.path.abspath(__file__))`-style), not hardcoded to the
author's machine/username — portable in that sense. What's NOT yet bridged: they still
expect the author's *original* project layout (a `Project/` folder one level above
`notebooks/optimization_lead/`, with `Project/data/geospatial/`, `Project/data/processed/`
and root-level raw CSVs named exactly as on the author's machine) rather than *this
repo's* own `data/raw/` + `data/interim/` layout (different folder names, several
files renamed — see `data/raw/daniel_add/README.md`). Cloning just this branch and
running `rebuild_v2.py` still won't work out of the box yet for that reason — the
remaining fix is remapping these scripts onto this repo's own `data/` layout, not just
making the paths relative, and hasn't been done (bigger, riskier change, deferred
rather than rushed). Message me if you want this finished.

## Real data from the other leads

`pricing_today.csv`, `availability.csv` and `price_forecast_live.csv` under `data/` are
now REAL — crosswalked from the Pricing & Availability Lead's `main` branch and the
Forecasting Lead's `forecasting` branch (profile_crosswalk.py, pricing_availability_adapter.py,
forecasting_adapter.py). 96.2% of profiles have real pricing/availability; forecasting
real coverage is 4-ROOM only (their model's own stated scope) — see `data/README.md`
and `OPTIMISER_METHODOLOGY_REPORT.md` §10 for the full methodology, what was found and
fixed (a look-ahead-bias risk in the backtest, and a hedonic-basis mismatch), and
exactly what's still needed from the other leads to close the remaining gaps.

## Running it

```bash
pip install -r requirements.txt   # pulp, pandas, numpy, statsmodels, scikit-learn, osmnx, networkx, fastapi
python rebuild_v2.py              # full pipeline: block accessibility -> profiles -> hedonic -> backtest
python recommender_v2.py          # one example household, printed to console
```

Generated data files (`block_accessibility.csv`, `housing_profiles_v2_full.csv`,
`market_wtp_coefficients.json`, the walking-network graphs, geocoding caches, etc.)
are **not** committed here — they're multi-hundred-MB in places (the walk-network
graphs alone are >500MB) and fully regenerable by `rebuild_v2.py` against the raw
datasets already in this repo's `data/raw/`. Message me if you want a copy of the
generated outputs directly rather than re-running the pipeline.

## Web app (the real solver, live)

```bash
cd webapp/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000` — calls `recommender_v2.solve()` / `solve_preemptive()`
directly (not a client-side approximation), with a live profile search, a Pareto
"trade-off frontier" tab, and both goal-programming modes. See
[webapp/README.md](webapp/README.md) for the full endpoint list.

## Key files

| File | What it is |
|---|---|
| `recommender_v2.py` | The production 0-1 IP solver — `solve()` (weighted-sum) and `solve_preemptive()` (literal lexicographic GP) |
| `hedonic_value.py`, `housing_profiles_v2.py` | Interim pricing model and profile construction |
| `block_accessibility.py` | Block-level feature pipeline (MRT/school/amenity distances, carpark, flood-prone flag, expressway, job-node distance) |
| `empirical_bands.py`, `monte_carlo.py`, `sensitivity_v2.py`, `chance_constraint.py` | Forecast bands, simulation, sensitivity, scenario-based chance constraint |
| `technique_comparison.py` | Standalone experiments: EB shrinkage, availability distribution, Pareto frontier, LP relaxation, GA benchmark |
| `backtest_v2.py` | Walk-forward historical validation, incl. diversity scoring and confidence intervals |
| `multigen_profiles.py` | Separate MULTI-GENERATION flat-type table (too thin for the main pipeline) |
| `rebuild_v2.py` | Re-runs the full chain in dependency order after any upstream change |

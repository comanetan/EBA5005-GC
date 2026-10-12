# SG HomeFit Optimiser — FastAPI + web frontend

A real full-stack version of the Claude-Artifact calculator. The difference that matters: the **Final Recommender tab now calls `recommender_v2.solve()` directly** — the project's actual PuLP 0-1 Integer Program — instead of a client-side brute-force approximation over 8–12 sample rows. Search queries all **712 real profiles** from `housing_profiles_v2_full.csv` with no size cap.

## Run it

```bash
cd webapp/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Then open **http://localhost:8000** — the backend serves the frontend too, so there's nothing else to start.

## What's real vs. what's not

| | Artifact (claude.ai) | This webapp |
|---|---|---|
| Final Recommender solver | JS brute-force over ≤25 candidates | **The real `recommender_v2.solve()` PuLP MIP**, over all eligible profiles |
| Profile search | 712 profiles embedded in the page | **Live query** against the same CSV the pipeline uses |
| Viewing-Time (LP) / Stretch-Budget (GP) | Validated JS, same algorithm | **Identical algorithm, ported to Python**, served by the API |
| Market rates (GP tab defaults) | Hardcoded | **Fetched live** from `market_wtp_coefficients.json` via `/api/meta` |
| Runs where | Anyone with the link, no setup | Your machine, needs Python + the project's data files |

## Architecture

```
webapp/
  backend/
    main.py            FastAPI app — imports recommender_v2.py directly from
                        ../.. (the optimization_lead folder), reads
                        housing_profiles_v2_full.csv and market_wtp_coefficients.json
    requirements.txt
  frontend/
    index.html          Single-file UI (same look as the Artifact version),
                         calls the API via fetch() — no build step
```

### Endpoints

| Route | Method | What it does |
|---|---|---|
| `/api/meta` | GET | Towns, flat types, profile count, live market rates |
| `/api/profiles/search` | GET | Filtered search over all 712 real profiles |
| `/api/recommend` | POST | **Calls the real solver** — `mode: "weighted"` (default) uses `recommender_v2.solve()`; `mode: "preemptive"` uses `recommender_v2.solve_preemptive()` (literal lexicographic GP, a user-orderable priority list); an optional `chance_alpha` swaps the default empirical growth-band budget rule for the scenario-based Monte Carlo chance constraint |
| `/api/pareto` | POST | **Epsilon-constraint Pareto frontier** — `technique_comparison.solve_pareto_point()` traced across a grid of allowed deviation, live |
| `/api/lp/viewing-time` | POST | Corner-point LP + shadow price / reduced cost |
| `/api/gp/stretch-budget` | POST | Preemptive sequential goal programming |

Every solve above defaults to the empirical growth-band budget rule computed once at startup (`EMPIRICAL_BANDS` in `main.py`) — `OPTIMISER_METHODOLOGY_REPORT.md` §6/§7.4 is why that's the default instead of the stub forecast band.

### Swapping in a live database later

`query_profiles()` in `main.py` currently reads an in-memory `pandas.DataFrame` loaded from the CSV at startup. Every caller (the search endpoint, and indirectly the recommender) only depends on that function's return shape — swap its body for a real database/warehouse query and nothing downstream changes. The comment directly above it in the source marks this.

## Limitations

- No auth, no rate limiting — this is a local dev tool, not deployed anywhere.
- `/api/recommend` reads `price_forecast.csv` and `hdb_rental_town_flattype_month.csv` the same way the notebook pipeline does; if those files are stale, re-run `rebuild_v2.py` first (see the optimization_lead folder's own docs).
- CORS is wide open (`allow_origins=["*"]`) for local convenience — tighten this before putting it anywhere public.

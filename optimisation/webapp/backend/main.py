# -*- coding: utf-8 -*-
"""
SG HomeFit Optimiser — FastAPI backend.

Serves the real project pipeline instead of the client-side approximation
the Claude-Artifact version used: /api/recommend calls recommender_v2.solve()
directly (the actual PuLP 0-1 MIP, not a JS brute-force stand-in), profile
search reads the real 712-row housing_profiles_v2_full.csv, and the stretch-
budget defaults come from the project's own market_wtp_coefficients.json.

Run:
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000
Then open http://localhost:8000 (serves the frontend too).
"""
import itertools
import json
import os
import sys
from typing import List, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
OPT_LEAD = os.path.dirname(os.path.dirname(HERE))  # .../optimization_lead
DATA = os.path.join(OPT_LEAD, "data")
FRONTEND = os.path.join(os.path.dirname(HERE), "frontend")
sys.path.insert(0, OPT_LEAD)

import recommender_v2 as rv2  # noqa: E402  (the project's real solver)
import empirical_bands as eb_mod  # noqa: E402
import block_analysis as ba  # noqa: E402
from technique_comparison import solve_pareto_point  # noqa: E402

app = FastAPI(title="SG HomeFit Optimiser API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PROFILES_DF = pd.read_csv(os.path.join(DATA, "housing_profiles_v2_full.csv"))
MARKET_RATES = json.load(open(os.path.join(DATA, "market_wtp_coefficients.json")))["log_points_per_km"]
REF_PRICE = 550_000  # reference price used to convert log-point rates into $ terms, same as the Artifact version

# Computed once at startup: the empirical, granularity-aware 90% price-growth band
# (technique_comparison.py's validated conclusion: this beats the stub forecast's flat
# band on reliability -- 98.8% vs 94.2% within-budget 12m later in the walk-forward
# backtest) -- used as the DEFAULT budget bound for every /api/recommend and /api/pareto
# call below, unless a caller opts into the scenario chance-constraint instead.
_TX_ALL = ba.load_transactions_with_access()
_TX_ALL = _TX_ALL[_TX_ALL["flat_type"] != "MULTI-GENERATION"]
EMPIRICAL_BANDS = eb_mod.empirical_growth_bands(_TX_ALL, horizon=12)


# =====================================================================================
# /api/meta — dropdown options + the project's own market rates, for the GP tab's defaults
# =====================================================================================
@app.get("/api/meta")
def meta():
    mrt_rate_per_km = REF_PRICE * (np.exp(-MARKET_RATES["dist_mrt_exit_km"]) - 1)
    lease_rate_per_year = 3000  # not in the hedonic (lease is a hard floor, not priced) -- carried from preferences.json's stub
    return {
        "towns": sorted(PROFILES_DF["town"].str.title().unique().tolist()),
        "flat_types": sorted(PROFILES_DF["flat_type"].unique().tolist()),
        "n_profiles": len(PROFILES_DF),
        "market_rate_mrt_per_km": round(mrt_rate_per_km, -2),
        "market_rate_lease_per_year": lease_rate_per_year,
        "as_of": MARKET_RATES if False else None,  # placeholder: expose the raw hedonic coefficients if a client wants them
    }


# =====================================================================================
# /api/profiles/search — real profile search (town, flat type, price, MRT, lease, liquidity)
# TODAY: queries the in-memory DataFrame loaded from housing_profiles_v2_full.csv.
# FUTURE: swap PROFILES_DF for a real database/warehouse query -- every caller below
# only depends on this function's return shape, not on where the rows came from.
# =====================================================================================
def query_profiles(town: Optional[str], flat_type: Optional[str], max_price: float,
                    max_mrt_km: float, min_lease: float, min_liquidity: float, limit: int = 40,
                    avoid_flood_prone: bool = False, require_carpark: bool = False,
                    max_secondary_school_km: Optional[float] = None, max_job_node_km: Optional[float] = None):
    d = PROFILES_DF
    if town:
        d = d[d["town"].str.upper() == town.upper()]
    if flat_type:
        d = d[d["flat_type"] == flat_type]
    d = d[(d["median_price"] <= max_price) & (d["dist_mrt_exit_km_p50"] <= max_mrt_km) &
          (d["median_remaining_lease"] >= min_lease) & (d["txn_count_12m"] >= min_liquidity)]
    # "share_*" columns are the fraction of a profile's underlying sales that are near/have the
    # amenity (same convention as essentials_score) -- >=0.5 reads as "true for most of this profile".
    if avoid_flood_prone and "share_near_flood_prone_area" in d.columns:
        d = d[d["share_near_flood_prone_area"] < 0.5]
    if require_carpark and "share_has_carpark_400m" in d.columns:
        d = d[d["share_has_carpark_400m"] >= 0.5]
    if max_secondary_school_km is not None and "dist_secondary_school_km_p50" in d.columns:
        d = d[d["dist_secondary_school_km_p50"] <= max_secondary_school_km]
    if max_job_node_km is not None and "dist_nearest_job_node_km_p50" in d.columns:
        d = d[d["dist_nearest_job_node_km_p50"] <= max_job_node_km]
    d = d.sort_values("median_price").head(limit)
    return [{
        "id": r.profile_id, "town": r.town.title(), "flat_type": r.flat_type, "lease_band": r.lease_band,
        "storey_band": r.storey_band, "mrt_band": r.mrt_band, "price": round(r.median_price),
        "mrt_km": round(r.dist_mrt_exit_km_p50, 2),
        "secondary_school_km": round(getattr(r, "dist_secondary_school_km_p50", float("nan")), 2),
        "has_carpark": bool(getattr(r, "share_has_carpark_400m", 0) >= 0.5),
        "near_flood_prone": bool(getattr(r, "share_near_flood_prone_area", 0) >= 0.5),
        "nearest_job_node": getattr(r, "nearest_job_node", None),
        "job_node_km": round(getattr(r, "dist_nearest_job_node_km_p50", float("nan")), 2),
        "lease": round(r.median_remaining_lease, 1), "liquidity_12m": int(r.txn_count_12m),
    } for r in d.itertuples()]


@app.get("/api/profiles/search")
def profiles_search(town: Optional[str] = None, flat_type: Optional[str] = None,
                     max_price: float = 10_000_000, max_mrt_km: float = 10.0,
                     min_lease: float = 0, min_liquidity: float = 0, limit: int = 40,
                     avoid_flood_prone: bool = False, require_carpark: bool = False,
                     max_secondary_school_km: Optional[float] = None, max_job_node_km: Optional[float] = None):
    return {"results": query_profiles(town, flat_type, max_price, max_mrt_km, min_lease, min_liquidity, limit,
                                       avoid_flood_prone, require_carpark, max_secondary_school_km, max_job_node_km)}


# =====================================================================================
# /api/recommend — the real thing: recommender_v2.HouseholdQuery2 + rv2.solve(),
# the project's actual PuLP 0-1 MIP with the weighted goal-programming objective.
# =====================================================================================
class RecommendRequest(BaseModel):
    budget: float
    min_lease_yrs: float = 60
    target_mrt_km: float = 0.5
    k: int = 3
    mrt_weight: float = 1.0
    needs_primary_school: bool = False
    target_storey: str = "Mid"
    flat_types: Optional[List[str]] = None
    mode: str = "weighted"               # "weighted" (default, Archimedean GP) | "preemptive" (literal lexicographic GP)
    priority: Optional[List[str]] = None  # preemptive only: ordered dev_ column names, highest priority first
    chance_alpha: Optional[float] = None  # None (default) = empirical growth-band budget rule (validated best);
                                           # 0 < alpha <= 1 = scenario-based chance constraint instead (backtested alternative)
    target_expressway_km: Optional[float] = None  # None (default) = goal inactive; else "at least this far
                                                    # from an expressway" -- priced at the real hedonic rate
                                                    # (market_wtp_coefficients.json, verified significant & correctly signed)


@app.post("/api/recommend")
def recommend(req: RecommendRequest):
    try:
        query = rv2.HouseholdQuery2(
            budget=req.budget, min_lease_yrs=req.min_lease_yrs, k=req.k, target_mrt_km=req.target_mrt_km,
            multipliers={"mrt": req.mrt_weight}, needs_primary_school=req.needs_primary_school,
            target_storey=req.target_storey, flat_types=req.flat_types, target_expressway_km=req.target_expressway_km,
            name="api",
        )
        if req.mode == "preemptive":
            result = rv2.solve_preemptive(query, priority=req.priority, chance_alpha=req.chance_alpha,
                                           upper_factors=EMPIRICAL_BANDS)
        else:
            result = rv2.solve(query, chance_alpha=req.chance_alpha, upper_factors=EMPIRICAL_BANDS)
    except Exception as e:
        raise HTTPException(500, f"solver error: {e}")

    cols = ["rank", "profile_id", "town", "flat_type", "lease_band", "storey_band", "mrt_band", "price_today", "price_upper",
            "median_remaining_lease", "dist_mrt_exit_km_p50", "essentials_score", "expected_wait_months",
            "p_no_matching_sale_3m", "surplus", "dev_mrt", "dev_school", "dev_storey", "dev_wait", "dev_expressway",
            "goal_deviation_total", "net_objective_value"]
    sl = result["shortlist"]
    shortlist = sl[[c for c in cols if c in sl.columns]].round(3).to_dict(orient="records") if len(sl) else []
    out = {
        "status": result["status"], "n_candidates": result["n_candidates"],
        "n_feasible_towns": result.get("n_feasible_towns"), "k_satisfied": result.get("k_satisfied"),
        "objective": None if pd.isna(result["objective"]) else round(result["objective"], 2),
        "shortlist": shortlist, "mode": req.mode,
    }
    if req.mode == "preemptive":
        out["priority_order"] = result.get("priority_order")
        out["stage_values"] = {k: round(v, 2) for k, v in result.get("stage_values", {}).items()}
    return out


# =====================================================================================
# /api/pareto — the epsilon-constraint Pareto frontier (technique_comparison.py's
# solve_pareto_point), as a selectable live mode instead of a standalone validation
# script: traces surplus achievable at each ALLOWED level of total goal-deviation
# compromise, rather than the single point the weighted-sum objective returns.
# =====================================================================================
class ParetoRequest(BaseModel):
    budget: float
    min_lease_yrs: float = 60
    target_mrt_km: float = 0.5
    k: int = 5
    mrt_weight: float = 1.0
    needs_primary_school: bool = False
    target_storey: str = "Mid"
    flat_types: Optional[List[str]] = None
    n_points: int = 8


PICK_COLS = ["profile_id", "town", "flat_type", "lease_band", "storey_band", "mrt_band", "price_today",
             "shrunk_value_gap", "preference_tilt", "surplus",
             "dev_mrt", "dev_school", "dev_essentials", "dev_storey", "dev_wait", "dev_expressway",
             "goal_deviation_total", "net_objective_value"]


def _serialize_picks(sl):
    cols = [c for c in PICK_COLS if c in sl.columns]
    return sl[cols].round(2).to_dict(orient="records") if len(sl) else []


@app.post("/api/pareto")
def pareto(req: ParetoRequest):
    query = rv2.HouseholdQuery2(
        budget=req.budget, min_lease_yrs=req.min_lease_yrs, k=req.k, target_mrt_km=req.target_mrt_km,
        multipliers={"mrt": req.mrt_weight}, needs_primary_school=req.needs_primary_school,
        target_storey=req.target_storey, flat_types=req.flat_types, name="api-pareto",
    )
    current = rv2.solve(query, upper_factors=EMPIRICAL_BANDS)
    if current["status"] != "Optimal" or current["n_candidates"] == 0:
        raise HTTPException(400, "No feasible candidates for this household (try a larger budget or fewer filters).")

    uncapped = solve_pareto_point(query, eps=10**9, upper_factors=EMPIRICAL_BANDS)
    max_dev = uncapped["total_deviation"] if uncapped else 0
    eps_grid = sorted(set([0] + [round(v, -2) for v in np.linspace(0, max_dev, req.n_points)]))
    frontier = []
    for e in eps_grid:
        pt = solve_pareto_point(query, eps=e, upper_factors=EMPIRICAL_BANDS)
        if pt is None:
            continue
        frontier.append({
            "eps_max_deviation": round(pt["eps"], 2), "status": pt["status"],
            "total_surplus": None if pd.isna(pt["total_surplus"]) else round(pt["total_surplus"], 2),
            "total_deviation": None if pd.isna(pt["total_deviation"]) else round(pt["total_deviation"], 2),
            "picks": _serialize_picks(pt["shortlist"]),
        })
    sl = current["shortlist"]
    return {
        "current_weighted_sum": {
            "total_surplus": round(sl["surplus"].sum(), 2),
            "total_deviation": round(sl["goal_deviation_total"].sum(), 2),
            "net_objective": round(current["objective"], 2),
            "picks": _serialize_picks(sl),
        },
        "frontier": frontier,
    }


# =====================================================================================
# /api/lp/viewing-time — corner-point LP solve + shadow price / reduced cost,
# a direct Python port of the (already-validated) Artifact version's engine.
# =====================================================================================
class LPRequest(BaseModel):
    valA: float; costA: float; valB: float; costB: float
    capA: float; capB: float          # liquidity caps (hrs/month)
    hrsPerA: float; hrsPerB: float; hrsBudget: float
    slotsPerA: float; slotsPerB: float; slotsCap: float


def _solve_2x2(a1, b1, r1, a2, b2, r2):
    det = a1 * b2 - a2 * b1
    if abs(det) < 1e-9:
        return None
    return ((r1 * b2 - r2 * b1) / det, (a1 * r2 - a2 * r1) / det)


@app.post("/api/lp/viewing-time")
def lp_viewing_time(req: LPRequest):
    c1, c2 = req.valA - req.costA, req.valB - req.costB
    cons = [
        {"name": "Liquidity cap A", "a": 1, "b": 0, "rhs": req.capA},
        {"name": "Liquidity cap B", "a": 0, "b": 1, "rhs": req.capB},
        {"name": "Monthly hours budget", "a": req.hrsPerA, "b": req.hrsPerB, "rhs": req.hrsBudget},
        {"name": "Agent viewing slots", "a": req.slotsPerA, "b": req.slotsPerB, "rhs": req.slotsCap},
    ]
    lines = [{"name": "H_A=0", "a": 1, "b": 0, "rhs": 0}, {"name": "H_B=0", "a": 0, "b": 1, "rhs": 0}] + cons
    corners = []
    for l1, l2 in itertools.combinations(lines, 2):
        p = _solve_2x2(l1["a"], l1["b"], l1["rhs"], l2["a"], l2["b"], l2["rhs"])
        if p:
            corners.append({"x": p[0], "y": p[1], "tag": f"{l1['name']} ∩ {l2['name']}"})
    EPS = 1e-6
    feasible = [p for p in corners if p["x"] >= -EPS and p["y"] >= -EPS and
                all(c["a"] * p["x"] + c["b"] * p["y"] <= c["rhs"] + 1e-4 for c in cons)]
    for p in feasible:
        p["z"] = c1 * p["x"] + c2 * p["y"]
    feasible.sort(key=lambda p: -p["z"])
    if not feasible:
        return {"corners": [], "best": None, "sensitivity": []}
    best = feasible[0]

    binding = [c for c in cons if abs(c["a"] * best["x"] + c["b"] * best["y"] - c["rhs"]) < 1e-3]
    sensitivity = []
    if len(binding) >= 2:
        b1, b2 = binding[0], binding[1]
        det = b1["a"] * b2["b"] - b2["a"] * b1["b"]
        y1 = y2 = 0.0
        if abs(det) > 1e-9:
            y1 = (c1 * b2["b"] - c2 * b2["a"]) / det
            y2 = (c2 * b1["a"] - c1 * b1["b"]) / det
        shadow = {b1["name"]: y1, b2["name"]: y2}
        for c in cons:
            is_binding = c in binding
            sensitivity.append({"kind": "constraint", "name": c["name"],
                                "value": round(shadow.get(c["name"], 0.0), 2), "note": "binding" if is_binding else "slack"})
        for name, c_, col, val in [("H_A", c1, (b1["a"], b2["a"]), best["x"]), ("H_B", c2, (b1["b"], b2["b"]), best["y"])]:
            implied = y1 * col[0] + y2 * col[1]
            reduced = c_ - implied
            sensitivity.append({"kind": "variable", "name": name, "value": 0.0 if val > 1e-6 else round(reduced, 2),
                                "note": "in solution" if val > 1e-6 else "reduced cost"})
    return {"corners": feasible, "best": best, "sensitivity": sensitivity}


# =====================================================================================
# /api/gp/stretch-budget — preemptive sequential GP, a direct port of the Artifact's engine.
# =====================================================================================
class GPRequest(BaseModel):
    a: float; b: float; C: float; t1: float; t2: float
    priority: int = 1  # 1 = goal 1 first, 2 = goal 2 first


@app.post("/api/gp/stretch-budget")
def gp_stretch_budget(req: GPRequest):
    first_is_1 = req.priority == 1
    coef_first, coef_second = (req.a, req.b) if first_is_1 else (req.b, req.a)
    target_first, target_second = (req.t1, req.t2) if first_is_1 else (req.t2, req.t1)

    max_first = req.C / coef_first if coef_first else 0
    x_first = min(target_first, max_first)
    dev_first = max(0.0, target_first - x_first)
    left = max(0.0, req.C - coef_first * x_first)

    max_second = left / coef_second if coef_second else 0
    x_second = min(target_second, max_second)
    dev_second = max(0.0, target_second - x_second)

    X1, X2 = (x_first, x_second) if first_is_1 else (x_second, x_first)
    d1, d2 = (dev_first, dev_second) if first_is_1 else (dev_second, dev_first)
    return {"X1": round(X1, 3), "X2": round(X2, 3), "d1_minus": round(d1, 3), "d2_minus": round(d2, 3),
            "budget_used": round(req.a * X1 + req.b * X2, 2)}


# serve the frontend (index.html + assets) at the root
if os.path.isdir(FRONTEND):
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")

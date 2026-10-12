# -*- coding: utf-8 -*-
"""
Task 3: the recommender itself -- mathematical programming (hard constraints,
diversity, top-k) blended with goal programming (dollar-weighted soft-goal
deviations), per the FINAL proposal's Prescribe-stage table:

  Mathematical Programming: "Selects a diverse shortlist of k profiles that
    maximises WTP-valued surplus. Hard constraints: budget >= upper forecast
    price, minimum lease, at most one profile per town."
  Goal Programming: "Soft goals (MRT, school, amenities, facilities, storey,
    expected wait) as dollar-weighted deviations from household targets."

Both are solved as ONE binary-selection MIP: the GP deviations are
precomputable constants per (profile, goal) once household targets are
fixed (profiles are a discrete, known candidate set -- unlike classical GP
over continuous resource allocation), so they fold directly into the
objective alongside the hard constraints.
"""
import json
import os

import numpy as np
import pandas as pd
import pulp

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


# ---------------------------------------------------------------------------
# Household query
# ---------------------------------------------------------------------------
class HouseholdQuery:
    def __init__(self, budget, min_lease_yrs=60, horizon_months=12, k=5,
                 target_mrt_km=0.6, target_schools_within=5, target_storey="Mid",
                 target_wait_months=6, target_amenity_count=10,
                 flat_types=None, towns_exclude=None):
        self.budget = budget
        self.min_lease_yrs = min_lease_yrs
        self.horizon_months = horizon_months
        self.k = k
        self.target_mrt_km = target_mrt_km
        self.target_schools_within = target_schools_within
        self.target_storey = target_storey
        self.target_wait_months = target_wait_months
        self.target_amenity_count = target_amenity_count
        self.flat_types = flat_types
        self.towns_exclude = towns_exclude or []


STOREY_RANK = {"Low": 0, "Mid": 1, "High": 2}


# ---------------------------------------------------------------------------
# Data assembly: join profiles + pricing + availability + forecast + WTP
# ---------------------------------------------------------------------------
def load_candidate_table():
    profiles = pd.read_csv(os.path.join(DATA_DIR, "housing_profiles.csv"))
    pricing = pd.read_csv(os.path.join(DATA_DIR, "pricing_today.csv"))
    avail = pd.read_csv(os.path.join(DATA_DIR, "availability.csv"))
    fcast = pd.read_csv(os.path.join(DATA_DIR, "price_forecast.csv"))
    with open(os.path.join(DATA_DIR, "preferences.json")) as f:
        prefs = json.load(f)

    df = profiles.merge(pricing[["profile_id", "price_today", "price_today_se"]], on="profile_id", how="inner")
    df = df.merge(avail[["profile_id", "expected_wait_months", "survival_prob_6m", "survival_prob_12m"]],
                   on="profile_id", how="left")
    return df, fcast, prefs


def attach_forecast(df, fcast, horizon_months):
    f = fcast[fcast["horizon_months"] == horizon_months][
        ["town", "flat_type", "growth_factor", "growth_factor_lower", "growth_factor_upper"]]
    df = df.merge(f, on=["town", "flat_type"], how="left")
    df["price_expected"] = df["price_today"] * df["growth_factor"]
    df["price_upper"] = df["price_today"] * df["growth_factor_upper"]
    df["price_lower"] = df["price_today"] * df["growth_factor_lower"]
    return df


def compute_wtp_value(df, prefs):
    w = prefs["wtp_sgd"]
    amenity_count = (df[["hawker_within", "parks_within", "cc_within", "polyclinic_within"]]
                      .fillna(0).sum(axis=1))
    if "supermarkets_within" in df.columns:
        amenity_count = amenity_count + df[["supermarkets_within", "chas_clinics_within", "childcare_within"]].fillna(0).sum(axis=1)
    storey_premium = df["storey_band"].map(w["storey_band_premium"]).fillna(0)
    # mrt value: dollar value of being close to MRT, referenced off a notional 2km "far" baseline
    mrt_value = (2.0 - df["nearest_mrt_km"].clip(upper=2.0)) * w["per_km_closer_to_mrt"]
    school_value = df["schools_within"].fillna(0) * w["per_additional_school_within_1km"]
    lease_value = df["median_remaining_lease"].fillna(0) * w["per_year_remaining_lease"]
    amenity_value = amenity_count * w["per_amenity_count"]
    return mrt_value + school_value + lease_value + storey_premium + amenity_value


def compute_goal_deviations_sgd(df, query: HouseholdQuery, prefs):
    w = prefs["wtp_sgd"]
    dev = pd.DataFrame(index=df.index)
    dev["mrt_dev"] = (df["nearest_mrt_km"] - query.target_mrt_km).clip(lower=0) * w["per_km_closer_to_mrt"]
    dev["school_dev"] = (query.target_schools_within - df["schools_within"].fillna(0)).clip(lower=0) * w["per_additional_school_within_1km"]
    storey_gap = (df["storey_band"].map(STOREY_RANK) - STOREY_RANK[query.target_storey]).clip(upper=0).abs()
    dev["storey_dev"] = storey_gap * (w["storey_band_premium"]["High"] - w["storey_band_premium"]["Low"]) / 2
    dev["wait_dev"] = (df["expected_wait_months"] - query.target_wait_months).clip(lower=0) * 2000  # SGD per extra month waited (documented assumption)
    amenity_count = (df[["hawker_within", "parks_within", "cc_within", "polyclinic_within"]].fillna(0).sum(axis=1))
    dev["amenity_dev"] = (query.target_amenity_count - amenity_count).clip(lower=0) * w["per_amenity_count"]
    dev["total_dev"] = dev.sum(axis=1)
    return dev


# ---------------------------------------------------------------------------
# The MIP
# ---------------------------------------------------------------------------
def solve_recommender(query: HouseholdQuery, verbose=False):
    df, fcast, prefs = load_candidate_table()
    df = attach_forecast(df, fcast, query.horizon_months)
    if query.flat_types:
        df = df[df["flat_type"].isin(query.flat_types)]
    if query.towns_exclude:
        df = df[~df["town"].isin(query.towns_exclude)]
    df = df[df["median_remaining_lease"] >= query.min_lease_yrs].reset_index(drop=True)
    df = df[df["price_upper"] <= query.budget].reset_index(drop=True)  # hard budget feasibility pre-filter

    if df.empty:
        return {"status": "Infeasible (no candidates after hard filters)", "shortlist": pd.DataFrame(),
                "n_candidates": 0, "query": query.__dict__}

    df["wtp_value"] = compute_wtp_value(df, prefs)
    df["wtp_surplus"] = df["wtp_value"] - df["price_today"]
    dev = compute_goal_deviations_sgd(df, query, prefs)
    df["goal_deviation_total"] = dev["total_dev"]
    df["net_objective_value"] = df["wtp_surplus"] - df["goal_deviation_total"]

    ids = df["profile_id"].tolist()
    towns = df["town"].tolist()
    unique_towns = sorted(set(towns))

    prob = pulp.LpProblem("Recommender_MathProg_GoalProg", pulp.LpMaximize)
    x = {i: pulp.LpVariable(f"x_{idx}", cat="Binary") for idx, i in enumerate(ids)}

    obj_coef = dict(zip(ids, df["net_objective_value"]))
    prob += pulp.lpSum(x[i] * obj_coef[i] for i in ids)

    # top-k
    prob += pulp.lpSum(x[i] for i in ids) == min(query.k, len(ids))

    # diversity: at most one profile per town
    for t in unique_towns:
        town_ids = [i for i, tt in zip(ids, towns) if tt == t]
        prob += pulp.lpSum(x[i] for i in town_ids) <= 1

    prob.solve(pulp.PULP_CBC_CMD(msg=1 if verbose else 0))
    status = pulp.LpStatus[prob.status]
    selected = [i for i in ids if x[i].value() and x[i].value() > 0.5]

    result = df[df["profile_id"].isin(selected)].copy()
    result = result.sort_values("net_objective_value", ascending=False)
    result["rank"] = range(1, len(result) + 1)

    cols = ["rank", "profile_id", "town", "flat_type", "storey_band", "price_today",
            "price_upper", "median_remaining_lease", "expected_wait_months",
            "wtp_surplus", "goal_deviation_total", "net_objective_value"]
    return {"status": status, "shortlist": result[cols], "n_candidates": len(df),
            "query": query.__dict__}


if __name__ == "__main__":
    q = HouseholdQuery(budget=550_000, min_lease_yrs=60, horizon_months=12, k=5,
                        target_mrt_km=0.5, target_schools_within=5, target_storey="High",
                        target_wait_months=6)
    res = solve_recommender(q, verbose=False)
    print("status:", res["status"], "| candidates after hard filters:", res["n_candidates"])
    print(res["shortlist"].to_string(index=False))

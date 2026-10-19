# -*- coding: utf-8 -*-
"""
Recommender v2 -- block-informed profiles (town x flat_type x storey x MRT band).

Objective, per profile p (all SGD):
  surplus_p   = shrunk hedonic value gap      (is it cheap for what it offers?)
              + household preference tilt     (does THIS household value its
                                               attributes more/less than the market?)
  deviation_p = sum of dollar-weighted shortfalls vs household goals
                (MRT distance, walkable essentials, primary school within 1km,
                 storey, expected wait -- waiting priced at real HDB rent)
  maximise  sum_p x_p * (surplus_p - deviation_p)

Why "tilt" and not raw attribute value: the hedonic shows the market already
prices MRT proximity (~1%/100m). A household valuing it exactly like the
market gets ZERO surplus from it -- it pays what it's worth. Surplus arises
only where the household's preferences differ from the market's (multiplier
!= 1) or where a profile trades below its attribute-implied value.

Hard constraints (proposal): budget >= upper forecast price (or a 90% chance
constraint), remaining lease >= minimum, <=1 profile per town, exactly k.
Optional household hard filter: worst acceptable MRT band. Optional, OFF by
default: max_per_mrt_band / max_per_flat_type cap repeats on those axes too,
for a shortlist that's diverse on more than just town.
"""
import json
import os

import numpy as np
import pandas as pd
import pulp

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ROOT = os.path.dirname(os.path.dirname(HERE))  # .../Project, portable across machines

# 2026-10-20 (OPTIMISER_METHODOLOGY_REPORT.md Sec. 26): polyclinic added here, not just to
# ESSENTIALS -- it passed the same sign+significance test every other tilt attribute here did
# (unlike expressway, a disamenity, which is a GOAL only -- see hedonic_value.py's WTP_ATTRS).
ATTR_COLS = {"mrt": "dist_mrt_exit_km_p50", "hawker": "dist_hawker_km_p50",
             "supermarket": "dist_supermarket_km_p50", "clinic": "dist_chas_clinic_km_p50",
             "park": "dist_park_km_p50", "polyclinic": "dist_polyclinic_km_p50"}
ATTR_BETA_KEY = {"mrt": "dist_mrt_exit_km", "hawker": "dist_hawker_km", "supermarket": "dist_supermarket_km",
                 "clinic": "dist_chas_clinic_km", "park": "dist_park_km", "polyclinic": "dist_polyclinic_km"}
BAND_RANK = {"Near": 0, "Mid": 1, "Far": 2}
STOREY_RANK = {"Low": 0, "Mid": 1, "High": 2}


class HouseholdQuery2:
    def __init__(self, budget, min_lease_yrs=60, horizon_months=12, k=5,
                 target_mrt_km=0.5, max_mrt_band=None, target_essentials=4.0,
                 needs_primary_school=False, school_goal=None, target_storey="Mid", target_wait_months=6,
                 multipliers=None, flat_types=None, towns_exclude=None, alpha=None,
                 w_school_sgd=None, w_essential_sgd=8_000, storey_step_sgd=15_000, shrink_k=10,
                 max_per_mrt_band=None, max_per_flat_type=None, target_expressway_km=None, name="household"):
        self.__dict__.update(locals())
        self.__dict__.pop("self")
        self.multipliers = {"mrt": 1.0, "hawker": 1.0, "supermarket": 1.0, "clinic": 1.0, "park": 1.0,
                            "polyclinic": 1.0,
                            **(multipliers or {})}
        self.towns_exclude = towns_exclude or []


def preference_overrides_from_file(preferences_path=None, market_path=None, ref_price=550_000):
    """Converts the Preference Lead's real conjoint WTP (preferences.json) into the kwargs
    HouseholdQuery2 already understands, so swapping in their real file needs no code change
    here -- just re-run. Only wired for the fields the CURRENT stub schema defines (wtp_sgd:
    per_km_closer_to_mrt, per_additional_school_within_1km, per_year_remaining_lease,
    storey_band_premium, per_amenity_count) -- if the real deliverable uses different field
    names, extend the `mapped` dict below rather than rewriting the caller.

    mrt multiplier: both sides are $ per km, so household/market is a clean ratio.
    school/essentials/storey: the stub's units don't line up with the market hedonic's tiered
    %-premium (count-based WTP vs tier-based market rate), so these pass through as direct SGD
    overrides (w_school_sgd, w_essential_sgd, storey_step_sgd) instead of a multiplier -- an
    approximation, printed below so it's auditable once the real schema is confirmed.
    """
    preferences_path = preferences_path or os.path.join(DATA, "preferences.json")
    market_path = market_path or os.path.join(DATA, "market_wtp_coefficients.json")
    prefs = json.load(open(preferences_path))
    betas = json.load(open(market_path))["log_points_per_km"]
    wtp = prefs.get("wtp_sgd", {})
    mapped, unmapped = {}, []
    overrides = {"multipliers": {}}

    if "per_km_closer_to_mrt" in wtp and "dist_mrt_exit_km" in betas:
        market_per_km = ref_price * (np.exp(-betas["dist_mrt_exit_km"]) - 1)
        if market_per_km > 0:
            overrides["multipliers"]["mrt"] = wtp["per_km_closer_to_mrt"] / market_per_km
            mapped["mrt multiplier"] = f"{overrides['multipliers']['mrt']:.2f} " \
                                       f"(household ${wtp['per_km_closer_to_mrt']:,.0f}/km vs market ${market_per_km:,.0f}/km @ ref price ${ref_price:,.0f})"

    if "per_amenity_count" in wtp:
        overrides["w_essential_sgd"] = wtp["per_amenity_count"]
        mapped["w_essential_sgd"] = f"${wtp['per_amenity_count']:,.0f}/missing essential (direct pass-through)"

    if "per_additional_school_within_1km" in wtp:
        overrides["w_school_sgd"] = wtp["per_additional_school_within_1km"]
        mapped["w_school_sgd"] = f"${wtp['per_additional_school_within_1km']:,.0f} (APPROX: stub is count-based, " \
                                 f"recommender's school goal is tier-based -- revisit once real schema is confirmed)"

    sbp = wtp.get("storey_band_premium")
    if isinstance(sbp, dict) and {"Low", "Mid", "High"} <= set(sbp):
        step = ((sbp["Mid"] - sbp["Low"]) + (sbp["High"] - sbp["Mid"])) / 2
        overrides["storey_step_sgd"] = step
        mapped["storey_step_sgd"] = f"${step:,.0f}/band (averaged from Low->Mid->High premiums {sbp})"

    for k in ["per_year_remaining_lease"]:
        if k in wtp:
            unmapped.append(f"{k}=${wtp[k]:,.0f} (recommender has no priced lease-preference term yet -- "
                            "lease is a hard floor only; see min_lease_yrs)")

    print("Preference overrides loaded from", preferences_path)
    for k, v in mapped.items():
        print(f"  {k}: {v}")
    if unmapped:
        print("  NOT mapped (no matching recommender term):")
        for u in unmapped:
            print(f"   - {u}")
    return overrides


def load_inputs(profiles=None, live=True):
    """live=True (profiles=None callers -- the actual current recommender/webapp/
    calculator): reads price_forecast_live.csv if it exists (the forecasting_adapter.py
    blend of real 4-ROOM forecasts + stub for every other flat type), else falls back to
    price_forecast.csv. live=False (backtest / multigen / any explicit historical
    `profiles` snapshot): ALWAYS reads price_forecast.csv (stub-only, time-invariant) --
    never the live-enhanced file, which reflects TODAY's real forecast and would leak
    look-ahead information into a historical cutoff."""
    if profiles is None:
        profiles = pd.read_csv(os.path.join(DATA, "housing_profiles_v2_full.csv"))
    betas = json.load(open(os.path.join(DATA, "market_wtp_coefficients.json")))["log_points_per_km"]
    live_path = os.path.join(DATA, "price_forecast_live.csv")
    fcast_path = live_path if (live and os.path.exists(live_path)) else os.path.join(DATA, "price_forecast.csv")
    fcast = pd.read_csv(fcast_path)
    rent = pd.read_csv(os.path.join(ROOT, "data", "processed", "hdb_rental_town_flattype_month.csv"),
                       parse_dates=["month"])
    rent = rent[rent["month"] > rent["month"].max() - pd.DateOffset(months=12)]
    rent["flat_type"] = rent["flat_type"].str.replace("-", " ")
    rent_tf = rent.groupby(["town", "flat_type"])["median_rent"].median().rename("monthly_rent").reset_index()
    return profiles, betas, fcast, rent_tf


def _load_real_pricing():
    """pricing_today.csv -- real output from the Pricing & Availability Lead, converted
    by pricing_availability_adapter.py. None if the file hasn't been produced yet."""
    path = os.path.join(DATA, "pricing_today.csv")
    return pd.read_csv(path) if os.path.exists(path) else None


def _load_real_availability():
    path = os.path.join(DATA, "availability.csv")
    return pd.read_csv(path) if os.path.exists(path) else None


def _load_price_calibration():
    """hedonic_price_calibration.json (build_price_calibration.py) -- recalibrates
    hedonic_value onto price_today's basis via a log-log fit on the overlap. None if not
    built yet (score() falls back to suppressing the bargain signal, the old behaviour)."""
    path = os.path.join(DATA, "hedonic_price_calibration.json")
    return json.load(open(path)) if os.path.exists(path) else None


def availability_stub(profiles, live=True):
    """Arrival rate of MATCHING transactions (the buyer-relevant quantity):
    lambda = sales_12m / 12 per month. Replaces v1's arbitrary '/20 units'
    scaling, which made 'buy now' look implausibly rare.

    If availability.csv (the Pricing & Availability Lead's real Cox-PH-derived output,
    via pricing_availability_adapter.py) exists, its values are used wherever it covers
    a profile; this formula-based stub fills in only the profiles it doesn't cover
    (partial real coverage, not all-or-nothing -- see availability_provenance.csv for
    which profiles got which)."""
    lam = (profiles["txn_count_12m"] / 12).clip(lower=1 / 24)
    stub = pd.DataFrame({"profile_id": profiles["profile_id"],
                         "expected_wait_months": (1 / lam).round(2),
                         "survival_prob_6m": (1 - np.exp(-lam * 6)).round(3),
                         "survival_prob_12m": (1 - np.exp(-lam * 12)).round(3),
                         # shown on every pick: thin profiles can see no matching sale for months
                         "p_no_matching_sale_3m": np.exp(-lam * 3).round(3)})
    real = _load_real_availability() if live else None
    if real is None:
        return stub
    merged = stub.merge(real[["profile_id", "expected_wait_months", "survival_prob_6m", "survival_prob_12m"]],
                        on="profile_id", how="left", suffixes=("_stub", ""))
    for c in ["expected_wait_months", "survival_prob_6m", "survival_prob_12m"]:
        merged[c] = merged[c].fillna(merged[f"{c}_stub"])
    # p_no_matching_sale_3m has no real-data equivalent -- stays stub-derived throughout,
    # but recomputed from whichever expected_wait_months (real or stub) ended up in use
    lam_final = (1 / merged["expected_wait_months"].clip(lower=0.1))
    merged["p_no_matching_sale_3m"] = np.exp(-lam_final * 3).round(3)
    return merged[["profile_id", "expected_wait_months", "survival_prob_6m", "survival_prob_12m",
                   "p_no_matching_sale_3m"]]


def assemble(query, profiles=None, live=None):
    """live: None (default) infers "today, live" iff profiles was not explicitly passed
    (profiles=None) -- the only case where substituting TODAY's real pricing/availability/
    forecast data is temporally valid. Backtest, multigen and any other caller that hands
    in an explicit historical profiles snapshot gets live=False automatically unless they
    override it, so real-data substitution can never leak into a historical cutoff."""
    if live is None:
        live = profiles is None
    prof, betas, fcast, rent_tf = load_inputs(profiles, live=live)
    df = prof.copy()
    df["price_today"] = df["median_price"]
    df["price_is_real"] = False
    real_price = _load_real_pricing() if live else None
    if real_price is not None:
        df = df.merge(real_price[["profile_id", "price_today"]].rename(columns={"price_today": "price_today_real"}),
                      on="profile_id", how="left")
        df["price_is_real"] = df["price_today_real"].notna()
        df["price_today"] = df["price_today_real"].fillna(df["price_today"])
        df = df.drop(columns=["price_today_real"])
    df = df.merge(availability_stub(df, live=live), on="profile_id", how="left")
    f = fcast[fcast["horizon_months"] == query.horizon_months][
        ["town", "flat_type", "growth_factor", "growth_factor_lower", "growth_factor_upper"]]
    df = df.merge(f, on=["town", "flat_type"], how="left").merge(rent_tf, on=["town", "flat_type"], how="left")
    df["monthly_rent"] = df["monthly_rent"].fillna(rent_tf["monthly_rent"].median())
    df["price_upper"] = df["price_today"] * df["growth_factor_upper"]
    return df, betas, fcast


def score(df, query, betas):
    d = df.copy()
    n = d["txn_count_12m"]
    # "is this a bargain" has to compare the hedonic VALUE estimate against whatever
    # price_today is actually in force -- recomputed fresh here rather than read from the
    # profile table's own frozen hedonic_gap (= hedonic_value - median_price at BUILD
    # time), which goes stale the moment price_today is overridden by real pricing data
    # (pricing_today.csv, see assemble()) and no longer matches what's being compared.
    if "hedonic_value" in d.columns:
        gap = d["hedonic_value"] - d["price_today"]
    else:
        gap = d["hedonic_gap"]
    if "price_is_real" in d.columns and d["price_is_real"].any():
        # 2026-10-18 (OPTIMISER_METHODOLOGY_REPORT.md Sec. 14): hedonic_value was fit to
        # predict THIS pipeline's own median_price, not the Pricing Lead's real (lease-band-
        # blended) price_today -- comparing them raw mostly measures model disagreement, not
        # genuine mispricing. A literal re-fit of the attribute regression against their
        # price isn't possible without their block-level predictions (not available -- only a
        # profile-level aggregate is). What's used instead: hedonic_price_calibration.json, a
        # log-log recalibration of hedonic_value onto price_today's basis (fit once on the
        # 706-profile overlap, R^2=0.934, applied to every profile including stub-priced
        # ones). Falls back to the old suppress-to-0 behaviour if that artifact is missing.
        calib = _load_price_calibration()
        if calib is not None and "hedonic_value" in d.columns:
            from hedonic_value import apply_price_calibration
            calibrated_value = apply_price_calibration(d["hedonic_value"], d["price_today"], calib)
            gap_real = calibrated_value - d["price_today"]
            gap = gap.where(~d["price_is_real"], gap_real)
        else:
            gap = gap.where(~d["price_is_real"], 0.0)
    d["shrunk_value_gap"] = gap.fillna(0) * n / (n + query.shrink_k)

    tilt = 0.0
    for a, col in ATTR_COLS.items():
        m, beta = query.multipliers[a], betas[ATTR_BETA_KEY[a]]
        tilt = tilt + d["price_today"] * (m - 1) * (-beta) * (1.0 - d[col].clip(upper=2.0))
    d["preference_tilt"] = tilt
    d["surplus"] = d["shrunk_value_gap"] + d["preference_tilt"]

    beta_mrt, m_mrt = -betas["dist_mrt_exit_km"], query.multipliers["mrt"]
    d["dev_mrt"] = d["price_today"] * beta_mrt * m_mrt * (d["dist_mrt_exit_km_p50"] - query.target_mrt_km).clip(lower=0)
    d["dev_essentials"] = query.w_essential_sgd * (query.target_essentials - d["essentials_score"]).clip(lower=0)
    # school_goal: "elite_1km" / "elite_2km" (popular SAP/GEP school, MOE P1 tiers) or "any_1km".
    # needs_primary_school=True with no explicit goal defaults to "elite_2km".
    goal = query.school_goal or ("elite_2km" if query.needs_primary_school else None)
    col = {"elite_1km": "share_elite_primary_1km", "elite_2km": "share_elite_primary_2km",
           "any_1km": "share_primary_1km"}.get(goal)
    # Priced at the MARKET premium for popular-school proximity (hedonic: ~+2.5-3% of price), unless the
    # household / conjoint supplies its own w_school_sgd. Multiplier "school" scales it like other attributes.
    school_rate = np.expm1(betas.get("elite_primary_1_2km", np.log1p(0.03)))
    school_value = (d["price_today"] * school_rate * query.multipliers.get("school", 1.0)
                    if query.w_school_sgd is None else query.w_school_sgd)
    d["dev_school"] = school_value * (1 - d[col]) if col else 0.0
    d["dev_storey"] = query.storey_step_sgd * (STOREY_RANK[query.target_storey] - d["storey_band"].map(STOREY_RANK)).clip(lower=0)
    d["dev_wait"] = d["monthly_rent"] * (d["expected_wait_months"] - query.target_wait_months).clip(lower=0)
    dev_cols = ["dev_mrt", "dev_essentials", "dev_school", "dev_storey", "dev_wait"]

    # Optional goal, OFF by default (None): "at least target_expressway_km from the nearest
    # expressway" -- a MINIMUM-distance goal, the mirror image of dev_mrt's MAXIMUM-distance
    # goal, since the hedonic confirms expressway proximity is a priced disamenity (farther =
    # pricier; see hedonic_value.py's WTP_ATTRS comment for the significance/sign test behind
    # this). Priced at the real market rate (betas["dist_expressway_km"], ~0.9%/km), not guessed.
    if query.target_expressway_km is not None and "dist_expressway_km_p50" in d.columns:
        beta_exp = betas.get("dist_expressway_km", 0.0)
        d["dev_expressway"] = (d["price_today"] * beta_exp *
                               (query.target_expressway_km - d["dist_expressway_km_p50"]).clip(lower=0))
        dev_cols = dev_cols + ["dev_expressway"]
    d["goal_deviation_total"] = d[dev_cols].sum(axis=1)
    d["net_objective_value"] = d["surplus"] - d["goal_deviation_total"]
    return d, dev_cols


def _prepare(query, profiles=None, fcast_override=None, chance_alpha=None, upper_factors=None):
    """Shared feasibility-filter + scoring pipeline behind both solve() (weighted-sum)
    and solve_preemptive() (literal lexicographic GP), so the two solve modes are
    guaranteed to see the identical candidate set and $ scoring -- only the MIP they
    build on top differs."""
    df, betas, fcast = assemble(query, profiles)
    if fcast_override is not None:
        fcast = fcast_override
    if upper_factors is not None:
        uf = upper_factors[["flat_type", "mrt_band", "growth_factor_upper"]].rename(
            columns={"growth_factor_upper": "emp_upper"})
        df["mrt_band"] = df["mrt_band"].astype(str)
        uf = uf.assign(mrt_band=uf["mrt_band"].astype(str))
        df = df.merge(uf, on=["flat_type", "mrt_band"], how="left")
        df["price_upper"] = df["price_today"] * df["emp_upper"].fillna(df["growth_factor_upper"])
    if query.flat_types:
        df = df[df["flat_type"].isin(query.flat_types)]
    if query.towns_exclude:
        df = df[~df["town"].isin(query.towns_exclude)]
    if query.max_mrt_band:
        df = df[df["mrt_band"].map(BAND_RANK) <= BAND_RANK[query.max_mrt_band]]
    df = df[df["median_remaining_lease"] >= query.min_lease_yrs]

    alpha = chance_alpha or query.alpha
    if alpha:
        from chance_constraint import chance_feasible_profiles
        df = chance_feasible_profiles(df, fcast, budget=query.budget, horizon_months=query.horizon_months,
                                      alpha=alpha, n_scenarios=400)
        df = df[df["chance_feasible"]]
    else:
        df = df[df["price_upper"] <= query.budget]
    df = df.reset_index(drop=True)
    if df.empty:
        return None
    d, dev_cols = score(df, query, betas)
    return d, dev_cols


def solve(query, profiles=None, fcast_override=None, chance_alpha=None, upper_factors=None):
    """upper_factors: optional DataFrame [flat_type, mrt_band, growth_factor_upper] -- the
    empirical, granularity-aware 90% band (empirical_bands.py). When given, it
    replaces the stub forecast's flat upper band in the hard budget constraint."""
    prepared = _prepare(query, profiles, fcast_override, chance_alpha, upper_factors)
    if prepared is None:
        return {"status": "Infeasible", "shortlist": pd.DataFrame(), "n_candidates": 0, "scored": pd.DataFrame(),
                "objective": float("nan"), "n_feasible_towns": 0, "k_satisfied": False}
    d, dev_cols = prepared
    ids, towns = d["profile_id"].tolist(), d["town"].tolist()
    n_towns = len(set(towns))
    # Cardinality is FIXED at k. If fewer than k towns are feasible we still
    # return the best one-per-town picks, but flag k_satisfied=False: those
    # objectives are not comparable to full-k solutions (summing 3 picks vs 5
    # was the cause of a spurious budget-monotonicity failure in iteration 1).
    k_eff = min(query.k, n_towns)
    prob = pulp.LpProblem("Recommender_v2", pulp.LpMaximize)
    x = {i: pulp.LpVariable(f"x_{j}", cat="Binary") for j, i in enumerate(ids)}
    obj = dict(zip(ids, d["net_objective_value"]))
    prob += pulp.lpSum(x[i] * obj[i] for i in ids)
    prob += pulp.lpSum(x.values()) == k_eff
    for t in set(towns):
        prob += pulp.lpSum(x[i] for i, tt in zip(ids, towns) if tt == t) <= 1
    # optional, OFF by default (None = old behaviour unchanged): caps repeats of a single MRT
    # band / flat type, so a "diverse" shortlist is diverse on more than just town -- e.g. without
    # this, a transit-indifferent household's picks can legitimately all land in the same band.
    if query.max_per_mrt_band:
        bands = d["mrt_band"].tolist()
        for b in set(bands):
            prob += pulp.lpSum(x[i] for i, bb in zip(ids, bands) if bb == b) <= query.max_per_mrt_band
    if query.max_per_flat_type:
        ftypes = d["flat_type"].tolist()
        for ft in set(ftypes):
            prob += pulp.lpSum(x[i] for i, ff in zip(ids, ftypes) if ff == ft) <= query.max_per_flat_type
    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    sel = [i for i in ids if (x[i].value() or 0) > 0.5]
    sl = d[d["profile_id"].isin(sel)].sort_values("net_objective_value", ascending=False).copy()
    sl["rank"] = range(1, len(sl) + 1)
    cols = (["rank", "profile_id", "town", "flat_type", "lease_band", "storey_band", "mrt_band", "price_today", "price_upper",
             "median_remaining_lease", "dist_mrt_exit_km_p50", "essentials_score", "share_elite_primary_1km",
             "share_elite_primary_2km", "p_no_matching_sale_3m",
             "expected_wait_months", "survival_prob_6m", "survival_prob_12m", "monthly_rent",
             "shrunk_value_gap", "preference_tilt", "surplus"] + dev_cols + ["goal_deviation_total", "net_objective_value"])
    return {"status": pulp.LpStatus[prob.status], "shortlist": sl[cols], "n_candidates": len(d), "scored": d,
            "objective": float(sl["net_objective_value"].sum()), "n_feasible_towns": n_towns,
            "k_satisfied": n_towns >= query.k}


DEFAULT_PRIORITY = ["dev_mrt", "dev_school", "dev_storey", "dev_wait", "dev_essentials"]


def solve_preemptive(query, priority=None, profiles=None, fcast_override=None, chance_alpha=None, upper_factors=None):
    """Production mode #2: LITERAL preemptive (lexicographic) goal programming,
    P1 >> P2 >> P3 >> ... exactly as GP lecture p.19-21 defines it, instead of
    solve()'s weighted-sum (Archimedean) objective that nets every goal's dollar
    deviation into one number. Each stage below minimises ONE goal's total shortlist
    deviation, subject to every higher-priority goal already being held at its own
    optimum (a hard constraint carried into every later stage) -- so a cheaper pick
    can never be preferred if it costs so much as $1 of a higher-priority goal.
    Surplus (is it a good deal at all) is deliberately the FINAL tiebreaker, not a
    goal -- it only decides between picks that are already tied on every goal.

    priority: ordered list of dev_cols, highest first. Defaults to DEFAULT_PRIORITY,
    the order the proposal itself emphasises business objective 1's goals in (transit
    access and schooling named first; storey and wait are secondary comfort goals).

    Use this instead of solve() when a household can state a strict ranking of
    what matters ("MRT access no matter what, THEN school, THEN ...") rather than
    dollar trade-off rates -- the weighted-sum mode needs those $ rates and silently
    lets a large-enough saving on a low-priority goal outweigh a small shortfall on
    a high-priority one; preemptive mode never does."""
    prepared = _prepare(query, profiles, fcast_override, chance_alpha, upper_factors)
    if prepared is None:
        return {"status": "Infeasible", "shortlist": pd.DataFrame(), "n_candidates": 0, "scored": pd.DataFrame(),
                "objective": float("nan"), "n_feasible_towns": 0, "k_satisfied": False, "stage_values": {}}
    d, dev_cols = prepared
    priority = [c for c in (priority or DEFAULT_PRIORITY) if c in dev_cols]
    ids, towns = d["profile_id"].tolist(), d["town"].tolist()
    n_towns = len(set(towns))
    k_eff = min(query.k, n_towns)
    dmap = d.set_index("profile_id")
    surplus = dmap["surplus"].to_dict()

    def _build_base():
        prob = pulp.LpProblem("Preemptive", pulp.LpMinimize)
        x = {i: pulp.LpVariable(f"x_{j}", cat="Binary") for j, i in enumerate(ids)}
        prob += pulp.lpSum(x.values()) == k_eff
        for t in set(towns):
            prob += pulp.lpSum(x[i] for i, tt in zip(ids, towns) if tt == t) <= 1
        return prob, x

    stage_values, locked = {}, []
    EPS = 1.0  # $1 slack when locking a stage's achieved value, for float/solver tolerance
    for col in priority:
        prob, x = _build_base()
        colvals = dmap[col].to_dict()
        prob += pulp.lpSum(x[i] * colvals[i] for i in ids)
        for lcol, lval in locked:
            lv = dmap[lcol].to_dict()
            prob += pulp.lpSum(x[i] * lv[i] for i in ids) <= lval + EPS
        prob.solve(pulp.PULP_CBC_CMD(msg=0))
        if pulp.LpStatus[prob.status] != "Optimal":
            return {"status": pulp.LpStatus[prob.status], "shortlist": pd.DataFrame(), "n_candidates": len(d),
                    "scored": d, "objective": float("nan"), "n_feasible_towns": n_towns,
                    "k_satisfied": n_towns >= query.k, "stage_values": stage_values}
        # computed from the realised selection, not pulp.value(prob.objective): that returns
        # None (not 0.0) when a stage's column is identically zero for every candidate (a
        # constant objective has no variable terms for pulp to evaluate), even though the
        # solve itself is genuinely optimal.
        sel_stage = [i for i in ids if (x[i].value() or 0) > 0.5]
        achieved = sum(colvals[i] for i in sel_stage)
        stage_values[col] = achieved
        locked.append((col, achieved))

    # final stage: maximise surplus (the tiebreaker), every goal still locked at its optimum
    prob, x = _build_base()
    prob.sense = pulp.LpMaximize
    prob += pulp.lpSum(x[i] * surplus[i] for i in ids)
    for lcol, lval in locked:
        lv = dmap[lcol].to_dict()
        prob += pulp.lpSum(x[i] * lv[i] for i in ids) <= lval + EPS
    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    sel = [i for i in ids if (x[i].value() or 0) > 0.5]
    sl = d[d["profile_id"].isin(sel)].sort_values("net_objective_value", ascending=False).copy()
    sl["rank"] = range(1, len(sl) + 1)
    cols = (["rank", "profile_id", "town", "flat_type", "lease_band", "storey_band", "mrt_band", "price_today", "price_upper",
             "median_remaining_lease", "dist_mrt_exit_km_p50", "essentials_score", "share_elite_primary_1km",
             "share_elite_primary_2km", "p_no_matching_sale_3m",
             "expected_wait_months", "survival_prob_6m", "survival_prob_12m", "monthly_rent",
             "shrunk_value_gap", "preference_tilt", "surplus"] + dev_cols + ["goal_deviation_total", "net_objective_value"])
    return {"status": pulp.LpStatus[prob.status], "shortlist": sl[cols], "n_candidates": len(d), "scored": d,
            "objective": float(sl["net_objective_value"].sum()), "n_feasible_towns": n_towns,
            "k_satisfied": n_towns >= query.k, "stage_values": stage_values, "priority_order": priority}


def block_drilldown(shortlist, top_n=3):
    drill = pd.read_csv(os.path.join(DATA, "profile_block_drilldown.csv"))
    d = drill[drill["profile_id"].isin(shortlist["profile_id"])]
    d = d.sort_values(["profile_id", "sales_12m", "dist_mrt_exit_km"], ascending=[True, False, True])
    cols = ["profile_id", "query", "sales_12m", "median_price", "dist_mrt_exit_km", "walk_mrt_exit_km", "elite_primary_tier"]
    return d.groupby("profile_id").head(top_n)[[c for c in cols if c in d]]


if __name__ == "__main__":
    q = HouseholdQuery2(budget=600_000, min_lease_yrs=60, k=5, target_mrt_km=0.4, needs_primary_school=True,
                        target_storey="Mid", multipliers={"mrt": 1.5}, name="young family, transit-reliant")
    r = solve(q)
    print(r["status"], "| candidates:", r["n_candidates"], "| objective $", round(r["objective"]))
    print(r["shortlist"][["rank", "profile_id", "price_today", "dist_mrt_exit_km_p50", "share_elite_primary_1km",
                          "expected_wait_months", "surplus", "goal_deviation_total", "net_objective_value"]]
          .round(2).to_string(index=False))
    print(block_drilldown(r["shortlist"]).round(3).to_string(index=False))

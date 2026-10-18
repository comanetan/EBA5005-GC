# -*- coding: utf-8 -*-
"""
Item 3 of the "other tests" follow-up list (OPTIMISER_METHODOLOGY_REPORT.md Sec. 20):
the LP-relaxation (Sec. 7.1) and GA-vs-CBC (Sec. 7.2) benchmarks only ever ran on
realistic household-sized candidate pools (11-52 profiles, later up to ~500 after the
lease-band expansion). Does the 0.000% integrality gap still hold, and does CBC's solve
time stay trivial, at the 1,000s-of-candidates scale a true block-level recommender
(13,356 geocoded blocks, vs. today's 1,184 profiles) would actually see?

Method: take the REAL ~1,184-candidate pool (a generous household query admits nearly
every profile), then synthetically expand it by duplicating each row with a small
jitter on net_objective_value (+-3%, representing within-profile block heterogeneity) --
same town preserved, so the real production constraint ("<=1 profile per town") stays
meaningfully binding at every scale tested, not trivialised away. This mirrors solve()'s
own exact IP construction (cardinality + <=1/town), not a reimplementation -- see
_build_ip() below, which is a faithful, directly-comparable copy of recommender_v2.py's
own PuLP construction, only operating on an expanded dataframe.
"""
import json
import os
import time

import numpy as np
import pandas as pd
import pulp

import recommender_v2 as rv2

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
K = 10
SCALES = [50, 200, 500, 1000, 2000, 5000, 10000, 20000]
SEED = 0


def base_candidates():
    """The real ~1,184-candidate pool: a generous query (huge budget, no lease floor)
    admits nearly every profile in housing_profiles_v2_full.csv."""
    q = rv2.HouseholdQuery2(budget=10_000_000, min_lease_yrs=0, k=K, name="scaling-base")
    prepared = rv2._prepare(q)
    if prepared is None:
        raise RuntimeError("Base query returned no candidates -- check budget/lease filter")
    d, dev_cols = prepared
    d = d[["profile_id", "town", "net_objective_value"]].reset_index(drop=True)
    # shuffle once, fixed seed: profile_id is alphabetical by town (e.g. "ANG MO KIO::..."
    # sorts before "BEDOK::..."), so an UNSHUFFLED small .iloc[:n] slice at the small scales
    # below would only ever see the first few towns alphabetically -- not town-diverse,
    # which can make k_eff=10 infeasible (fewer than 10 distinct towns in the slice) for a
    # reason that has nothing to do with scale. Shuffling once makes every scale a fair,
    # town-diverse sample of the same real population.
    return d.sample(frac=1.0, random_state=SEED).reset_index(drop=True)


def expand(d_base, target_n, jitter_std=0.03, seed=SEED):
    """Duplicate the real candidate pool up to target_n rows, same town per duplicate
    (keeps the <=1/town constraint meaningfully binding), net_objective_value jittered
    +-jitter_std (relative) to represent within-profile block-level heterogeneity."""
    rng = np.random.default_rng(seed)
    n_base = len(d_base)
    if target_n <= n_base:
        return d_base.iloc[:target_n].copy()
    reps = int(np.ceil(target_n / n_base))
    rows = []
    for r in range(reps):
        d = d_base.copy()
        if r > 0:
            jitter = rng.normal(1.0, jitter_std, size=len(d))
            d["net_objective_value"] = d["net_objective_value"] * jitter
            d["profile_id"] = d["profile_id"] + f"__dup{r}"
        rows.append(d)
    out = pd.concat(rows, ignore_index=True)
    return out.iloc[:target_n].reset_index(drop=True)


def _build_ip(d, k_eff, relax=False):
    """Faithful copy of recommender_v2.py::solve()'s own PuLP construction -- cardinality
    + <=1/town only (the two constraints every live recommendation actually uses; the
    optional max_per_mrt_band/max_per_flat_type extras are off by default in production
    too). cat is Binary for the real IP, Continuous [0,1] for the LP relaxation."""
    ids = d["profile_id"].tolist()
    towns = d["town"].tolist()
    obj = dict(zip(ids, d["net_objective_value"]))
    cat = "Continuous" if relax else "Binary"
    prob = pulp.LpProblem("ScalingTest", pulp.LpMaximize)
    if relax:
        x = {i: pulp.LpVariable(f"x_{j}", lowBound=0, upBound=1, cat=cat) for j, i in enumerate(ids)}
    else:
        x = {i: pulp.LpVariable(f"x_{j}", cat=cat) for j, i in enumerate(ids)}
    prob += pulp.lpSum(x[i] * obj[i] for i in ids)
    prob += pulp.lpSum(x.values()) == k_eff
    for t in set(towns):
        prob += pulp.lpSum(x[i] for i, tt in zip(ids, towns) if tt == t) <= 1
    return prob, x, ids


def solve_at_scale(d, k_eff):
    results = {}
    for relax, label in [(False, "ip"), (True, "lp_relax")]:
        prob, x, ids = _build_ip(d, k_eff, relax=relax)
        t0 = time.perf_counter()
        prob.solve(pulp.PULP_CBC_CMD(msg=0))
        elapsed = time.perf_counter() - t0
        status = pulp.LpStatus[prob.status]
        objective = pulp.value(prob.objective) if status == "Optimal" else None
        n_fractional = 0
        if relax and status == "Optimal":
            n_fractional = sum(1 for i in ids if 1e-6 < (x[i].value() or 0) < 1 - 1e-6)
        results[label] = {"status": status, "objective": objective, "seconds": elapsed,
                           "n_fractional": n_fractional if relax else None}
    gap = None
    if results["ip"]["objective"] is not None and results["lp_relax"]["objective"]:
        denom = abs(results["lp_relax"]["objective"]) or 1.0
        gap = abs(results["lp_relax"]["objective"] - results["ip"]["objective"]) / denom
    return results, gap


def run():
    d_base = base_candidates()
    n_towns = d_base["town"].nunique()
    k_eff = min(K, n_towns)
    print(f"Base real candidate pool: {len(d_base)} profiles, {n_towns} towns, k_eff={k_eff}")

    rows = []
    for n in SCALES:
        d = expand(d_base, n)
        results, gap = solve_at_scale(d, k_eff)
        rows.append({"n_candidates": n, "n_towns": d["town"].nunique(), **results, "integrality_gap": gap})
        print(f"n={n:>6}  IP: {results['ip']['status']:<8} obj={results['ip']['objective']:>14,.2f} "
              f"{results['ip']['seconds']*1000:>8.1f}ms   |  LP relax: {results['lp_relax']['status']:<8} "
              f"obj={results['lp_relax']['objective']:>14,.2f}  frac_vars={results['lp_relax']['n_fractional']:>3}  "
              f"{results['lp_relax']['seconds']*1000:>8.1f}ms   |  gap={gap*100:.4f}%")
    return rows


if __name__ == "__main__":
    rows = run()
    with open(os.path.join(DATA, "ip_scaling_test.json"), "w") as f:
        json.dump(rows, f, indent=2)
    print("\nWrote data/ip_scaling_test.json")

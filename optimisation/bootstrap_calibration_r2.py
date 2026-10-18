# -*- coding: utf-8 -*-
"""
Item 2 of the "other tests" follow-up list (OPTIMISER_METHODOLOGY_REPORT.md Sec. 18):
the hedonic-to-real-price calibration's R^2 (currently reported as a single point
estimate, 0.960) is a sample statistic from one fit on the 1,119-profile overlap --
how much would it move on a different sample of the same population?

Bootstrap: resample the overlap WITH replacement (same n each time), refit the
identical log-log OLS hedonic_value.py::fit_price_calibration() uses, B=2000 times.
Reports the empirical distribution of R^2 (and alpha, beta, resid_std for completeness)
instead of just the one number already in the report.
"""
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
B = 2000
SEED = 0


def _fit(x, y):
    """Identical formula to hedonic_value.py::fit_price_calibration() -- same inputs,
    same math, just operating on already-extracted log arrays so a resample doesn't
    need to round-trip through a profile_id merge each time."""
    beta, alpha = np.polyfit(x, y, 1)
    pred = alpha + beta * x
    resid = y - pred
    ss_res, ss_tot = float((resid ** 2).sum()), float(((y - y.mean()) ** 2).sum())
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return alpha, beta, r_squared, float(resid.std(ddof=2))


def run(b=B, seed=SEED):
    profiles = pd.read_csv(os.path.join(DATA, "housing_profiles_v2_full.csv"))
    real_price = pd.read_csv(os.path.join(DATA, "pricing_today.csv"))
    d = profiles[["profile_id", "hedonic_value"]].merge(
        real_price[["profile_id", "price_today"]], on="profile_id", how="inner")
    d = d[(d["hedonic_value"] > 0) & (d["price_today"] > 0)]
    x_full = np.log(d["hedonic_value"].to_numpy())
    y_full = np.log(d["price_today"].to_numpy())
    n = len(x_full)

    point = _fit(x_full, y_full)

    rng = np.random.default_rng(seed)
    r2s, alphas, betas, resids = [], [], [], []
    for _ in range(b):
        idx = rng.integers(0, n, size=n)
        alpha, beta, r2, resid_std = _fit(x_full[idx], y_full[idx])
        alphas.append(alpha); betas.append(beta); r2s.append(r2); resids.append(resid_std)
    r2s = np.array(r2s)

    result = {
        "n_profiles": n, "n_bootstrap": b, "seed": seed,
        "point_estimate": {"alpha": point[0], "beta": point[1], "r_squared": point[2], "resid_std": point[3]},
        "bootstrap_r_squared": {
            "mean": float(r2s.mean()), "std": float(r2s.std(ddof=1)),
            "ci95_lo": float(np.percentile(r2s, 2.5)), "ci95_hi": float(np.percentile(r2s, 97.5)),
            "min": float(r2s.min()), "max": float(r2s.max()),
        },
        "bootstrap_alpha": {"mean": float(np.mean(alphas)), "std": float(np.std(alphas, ddof=1))},
        "bootstrap_beta": {"mean": float(np.mean(betas)), "std": float(np.std(betas, ddof=1))},
    }
    return result


if __name__ == "__main__":
    result = run()
    p = result["point_estimate"]
    bs = result["bootstrap_r_squared"]
    print(f"n={result['n_profiles']} profiles, B={result['n_bootstrap']} bootstrap resamples")
    print(f"Point estimate (full sample):  R^2={p['r_squared']:.4f}  alpha={p['alpha']:.4f}  beta={p['beta']:.4f}  resid_std={p['resid_std']:.4f}")
    print(f"Bootstrap R^2:  mean={bs['mean']:.4f}  std={bs['std']:.4f}  95% CI=[{bs['ci95_lo']:.4f}, {bs['ci95_hi']:.4f}]  range=[{bs['min']:.4f}, {bs['max']:.4f}]")
    print(f"Bootstrap beta: mean={result['bootstrap_beta']['mean']:.4f}  std={result['bootstrap_beta']['std']:.4f}")

    with open(os.path.join(DATA, "calibration_r2_bootstrap.json"), "w") as f:
        json.dump(result, f, indent=2)
    print("\nWrote data/calibration_r2_bootstrap.json")

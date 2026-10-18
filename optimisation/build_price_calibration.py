# -*- coding: utf-8 -*-
"""
Fits and writes data/hedonic_price_calibration.json -- see hedonic_value.py's
fit_price_calibration() docstring for why this exists and what it does and doesn't fix.
Re-run whenever pricing_today.csv is refreshed (e.g. after pricing_availability_adapter.py).
"""
import json
import os

import pandas as pd

from hedonic_value import fit_price_calibration

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def build(write=True):
    profiles = pd.read_csv(os.path.join(DATA, "housing_profiles_v2_full.csv"))
    real_price = pd.read_csv(os.path.join(DATA, "pricing_today.csv"))
    calib = fit_price_calibration(profiles, real_price)
    calib["_source"] = ("log(price_today) ~ alpha + beta*log(hedonic_value), OLS on the "
                         f"{calib['n']}-profile overlap with pricing_today.csv; "
                         "see OPTIMISER_METHODOLOGY_REPORT.md Sec. 14")
    if write:
        with open(os.path.join(DATA, "hedonic_price_calibration.json"), "w") as f:
            json.dump(calib, f, indent=2)
    return calib


if __name__ == "__main__":
    calib = build()
    print(f"Fit on {calib['n']} profiles: alpha={calib['alpha']:.4f}, beta={calib['beta']:.4f}, "
          f"R^2={calib['r_squared']:.4f}, resid_std={calib['resid_std']:.4f} (log scale)")
    import numpy as np
    print(f"At the median hedonic_value, implied multiplicative correction: "
          f"{np.exp(calib['alpha'] + (calib['beta']-1)*np.log(700000)):.4f}")

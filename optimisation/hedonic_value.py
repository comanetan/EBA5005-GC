# -*- coding: utf-8 -*-
"""
Interim hedonic valuation engine (stand-in for the Pricing & Availability
Lead's model until it lands; same role, so the recommender's objective is
already dollar-denominated and attribute-driven).

Fits log(price) on structural attributes + town & month effects + BLOCK-
level accessibility, using ONLY transactions up to `as_of` (no look-ahead,
so the same function powers the backtest). Exposes:
  - per-transaction predicted market value
  - attribute coefficients (log points per km / per unit) = the market's
    revealed willingness-to-pay for each attribute
"""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

# Attributes whose market coefficient is used as a WTP rate. Primary-school
# and childcare distance are deliberately excluded: their within-town
# coefficients came out with counterintuitive signs (likely collinearity with
# older, denser estates / "too close" noise disamenity) -- not a trustworthy
# WTP. School access enters the recommender as a household GOAL instead.
#
# 2026-10-10 attribute-expansion pass (see OPTIMISER_METHODOLOGY_REPORT.md Sec. 9): secondary
# school distance, carpark distance and the PUB flood-prone flag were all TESTED the same way
# and REJECTED -- secondary school came out with the same counterintuitive positive sign as
# primary (+2.1%/km, same likely cause); carpark was not significant (p=0.26, expected given
# carparks are within ~80m of nearly every HDB block); the flood-prone flag's coefficient
# (+2.6%, p<0.0001) is CONFOUNDED, not causal -- its 175 flagged blocks sit disproportionately
# in Bukit Merah/Queenstown/Kallang-Whampoa (prime, central, MRT-close mature estates; mean
# 0.55km to MRT vs 0.71km overall), so the coefficient is picking up unmodelled prime-location
# value, not a flood-risk discount. Pricing any of the three in would be actively misleading.
# Expressway distance is the one that passed both tests: statistically significant (p<0.0001)
# AND correctly signed (farther from an expressway = higher price, the expected disamenity
# direction) -- added below, and wired into the recommender as a GOAL (dev_expressway, "at
# least this far from an expressway"), not a tilt multiplier, since "closer is better" framing
# (used for every other WTP_ATTR) would be backwards for a disamenity.
WTP_ATTRS = ["dist_mrt_exit_km", "dist_hawker_km", "dist_supermarket_km", "dist_chas_clinic_km", "dist_park_km",
             "dist_expressway_km"]
# School access enters as MOE-style tiers for POPULAR (SAP/GEP) primary schools -- "any primary within 1km"
# is true for 97% of blocks, so it can't distinguish flats (the cause of v2's counterintuitive sign).
CONTROL_ACCESS = ["n_bus_stop_400m", "dist_planned_rail_km"]

FORMULA = ("log_price ~ C(month_s) + C(flat_type) + C(flat_model) + storey_mid + floor_area_sqm"
           " + remaining_lease_yrs + I(remaining_lease_yrs**2) + C(town) + "
           + " + ".join(WTP_ATTRS + CONTROL_ACCESS) + " + C(elite_primary_tier, Treatment('Beyond 2km'))")


def fit_hedonic(tx: pd.DataFrame, as_of=None, train_months=36, sample_n=120_000, seed=0):
    d = tx.copy()
    if as_of is not None:
        d = d[d["month"] <= pd.Timestamp(as_of)]
    d = d[d["month"] > d["month"].max() - pd.DateOffset(months=train_months)]
    if "dist_mrt_exit_km_at_sale" in d.columns:  # fit on the network that existed at each sale
        d["dist_mrt_exit_km"] = d["dist_mrt_exit_km_at_sale"]
    d = d.dropna(subset=WTP_ATTRS + CONTROL_ACCESS + ["remaining_lease_yrs", "storey_mid"])
    if sample_n and len(d) > sample_n:
        d = d.sample(sample_n, random_state=seed)
    d["month_s"] = d["month"].dt.strftime("%Y-%m")
    model = smf.ols(FORMULA, data=d).fit()
    return model, d["month_s"].max()


def predict_value(model, tx: pd.DataFrame, at_month: str):
    """Predict market value for each transaction's attributes, AS IF sold in
    `at_month` (removes the month-of-sale effect so profiles are comparable)."""
    d = tx.copy()
    d["month_s"] = at_month
    known_models = set(model.model.data.frame["flat_model"]) if hasattr(model.model.data, "frame") else None
    if known_models is not None:
        d = d[d["flat_model"].isin(known_models)]
    resid_var = model.mse_resid
    return d.index, np.exp(model.predict(d) + resid_var / 2)  # smearing-style bias correction


def market_wtp_coefficients(model):
    out = {a: float(model.params[a]) for a in WTP_ATTRS}
    for lvl, key in [("Within 1km", "elite_primary_within_1km"), ("1-2km", "elite_primary_1_2km")]:
        k = f"C(elite_primary_tier, Treatment('Beyond 2km'))[T.{lvl}]"
        if k in model.params:
            out[key] = float(model.params[k])  # log points vs 'Beyond 2km'
    return out

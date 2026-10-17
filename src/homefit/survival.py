"""Survival model: months until the next resale of a flat type in a block (Cox proportional hazards, lifelines).

Unit = block x flat type. Spells run between successive sales; the last one is right-censored at `as_of`. Old blocks drop
the spell before their first observed sale (its start is unknown); newer blocks start at MOP eligibility; groups that never
sold are censored from Jan 2017 (or eligibility). Block age violates proportional hazards, so it is a stratum.
`profile_waits` turns block-level sale rates into an expected wait for ANY flat in a profile, calibrated by
flat type and blended with the profile's own recent sales (see its docstring)."""
import numpy as np, pandas as pd
from lifelines import CoxPHFitter
from lifelines.utils import concordance_index
from scipy.stats import gamma
import config as C
from . import common as K, profiles as PR

AGE_BANDS, AGE_LABELS = [-1, 15, 30, 45, 200], ["<15", "15-29", "30-44", "45+"]
REGION_OF = {t: r for r, ts in C.REGIONS.items() for t in ts}
LOC = ["dist_hawker_m", "dist_park_m", "dist_supermarket_m", "n_primary_1km"]

def spells(as_of):
    s = K.sales()
    s = s[s["in_scope"] & s["flat_type"].isin(K.TYPES) & (s["month"] <= as_of)]
    t0, t_end = K.month_index("2017-01"), K.month_index(as_of)
    st = K.stock()
    st = st[st["flat_type"].isin(K.TYPES)].copy()
    st["t_eligible"] = (st["year_completed"] + 5) * 12 + 6
    st = st[st["t_eligible"] <= t_end]
    times = s.groupby(["address", "flat_type"])["t"].apply(lambda x: np.sort(x.to_numpy()))
    rows = []
    for g in st.itertuples():
        ts = times.get((g.address, g.flat_type), np.array([], dtype=int))
        start = None if g.t_eligible <= t0 else g.t_eligible
        if g.t_eligible <= t0 and len(ts) == 0:
            start = t0
        for t in ts:
            if start is not None and t >= start:
                rows.append((g.address, g.flat_type, start, max(t - start, 0.5), 1))
            start = t
        if start is not None and start <= t_end:
            rows.append((g.address, g.flat_type, start, max(t_end - start, 0.5), 0))
    sp = pd.DataFrame(rows, columns=["address", "flat_type", "t_start", "duration", "event"])
    sp = sp.merge(st[["address", "flat_type", "units", "year_completed", "max_floor_lvl", "town"]], on=["address", "flat_type"])
    sp["start_year"] = sp["t_start"] // 12
    sp["month"] = sp["t_start"].map(K.month_str)
    # MRT distance when the spell started: from the sale itself, else from the network open that month
    at_sale = s.drop_duplicates(["address", "month"]).set_index(["address", "month"])["dist_mrt_at_sale_m"]
    sp["dist_mrt_m"] = at_sale.reindex(list(zip(sp["address"], sp["month"]))).to_numpy()
    for m in sp.loc[sp["dist_mrt_m"].isna(), "month"].unique():
        idx = sp["dist_mrt_m"].isna() & (sp["month"] == m)
        sp.loc[idx, "dist_mrt_m"] = sp.loc[idx, "address"].map(K.mrt_distance_as_of(m)).to_numpy()
    b = K.blocks().set_index("address")
    for c in LOC:
        sp[c] = sp["address"].map(b[c])
    sp["block_age"] = sp["start_year"] - sp["year_completed"]
    sp["from_2020"] = (sp["start_year"] >= 2020).astype(float)
    return sp.dropna(subset=["dist_mrt_m"] + LOC)

def model_frame(F, columns=None):
    M = pd.get_dummies(F[["flat_type"]].assign(region=F["town"].map(REGION_OF)), drop_first=True, dtype=float)
    for c in ["dist_mrt_m"] + LOC[:3]:
        M["log_" + c[:-2]] = np.log1p(F[c].astype(float))
    M["log_units"] = np.log(F["units"].astype(float))
    M[["max_floor_lvl", "from_2020", "n_primary_1km"]] = F[["max_floor_lvl", "from_2020", "n_primary_1km"]].astype(float)
    M["age_band"] = pd.cut(F["block_age"], AGE_BANDS, labels=AGE_LABELS).astype(str)
    if columns is not None:
        M = M.reindex(columns=columns, fill_value=0.0)
    return M

def fit(as_of, data=None):
    F = spells(as_of) if data is None else data
    M = model_frame(F)
    # a covariate with no variation (e.g. the post-2020 flag before 2020) cannot be estimated: drop it
    M = M[[c for c in M.columns if c == "age_band" or M[c].nunique() > 1]]
    M["duration"], M["event"] = F["duration"].to_numpy(), F["event"].to_numpy()
    cph = CoxPHFitter(penalizer=0.01).fit(M, "duration", "event", strata=["age_band"])
    cph.columns_ = [c for c in M.columns if c not in ("duration", "event")]
    cph.as_of_ = as_of
    return cph

def evaluate(as_of, test_from_year):
    """Fit on spells starting before `test_from_year`, score the C-index on later spells (expected wait as the score,
    because block age sits in the strata baselines)."""
    F = spells(as_of)
    tr, te = F[F["start_year"] < test_from_year], F[F["start_year"] >= test_from_year]
    cph = fit(as_of, data=tr)
    score = lambda D: concordance_index(D["duration"], cph.predict_expectation(model_frame(D, cph.columns_)), D["event"])
    return {"c_index_train": score(tr), "c_index_test": score(te), "n_train": len(tr), "n_test": len(te)}

PRIOR_YEARS = 0.25   # weight of the model prior, in years of observed sales (chosen on the Jun 2023 backtest)

def model_rates(cph, as_of, rows):
    """Cox-implied sales per year for every row (block x flat type x storey band): share / expected gap between sales."""
    g = rows.drop_duplicates(["address", "flat_type"]).copy()
    b = K.blocks().set_index("address")
    for c in LOC:
        g[c] = g["address"].map(b[c])
    g["block_age"] = K.year_frac(as_of) // 1 - g["year_completed"]
    g["from_2020"] = float(K.year_frac(as_of) >= 2020)
    g["max_floor_lvl"] = g["max_floor_lvl"].fillna(g["max_floor_lvl"].median())
    times = np.arange(0, 121)
    S = cph.predict_survival_function(model_frame(g, cph.columns_), times=times).to_numpy()
    area = getattr(np, "trapezoid", None) or np.trapz
    g["gap_months"] = area(S, times, axis=0)
    rows = rows.merge(g[["address", "flat_type", "gap_months"]], on=["address", "flat_type"])
    rows["model_per_year"] = 12 * rows["share"] / rows["gap_months"]
    return rows

def profile_waits(cph, as_of, scheme="homefit", horizon=120, prior_years=PRIOR_YEARS):
    """Expected months until the next sale of ANY flat in each profile at as_of.

    1. Cox model -> sales per year for each profile (sum over its blocks of share / expected gap).
    2. Calibrate by flat type: scale so each flat type's total matches its actual sales in the 12 months to as_of.
       (Uncalibrated, the model over-predicts Executive and 5-room turnover and under-predicts 3-room.)
    3. Blend with the profile's own sales in the last 12 months (Poisson-gamma / empirical Bayes):
          rate = (sales_last12 + prior_years x model_rate) / (1 + prior_years)
       Observed sales dominate where there are many; the model fills in for thin profiles.
    4. wait = 12 / rate months, capped at `horizon` (flagged scarce); wait_p10/wait_p90 = 80% interval from the gamma posterior.
    Everything uses data up to as_of only, so the same code runs in the backtest."""
    rows = model_rates(cph, as_of, PR.profile_rows(as_of, scheme))
    p = rows.groupby("profile_id").agg(flat_type=("flat_type", "first"), model_per_year=("model_per_year", "sum"))
    p["sales_last12"] = PR.recent_sales(as_of, rows, scheme).reindex(p.index).fillna(0)
    by_type = p.groupby("flat_type")
    p["calib"] = by_type["sales_last12"].transform("sum") / by_type["model_per_year"].transform("sum")
    p["model_calibrated"] = p["model_per_year"] * p["calib"]
    p["sales_per_year"] = (p["sales_last12"] + prior_years * p["model_calibrated"]) / (1 + prior_years)
    wait = 12 / p["sales_per_year"]
    # 80% interval: the blend is a Poisson-gamma model, so the yearly rate has a Gamma(shape, rate) posterior
    shape, rate = (p["sales_last12"] + prior_years * p["model_calibrated"]).clip(lower=1e-9), 1 + prior_years
    p["wait_p10"] = np.minimum(12 / gamma.ppf(0.9, shape, scale=1 / rate), horizon)
    p["wait_p90"] = np.minimum(12 / gamma.ppf(0.1, shape, scale=1 / rate), horizon)
    out = pd.DataFrame({"profile_id": p.index, "wait_months": np.minimum(wait, horizon).round(2).to_numpy(),
                        "wait_p10": p["wait_p10"].round(2).to_numpy(), "wait_p90": p["wait_p90"].round(2).to_numpy(),
                        "scarce": (wait >= horizon).to_numpy()})
    return out, p.reset_index()

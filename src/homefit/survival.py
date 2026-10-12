"""Survival model: months until the next resale of a flat type in a block (Cox proportional hazards, lifelines).

Unit = block x flat type. Spells run between successive sales; the last one is right-censored at `as_of`. Old blocks drop
the spell before their first observed sale (its start is unknown); newer blocks start at MOP eligibility; groups that never
sold are censored from Jan 2017 (or eligibility). Block age violates proportional hazards, so it is a stratum.
`profile_waits` turns block-level sale rates into an expected wait for ANY flat in a profile: 1 / sum of block rates."""
import numpy as np, pandas as pd
from lifelines import CoxPHFitter
from lifelines.utils import concordance_index
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

def profile_waits(cph, as_of, horizon=120):
    """Expected months until the next sale of ANY flat in each profile at as_of."""
    rows = PR.profile_rows(as_of)
    g = rows.drop_duplicates(["address", "flat_type"]).copy()
    b = K.blocks().set_index("address")
    for c in LOC:
        g[c] = g["address"].map(b[c])
    g["block_age"] = K.year_frac(as_of) // 1 - g["year_completed"]
    g["from_2020"] = float(K.year_frac(as_of) >= 2020)
    g["max_floor_lvl"] = g["max_floor_lvl"].fillna(g["max_floor_lvl"].median())
    times = np.arange(0, horizon + 1)
    S = cph.predict_survival_function(model_frame(g, cph.columns_), times=times).to_numpy()
    area = getattr(np, "trapezoid", None) or np.trapz
    g["gap_months"] = area(S, times, axis=0)
    rows = rows.merge(g[["address", "flat_type", "gap_months"]], on=["address", "flat_type"])
    rows["rate"] = rows["share"] / rows["gap_months"]
    w = rows.groupby("profile_id")["rate"].sum()
    wait = 1 / w
    # Profiles with almost no supply get waits far beyond what 10 years of data can support: cap at the horizon, flag them
    out = pd.DataFrame({"profile_id": w.index, "wait_months": np.minimum(wait, horizon).round(2).to_numpy(),
                        "scarce": (wait >= horizon).to_numpy()})
    return out, rows

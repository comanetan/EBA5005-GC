"""Hedonic price model: LightGBM on log resale price, trained only on sales up to `as_of`.

Features: flat (type, model, size, remaining lease, storey), location (town, MRT distance at time of sale, amenities),
and market timing (month). Monotone constraints keep price rising with floor area, remaining lease and storey.
`price_profiles` prices every profile at `as_of` from a representative flat in each block, then averages across blocks."""
import numpy as np, pandas as pd
import lightgbm as lgb
from . import common as K, profiles as PR

NUM = ["floor_area_sqm", "remaining_lease_yrs", "storey_mid", "t", "dist_mrt_m", "dist_hawker_m", "dist_park_m",
       "dist_supermarket_m", "dist_polyclinic_m", "dist_primary_m", "n_primary_1km", "n_preschool_500m", "n_chas_500m",
       "n_supermarket_500m", "max_floor_lvl"]
CAT = ["flat_type", "flat_model_group", "town"]
FEATURES = NUM + CAT
MONOTONE = {"floor_area_sqm": 1, "remaining_lease_yrs": 1, "storey_mid": 1}
PARAMS = dict(objective="regression", learning_rate=0.05, num_leaves=63, min_child_samples=40, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, seed=7)

def training_frame(as_of):
    d = K.sales()
    d = d[d["in_scope"] & ~d["psm_outlier"] & d["flat_type"].isin(K.TYPES) & (d["month"] <= as_of)].copy()
    d["dist_mrt_m"] = d["dist_mrt_at_sale_m"]                       # MRT network as it was at the sale
    # 1 block (82 MacPherson Lane) is missing from HDB Property Information: use its highest recorded storey instead
    d["max_floor_lvl"] = d["max_floor_lvl"].fillna(d.groupby("address")["storey_hi"].transform("max"))
    return d

def _X(d, categories=None):
    X = d[FEATURES].copy()
    for c in CAT:
        X[c] = pd.Categorical(X[c], categories=None if categories is None else categories[c])
    return X

def _params(X):
    p = dict(PARAMS)
    p["monotone_constraints"] = [MONOTONE.get(c, 0) for c in X.columns]
    return p

def fit(as_of, rounds=None, data=None):
    """Train on sales up to as_of. If `rounds` is None, pick it by early stopping on the last 6 months, then refit on all."""
    d = training_frame(as_of) if data is None else data
    X, y = _X(d), np.log(d["resale_price"].to_numpy())
    cats = {c: X[c].cat.categories for c in CAT}
    if rounds is None:
        cut = d["t"].max() - 6
        tr, va = (d["t"] <= cut).to_numpy(), (d["t"] > cut).to_numpy()
        m = lgb.train(_params(X), lgb.Dataset(X[tr], y[tr]), num_boost_round=4000,
                      valid_sets=[lgb.Dataset(X[va], y[va])], callbacks=[lgb.early_stopping(100, verbose=False)])
        rounds = m.best_iteration
    model = lgb.train(_params(X), lgb.Dataset(X, y), num_boost_round=rounds)
    model.categories_, model.as_of_, model.rounds_ = cats, as_of, rounds
    return model

def predict(model, d):
    return np.exp(model.predict(_X(d, model.categories_)))

def _linear_baseline(train, test):
    """Time-dummy hedonic regression (the price-index method) with the same information, as a benchmark."""
    def design(d, cols=None):
        X = pd.concat([d[NUM].drop(columns=["t"]).assign(lease2=d["remaining_lease_yrs"] ** 2 / 100,
                                                          log_area=np.log(d["floor_area_sqm"])),
                       pd.get_dummies(d[CAT + ["month"]].astype(str), dtype=float)], axis=1)
        X.insert(0, "const", 1.0)
        return X if cols is None else X.reindex(columns=cols, fill_value=0.0)
    Xtr = design(train); beta, *_ = np.linalg.lstsq(Xtr.to_numpy(float), np.log(train["resale_price"].to_numpy()), rcond=None)
    return np.exp(design(test, Xtr.columns).to_numpy(float) @ beta)

def evaluate(as_of, test_share=0.2, seed=0):
    """Hold out 20% of BLOCKS (all their sales) and score on them: tests pricing flats in blocks the model never saw,
    which is exactly the job for profiles with few or no sales. Compares with the linear time-dummy baseline."""
    d = training_frame(as_of)
    rng = np.random.default_rng(seed)
    blocks = d["address"].unique()
    test_blocks = set(rng.choice(blocks, int(len(blocks) * test_share), replace=False))
    te = d["address"].isin(test_blocks).to_numpy()
    model = fit(as_of, data=d[~te])
    y = d.loc[te, "resale_price"].to_numpy()
    out = {}
    for name, pred in [("lightgbm", predict(model, d[te])), ("linear_baseline", _linear_baseline(d[~te], d[te]))]:
        ape = np.abs(pred / y - 1)
        recent = (d.loc[te, "t"] > d["t"].max() - 12).to_numpy()
        out[name] = {"MAPE": ape.mean(), "median_APE": np.median(ape), "within_10pct": (ape <= 0.10).mean(),
                     "R2_log": 1 - np.var(np.log(y) - np.log(pred)) / np.var(np.log(y)), "MAPE_last12m": ape[recent].mean()}
    res = pd.DataFrame(out).T
    res.attrs.update(n_train=int((~te).sum()), n_test=int(te.sum()), test_blocks=len(test_blocks), rounds=model.rounds_)
    return res, model, d[te].assign(pred=predict(model, d[te]))

def price_profiles(model, as_of):
    """Price every profile at as_of: a representative flat per block x flat type x storey band, then a units-weighted
    average across the profile's blocks (geometric mean), with the 10th-90th percentile spread across blocks."""
    rows = PR.profile_rows(as_of)
    hist = training_frame(as_of)
    area = hist.groupby(["address", "flat_type"])["floor_area_sqm"].median()
    area_town = hist.groupby(["town", "flat_type"])["floor_area_sqm"].median()
    model_mode = hist.groupby(["address", "flat_type"])["flat_model_group"].agg(lambda s: s.mode()[0])
    model_town = hist.groupby(["town", "flat_type"])["flat_model_group"].agg(lambda s: s.mode()[0])
    k_blk, k_town = list(zip(rows["address"], rows["flat_type"])), list(zip(rows["town"], rows["flat_type"]))
    rows["floor_area_sqm"] = pd.Series(area.reindex(k_blk).to_numpy()).fillna(pd.Series(area_town.reindex(k_town).to_numpy())).to_numpy()
    rows["flat_model_group"] = pd.Series(model_mode.reindex(k_blk).to_numpy()).fillna(pd.Series(model_town.reindex(k_town).to_numpy())).to_numpy()
    b = K.blocks().set_index("address")
    for c in ["dist_hawker_m", "dist_park_m", "dist_supermarket_m", "dist_polyclinic_m", "dist_primary_m",
              "n_primary_1km", "n_preschool_500m", "n_chas_500m", "n_supermarket_500m"]:
        rows[c] = rows["address"].map(b[c])
    rows["t"] = K.month_index(as_of)
    rows = rows.dropna(subset=["floor_area_sqm", "flat_model_group"])
    rows["pred_price"] = predict(model, rows)
    rows["w"] = rows["units"] * rows["share"]

    def agg(g):
        w = g["w"].to_numpy(); lp = np.log(g["pred_price"].to_numpy()); o = np.argsort(lp); cw = np.cumsum(w[o]) / w.sum()
        q = lambda p: np.exp(lp[o][np.searchsorted(cw, p)])
        return pd.Series({"price": np.exp(np.average(lp, weights=w)), "price_low": q(0.10), "price_high": q(0.90)})
    out = rows.groupby("profile_id")[["w", "pred_price", "address"]].apply(agg).reset_index()
    out[["price", "price_low", "price_high"]] = out[["price", "price_low", "price_high"]].round(-3)
    return out, rows

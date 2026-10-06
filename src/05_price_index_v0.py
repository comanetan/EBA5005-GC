"""Step 5 (offline): quality-adjusted price index, v0 and (once location features exist) v1. Hand-over to the Forecasting Lead.
Time-dummy hedonic method: within each region x flat type, regress log(price) on flat characteristics + a dummy for every
month. The month coefficients are price changes holding quality fixed; exp(coef) x 100 is the index (Jan 2017 = 100).

v0 controls (no coordinates needed): log floor area, remaining lease (+ squared), storey, flat-model family, town.
v1 adds location features (MRT, amenities) once geocoding is done. Same output format, so Forecasting just swaps the file.
Output: outputs/price_index_v0.csv  (month, region, flat_type, index, n_sales, median_price)"""
import numpy as np, pandas as pd
import config as C

TYPES = ["2 ROOM", "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE"]

LOCATION = ["log_dist_mrt", "log_dist_hawker", "log_dist_park", "n_primary_1km", "n_chas_500m", "n_preschool_500m"]

def time_dummy_index(d, location=False):
    d = d.copy()
    d["log_area"] = np.log(d["floor_area_sqm"])
    d["lease2"] = d["remaining_lease_yrs"] ** 2 / 100
    controls = ["log_area", "remaining_lease_yrs", "lease2", "storey_mid"]
    if location:                                   # v1: MRT distance AT TIME OF SALE + amenities
        for c, src in [("log_dist_mrt", "dist_mrt_at_sale_m"), ("log_dist_hawker", "dist_hawker_m"), ("log_dist_park", "dist_park_m")]:
            d[c] = np.log1p(d[src])
        controls += LOCATION
    X = pd.concat([
        d[controls],
        pd.get_dummies(d["flat_model_group"], prefix="fm", drop_first=True, dtype=float),
        pd.get_dummies(d["town"], prefix="town", drop_first=True, dtype=float),
        pd.get_dummies(d["month"], prefix="m", dtype=float).iloc[:, 1:],        # first month = base (index 100)
    ], axis=1)
    X.insert(0, "const", 1.0)
    y = np.log(d["resale_price"].to_numpy())
    beta, *_ = np.linalg.lstsq(X.to_numpy(float), y, rcond=None)
    resid = y - X.to_numpy(float) @ beta
    r2 = 1 - resid.var() / y.var()
    coefs = pd.Series(beta, index=X.columns)
    months = sorted(d["month"].unique())
    idx = pd.Series([0.0] + [coefs.get(f"m_{m}", np.nan) for m in months[1:]], index=months)
    return (np.exp(idx) * 100).round(2), r2, coefs

def build(df, location, out_name):
    out, fit = [], []
    segments = [(r, t) for r in C.REGIONS for t in TYPES] + [("ALL", t) for t in TYPES]
    for region, ft in segments:
        d = df[(df["flat_type"] == ft) & ((df["region"] == region) | (region == "ALL"))]
        if len(d) < 500:
            print(f"skip {region} {ft}: only {len(d)} sales"); continue
        idx, r2, coefs = time_dummy_index(d, location)
        g = d.groupby("month")["resale_price"].agg(n_sales="size", median_price="median")
        out.append(pd.DataFrame({"month": idx.index, "region": region, "flat_type": ft, "index": idx.values})
                   .merge(g, left_on="month", right_index=True))
        row = {"region": region, "flat_type": ft, "n": len(d), "r2": round(r2, 3), "min_monthly_n": int(g["n_sales"].min()),
               "index_latest": idx.iloc[-1]}
        if location:
            row["mrt_elasticity"] = round(coefs["log_dist_mrt"], 3)
        fit.append(row)
    res = pd.concat(out, ignore_index=True)
    res.to_csv(C.OUTPUTS / out_name, index=False)
    fit = pd.DataFrame(fit)
    print(fit.to_string(index=False))
    print(f"\n-> outputs/{out_name}: {len(res):,} rows, {fit.shape[0]} series, {res['month'].min()} to {res['month'].max()}\n")
    return fit

df = pd.read_csv(C.RESALE_CLEAN, dtype={"block": str})
df = df[df["in_scope"] & ~df["psm_outlier"] & df["flat_type"].isin(TYPES)]
print("== v0: flat characteristics only"); build(df, False, "price_index_v0.csv")

feat = C.PROCESSED / "resale_features.csv"
if feat.exists():                                  # v1 once location features exist (after geocoding + step 4)
    d1 = pd.read_csv(feat, dtype={"block": str}, low_memory=False)
    d1 = d1[d1["in_scope"] & ~d1["psm_outlier"] & d1["flat_type"].isin(TYPES)].dropna(subset=["dist_mrt_at_sale_m", "dist_park_m"])
    print("== v1: + location (MRT at time of sale, hawker, park, schools, clinics, preschools)"); build(d1, True, "price_index_v1.csv")

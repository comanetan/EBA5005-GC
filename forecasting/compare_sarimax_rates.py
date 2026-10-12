"""Origin-refitted v0 hedonic index + paired ARIMA/SARIMA vs SORA experiment.

Run: python -m forecasting.compare_sarimax_rates
Deliberately uses raw flat controls (v0), NOT the full-sample location-adjusted v1.
Current-vintage retrospective experiment; not a pristine final project holdout.
"""
from pathlib import Path
import importlib.util
import json
import warnings
import hashlib
import numpy as np
import pandas as pd
from scipy.stats import norm
from statsmodels.tsa.statespace.sarimax import SARIMAX
from .prepare_mas_rates import parse_mas, prepare_monthly, SOURCE as RATE_SOURCE

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "outputs/sarimax_experiment"
REGION, FLAT_TYPE = "NORTH-EAST", "4 ROOM"
DATES = pd.date_range("2017-01", "2026-09", freq="MS")
SPECS = {
    "ARIMA_011_drift": ((0, 1, 1), (0, 0, 0, 0), "c"),
    "SARIMA_110_100": ((1, 1, 0), (1, 0, 0, 12), "n"),
}


def source_data(region=REGION, flat_type=FLAT_TYPE):
    spec = importlib.util.spec_from_file_location("team_config", ROOT / "src/config.py")
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)  # Constants only; no pipeline execution.
    df = pd.read_csv(config.RESALE)
    df["month"] = pd.to_datetime(df.month)
    df = df[df.town.isin(config.REGIONS[region]) & df.flat_type.eq(flat_type)
            & df.month.between(DATES[0], DATES[-1]) & ~df.flat_model.isin(["Terrace"])].copy()
    if df.empty or df[["resale_price", "floor_area_sqm"]].isna().any().any():
        raise ValueError("Missing core price data.")
    if not np.isfinite(df[["resale_price", "floor_area_sqm"]]).all().all() or (df[["resale_price", "floor_area_sqm"]] <= 0).any().any():
        raise ValueError("Invalid area or price.")
    lease = df.remaining_lease.str.extract(r"(?P<years>\d+) years?(?: (?P<months>\d+) months?)?")
    df["lease"] = pd.to_numeric(lease.years) + pd.to_numeric(lease.months).fillna(0)/12
    storey = df.storey_range.str.extract(r"(\d+) TO (\d+)").astype(float)
    df["storey"] = storey.mean(axis=1)
    df["log_area"] = np.log(df.floor_area_sqm)
    df["lease2"] = df.lease ** 2 / 100
    df["flat_model_group"] = df.flat_model.map(config.FLAT_MODEL_GROUPS)
    if df[["lease", "storey", "flat_model_group"]].isna().any().any():
        raise ValueError("Unparsed attributes; investigate before modelling.")
    # No full-year outlier screen: such a screen could inspect future values.
    return df, config.RESALE


def design(frame, levels, extra_controls=()):
    x = frame[["log_area", "lease", "lease2", "storey"]].copy()
    for column in extra_controls:
        x[column] = frame[column]
    for col, categories in levels.items():
        if not frame[col].isin(categories).all():
            raise ValueError(f"Unseen {col} at evaluation: specify handling rather than silently map.")
        for value in categories[1:]:
            x[f"{col}={value}"] = frame[col].eq(value).astype(float)
    return x.astype(float)


def refit_index(df, end, evaluation_end, extra_controls=()):
    train = df[df.month <= end].copy()
    test = df[(df.month > end) & (df.month <= evaluation_end)].copy()
    levels = {c: sorted(train[c].unique()) for c in ["town", "flat_model_group"]}
    x = design(train, levels, extra_controls)
    logp = pd.Series(np.log(train.resale_price), index=train.index)
    # Within-month demeaning is equivalent to fitting month fixed effects + controls.
    xd = x - x.groupby(train.month).transform("mean")
    yd = logp - logp.groupby(train.month).transform("mean")
    beta, _, rank, _ = np.linalg.lstsq(xd.to_numpy(), yd.to_numpy(), rcond=None)
    if rank < x.shape[1]:
        raise ValueError("Rank-deficient hedonic controls.")
    adjusted = logp.to_numpy() - x.to_numpy() @ beta
    alpha = pd.Series(adjusted, index=train.index).groupby(train.month).mean()
    base = alpha.iloc[0]
    train_index = (100*np.exp(alpha-base)).reindex(pd.date_range(DATES[0], end, freq="MS"))
    if train_index.isna().any():
        raise ValueError("Missing training index month.")
    test_index = pd.Series(dtype=float)
    if len(test):
        adjusted_test = np.log(test.resale_price.to_numpy()) - design(test, levels, extra_controls).to_numpy() @ beta
        test_index = 100*np.exp(pd.Series(adjusted_test, index=test.index).groupby(test.month).mean()-base)
        test_index = test_index.reindex(pd.date_range(end + pd.offsets.MonthBegin(1), evaluation_end, freq="MS"))
        if test_index.isna().any():
            raise ValueError("Missing evaluation index month.")
    return train_index, test_index


def run_forecast(y, rates, name, future_dates):
    z = np.log(y)
    h = np.arange(1, len(future_dates)+1)
    info = {}
    if name == "naive":
        mu = np.repeat(z.iloc[-1], len(h)); var = np.mean(z.diff().dropna()**2)*h
    elif name == "seasonal_naive":
        mu = np.resize(z.iloc[-12:], len(h)); var = np.mean(z.diff(12).dropna()**2)*np.ceil(h/12)
    else:
        use_rate = name.endswith("_SORA")
        base = name.removesuffix("_SORA")
        order, seasonal, trend = SPECS[base]
        x = future_x = None
        if use_rate:
            # Target month t uses rate published by END of month t-1.
            x = rates.sora_3m_eom_lag1_pct_pa.reindex(y.index).to_frame("lagged_sora_3m")
            if x.isna().any().any(): raise ValueError("Missing training regressor.")
            # Last known rate held flat for all future months, NOT realised future rates.
            last_known = float(rates.loc[y.index[-1], "sora_3m_eom_pct_pa"])
            future_x = pd.DataFrame({"lagged_sora_3m": last_known}, index=future_dates)
            info["future_rate_scenario_pct_pa"] = last_known
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fit = SARIMAX(z, exog=x, order=order, seasonal_order=seasonal, trend=trend).fit(disp=False, maxiter=500)
            if not fit.mle_retvals.get("converged", False):
                # Numerical retry, same data/specification; no model change based on test errors.
                fit = fit.model.fit(method="powell", disp=False, maxiter=1000)
                info["optimizer_retry"] = "powell"
        info.update(converged=bool(fit.mle_retvals.get("converged")), aic=float(fit.aic),
                    warnings=" | ".join(str(w.message) for w in caught))
        if not info["converged"]: raise ValueError("Nonconvergent model fit.")
        p = fit.get_forecast(len(h), exog=future_x)
        mu, var = np.asarray(p.predicted_mean), np.asarray(p.var_pred_mean)
        if use_rate: info["rate_coefficient"] = float(fit.params["lagged_sora_3m"])
    sd = np.sqrt(np.maximum(var, 0))
    values = np.exp(np.column_stack([mu, mu-norm.ppf(.95)*sd, mu+norm.ppf(.95)*sd]))
    if not np.isfinite(values).all(): raise ValueError("Non-finite forecast.")
    return pd.DataFrame(values, index=future_dates, columns=["forecast_index", "lower90", "upper90"]), info


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df, raw_path = source_data()
    rates = prepare_monthly(parse_mas(RATE_SOURCE))
    rates.index = pd.to_datetime(rates.month)
    models = ["naive", "seasonal_naive", *SPECS, *(m+"_SORA" for m in SPECS)]
    records, logs, index_rows = [], [], []
    for end_i in [69, 81, 93, 105]:
        origin = DATES[end_i-1]; end = DATES[end_i+11]
        stage = "validation" if end_i < 105 else "later_period_check"
        train, actual = refit_index(df, origin, end)
        for kind, series in [("training", train), ("evaluation_frozen_coefficients", actual)]:
            index_rows.extend(dict(origin=str(origin.date()), month=str(d.date()), kind=kind, index=float(v)) for d,v in series.items())
        for name in models:
            print(f"{origin:%Y-%m}: {name}", flush=True)
            try:
                prediction, info = run_forecast(train, rates, name, actual.index)
                for horizon, (month, row) in enumerate(prediction.iterrows(), 1):
                    records.append(dict(stage=stage, model=name, origin=str(origin.date()), month=str(month.date()),
                                        horizon=horizon, actual_index=float(actual.loc[month]), **row.to_dict()))
                logs.append(dict(origin=str(origin.date()), model=name, **info))
            except Exception as exc:
                logs.append(dict(origin=str(origin.date()), model=name, error=str(exc)))
    pred = pd.DataFrame(records)
    pred.to_csv(OUT / "predictions.csv", index=False)
    pd.DataFrame(logs).to_csv(OUT / "fit_log.csv", index=False)
    pd.DataFrame(index_rows).to_csv(OUT / "origin_specific_indices.csv", index=False)
    metrics = []
    for (stage, model), g in pred.groupby(["stage", "model"]):
        for window, s in [("months_1_to_12", g), ("month_6", g[g.horizon==6]), ("month_12", g[g.horizon==12])]:
            error = (s.forecast_index-s.actual_index).abs()
            metrics.append(dict(stage=stage, model=model, window=window, n=len(s),
                                MAE_index=float(error.mean()), MAPE_pct=float((error/s.actual_index).mean()*100),
                                coverage90_pct=float(s.actual_index.between(s.lower90,s.upper90).mean()*100)))
    metrics = pd.DataFrame(metrics)
    metrics.to_csv(OUT / "metrics.csv", index=False)
    ranking=metrics[(metrics.stage=="validation") & (metrics.window=="months_1_to_12") & (metrics.n==36)].sort_values("MAPE_pct")
    winner = ranking.iloc[0].model
    full, _ = refit_index(df, DATES[-1], DATES[-1])
    future_dates = pd.date_range("2026-10", periods=12, freq="MS")
    future,final_info = run_forecast(full,rates,winner,future_dates)
    (OUT / "final_fit.json").write_text(json.dumps(final_info,indent=2),encoding="utf-8")
    future["growth_factor"] = future.forecast_index / full.iloc[-1]
    future["model"] = winner
    future.to_csv(OUT / "candidate_future_forecast.csv", index_label="month")
    manifest=dict(region=REGION, flat_type=FLAT_TYPE, winner_by_validation_mape=winner,
                  transaction_rows=len(df), source_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                  rate_source_sha256=hashlib.sha256(RATE_SOURCE.read_bytes()).hexdigest(),
                  index="origin-refitted v0 flat-controls; frozen-coefficient evaluation",
                  rate_scenario="last published origin-month rate held constant",
                  limitations=["No location/amenity controls yet; not Comane's v1 index.",
                               "Current data vintages; original historical availability of back-calculated compounded rates not reconstructed.",
                               "Same recent calendar year was seen in preliminary work: later-period check is not pristine final holdout.",
                               "Intervals conditional on fixed rate scenario; exclude index-estimation and regressor uncertainty.",
                               "Single regional segment; no automatic change to saved UI model or shared handover."])
    (OUT / "manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    assert (pd.to_datetime(pred.month)>pd.to_datetime(pred.origin)).all()
    assert ((pred.lower90<=pred.forecast_index)&(pred.forecast_index<=pred.upper90)).all()
    print(metrics[metrics.window=="months_1_to_12"].to_string(index=False))
    print(f"Validation-selected candidate: {winner}")


if __name__ == "__main__": main()

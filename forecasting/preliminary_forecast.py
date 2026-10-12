"""Preliminary HDB forecasting: run this file, not individual copied fragments.

Target: monthly median transaction price per square metre, NOT a hedonic index.
Course: CPMF Day 4, Seasonal ARIMA and ARIMAX (July 2026), especially pp. 7-12,
26-34. Macro regressors (pp. 37-45), LSTM and price-path simulation come later.
"""
from pathlib import Path
import hashlib
import json
import platform
import os
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import scipy
from scipy.stats import norm
# Keep the font cache in the project, including in restricted environments.
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parent / ".mplconfig"))
import matplotlib
matplotlib.use("Agg")  # Save charts reliably, including from the VS Code terminal.
import matplotlib.pyplot as plt
import statsmodels
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.graphics.tsaplots import plot_acf, plot_pacf
if __package__:
    from .model_api import export_model
else:
    from model_api import export_model

# ---------- SETTINGS: these are the only lines you usually need to change ----------
RAW_CSV = Path(os.environ.get(
    "HDB_RESALE_CSV",
    str(Path(__file__).resolve().parents[1] / "data" / "raw" /
        "ResaleflatpricesbasedonregistrationdatefromJan2017onwards.csv"),
))
START_MONTH = "2017-01"
CUTOFF_MONTH = "2026-09"  # October is incomplete. Do not silently use today's month.
TOWN = None  # None chooses a well-supported example using INITIAL TRAINING data only.
FLAT_TYPE = "4 ROOM"  # To choose manually, also set TOWN, e.g. "TAMPINES".
HORIZON = 12
INTERVAL_LEVEL = 0.90
OUT = Path(__file__).resolve().parent / "outputs"

# Small, predeclared candidate set. Seasonal models must earn their place.
# Values: ordinary order (p,d,q), seasonal order (P,D,Q,s), deterministic trend.
SPECS = {
    "ARIMA_110": ((1, 1, 0), (0, 0, 0, 0), "n"),
    "ARIMA_011": ((0, 1, 1), (0, 0, 0, 0), "n"),
    "ARIMA_011_drift": ((0, 1, 1), (0, 0, 0, 0), "c"),
    "SARIMA_011_011_12": ((0, 1, 1), (0, 1, 1, 12), "n"),
    "SARIMA_110_100_12": ((1, 1, 0), (1, 0, 0, 12), "n"),
}
MODELS = ["naive", "seasonal_naive", *SPECS]
FIT_LOG = []


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")


def read_and_aggregate():
    if not RAW_CSV.exists():
        raise FileNotFoundError(f"Data not found. Check RAW_CSV at the top:\n{RAW_CSV}")
    df = pd.read_csv(RAW_CSV)
    required = ["month", "town", "flat_type", "floor_area_sqm", "resale_price"]
    if not set(required).issubset(df.columns):
        raise ValueError(f"Required columns: {required}")
    raw_rows = len(df)
    duplicate_rows = int(df.duplicated().sum())
    # Anonymous records can coincide: report duplicate-looking rows, do not delete.
    df["month"] = pd.to_datetime(df["month"], format="%Y-%m", errors="coerce")
    for col in ["floor_area_sqm", "resale_price"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    valid = (df[required].notna().all(axis=1)
             & np.isfinite(df["floor_area_sqm"]) & np.isfinite(df["resale_price"])
             & df["floor_area_sqm"].gt(0) & df["resale_price"].gt(0))
    if (~valid).any():
        df.loc[~valid].to_csv(OUT / "invalid_rows.csv", index=False)
    after = int((valid & df.month.gt(pd.Timestamp(CUTOFF_MONTH))).sum())
    clean = df.loc[valid & df.month.between(pd.Timestamp(START_MONTH),
                                           pd.Timestamp(CUTOFF_MONTH))].copy()
    clean["price_psm"] = clean.resale_price / clean.floor_area_sqm
    monthly = clean.groupby(["town", "flat_type", "month"], as_index=False).agg(
        median_price_psm=("price_psm", "median"),
        transaction_count=("price_psm", "size"),
    )
    monthly.to_csv(OUT / "monthly_town_flat_type.csv", index=False)
    audit = dict(source=str(RAW_CSV), source_sha256=hashlib.sha256(RAW_CSV.read_bytes()).hexdigest(),
                 run_time_singapore=str(datetime.now(ZoneInfo("Asia/Singapore"))),
                 raw_rows=raw_rows, invalid_rows=int((~valid).sum()),
                 duplicate_looking_rows_retained=duplicate_rows,
                 excluded_valid_rows_after_cutoff=after, included_rows=len(clean),
                 cutoff=CUTOFF_MONTH, start=START_MONTH,
                 target="monthly median SGD per square metre; not quality adjusted",
                 warning="Latest downloaded vintage; historical revisions/publication lags not reconstructed.")
    save_json(OUT / "data_audit.json", audit)
    return monthly, audit


def choose_series(monthly, dates, initial_end):
    rows = []
    for (town, flat), group in monthly.groupby(["town", "flat_type"]):
        counts = group.set_index("month").transaction_count.reindex(dates, fill_value=0)
        first = counts.iloc[:initial_end]
        rows.append(dict(town=town, flat_type=flat,
                         initial_missing_months=int(first.eq(0).sum()),
                         initial_median_monthly_count=float(first.median()),
                         initial_total_transactions=int(first.sum()),
                         full_missing_months=int(counts.eq(0).sum()),
                         full_months_below_10=int(counts.lt(10).sum())))
    coverage = pd.DataFrame(rows)
    coverage.to_csv(OUT / "segment_coverage.csv", index=False)
    eligible = coverage.loc[(coverage.flat_type == FLAT_TYPE)
                            & coverage.initial_missing_months.eq(0)
                            & coverage.initial_median_monthly_count.ge(10)]
    if TOWN is not None:
        eligible = eligible.loc[eligible.town == TOWN]
    if eligible.empty:
        raise ValueError("No eligible segment. Inspect segment_coverage.csv; do not fill missing prices with zero.")
    # Coverage screen is an engineering choice, not a statistical guarantee.
    selected = eligible.sort_values(["initial_total_transactions", "town"],
                                    ascending=[False, True]).iloc[0]
    g = monthly.loc[(monthly.town == selected.town)
                    & (monthly.flat_type == selected.flat_type)].set_index("month").reindex(dates)
    if g.median_price_psm.isna().any():
        raise ValueError("Chosen segment has later missing months. Stop and review aggregation; no silent imputation.")
    g.index.name = "month"
    g.to_csv(OUT / "selected_segment_monthly.csv")
    return g, selected.town


def forecast(train, name, steps, stage):
    """Fit on log prices. Back-transformed centre is a predictive MEDIAN, not mean."""
    z = np.log(train)
    result = None
    h = np.arange(1, steps + 1)
    if name == "naive":
        centre = np.repeat(z.iloc[-1], steps)
        variance = float(np.mean(np.square(z.diff().dropna()))) * h
    elif name == "seasonal_naive":
        centre = np.resize(z.iloc[-12:].to_numpy(), steps)
        variance = float(np.mean(np.square(z.diff(12).dropna()))) * np.ceil(h / 12)
    else:
        order, seasonal, trend = SPECS[name]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = SARIMAX(z, order=order, seasonal_order=seasonal, trend=trend,
                             enforce_stationarity=True, enforce_invertibility=True).fit(
                                 disp=False, maxiter=300)
        converged = bool(result.mle_retvals.get("converged", False))
        FIT_LOG.append(dict(stage=stage, model=name, train_end=str(train.index[-1].date()),
                            converged=converged, aic=float(result.aic), bic=float(result.bic),
                            warnings=" | ".join(str(w.message) for w in caught)))
        if not converged:
            raise ValueError("Optimizer did not converge; candidate excluded for this stage.")
        pred = result.get_forecast(steps=steps)
        centre, variance = np.asarray(pred.predicted_mean), np.asarray(pred.var_pred_mean)
    quantile = norm.ppf((1 + INTERVAL_LEVEL) / 2)
    spread = quantile * np.sqrt(np.maximum(variance, 0))
    with np.errstate(over="raise", invalid="raise"):
        values = np.column_stack([np.exp(centre), np.exp(centre - spread), np.exp(centre + spread)])
    if not np.isfinite(values).all():
        raise ValueError("Non-finite predictions.")
    future_dates = pd.date_range(train.index[-1] + pd.offsets.MonthBegin(1), periods=steps, freq="MS")
    frame = pd.DataFrame(values, columns=["forecast_psm", "lower_90_psm", "upper_90_psm"], index=future_dates)
    frame.index.name = "month"
    return frame, result


def evaluate(train, actual, name, stage):
    pred, fitted = forecast(train, name, len(actual), stage)
    pred["actual_psm"] = actual
    pred["model"] = name
    pred["stage"] = stage
    pred["origin"] = train.index[-1]
    pred["horizon"] = np.arange(1, len(actual) + 1)
    return pred.reset_index(), fitted


def scores(pred):
    rows = []
    for name, group in pred.groupby("model"):
        for label, subset in [("months_1_to_6", group[group.horizon <= 6]),
                              ("months_1_to_12", group),
                              ("exact_month_6", group[group.horizon == 6]),
                              ("exact_month_12", group[group.horizon == 12])]:
            error = subset.actual_psm - subset.forecast_psm
            rows.append(dict(model=name, evaluation_window=label, n_predictions=len(subset),
                             MAE_psm=float(error.abs().mean()),
                             RMSE_psm=float(np.sqrt(np.mean(error ** 2))),
                             MAPE_pct=float((error.abs() / subset.actual_psm).mean() * 100),
                             coverage_90_pct=float(subset.actual_psm.between(
                                 subset.lower_90_psm, subset.upper_90_psm).mean() * 100),
                             average_interval_width_psm=float((subset.upper_90_psm-subset.lower_90_psm).mean())))
    return pd.DataFrame(rows)


def diagnostic_plots(series, initial_end, selected_name, fitted):
    # Identification only uses the earliest training window; final holdout stays unseen.
    z = np.log(series.iloc[:initial_end])
    diff = z.diff().dropna()
    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    z.plot(ax=axes[0, 0], title="Initial training: log price per m2")
    diff.plot(ax=axes[0, 1], title="First difference of log price")
    plot_acf(diff, lags=min(24, len(diff)//2-1), ax=axes[1, 0])
    plot_pacf(diff, lags=min(24, len(diff)//2-1), method="ywm", ax=axes[1, 1])
    fig.tight_layout(); fig.savefig(OUT / "02_initial_training_diagnostics.png", dpi=150); plt.close(fig)
    adf = []
    for label, vals in [("log_level", z), ("first_difference_log", diff)]:
        test = adfuller(vals, autolag="AIC")
        adf.append(dict(series=label, statistic=test[0], p_value=test[1], lags=test[2], observations=test[3]))
    pd.DataFrame(adf).to_csv(OUT / "stationarity_initial_training.csv", index=False)
    if fitted is None:
        residual = np.log(series).diff(12 if selected_name == "seasonal_naive" else 1).dropna()
        model_df = 0
    else:
        burn = max(13, int(fitted.loglikelihood_burn))
        residual = pd.Series(np.asarray(fitted.filter_results.standardized_forecasts_error)[0],
                             index=series.index).iloc[burn:].dropna()
        order, seasonal, _ = SPECS[selected_name]
        model_df = order[0] + order[2] + seasonal[0] + seasonal[2]
        (OUT / "selected_model_summary.txt").write_text(str(fitted.summary()), encoding="utf-8")
    acorr_ljungbox(residual, lags=[12, 24], model_df=model_df, return_df=True).to_csv(
        OUT / "residual_ljung_box_final_fit.csv", index_label="lag")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    residual.plot(ax=axes[0], title="Final-fit residual diagnostic")
    plot_acf(residual, lags=24, ax=axes[1])
    fig.tight_layout(); fig.savefig(OUT / "05_final_residuals.png", dpi=150); plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not 0 < INTERVAL_LEVEL < 1 or INTERVAL_LEVEL != 0.90:
        raise ValueError("This starter labels outputs as 90% intervals; keep INTERVAL_LEVEL=0.90.")
    dates = pd.date_range(START_MONTH, CUTOFF_MONTH, freq="MS")
    n = len(dates)
    # Three 12-month validation windows, then an untouched 12-month final test.
    origins = [n - 48, n - 36, n - 24]
    if origins[0] < 48:
        raise ValueError("Need at least 96 months for this predeclared evaluation design.")
    monthly, audit = read_and_aggregate()
    group, town = choose_series(monthly, dates, origins[0])
    y = group.median_price_psm.astype(float)
    print(f"Selected example: {town}, {FLAT_TYPE}. {len(y)} monthly observations.", flush=True)
    print("Target: median SGD/m2, NOT individual flat prices or a hedonic index.", flush=True)
    validation = []
    for end in origins:
        for name in MODELS:
            stage = f"validation_{dates[end-1]:%Y-%m}"
            print(f"{stage}: {name}", flush=True)
            try:
                pred, _ = evaluate(y.iloc[:end], y.iloc[end:end+12], name, stage)
                validation.append(pred)
            except Exception as exc:
                FIT_LOG.append(dict(stage=stage, model=name, error=str(exc)))
    val = pd.concat(validation, ignore_index=True)
    val.to_csv(OUT / "validation_predictions.csv", index=False)
    table = scores(val)
    complete = val.groupby("model").size().eq(36)
    table["all_validation_folds_succeeded"] = table.model.map(complete)
    table.to_csv(OUT / "validation_metrics.csv", index=False)
    ranking = table.loc[(table.evaluation_window == "months_1_to_12")
                         & table.all_validation_folds_succeeded].sort_values(["MAE_psm", "model"])
    # Lock selection BEFORE looking at the final 12 months.
    winner = ranking.iloc[0].model
    print(f"Validation-selected model: {winner}", flush=True)
    test_names = list(dict.fromkeys([winner, "naive", "seasonal_naive"]))
    test_frames = [evaluate(y.iloc[:-12], y.iloc[-12:], name, "final_holdout")[0]
                   for name in test_names]
    holdout = pd.concat(test_frames, ignore_index=True)
    holdout.to_csv(OUT / "holdout_predictions.csv", index=False)
    holdout_scores = scores(holdout)
    holdout_scores.to_csv(OUT / "holdout_metrics.csv", index=False)
    future, fitted = forecast(y, winner, HORIZON, "final_refit_all_data")
    future["model"] = winner
    future["town"] = town
    future["flat_type"] = FLAT_TYPE
    future["origin"] = y.index[-1]
    future["horizon"] = np.arange(1, HORIZON+1)
    future["target"] = "monthly_median_price_per_sqm"
    future["point_estimate"] = "predictive_median"
    future["interval_level"] = INTERVAL_LEVEL
    future.to_csv(OUT / "forecast_next_12_months.csv")
    fig, ax = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    ax[0].plot(y.index, y.to_numpy())
    ax[0].set_title(f"{town} | {FLAT_TYPE}: monthly median transaction price per m2")
    ax[0].set_ylabel("SGD/m2")
    ax[0].axvline(y.index[-12], color="red", linestyle="--", label="Final test starts")
    ax[0].legend()
    ax[1].bar(y.index, group.transaction_count, width=22)
    ax[1].set_ylabel("Transactions")
    fig.tight_layout(); fig.savefig(OUT / "01_price_and_volume.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(y.index[-24:], y.to_numpy()[-24:], color="black", label="Observed")
    for name, g in holdout.groupby("model"):
        ax.plot(g.month, g.forecast_psm, label=name)
    ax.axvline(y.index[-12], color="grey", linestyle="--")
    ax.set(title="Final holdout: selection was locked before this period", ylabel="SGD/m2")
    ax.legend(); fig.tight_layout(); fig.savefig(OUT / "03_holdout_comparison.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(y.index[-36:], y.to_numpy()[-36:], label="Observed")
    ax.plot(future.index, future.forecast_psm, label=f"Forecast: {winner}")
    ax.fill_between(future.index, future.lower_90_psm, future.upper_90_psm, alpha=.2,
                    label="90% model-based pointwise prediction interval")
    ax.set(title=f"{town} | {FLAT_TYPE}: preliminary forecast", ylabel="SGD/m2")
    ax.legend(); fig.tight_layout(); fig.savefig(OUT / "04_future_forecast.png", dpi=150); plt.close(fig)
    diagnostic_plots(y, origins[0], winner, fitted)
    audit.update(selected_town=town, flat_type=FLAT_TYPE, selected_model=winner,
                 selection_rule="Lowest mean validation absolute error across all 36 predictions",
                 initial_training_end=str(dates[origins[0]-1].date()),
                 validation_origins=[str(dates[i-1].date()) for i in origins],
                 holdout_start=str(dates[-12].date()), holdout_end=str(dates[-1].date()),
                 versions=dict(python=platform.python_version(), pandas=pd.__version__,
                               numpy=np.__version__, scipy=scipy.__version__,
                               statsmodels=statsmodels.__version__, matplotlib=matplotlib.__version__))
    save_json(OUT / "run_manifest.json", audit)
    export_model(Path(__file__).resolve().parent / "models" / "preliminary", y, winner, fitted, audit)
    pd.DataFrame(FIT_LOG).to_csv(OUT / "model_fit_log.csv", index=False)
    report = f"""# Preliminary forecasting run

Example: {town}, {FLAT_TYPE}. Model selected on validation: {winner}.
See validation_metrics.csv and holdout_metrics.csv; do not select again using holdout errors.
MAE is in SGD per square metre. Smaller is better. MAPE and coverage are percentages.
Coverage estimated from one final year is imprecise; use validation folds as additional evidence.

## Interpretation boundaries
- This is a single coverage-selected example, not evidence for all towns or flat types.
- Monthly median price per m2 changes when the mix of sold flats changes. It is not quality adjusted.
- Point forecasts are predictive medians after exponentiating log forecasts.
- 90% intervals are pointwise, conditional model intervals, not guarantees or simultaneous price paths.
- They do not include individual-flat valuation error, model-selection uncertainty or data revisions.
- This retrospective experiment uses the current data vintage, not historical release snapshots.
- A low ADF p-value is evidence against a unit root, not proof of model suitability.
- Low Ljung-Box p-values flag residual dependence. A high value does not establish accuracy.
- No external regressors, hedonic index, LSTM, SHAP or Monte Carlo paths are implemented yet.
- Do not send this proxy straight to the optimiser as calibrated individual-flat affordability risk.

## Course link
CPMF Day 4, Seasonal ARIMA and ARIMAX (July 2026): pp. 7-12 planning and workflow;
pp. 26-31 seasonality/differencing/ACF/PACF; pp. 32-34 residual diagnostics and AIC/BIC.
The small candidate set is a starter comparison, not an exhaustive automatic specification search.
ARIMAX external inputs (pp. 37-45) are the next stage after source and timing checks.
"""
    (OUT / "RESULTS_README.md").write_text(report, encoding="utf-8")
    print("\nFINAL HOLDOUT (not used to choose model):")
    print(holdout_scores.loc[holdout_scores.evaluation_window.eq("months_1_to_12")].to_string(index=False))
    print(f"\nSaved outputs to: {OUT}")


if __name__ == "__main__":
    try:
        main()
    finally:
        # Preserve failed fits as well, even if a later stage stops execution.
        if FIT_LOG and OUT.exists():
            pd.DataFrame(FIT_LOG).to_csv(OUT / "model_fit_log.csv", index=False)

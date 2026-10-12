# Yi Ling's preliminary HDB forecasting

This folder contains the complete runnable Python script, not pseudocode.
The shared OneDrive source is read only. All results are saved under `forecasting/outputs`.

The script now also exports a saved model under `forecasting/models/preliminary`.
For Daniel's UI integration, see `HANDOVER.md`: `Forecaster.predict()` loads this bundle
without the raw CSV and without retraining. Try `python -m forecasting.example_ui_call`.

## Run in the team repository

From the repository root, use a Python 3.12 environment:

```powershell
python -m pip install -r forecasting/requirements-tested.txt
python -m forecasting.example_ui_call
```

The example loads the saved model; it does not train or need raw data.
To rebuild and evaluate: `python forecasting/preliminary_forecast.py`.
The training script defaults to the repository's
`data/raw/ResaleflatpricesbasedonregistrationdatefromJan2017onwards.csv`.
Override with the `HDB_RESALE_CSV` environment variable if needed.
The script reads raw data without modifying it. Outputs go to `forecasting/outputs`.

## Integration status

This preliminary example is not yet the team's final handover adapter. The team
README specifies `outputs/price_index_v1.csv` (region x flat type) as the target
and `outputs/price_paths.csv` (profile_id, month, p10, p50, p90) as the handover.
This package currently models one town/flat-type median-price-per-m2 proxy and
returns central intervals. It does not write or replace the shared handover files.
A central 90% interval is p5/p95, not p10/p90. Integration with the hedonic index,
profile mapping and appropriate quantile outputs remains pending.

## What happens

1. Check required fields and non-positive/non-finite price and area. Invalid rows are
   reported if present. Duplicate-looking anonymised transactions are retained.
2. Exclude months after September 2026. October is incomplete in this source.
3. Calculate price/m2 for each transaction, then take its monthly median by town/flat type.
   This is different from dividing median price by median area.
4. Select a 4-room example using transaction coverage and volume in the earliest training
   window only, not future errors. Require no missing months and median count >=10 in that
   window; this is a transparent screening rule, not proof of statistical reliability.
5. Compare naive, seasonal-naive, three ARIMA and two SARIMA specifications using log prices.
6. Use three expanding training windows, each followed by a non-overlapping 12-month
   validation window. Lock the model with the lowest pooled validation MAE.
7. Evaluate that model and baselines on the last 12 months, which were excluded from
   model selection. Do not change the winner merely because of these test results.
8. Refit the locked model to all included observations and forecast the following year.

For the default dates:

| Purpose | Train through | Forecast/evaluate |
|---|---|---|
| Validation 1 | September 2022 | October 2022-September 2023 |
| Validation 2 | September 2023 | October 2023-September 2024 |
| Validation 3 | September 2024 | October 2024-September 2025 |
| Final test | September 2025 | October 2025-September 2026 |
| Future forecast | September 2026 | October 2026-September 2027 |

This fixed split is a starting design. Repeatedly tuning after seeing the final test turns
it into development data; reserve a fresh evaluation before making final performance claims.

## Files to inspect first

- `01_price_and_volume.png`: are monthly prices noisy when transactions are sparse?
- `validation_metrics.csv`: the model selection results.
- `holdout_metrics.csv`: performance on the untouched last year.
- `03_holdout_comparison.png`: forecasts against actual prices.
- `04_future_forecast.png`: the selected model's preliminary future forecast.
- `forecast_next_12_months.csv`: numeric forecast and pointwise 90% bounds, in SGD/m2.
- `model_fit_log.csv`: warnings, convergence and AIC/BIC for statistical models.
- `stationarity_initial_training.csv`, `02_initial_training_diagnostics.png`: ADF and ACF/PACF.
- `residual_ljung_box_final_fit.csv`, `05_final_residuals.png`: residual dependence checks.
- `run_manifest.json`: source fingerprint, settings, split dates and versions.

MAE: typical absolute error in SGD/m2. MAPE: average absolute percentage error.
RMSE: penalises large errors more strongly. Coverage: fraction of observations within
the nominal 90% interval; intervals should be judged alongside their width.
The `months_1_to_6` row averages months 1-6; `exact_month_6` means the six-step endpoint.
Endpoint test metrics contain only one observation and are especially noisy.

## Lecture links

CPMF Day 4, `Seasonal ARIMA and ARIMAX_v2 (July 2026)`:

- pp. 7-12: define target, planning horizon, prepare data, estimate and validate.
- pp. 26-29: seasonal period 12, differencing, SARIMA notation.
- pp. 30-31: ACF/PACF for model identification; inspect the starter specifications critically.
- pp. 32-34: residuals, Ljung-Box, AIC/BIC. AIC/BIC are logged, while validation MAE
  is used to select across statistical models AND simple baselines on a common scale.
- pp. 37-45: external inputs/ARIMAX, reserved for the next stage.

Rolling validation and the untouched test operationalise out-of-sample assessment;
the specific split dates and candidate list are project choices, not copied lecture requirements.
Python uses the `SARIMAX` class with no external regressors, so these fits are ARIMA/SARIMA.

## Boundaries and next stages

This is a proxy for a market segment, not an individual-flat valuation model. Changing
transaction mix affects medians. Replace this target with the pricing lead's hedonic
index once its construction and historical refitting are agreed.

All point estimates are predictive medians in original units, after log modelling.
Intervals assume the fitted log-scale model; baseline bands use simple random-walk or
seasonal-random-walk innovation assumptions. Check empirical coverage. Parameter and
model-selection uncertainty, historical data revisions and flat-specific pricing error
are not included. Pointwise bands are not joint simulated paths or a guarantee that
an option remains affordable throughout the year.

Next: broader segment validation, trustworthy dated external regressors with future
scenarios, hedonic index handover, pooled LSTM and SHAP, then correlated price-path
simulation and recommender backtesting. These are not claimed as implemented here.

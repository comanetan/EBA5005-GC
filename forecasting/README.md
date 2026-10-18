# Yi Ling's preliminary HDB forecasting

**19 October final review:** start with [FINAL_REVIEW.md](FINAL_REVIEW.md) for
town validation, joint scenarios, LSTM explanations, residual diagnostics and
the dated optimiser replay. Reproducible results are in `evidence/final/`.
The original experiment notes below describe successive stages, not all the
current dashboard interface. Use `REGIONAL_HANDOVER.md` for current integration.

## Current dashboard handover

Use [REGIONAL_HANDOVER.md](REGIONAL_HANDOVER.md) and `regional_api.RegionalForecaster`
for the validation-selected regional model. `outputs/price_paths.csv` at repository
root supplies the agreed four-room profile-price quantiles. See
[EVALUATION.md](EVALUATION.md) for time splits and accuracy metrics.
The original `model_api.Forecaster` remains as a legacy preliminary interface.

## Pooled LSTM benchmark

The optional PyTorch experiment is now implemented and evaluated. See
[LSTM_BENCHMARK.md](LSTM_BENCHMARK.md) for setup, results, lecture links and limitations.
Run `python -m forecasting.compare_pooled_lstm` after the regional experiment.
It does not replace the saved preliminary UI model. Later sections describing the
original preliminary pipeline refer to that pipeline, not this separate experiment.

## Regional location-adjusted experiment

1. `python -m forecasting.build_location_inputs` reuses the team's feature scripts but
   redirects all generated data, reports and handovers into `forecasting/outputs/location_inputs`.
   It checks that existing shared output files are unchanged.
2. `python -m forecasting.compare_regional_location` compares six forecasting specifications
   across the five regions for 4-room flats, using four historical forecast origins.
3. `python -m unittest forecasting.test_location_index -v` checks that changing future
   transaction prices and location attributes cannot change the training index.

Results live under `forecasting/outputs/regional_location`. Start with `aggregate_metrics.csv`,
then `metrics_by_region.csv` and `validation_selected_models.csv`. The `manifest.json`
records limitations. Aggregate errors weight each region equally, not by transaction volume.

This is an origin-refitted v1-style hedonic index with area, lease, storey, town, flat model,
MRT distance and amenity controls. It deliberately ignores full-year outlier flags. The
current amenity snapshots are held fixed historically; they are not genuine as-of amenity
histories. MRT uses supplied opening dates but current exit geometry. Therefore these
are retrospective experiments, not fully vintage-correct live forecast simulations.

All 120 model-origin-region runs completed in the first run. ARIMA with drift won earlier
validation in every region (mean regional MAPE 1.43%), while naive performed best on
average in the later-year check (0.83%, vs 3.41% for ARIMA with drift). SORA did not improve
average validation error. Do not retrospectively switch winners using the later-year check.
These results do not include other flat types or a pooled LSTM. The saved UI bundle remains
the original preliminary model. Keep result scales distinct from the older SGD/m2 experiment.

## New experiment: origin-refitted hedonic index and SORA

Run `python -m forecasting.compare_sarimax_rates` from the repository root.
This tests NORTH-EAST 4 ROOM with origin-refitted flat controls (v0), not the
full-sample location-adjusted v1 index. It leaves the existing UI bundle unchanged.
Outputs: `forecasting/outputs/sarimax_experiment/metrics.csv`, `predictions.csv`,
`origin_specific_indices.csv`, `candidate_future_forecast.csv`, `fit_log.csv`,
`final_fit.json` and `manifest.json`.

Paired ARIMA/SARIMA specifications are compared with/without a one-month-lagged
3-month compounded SORA rate. Future rates use the last known value held flat.
Future realised rates never enter the forecast. The hedonic regression is refitted
at each origin; evaluation uses frozen training characteristic coefficients.
No full-year outlier screen or future-derived amenity adjustment is used.

Test timing protections: `python -m unittest forecasting.test_sarimax_experiment -v`.
These tests deliberately change future prices/rates and verify training/forecasts
stay unchanged. This does not reconstruct historical data vintages, and the recent
calendar year already appeared in earlier experiments, so it is labelled a later-period
check rather than a pristine final project holdout. Exact 6/12-month results use only
3 validation origins and 1 later-period origin; report that limitation.

Next: location-aware historical features and v1 refits, more regional segments,
pooled LSTM, uncertainty calibration, and the shared profile_id/p10/p50/p90 adapter.

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

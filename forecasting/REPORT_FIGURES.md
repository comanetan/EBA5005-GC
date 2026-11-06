# Forecasting report figures

From the repository root, with the forecasting dependencies installed:

```powershell
python -m forecasting.plot_report_figures
python -m forecasting.plot_forecast_fan --region NORTH-EAST --flat-type "4 ROOM"
```

The first command writes PNG and SVG figures, supporting CSVs and input hashes to
`forecasting/outputs/report_figures/`. The second writes a presentation fan chart
to `forecasting/outputs/presentation/`. Generated outputs are intentionally ignored
by Git. Only load the trusted fitted-model artifacts supplied with this project.
Neither command retrains models or changes the delivered forecasts.

## Suggested report placement and captions

| Figure | Placement | Caption / interpretation |
| --- | --- | --- |
| 01_index_acf_pacf | Index construction and time-series exploration | North-East 4-room quality-adjusted index, monthly log changes and their ACF/PACF. Bands are pointwise 95% references. These are descriptive plots of the final training series, not evidence of a separate order-selection exercise. |
| 02_residual_diagnostics | Model diagnostics | Standardised forecast errors of the selected North-East 4-room model, omitting the first 12 observations, with residual ACF, normal Q-Q and squared-residual ACF. Remaining dependence and departures from normality qualify model assumptions. |
| 03_all_segment_diagnostics | Model diagnostics | Ljung–Box (lag 12, AR/MA degrees-of-freedom adjustment) and ARCH LM (lag 6) p-values for all 15 selected models. Stars denote individual p-values below 0.05, without a multiplicity adjustment. |
| 04_model_comparison | Forecast evaluation | MAPE for all 12 candidates, separated into earlier model-selection origins and the later retrospective assessment. Lower is better; values measure index forecasts rather than individual-flat valuation. |
| 05_expanding_windows | Temporal validation | Expanding training windows and subsequent 12-month evaluation periods. The later assessment was inspected during development and is not an untouched final test. |
| 06_forecast_fan | Forecast outputs and uncertainty | North-East 4-room central forecast and empirical p10–p90 scenario range from September 2026. The range excludes profile-valuation uncertainty and does not guarantee future coverage. |
| 07_lstm_shap | Deep-learning benchmark and explainability | Permutation Shapley contributions to the pooled LSTM's 12-month log-growth forecast at the September 2025 origin. Red raises predicted log growth relative to the background; blue lowers it. These do not explain the selected ARIMA model or establish causality. |
| 08_interval_coverage | Scenario validation | Historical empirical coverage using fully matured earlier error paths. Coverage above the nominal reference indicates conservative ranges rather than exact calibration. |

The appendix contains equivalent index/ACF/PACF and residual panels for the other
14 segments, plus numerical exports for all 15. The script verifies the saved
training anchors and reproduces the recorded Ljung–Box and ARCH p-values before
exporting figures. `figure_sources.json` records model version and source hashes.

Use the all-segment diagnostic summary alongside the illustrative North-East
plots. A single segment cannot represent the diagnostic results of every model.
Do not describe these retrospective plots as diagnostics performed before model
selection, or describe non-significant comparisons as proof of equivalence.

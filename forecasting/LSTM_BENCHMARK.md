# Pooled LSTM experiment

Completed comparison (mean regional MAPE across all 12 forecast months; lower is better):

| Model | Three validation origins | Later period check |
|---|---:|---:|
| ARIMA with drift | 1.43% | 3.41% |
| ARIMA with SORA | 1.45% | 3.31% |
| SARIMA | 2.16% | 1.75% |
| SARIMA with SORA | 2.31% | 1.82% |
| Pooled LSTM | 1.99% | 3.74% |
| Last-value naive | 3.68% | 0.83% |
| Seasonal naive | 7.49% | 1.62% |

The fixed LSTM does not improve on validation-selected ARIMA. Keep it as a
benchmark, not the deployment default. The later year favours a flat forecast;
selecting a new winner using that year would require another future evaluation.

Run from the team-repo folder, after the regional location experiment:

```powershell
..\.venv\Scripts\python.exe -m pip install -r forecasting/requirements-lstm.txt
..\.venv\Scripts\python.exe -m forecasting.compare_pooled_lstm
..\.venv\Scripts\python.exe -m unittest forecasting.test_pooled_lstm
```

Input: `outputs/regional_location/origin_specific_indices.csv` under forecasting.
Output: `outputs/pooled_lstm/` (generated, ignored by Git).

One shared network learns from North, North-East, East, West and Central four-room
indices. Each example contains 12 monthly log changes. The target is the cumulative
log change from that example's anchor to each of the next 12 months. A single LSTM
layer with 16 hidden units feeds a linear layer with 12 outputs. Forecast indices
equal the origin index multiplied by the exponential of the predicted growth.

The model has no region label, SORA or direct location inputs. Location and flat
characteristics enter through construction of the hedonic target. This tests whether
shared nonlinear patterns in past index changes improve forecasts.

Architecture, Adam learning rate 0.005, weight decay 0.001 and 150 full-batch epochs
are fixed before inspecting results. Seeds 11, 29 and 47 are averaged in log space;
none is selected for superior test accuracy. This is a geometric-mean point forecast,
not a calibrated predictive median. No intervals or joint price paths are claimed.

At each September 2022-2025 origin, use that origin's separately estimated index.
Training targets must end on/before the origin. Input and target scaling uses only
the training examples. Actual future index values use frozen hedonic coefficients.
The first three origins are validation; September 2025-September 2026 is a later
check already examined during other experiments, not an untouched test.

The initial training set contains 225 overlapping windows, rising to 405 at the
last origin. These are not hundreds of independent market histories. Overfitting
remains possible; compare against naive and statistical models before deployment.
The same static-amenity and current-data-vintage limitations as the index apply.

Read the code in this order: `training_arrays` (examples), `PooledLSTM` (architecture),
`fit_predict` (scale, train, forecast), `main` (historical comparisons and saving).
Each origin/seed checkpoint includes weights and scaling metadata; these are
experiment checkpoints, not replacements for Daniel's existing callable API.

Lecture connection: CPMF Day 3, Deep Learning with PyTorch, pp. 23-26 introduce
LSTM memory and gates; pp. 27-29 show PyTorch LSTM implementation. The direct
12-output head and pooling across regions are project design choices. CPMF Day 4
ARIMA/ARIMAX provides the statistical comparison. SHAP is not implemented here.

MRT extension worth testing separately: distinguish proximity to an operating
station from proximity to an announced, unopened station. Use the first public
station-location announcement and coordinates known then; a broad line proposal
does not necessarily identify a station location. Only activate the announcement
feature after it was public (monthly data: conservatively the following month).
Treat actual opening separately; never inject a revised future opening date into
an earlier backtest. Fit this first as a hedonic pricing feature and compare
forecast accuracy with/without it. Association does not establish a causal premium.
An official dated example is LTA's 10 March 2020 CRL Punggol Extension announcement:
https://www.lta.gov.sg/content/ltagov/en/newsroom/2020/3/news-releases/Cross_island_line_Punggol_extension.html

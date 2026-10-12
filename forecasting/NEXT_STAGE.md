# Next forecasting stage: hedonic index and external indicators

## What has been inspected

Shared source: `src/05_price_index_v0.py`, `src/config.py`, and `outputs/price_index_v1.csv`.
The v1 model contains log area, remaining lease and its square, storey midpoint,
flat-model and town dummies, month dummies, log MRT/hawker/park distances,
primary schools within 1 km, CHAS clinics and preschools within 500 m.
MRT distance uses the network at time of sale. Other amenity histories require review.
Age is not an additional input in this price-index model; remaining lease captures a
closely related dimension. Do not blindly add both without examining dependence.

Run `python -m forecasting.audit_hedonic_index` to create coverage and readiness
outputs under `forecasting/outputs/hedonic_audit`. No shared outputs are replaced.
The audit's initial count screen is a practical rule, not proof of model reliability.
ALL series overlap regional data and should be treated as aggregate benchmarks,
not independent regions or independent observations in pooled evaluation.

## Required backtesting design

The supplied index was fitted to all dates. Its historical coefficients incorporate
future transactions. Slicing this exported series does NOT fix that look-ahead.
For each forecast origin:
1. Restrict transactions and available features to the origin.
2. Fit preprocessing/outlier rules and characteristic coefficients using training data.
3. Construct the training index from that fit and forecast 6/12 months ahead.
4. Construct evaluation-month adjusted prices using the frozen training characteristic
   coefficients and subsequently observed transaction attributes/prices. Keep the same
   index base. Specify treatment of new categorical levels and sparse evaluation months.
5. Refit at the next origin. Keep data-vintage limitations explicit.

Current full-sample index can support exploratory plots and current-origin development,
but historical accuracy is provisional until this procedure is implemented. Do not
declare the model leakage-free by checking forecast split dates alone.

## Controlled comparison

A. Naive and seasonal-naive baselines.
B. ARIMA/SARIMA without external regressors.
C. Same forecasting target with one appropriately lagged interest-rate variable.
D. Add CPI growth or a justified policy indicator separately; retain if validation improves.
E. Pooled LSTM on the same eligible regional/flat-type series and forecast origins.

Report error at 6 and 12 months, interval coverage/width, and errors by segment.
Do not select against the final holdout repeatedly. Compare models on matching targets,
origins and horizons. Avoid large specification searches with around 117 monthly points.

## External data contract

Each series needs `observation_month`, `available_date`, `value`, `source`, `units`,
and preferably `vintage_date`. Use information actually available by each origin.
MAS SORA is the first candidate, not an automatic improvement or a direct mortgage
rate. Keep historical series definitions consistent; do not splice SIBOR and SORA blindly.
For horizons beyond observed regressors, supply an explicit scenario or forecast fitted
only to past data. Never feed realised future interest rates to an ordinary backtest.
CPI is optional and needs publication-lag handling. Policy dates require authoritative
verification and predefined coding; future policy surprises cannot be known.
Building completion year alone does not establish a reliable MOP-expiry series.

## Existing API and team contract

Keep the current preliminary bundle unchanged until a replacement is validated.
The next model uses REGION::FLAT_TYPE IDs, whereas the preliminary model uses
TOWN::FLAT_TYPE. Explicitly map each profile's town through the shared REGIONS mapping.
Shared output requires profile_id, month, p10, p50, p90; p10/p90 form a central 80%
interval, not 90%. These marginal quantiles are not simulated joint trajectories.
Future profile prices must use matching origin-date base prices and clearly state the
segment-growth transfer assumption and which sources of uncertainty are included.

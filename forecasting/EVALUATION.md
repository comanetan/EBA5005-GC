# How forecasting is evaluated

We forecast monthly, location-adjusted four-room regional price indices, not
individual transaction prices. Monthly history is January 2017-September 2026.
Partial October 2026 is excluded. Splits follow time; there is no random split.

| Role | Fit using | Forecast and score |
|---|---|---|
| Validation 1 | Jan 2017-Sep 2022 (69 months) | Oct 2022-Sep 2023 |
| Validation 2 | Jan 2017-Sep 2023 (81 months) | Oct 2023-Sep 2024 |
| Validation 3 | Jan 2017-Sep 2024 (93 months) | Oct 2024-Sep 2025 |
| Later-period check | Jan 2017-Sep 2025 (105 months) | Oct 2025-Sep 2026 |
| Deployment refit | Jan 2017-Sep 2026 (117 months) | Oct 2026-Sep 2027 (unknown) |

The fitting window expands. At each historical origin, rebuild the hedonic index
using transactions available up to that month. Freeze the hedonic characteristics'
coefficients when constructing the next year's realised comparison index. Do not
use the team's full-history fitted index for historical training. The next 12 months
are predicted in one operation without adding actual prices during that horizon.

Three validation origins supply 36 errors per region, or 180 region-month errors.
The later check supplies 12 per region, or 60 total. The primary selection rule uses
one model family for all five regions, averaging each region's validation MAPE with
equal weight. It does not pick each region's winner independently or optimise only
the six/twelve-month endpoints. Regional and endpoint metrics are also available.

Candidates: last-value naive, seasonal naive, ARIMA with drift, ARIMA+SORA,
SARIMA, SARIMA+SORA, pooled LSTM. SORA models use lagged published rates and hold
the last known rate constant into the forecast horizon; no realised future rates.
LSTM scaling/windows are training-only; its architecture, epochs and three seeds
are fixed. Pooling uses all five training histories, not their evaluation values.

MAPE = mean(100 * abs(forecast - actual) / actual). Example: forecast 153, actual
150 gives 2% error. Under- and over-predictions cannot cancel. Regional index MAPE
is NOT an individual flat's pricing error and NOT '100 minus MAPE percent accurate'.

MAE = mean absolute error in index points (reported in the earlier single-region
experiment). It is easy to interpret within one index but depends on index scaling;
MAPE is the main comparison across regions. AIC is a fit diagnostic, not the primary
out-of-sample selection criterion. Training loss is not forecast test accuracy.

Interval coverage = percent of realised indices between the lower and upper bounds.
For nominal 90% bands, coverage should be near 90% over sufficiently many trials.
Also inspect interval width: excessively wide intervals can achieve coverage while
being unhelpful. The model's nominal quantiles are not automatically calibrated.
LSTM currently supplies point forecasts only, so no interval coverage is claimed.

The later year was previously viewed in exploratory work. Call it a later-period
check, not an untouched final test. Choosing its winning baseline after inspecting
it would reuse the evaluation sample for selection. Refit the validation-selected
family on all 117 months for the dashboard, then assess future outcomes as available.

Current data vintages and static amenity histories limit strict as-of claims even
though price fitting/scaling avoids future values. The few annual forecast origins
and correlated regional errors also limit how confidently small metric differences
can be generalised. No claim of statistically significant superiority is made.

Software checks supplement statistical evaluation: perturb future observations and
verify training is unchanged; verify exported forecasts match the fitted models;
verify inference never trains; verify price scaling, dates and invalid-input handling.
Passing software tests does not establish forecasting accuracy.

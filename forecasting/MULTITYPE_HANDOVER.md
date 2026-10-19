# Current forecasting handover for Daniel

**Current scope: 3 ROOM, 4 ROOM and 5 ROOM in five regions — fifteen trained
regional flat-type series.** This supersedes the four-room-only handover.

The selected family is ARIMA(0,1,1) with drift and a selected-policy-package
regressor, fitted separately for each regional flat type. Selection used the
lowest equal-region MAPE over the three earlier annual validation origins, once
per flat type. The policy coefficient is a predictive association, not a causal
effect. The expanded specification comparison is retrospective.

## Load the callable model

From repository root, install `forecasting/requirements-tested.txt`. Inference
needs no raw data, PyTorch, geocoding or training. Either load the JSON bundle:

The tested training/runtime environment uses Python 3.12. The delivered pickle
was loaded successfully from a separate unittest entry point, and all 26
forecasting tests passed, including the earlier four-room regression tests.

```python
from forecasting.multitype_api import MultiTypeForecaster

model = MultiTypeForecaster()  # Load once at application startup.
result = model.predict(
    region="NORTH-EAST",
    flat_type="5 ROOM",
    horizon_months=12,
    base_price_sgd=750000,
    base_price_month="2026-09",
)
rows = result["forecasts"]
```

Or load **the trusted callable pickle**, with the forecasting source package
available on the Python path:

```python
import pickle

with open("forecasting/models/multitype/forecast_model.pkl", "rb") as stream:
    model = pickle.load(stream)

result = model.predict("NORTH-EAST", "3 ROOM", horizon_months=6)
```

This pickle contains the inference object, forecast distributions and scenario
banks. It does not require the original author's local folders. Only load a
trusted pickle. The fifteen individual statistical-model PKLs are audit/refit
objects; loading one of those directly requires the appropriate future exogenous
inputs. Use the callable model above for the dashboard.

## Data contracts

`model.predict()` returns monthly index and growth-factor p10/p50/p90 values, and
SGD quantiles if a base price is supplied. Dates are October 2026–September 2027.
Base-price and forecast origins must match. Budget changes belong in the
optimiser; they do not refit the forecasting model.

```python
import pandas as pd

prices = pd.read_csv("outputs/prices_today.csv")
supported = prices.profile_id.str.split("|").str[1].isin(["3 ROOM", "4 ROOM", "5 ROOM"])
paths = model.price_profiles(prices[supported], base_price_month="2026-09")
# Existing contract: profile_id, month, p10, p50, p90 (SGD)

town_table = model.town_forecast()
# 156 rows: 26 towns x 3 flat types x 2 horizons.
# town, flat_type, horizon_months, growth_factor,
# growth_factor_lower, growth_factor_upper, _source
```

Pre-generated handover files:

- `forecasting/evidence/multitype/price_paths.csv`: 1,330 supported pricing profiles
  × twelve months; 15,960 rows.
- `forecasting/evidence/multitype/price_paths_metadata.json`: coverage, source hash,
  base date and uncertainty limitations.
- `forecasting/evidence/multitype/price_forecast.csv`: direct town/flat-type table
  for deterministic optimiser loading.

The older root `outputs/price_paths.csv` is the previous four-room nominal export.
Do not confuse it with the current three-type handover above. Unsupported
two-room, executive and other types must retain an explicit unsupported/stub
status; the API rejects them.

## Joint Monte Carlo and named scenarios

```python
from forecasting.multitype_api import run_joint_monte_carlo

batch = model.draw_market_paths(n_scenarios=2000, seed=42)
# growth_factors shape: scenario x month x 15 regional flat-type segments.
# Keep common scenario IDs when comparing profiles or horizons.

mc_rows = run_joint_monte_carlo(
    shortlist,
    n_scenarios=2000,
    seed=42,
    base_price_month="2026-09",
)
# shortlist requires profile_id, town, flat_type, price_today,
# survival_prob_6m and survival_prob_12m.
# Result matches the existing monte_carlo.summarize_strategies contract.
```

The default scenario is the validation-selected family. An explicitly separate
full-regressor ARIMAX challenger supplies conditional sensitivities:

```python
rate_stress = model.draw_market_paths(
    n_scenarios=2000, seed=42, scenario="rate_plus_1pp"
)
mc_stress = run_joint_monte_carlo(
    shortlist, scenario="cohort_plus20pct", base_price_month="2026-09"
)
```

Named challenger scenarios are `base`, `rate_minus_1pp`, `rate_plus_1pp`,
`cohort_minus20pct` and `cohort_plus20pct`. Rate shifts are percentage points,
not percentages. The first forecast month's lagged inputs are already known and
are not changed by a future shock. Later rate assumptions are held at the shifted
level. Supply scenarios change the effective completion-cohort proxy by ±20%.
These assumptions have no assigned probabilities and are not causal policy estimates.

**Named macro scenarios are diagnostic only.** In the full challenger, twelve of
fifteen estimated SORA coefficients are positive, inconsistent with using the
model as a simple causal borrowing-cost mechanism. Returns include
`scenario_status="diagnostic_only"`. Keep `scenario="selected"` as the default;
do not claim that increasing rates would cause the simulated price response.

The challenger has **its own** joint historical error bank. It does not borrow
calibration errors from the selected policy-only model. Counterfactual scenario
uncertainty still assumes historical error behaviour transfers to the assumed
future path.

## Interpretation and integration requirements

- p10–p90 is a central **80%** interval. Bounds come from exploratory sign-mirrored
  historical errors, not a proven 90% affordability guarantee.
- One draw samples a complete 12 × 15 error matrix. Cross-region, cross-flat-type
  and cross-horizon dependence is retained. There are 21 overlapping historical
  paths, or 42 mirrored possibilities; 2,000 draws are not 2,000 independent histories.
- All profiles in a regional flat-type segment share growth. Different towns in
  that segment keep their current relative price difference; town-specific
  appreciation is not separately predicted.
- Current profile-valuation uncertainty is excluded. Do not multiply low price
  estimates by low growth estimates and label the result a calibrated quantile.
- Availability is supplied by the availability workstream. The bridge assumes it
  is independent of market shocks and independent between profiles, with
  cumulative arrivals consistent across horizons. A matching transaction is not
  a guaranteed listing or successful purchase.
- In the tested optimiser commit, `fcast_override` alone does not recompute
  deterministic `price_upper`. Supply the chosen forecast through `load_inputs`,
  or fix the integration so the bound is recomputed before budget filtering.
- Replacing marginal forecast CSVs alone does not replace the existing Monte Carlo
  engine. Use the joint function if shared scenarios are intended.

The actual optimiser branch remains Daniel's responsibility. The forecasting
branch supplies the callable component, contracts, dated evidence and local tests.

## Reproduction

For training/evaluation, also install `requirements-lstm.txt`; raw team inputs and
the local feature build are needed. Run from repository root:

```powershell
python -m forecasting.build_location_inputs
python -m forecasting.expand_multitype --stage all
python -m forecasting.explain_multitype
python -m forecasting.multitype_api
python -m forecasting.stress_multitype
python -m forecasting.plot_multitype
python -m unittest discover -s forecasting -t . -p "test_*.py"
```

Optional actual-optimiser reconstruction uses `prepare_team_replay` and
`requirements-integration.txt` as described in the earlier `FINAL_REVIEW.md`:

```powershell
python -m forecasting.check_optimisation_integration --multitype
python -m forecasting.replay_optimisation --multitype
```

Raw/regenerated features, training checkpoints and the isolated optimiser layout
stay under ignored `forecasting/outputs/`. Current model bundles and evaluation
evidence are committed. Model expansion does not remove data-vintage, residual
dependence or retrospective model-selection limitations.

# Current forecasting handover for Daniel

Use `RegionalForecaster`, not the legacy Sengkang median-PSM `Forecaster`.
Scope: four-room flats in North, North-East, East, West and Central.
Model: ARIMA(0,1,1) with drift on a location-adjusted log index, selected as
the best single model family by mean regional validation MAPE across seven candidates.
This does not claim to be the best model for every individual region.

Install `forecasting/requirements-tested.txt`; PyTorch is only needed to reproduce
the LSTM benchmark, not for dashboard inference. Run from the repository root:

```python
from forecasting.regional_api import RegionalForecaster

forecaster = RegionalForecaster()  # load once at dashboard startup
result = forecaster.predict(
    region="NORTH-EAST", flat_type="4 ROOM", horizon_months=12,
    base_price_sgd=600000, base_price_month="2026-09",
)
rows = result["forecasts"]
```

The price is an input from the pricing model, not a hardcoded recommended price.
Base price must have the same date as the saved forecast origin. Changing the
household budget does not refit the forecast; it changes the optimiser's constraints.
Indices are not SGD/m2. Growth factors multiply the pricing lead's dollar valuation.

For the exact agreed CSV contract:

```python
import pandas as pd
prices = pd.read_csv("outputs/prices_today.csv")
four_room = prices[prices.profile_id.str.split("|").str[1].eq("4 ROOM")]
price_paths = forecaster.price_profiles(four_room, base_price_month="2026-09")
# columns: profile_id, month, p10, p50, p90 (SGD)
```

`outputs/price_paths.csv` is already generated from the current shared pricing
file. Its metadata records coverage, excluded other flat types, source hash and
limitations. Do not inner-join and inadvertently treat excluded types as evaluated.
Unsupported types fail in the API. No dashboard source currently exists in this
repository; this supplies the callable component and handover data for integration.

The portable JSON bundle stores the selected model's forecast log means and
variances for October 2026-September 2027. It needs no raw data or fitting at
runtime. Separate saved statistical-model files support offline auditing; only
load trusted pickle files. Refitting is an explicit offline step:

```powershell
python -m forecasting.build_location_inputs
python -m forecasting.compare_regional_location
python -m forecasting.compare_pooled_lstm
python -m forecasting.export_regional_model
python -m unittest forecasting.test_regional_api
```

## Interpretation and limits

- p10/p90 bound a central 80% interval. p90 is a one-sided 90th percentile;
  it is not the upper endpoint of a central 90% interval (that is p95).
- These are model-based marginal quantiles, not calibrated affordability promises.
  Poor coverage in the later-year check must be reported alongside point accuracy.
- The existing filename `price_paths.csv` follows the team's contract; rows are
  marginal quantiles, not simulated joint paths. Do not independently sample these
  rows for Monte Carlo. Joint simulation remains unimplemented.
- Multiply all three growth quantiles by the same current central price. The pricing
  model's price_low/high describe variation across blocks, not automatically forecast
  errors; combining them would require a specified uncertainty model.
- Current price uncertainty, index estimation, future lease/profile changes and
  cross-region dependence are not modelled. All profiles in a region share growth.
- Amenity snapshots and raw-data vintages are retrospective. MRT announcement
  features have not been added. This is a project prototype, not production advice.

See `EVALUATION.md` for splits and metric definitions. The old `HANDOVER.md` is
retained only to explain the original preliminary interface.

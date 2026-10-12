"""Run from repo root: python -m forecasting.example_ui_call"""
import json
from .model_api import Forecaster

def main():
    forecaster = Forecaster()  # Load once, not on every UI slider change.
    result = forecaster.predict(
        segment_id=forecaster.available_segments()[0],
        horizon_months=12,
        confidence_level=0.90,
        base_price_sgd=600000,  # Illustrative Comane price, not a real valuation.
        base_price_month=forecaster.metadata["origin"],
    )
    print(json.dumps(result, indent=2, allow_nan=False))

if __name__ == "__main__":
    main()

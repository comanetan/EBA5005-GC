"""Inference-only interface. Loading/predicting never reads raw data or trains a model."""
from pathlib import Path
import json
import math
import platform

import numpy as np
import pandas as pd
import statsmodels
from scipy.stats import norm
from statsmodels.tsa.statespace.sarimax import SARIMAXResults

DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "models" / "preliminary"


def export_model(directory, series, model_name, fitted, metadata):
    """Called after offline selection/refitting, not by the UI."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if fitted is not None:
        fitted.save(directory / "fitted_model.pkl")
    z = np.log(series)
    manifest = {
        "schema_version": 1,
        "model_version": f"preliminary-{series.index[-1]:%Y%m}-{metadata['source_sha256'][:12]}",
        "segment_id": f"{metadata['selected_town']}::{metadata['flat_type']}",
        "model_name": model_name,
        "backend": "statsmodels" if fitted is not None else model_name,
        "origin": series.index[-1].strftime("%Y-%m"),
        "reference_value_psm": float(series.iloc[-1]),
        "max_horizon_months": 12,
        "last_12_log_values": z.iloc[-12:].tolist(),
        "naive_innovation_mse": float(np.mean(z.diff().dropna() ** 2)),
        "seasonal_innovation_mse": float(np.mean(z.diff(12).dropna() ** 2)),
        "status": "preliminary_not_calibrated_for_affordability",
        "target": "monthly_median_price_per_sqm",
        "source_sha256": metadata["source_sha256"],
        "python_version": platform.python_version(),
        "statsmodels_version": statsmodels.__version__,
        "warnings": [
            "Only the listed segment is supported; no silent substitution for other segments.",
            "Median transaction SGD/m2 is not a hedonic index or an individual-flat valuation.",
            "Bounds are conditional pointwise intervals, not joint price paths or affordability guarantees.",
            "Growth factors assume a profile follows this segment from the same reference month.",
            "Profile scenarios exclude current-price estimation uncertainty and future macro scenarios.",
        ],
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")


class Forecaster:
    """Load once at UI startup. Reuse predict() on every interaction.

    Only load model bundles from trusted team sources: statsmodels files use pickle.
    """
    def __init__(self, model_dir=DEFAULT_MODEL_DIR):
        self.model_dir = Path(model_dir)
        self.metadata = json.loads((self.model_dir / "manifest.json").read_text(encoding="utf-8"))
        if self.metadata["schema_version"] != 1:
            raise ValueError("Unsupported model interface version.")
        self._fitted = None
        if self.metadata["backend"] == "statsmodels":
            if self.metadata["statsmodels_version"] != statsmodels.__version__:
                raise RuntimeError("Install requirements-tested.txt: saved model statsmodels version differs.")
            self._fitted = SARIMAXResults.load(self.model_dir / "fitted_model.pkl")

    def available_segments(self):
        return [self.metadata["segment_id"]]

    def predict(self, segment_id, horizon_months=12, confidence_level=0.90,
                base_price_sgd=None, base_price_month=None):
        """Return JSON-ready forecasts, factors and optional conditional price scenarios.

        confidence_level is the central interval probability. A central 90% upper
        bound is the 95th percentile, NOT the 90th percentile for a chance constraint.
        """
        m = self.metadata
        if segment_id not in self.available_segments():
            raise ValueError(f"Unsupported segment {segment_id!r}. Available: {self.available_segments()}")
        if isinstance(horizon_months, bool) or not isinstance(horizon_months, int) or not 1 <= horizon_months <= m["max_horizon_months"]:
            raise ValueError("horizon_months must be an integer from 1 to 12.")
        if isinstance(confidence_level, bool) or not isinstance(confidence_level, (int, float)) or not 0 < confidence_level < 1:
            raise ValueError("confidence_level must be a number strictly between 0 and 1.")
        if base_price_sgd is not None:
            if isinstance(base_price_sgd, bool) or not isinstance(base_price_sgd, (int, float)) or not math.isfinite(base_price_sgd) or base_price_sgd <= 0:
                raise ValueError("base_price_sgd must be a finite positive number.")
            if base_price_month != m["origin"]:
                raise ValueError(f"base_price_month must equal model origin {m['origin']}; do not mix price dates.")
        elif base_price_month is not None:
            raise ValueError("base_price_month requires base_price_sgd.")
        h = np.arange(1, horizon_months + 1)
        if self._fitted is not None:
            prediction = self._fitted.get_forecast(steps=horizon_months)
            mean = np.asarray(prediction.predicted_mean)
            variance = np.asarray(prediction.var_pred_mean)
        elif m["backend"] == "naive":
            mean = np.repeat(m["last_12_log_values"][-1], horizon_months)
            variance = m["naive_innovation_mse"] * h
        elif m["backend"] == "seasonal_naive":
            mean = np.resize(m["last_12_log_values"], horizon_months)
            variance = m["seasonal_innovation_mse"] * np.ceil(h / 12)
        else:
            raise ValueError("Unknown model backend.")
        q = norm.ppf((1 + confidence_level) / 2)
        spread = q * np.sqrt(np.maximum(variance, 0))
        values = np.exp(np.column_stack([mean, mean - spread, mean + spread]))
        if not np.isfinite(values).all():
            raise ValueError("Non-finite forecast: model must be reviewed.")
        dates = pd.date_range(pd.Timestamp(m["origin"]) + pd.offsets.MonthBegin(1), periods=horizon_months, freq="MS")
        records = []
        for step, (date, (point, lower, upper)) in enumerate(zip(dates, values), 1):
            factors = np.array([point, lower, upper]) / m["reference_value_psm"]
            record = dict(month=date.strftime("%Y-%m"), horizon=step,
                          forecast_psm=float(point), lower_psm=float(lower), upper_psm=float(upper),
                          growth_factor=float(factors[0]), growth_factor_lower=float(factors[1]),
                          growth_factor_upper=float(factors[2]))
            if base_price_sgd is not None:
                record.update(profile_price_scenario_sgd=float(base_price_sgd * factors[0]),
                              profile_price_scenario_lower_sgd=float(base_price_sgd * factors[1]),
                              profile_price_scenario_upper_sgd=float(base_price_sgd * factors[2]))
            records.append(record)
        return dict(schema_version=1, model_version=m["model_version"], model=m["model_name"],
                    segment_id=segment_id, origin=m["origin"], status=m["status"], target=m["target"],
                    units="SGD per square metre", point_estimate="predictive_median",
                    reference_value_psm=m["reference_value_psm"], confidence_level=confidence_level,
                    interval_type="central_pointwise_conditional",
                    lower_quantile=(1-confidence_level)/2, upper_quantile=(1+confidence_level)/2,
                    base_price_sgd=base_price_sgd, base_price_month=base_price_month,
                    warnings=list(m["warnings"]), forecasts=records)

    def simulate_paths(self, *args, **kwargs):
        raise NotImplementedError("Joint price-path simulation is not available in this preliminary bundle. Do not sample independent pointwise bounds.")

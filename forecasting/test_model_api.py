"""Integration tests for a trusted locally exported bundle."""
import json
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
import pandas as pd
from .model_api import Forecaster

class ModelApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = Forecaster()
        cls.segment = cls.model.available_segments()[0]

    def test_predictions_match_training_export_without_retraining(self):
        with patch("statsmodels.tsa.statespace.sarimax.SARIMAX.fit", side_effect=AssertionError("UI must not train")):
            output = self.model.predict(self.segment)
        expected = pd.read_csv(Path(__file__).parent / "outputs/forecast_next_12_months.csv")
        actual = pd.DataFrame(output["forecasts"])
        np.testing.assert_allclose(actual.forecast_psm, expected.forecast_psm)
        np.testing.assert_allclose(actual.lower_psm, expected.lower_90_psm)
        np.testing.assert_allclose(actual.upper_psm, expected.upper_90_psm)
        json.dumps(output, allow_nan=False)

    def test_horizon_confidence_and_price_mapping(self):
        low = self.model.predict(self.segment, 6, .8)
        high = self.model.predict(self.segment, 6, .95, 600000, self.model.metadata["origin"])
        self.assertEqual(len(high["forecasts"]), 6)
        for a, b in zip(low["forecasts"], high["forecasts"]):
            self.assertAlmostEqual(a["forecast_psm"], b["forecast_psm"])
            self.assertLessEqual(b["lower_psm"], a["lower_psm"])
            self.assertGreaterEqual(b["upper_psm"], a["upper_psm"])
            self.assertAlmostEqual(b["profile_price_scenario_sgd"], 600000*b["growth_factor"])

    def test_reject_bad_inputs(self):
        for horizon in [0, 13, True, 6.5]:
            with self.assertRaises(ValueError): self.model.predict(self.segment, horizon)
        for level in [0, 1, float("nan"), True]:
            with self.assertRaises(ValueError): self.model.predict(self.segment, confidence_level=level)
        with self.assertRaises(ValueError): self.model.predict("NONEXISTENT::4 ROOM")
        with self.assertRaises(ValueError): self.model.predict(self.segment, base_price_sgd=600000, base_price_month="2020-01")
        with self.assertRaises(ValueError): self.model.predict(self.segment, base_price_sgd=-1)
        with self.assertRaises(NotImplementedError): self.model.simulate_paths()

if __name__ == "__main__":
    unittest.main()

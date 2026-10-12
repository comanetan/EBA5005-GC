import unittest
import pandas as pd
import numpy as np
from .compare_sarimax_rates import source_data, refit_index, run_forecast
from .prepare_mas_rates import prepare_monthly, parse_mas, SOURCE

class TimingTests(unittest.TestCase):
    def test_future_prices_do_not_change_training_index(self):
        df, _ = source_data()
        origin, end = pd.Timestamp("2024-09-01"), pd.Timestamp("2025-09-01")
        train, actual = refit_index(df, origin, end)
        altered = df.copy()
        altered.loc[altered.month > origin, "resale_price"] *= 2
        train2, actual2 = refit_index(altered, origin, end)
        np.testing.assert_allclose(train, train2)
        np.testing.assert_allclose(actual2, 2*actual)

    def test_future_realised_rates_not_used(self):
        df, _ = source_data()
        origin, end = pd.Timestamp("2024-09-01"), pd.Timestamp("2025-09-01")
        train, actual = refit_index(df, origin, end)
        rates = prepare_monthly(parse_mas(SOURCE)); rates.index = pd.to_datetime(rates.month)
        a,_ = run_forecast(train, rates, "ARIMA_011_drift_SORA", actual.index)
        altered = rates.copy()
        altered.loc[altered.index > origin, ["sora_3m_eom_pct_pa", "sora_3m_eom_lag1_pct_pa"]] = 999
        b,_ = run_forecast(train, altered, "ARIMA_011_drift_SORA", actual.index)
        np.testing.assert_allclose(a,b)

if __name__ == "__main__": unittest.main()

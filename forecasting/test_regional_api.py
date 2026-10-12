import json
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from scipy.stats import norm
from statsmodels.tsa.statespace.sarimax import SARIMAX, SARIMAXResults
from .regional_api import RegionalForecaster, DEFAULT_BUNDLE


class RegionalAPITests(unittest.TestCase):
    def test_export_matches_fitted_model_and_price_scaling_without_fitting(self):
        api = RegionalForecaster()
        for segment in api.available_segments():
            region = segment.split('::')[0]
            fitted = SARIMAXResults.load(DEFAULT_BUNDLE.parent / f'{region}.pkl')
            expected = fitted.get_forecast(12)
            quantiles = np.exp(np.asarray(expected.predicted_mean)[:,None] +
                               np.sqrt(np.asarray(expected.var_pred_mean))[:,None]*norm.ppf([.1,.5,.9]))
            with patch.object(SARIMAX,'fit',side_effect=AssertionError('UI must not fit')):
                rows = api.predict(region, base_price_sgd=600000,base_price_month='2026-09')['forecasts']
            actual = np.array([[r['index_p10'],r['index_p50'],r['index_p90']] for r in rows])
            np.testing.assert_allclose(actual,quantiles,rtol=1e-12)
            self.assertEqual(rows[0]['month'],'2026-10')
            self.assertEqual(rows[-1]['month'],'2027-09')
            for row in rows:
                self.assertAlmostEqual(row['p50'],600000*row['growth_factor_p50'])
                self.assertLessEqual(row['p10'],row['p50'])
                self.assertLessEqual(row['p50'],row['p90'])
            json.dumps(rows,allow_nan=False)

    def test_invalid_inputs_fail(self):
        api = RegionalForecaster()
        for kwargs in [dict(flat_type='3 ROOM'),dict(horizon_months=0),dict(horizon_months=True),
                       dict(horizon_months=13),dict(base_price_sgd=float('nan'),base_price_month='2026-09'),
                       dict(base_price_sgd=100,base_price_month='2026-08')]:
            with self.assertRaises(ValueError): api.predict('NORTH',**kwargs)
        with self.assertRaises(NotImplementedError): api.simulate_paths()

    def test_handover_contract_and_mapping(self):
        api = RegionalForecaster()
        prices = pd.DataFrame({'profile_id':['SENGKANG|4 ROOM|80+|<500m|13+'], 'price':[600000]})
        result = api.price_profiles(prices,'2026-09',6)
        self.assertEqual(list(result.columns),['profile_id','month','p10','p50','p90'])
        self.assertEqual(len(result),6)
        expected = api.predict('NORTH-EAST',horizon_months=6,base_price_sgd=600000,base_price_month='2026-09')
        self.assertEqual(result.iloc[-1].p90,expected['forecasts'][-1]['p90'])
        with self.assertRaises(ValueError): api.price_profiles(pd.concat([prices,prices]),'2026-09')
        prices['profile_id']='SENGKANG|3 ROOM|80+|<500m|13+'
        with self.assertRaises(ValueError): api.price_profiles(prices,'2026-09')


if __name__ == '__main__': unittest.main()

import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from .joint_scenarios import JointScenarioForecaster
from .final_validation import available_error_paths, OUT
from .optimisation_bridge import historical_forecast, run_joint_monte_carlo
from .explain_forecasts import permutation_shap


class FinalDeliveryTests(unittest.TestCase):
    def test_joint_dependence_and_reproducibility(self):
        model=JointScenarioForecaster()
        a=model.draw(500,12,7);b=model.draw(500,12,7)
        np.testing.assert_array_equal(a['growth_factors'],b['growth_factors'])
        self.assertEqual(a['growth_factors'].shape,(500,12,5))
        self.assertTrue((a['growth_factors']>0).all())
        for i in range(5):
            j=model.metadata['source_origins'].index(a['sampled_error_origins'][i])
            reconstructed=np.log(a['growth_factors'][i]/model._base_growth())
            np.testing.assert_allclose(reconstructed,a['error_signs'][i]*model.errors[j],atol=1e-12)

    def test_calibration_does_not_use_future_outcomes(self):
        data=pd.read_csv(OUT/'historical_errors.csv')
        original,labels=available_error_paths(data,'2024-09')
        changed=data.copy()
        changed.loc[pd.to_datetime(changed.month)>pd.Timestamp('2024-09'),'log_error']=99
        result,labels2=available_error_paths(changed,'2024-09')
        np.testing.assert_array_equal(original,result)
        self.assertEqual(labels,labels2)
        self.assertTrue(all(pd.Timestamp(x)+pd.DateOffset(months=12)<=pd.Timestamp('2024-09') for x in labels))

    def test_profile_scaling_uses_same_scenario(self):
        model=JointScenarioForecaster()
        prices=pd.DataFrame({'profile_id':['SENGKANG|4 ROOM|80+|<500m|13+','HOUGANG|4 ROOM|80+|<500m|13+'],
                             'price':[600000,500000]})
        data=model.profile_paths(prices,'2026-09',20)
        a=data[data.profile_id.str.startswith('SENGKANG')].price_sgd.to_numpy()/600000
        b=data[data.profile_id.str.startswith('HOUGANG')].price_sgd.to_numpy()/500000
        np.testing.assert_allclose(a,b)
        for args in [dict(n_scenarios=0),dict(horizon_months=True),dict(seed=-1)]:
            with self.assertRaises(ValueError):model.draw(**args)

    def test_bridge_cumulative_availability_and_price_dependence(self):
        shortlist=pd.DataFrame(dict(profile_id=['A','B'],town=['SENGKANG','HOUGANG'],flat_type=['4 ROOM']*2,
            price_today=[600000,500000],survival_prob_6m=[.4,.6],survival_prob_12m=[.7,.8]))
        result=run_joint_monte_carlo(shortlist,n_scenarios=100)
        self.assertFalse((result.wait6_available & ~result.wait12_available).any())
        self.assertFalse((result.buy_now_available & ~result.wait6_available).any())
        np.testing.assert_allclose(result[result.profile_id=='A'].wait12_price/600000,
                                   result[result.profile_id=='B'].wait12_price/500000)
        shortlist.loc[0,'flat_type']='3 ROOM'
        with self.assertRaises(ValueError):run_joint_monte_carlo(shortlist)

    def test_historical_adapter_rejects_missing_origin(self):
        result=historical_forecast('2024-12','symmetric')
        self.assertEqual(len(result),52)
        self.assertFalse(result.duplicated(['town','flat_type','horizon_months']).any())
        self.assertTrue((result.growth_factor_upper>=result.growth_factor).all())
        self.assertNotIn('actual_index',result)
        with self.assertRaises(ValueError):historical_forecast('2026-09')

    def test_shapley_implementation_on_known_additive_function(self):
        coef=np.array([2.,-3.,.5])
        pred=lambda x:(x@coef+4)[:,None]
        x=np.array([1.,2.,3.])
        phi,se,base,target,error=permutation_shap(pred,x,np.zeros((5,3)),n_permutations=20)
        np.testing.assert_allclose(phi[:,0],coef*x)
        np.testing.assert_allclose(base+phi.sum(axis=0),target)
        self.assertLess(error,1e-10)


if __name__=='__main__':unittest.main()

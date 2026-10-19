import unittest
import pickle
from unittest.mock import patch
import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX
from .multitype_core import index_at_origin, regressors, SEGMENTS, CONTROLS
from .forecast_comparison import dm_test, bh_adjust
from .multitype_api import MultiTypeForecaster, run_joint_monte_carlo, DEFAULT_BUNDLE
from .multitype_bridge import historical_forecast


class ExpandedMethodTests(unittest.TestCase):
    def test_index_fit_is_unchanged_by_future_prices_and_attributes(self):
        rng=np.random.default_rng(3);dates=pd.date_range('2017-01',periods=36,freq='MS');n=len(dates)*8
        d=pd.DataFrame(dict(month=np.repeat(dates,8),town=np.tile(['A','B'],n//2),flat_model_group='M',
            log_area=rng.normal(4.5,.1,n),lease=rng.uniform(50,90,n),storey=rng.uniform(1,15,n)))
        d['lease2']=d.lease**2/100
        for c in CONTROLS:d[c]=rng.normal(size=n)
        d['resale_price']=np.exp(10+.01*np.repeat(np.arange(36),8)+.3*d.log_area+.004*d.lease+rng.normal(0,.01,n))
        origin=dates[23];a,_,_=index_at_origin(d,origin,dates[-1])
        changed=d.copy();future=changed.month>origin
        changed.loc[future,'resale_price']*=3;changed.loc[future,'lease']+=7;changed.loc[future,'log_dist_mrt']+=2
        b,_,_=index_at_origin(changed,origin,dates[-1]);np.testing.assert_allclose(a,b,rtol=1e-13)
        changed.loc[changed.index[-1],'flat_model_group']='UNSEEN'
        _,_,info=index_at_origin(changed,origin,dates[-1]);self.assertEqual(info['excluded_future_categories'],1)

    def test_regressors_respect_publication_and_future_policy_knowledge(self):
        dates=pd.date_range('2020-01',periods=36,freq='MS');origin=pd.Timestamp('2021-08')
        rates=pd.DataFrame(dict(sora_3m_eom_pct_pa=1.,sora_3m_eom_lag1_pct_pa=.9),index=dates)
        supply=pd.DataFrame(dict(region='NORTH',flat_type='3 ROOM',year=range(2019,2024),proxy_units=100))
        a=regressors(dates,origin,'NORTH::3 ROOM',rates,supply)
        rates.loc[rates.index>origin,:]=99
        b=regressors(dates,origin,'NORTH::3 ROOM',rates,supply)
        pd.testing.assert_frame_equal(a,b)
        self.assertTrue(a.policy.eq(0).all())  # December 2021 package not known in August.
        scenario=regressors(dates,origin,'NORTH::3 ROOM',rates,supply,rate_shift=1,supply_multiplier=1.2)
        pd.testing.assert_frame_equal(a.loc[:'2021-09'],scenario.loc[:'2021-09'])
        self.assertEqual(scenario.loc['2021-10-01','sora'],2.)

    def test_dm_pairing_overlap_and_zero_variance(self):
        a=np.linspace(1,3,21)+np.sin(np.arange(21));b=np.ones(21)
        first=dm_test(a,b,12);second=dm_test(b,a,12)
        self.assertEqual(first['n_origins'],21);self.assertEqual(first['hac_lag'],3)
        self.assertAlmostEqual(first['statistic'],-second['statistic'])
        self.assertAlmostEqual(first['p_value'],second['p_value'])
        self.assertEqual(dm_test(a,a,6)['status'],'zero_loss_variance')
        self.assertIsNone(dm_test(a[:4],b[:4],12)['p_value'])
        np.testing.assert_allclose(bh_adjust([.01,.04,.03]),[.03,.04,.04])


class ExpandedDeliveryTests(unittest.TestCase):
    def test_all_fifteen_segments_and_inference_does_not_fit(self):
        with patch.object(SARIMAX,'fit',side_effect=AssertionError('Runtime must not fit')):
            api=MultiTypeForecaster();self.assertEqual(set(api.available_segments()),set(SEGMENTS))
            for segment in SEGMENTS:
                region,ft=segment.split('::');result=api.predict(region,ft,base_price_sgd=600000,base_price_month='2026-09')
                self.assertEqual(len(result['forecasts']),12)
                self.assertEqual(result['forecasts'][0]['month'],'2026-10')
                for row in result['forecasts']:
                    self.assertLessEqual(row['p10'],row['p50']);self.assertLessEqual(row['p50'],row['p90'])
                    self.assertAlmostEqual(row['p50'],600000*row['growth_factor_p50'])
        for kwargs in [dict(flat_type='2 ROOM'),dict(horizon_months=True),dict(horizon_months=13),
                       dict(base_price_sgd=100,base_price_month='2026-08')]:
            with self.assertRaises(ValueError):api.predict('NORTH',**kwargs)

    def test_scenario_matrix_preserves_all_segment_dependence(self):
        api=MultiTypeForecaster();a=api.draw_market_paths(30,12,5);b=api.draw_market_paths(30,12,5)
        np.testing.assert_array_equal(a['growth_factors'],b['growth_factors'])
        self.assertEqual(a['growth_factors'].shape,(30,12,15))
        point=np.column_stack([np.exp(api.metadata['segments'][s]['log_mean'])/api.metadata['segments'][s]['reference_index'] for s in api.segment_ids])
        for i in range(4):
            j=api.scenario_metadata['source_origins'].index(a['sampled_error_origins'][i])
            np.testing.assert_allclose(np.log(a['growth_factors'][i]/point),a['error_signs'][i]*api.errors[j],atol=1e-12)
        for bad in [dict(n_scenarios=0),dict(horizon_months=True),dict(seed=-1)]:
            with self.assertRaises(ValueError):api.draw_market_paths(**bad)

    def test_mixed_type_price_contract_and_cumulative_availability(self):
        api=MultiTypeForecaster()
        prices=pd.DataFrame(dict(profile_id=[f'HOUGANG|{ft}|80+|<500m|13+' for ft in ['3 ROOM','4 ROOM','5 ROOM']],price=[400000,500000,600000]))
        self.assertEqual(len(api.price_profiles(prices,'2026-09')),36)
        paths=api.simulate_paths(prices,'2026-09',20);self.assertEqual(len(paths),720)
        shortlist=pd.DataFrame(dict(profile_id=['A','B','C'],town='HOUGANG',flat_type=['3 ROOM','4 ROOM','5 ROOM'],
            price_today=[400000,500000,600000],survival_prob_6m=.5,survival_prob_12m=.8))
        scenarios=run_joint_monte_carlo(shortlist,n_scenarios=30)
        self.assertEqual(len(scenarios),90)
        self.assertFalse((scenarios.wait6_available&~scenarios.wait12_available).any())
        self.assertFalse((scenarios.buy_now_available&~scenarios.wait6_available).any())

    def test_scenario_challenger_uses_own_errors_and_preserves_known_lag(self):
        api=MultiTypeForecaster();base=api.draw_market_paths(20,12,9,scenario='base')
        shifted=api.draw_market_paths(20,12,9,scenario='rate_plus_1pp')
        self.assertEqual(shifted['scenario_status'],'diagnostic_only')
        np.testing.assert_allclose(base['growth_factors'][:,0,:],shifted['growth_factors'][:,0,:],rtol=1e-12)
        self.assertFalse(np.allclose(base['growth_factors'][:,11,:],shifted['growth_factors'][:,11,:]))
        reference=np.column_stack([np.exp(api.metadata['scenario_segments']['base'][s]['log_mean'])/api.metadata['scenario_segments']['base'][s]['reference_index'] for s in api.segment_ids])
        j=api.scenario_metadata['source_origins'].index(base['sampled_error_origins'][0])
        np.testing.assert_allclose(np.log(base['growth_factors'][0]/reference),base['error_signs'][0]*api.scenario_errors[j],atol=1e-12)
        with self.assertRaises(ValueError):api.draw_market_paths(scenario='unknown')

    def test_historical_contract_and_calibration_boundaries(self):
        api=MultiTypeForecaster()
        for o in api.scenario_metadata['source_origins']:
            self.assertLessEqual(pd.Timestamp(o)+pd.DateOffset(months=12),pd.Timestamp(api.metadata['origin']))
        table=historical_forecast('2024-12')
        self.assertEqual(len(table),156)
        self.assertEqual(set(table.flat_type),{'3 ROOM','4 ROOM','5 ROOM'})
        self.assertFalse(table.duplicated(['town','flat_type','horizon_months']).any())
        with self.assertRaises(ValueError):historical_forecast('2024-11')

    def test_trusted_pickle_roundtrip_is_a_callable_inference_model(self):
        api=MultiTypeForecaster();loaded=pickle.loads(pickle.dumps(api))
        self.assertEqual(api.predict('NORTH-EAST','5 ROOM'),loaded.predict('NORTH-EAST','5 ROOM'))
        with DEFAULT_BUNDLE.with_name('forecast_model.pkl').open('rb') as stream:
            delivered=pickle.load(stream)
        self.assertEqual(api.predict('NORTH','3 ROOM'),delivered.predict('NORTH','3 ROOM'))


if __name__=='__main__':unittest.main()

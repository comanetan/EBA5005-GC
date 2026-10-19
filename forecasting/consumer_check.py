"""Consumer acceptance checks using ONLY the inference handover.

python -m forecasting.consumer_check
No training modules, raw datasets, Torch, statsmodels or optimisation sources.
Synthetic prices/availability below demonstrate the interface, not market facts.
"""
from pathlib import Path
import json
import pickle
import numpy as np
import pandas as pd
from .multitype_api import MultiTypeForecaster, DEFAULT_BUNDLE, run_joint_monte_carlo


def expect_rejection(call):
    try:call()
    except ValueError:return
    raise AssertionError('Invalid input did not raise the documented ValueError')


def check():
    api=MultiTypeForecaster()
    with DEFAULT_BUNDLE.with_name('forecast_model.pkl').open('rb') as stream:loaded=pickle.load(stream)
    assert loaded.__class__.__module__=='forecasting.multitype_api'
    assert api.metadata==loaded.metadata
    np.testing.assert_array_equal(api.errors,loaded.errors)
    np.testing.assert_array_equal(api.scenario_errors,loaded.scenario_errors)
    assert len(api.available_segments())==15
    for segment in api.available_segments():
        region,ft=segment.split('::')
        result=loaded.predict(region,ft,12,600000,api.metadata['origin'])
        assert result==api.predict(region,ft,12,600000,api.metadata['origin'])
        values=pd.DataFrame(result['forecasts'])
        assert len(values)==12 and values.month.is_unique
        assert values.month.iloc[0]=='2026-10' and values.month.iloc[-1]=='2027-09'
        assert np.isfinite(values[['p10','p50','p90']]).all().all()
        assert (values.p10.gt(0)&values.p10.le(values.p50)&values.p50.le(values.p90)).all()
        np.testing.assert_allclose(values.p50,600000*values.growth_factor_p50)
    scaled=pd.DataFrame(loaded.predict('NORTH-EAST','4 ROOM',12,660000,api.metadata['origin'])['forecasts'])
    base=pd.DataFrame(loaded.predict('NORTH-EAST','4 ROOM',12,600000,api.metadata['origin'])['forecasts'])
    np.testing.assert_allclose(scaled[['p10','p50','p90']],1.1*base[['p10','p50','p90']])
    print('PASS: JSON and delivered PKL agree for all 15 segments; dates, units and bounds are valid.')

    prices=pd.DataFrame(dict(profile_id=[f'HOUGANG|{ft}|80+|<500m|13+' for ft in ['3 ROOM','4 ROOM','5 ROOM']],
                             price=[400000.,550000.,700000.]))
    marginal=loaded.price_profiles(prices,api.metadata['origin'])
    assert list(marginal)==['profile_id','month','p10','p50','p90'] and len(marginal)==36
    table=loaded.town_forecast()
    assert len(table)==156 and not table.duplicated(['town','flat_type','horizon_months']).any()
    print('PASS: pricing input -> 36 profile-month rows and 156 town/type/horizon rows.')

    first=loaded.draw_market_paths(200,12,42);second=loaded.draw_market_paths(200,12,42)
    np.testing.assert_array_equal(first['growth_factors'],second['growth_factors'])
    assert first['growth_factors'].shape==(200,12,15)
    assert loaded.draw_market_paths(20,12,42,'rate_plus_1pp')['scenario_status']=='diagnostic_only'
    shortlist=pd.DataFrame(dict(profile_id=['demo3','demo4','demo5'],town='HOUGANG',
        flat_type=['3 ROOM','4 ROOM','5 ROOM'],price_today=[400000.,550000.,700000.],
        survival_prob_6m=.5,survival_prob_12m=.8))
    mc=run_joint_monte_carlo(shortlist,n_scenarios=200,seed=42)
    assert len(mc)==600
    assert not (mc.buy_now_available&~mc.wait6_available).any()
    assert not (mc.wait6_available&~mc.wait12_available).any()
    required={'profile_id','scenario_id','buy_now_price','buy_now_available','wait6_price','wait6_available','wait12_price','wait12_available'}
    assert required.issubset(mc.columns)
    print('PASS: joint paths are reproducible; mixed-type Monte Carlo schema and cumulative availability are valid.')

    for kwargs in [dict(region='NOT_A_REGION'),dict(flat_type='2 ROOM'),dict(horizon_months=13),
                   dict(horizon_months=True),dict(base_price_sgd=-1,base_price_month=api.metadata['origin']),
                   dict(base_price_sgd=500000,base_price_month='2026-08')]:
        expect_rejection(lambda kwargs=kwargs:loaded.predict(**{'region':'NORTH-EAST',**kwargs}))
    expect_rejection(lambda:loaded.price_profiles(pd.concat([prices,prices]),api.metadata['origin']))
    expect_rejection(lambda:loaded.price_profiles(prices.iloc[:0],api.metadata['origin']))
    bad=prices.copy();bad.loc[0,'price']=np.nan
    expect_rejection(lambda:loaded.price_profiles(bad,api.metadata['origin']))
    bad=prices.copy();bad['price']=True
    expect_rejection(lambda:loaded.price_profiles(bad,api.metadata['origin']))
    bad_shortlist=shortlist.copy();bad_shortlist.loc[0,'survival_prob_6m']=.9
    expect_rejection(lambda:run_joint_monte_carlo(bad_shortlist,n_scenarios=20))
    expect_rejection(lambda:loaded.simulate_paths(prices,api.metadata['origin'],n_scenarios='200'))
    expect_rejection(lambda:run_joint_monte_carlo(shortlist,n_scenarios='200'))
    print('PASS: unsupported types, dates, invalid prices/probabilities and duplicate/empty profiles fail clearly.')
    return dict(status='passed',model_version=api.metadata['model_version'],segments=15,
                profile_rows=len(marginal),town_forecast_rows=len(table),scenario_rows=len(mc),
                fixture='Synthetic interface checks; does not measure forecast accuracy or final UI integration.')


if __name__=='__main__':
    print(json.dumps(check(),indent=2))

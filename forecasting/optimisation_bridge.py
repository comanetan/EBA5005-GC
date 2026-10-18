"""Opt-in bridge matching Daniel's town forecast and Monte Carlo result columns.

Does not edit the optimisation branch. No untested flat type gets a silent fallback.
"""
from pathlib import Path
import numpy as np
import pandas as pd
from .joint_scenarios import JointScenarioForecaster
from .final_validation import available_error_paths, REGIONS

BASE=Path(__file__).resolve().parent


def historical_forecast(origin,method='nominal'):
    """Dated four-room growth factors; exact completed-month origin, never nearest match.

    Supported quarterly origins in evidence/final/historical_errors.csv. The output
    contains no realised outcomes. Price factor forecasts use only that origin's fit.
    """
    if method not in ['nominal','symmetric']:
        raise ValueError('method must be nominal or symmetric')
    origin=pd.Timestamp(origin)
    if origin.day!=1: raise ValueError('Use YYYY-MM, a monthly observation label')
    d=pd.read_csv(BASE/'evidence/final/historical_errors.csv')
    subset=d[d.origin.eq(str(origin.date()))]
    if len(subset)!=60: raise ValueError('No exact origin: generate an as-of fit instead of substituting a live forecast')
    model=JointScenarioForecaster()
    if method=='symmetric':
        bank,_=available_error_paths(d,origin)
        low,high=np.quantile(np.concatenate([bank,-bank]),[.1,.9],axis=0)
    rows=[]
    for town,region in model.point_model.metadata['town_to_region'].items():
        for h in [6,12]:
            row=subset[subset.region.eq(region)&subset.horizon.eq(h)].iloc[0]
            factor=row.growth_factor
            if method=='nominal':
                sd=(np.log(row.upper90)-np.log(row.forecast_index))/1.6448536269514722
                lo,hi=factor*np.exp(np.array([-1,1])*1.2815515655446004*sd)
            else:
                ri=REGIONS.index(region)
                lo,hi=factor*np.exp([low[h-1,ri],high[h-1,ri]])
            rows.append(dict(town=town,flat_type='4 ROOM',horizon_months=h,growth_factor=factor,
                growth_factor_lower=lo,growth_factor_upper=hi,
                _source=f'as-of {origin:%Y-%m}, {method}; four-room regional factors; retrospective model-family selection'))
    return pd.DataFrame(rows)


def run_joint_monte_carlo(shortlist,n_scenarios=2000,seed=42,base_price_month='2026-09',mode='symmetric'):
    """Drop-in result schema for Daniel's summarize_strategies (price+availability).

    Availability uses supplied cumulative probabilities and a single arrival uniform
    per profile/scenario: an arrival by month 6 must also be an arrival by month 12.
    Availability is assumed independent of market-price shocks and between profiles.
    This independence is a modelling assumption, not evidence from the pricing data.
    """
    required={'profile_id','town','flat_type','price_today','survival_prob_6m','survival_prob_12m'}
    if not required.issubset(shortlist.columns) or shortlist.empty or shortlist.profile_id.duplicated().any():
        raise ValueError('Supply a nonempty unique shortlist with prices and cumulative availability probabilities')
    if not shortlist.flat_type.eq('4 ROOM').all(): raise ValueError('Only four-room profiles are supported')
    model=JointScenarioForecaster(mode=mode)
    if base_price_month!=model.metadata['origin']: raise ValueError('Base prices and model origins must match')
    batch=model.draw(n_scenarios,12,seed)
    if len(shortlist)*n_scenarios>2_000_000: raise ValueError('Request a smaller shortlist/scenario count')
    rng=np.random.default_rng(seed+2)
    tables=[]
    for row in shortlist.itertuples(index=False):
        town=row.town.replace('-','/') if row.town=='KALLANG-WHAMPOA' else row.town
        region=model.point_model.metadata['town_to_region'].get(town)
        if region is None: raise ValueError(f'Unknown town: {town}')
        if not np.isfinite(row.price_today) or row.price_today<=0: raise ValueError('Invalid base price')
        p6,p12=float(row.survival_prob_6m),float(row.survival_prob_12m)
        if not 0<=p6<=p12<=1: raise ValueError('Availability must be finite cumulative probabilities: 0 <= p6 <= p12 <= 1')
        # Same approximation as existing pipeline: infer 1.5-month probability from p6.
        pnow=1-(1-p6)**.25
        arrival=rng.random(n_scenarios)
        ri=model.regions.index(region)
        tables.append(pd.DataFrame(dict(profile_id=row.profile_id,scenario_id=batch['scenario_ids'],
            regime=f'historical_{mode}',buy_now_price=row.price_today,buy_now_available=arrival<pnow,
            wait6_price=row.price_today*batch['growth_factors'][:,5,ri],wait6_available=arrival<p6,
            wait12_price=row.price_today*batch['growth_factors'][:,11,ri],wait12_available=arrival<p12,
            source_error_origin=batch['sampled_error_origins'],error_sign=batch['error_signs'])))
    result=pd.concat(tables,ignore_index=True)
    result.attrs['limitations']=model.metadata['warnings']+[
        'Availability/market independence and exponential 1.5-month interpolation are explicit approximations.',
        'Availability means a matching recorded transaction proxy, not guaranteed listing access or successful purchase.']
    return result


def main():
    root=BASE/'evidence/final/as_of'
    for origin in ['2022-12','2023-03','2023-06','2023-09','2023-12','2024-03','2024-06','2024-09','2024-12','2025-03','2025-06','2025-09']:
        dest=root/origin;dest.mkdir(parents=True,exist_ok=True)
        for method in ['nominal','symmetric']:
            historical_forecast(origin,method).to_csv(dest/f'price_forecast_{method}.csv',index=False)
    print('Exported 12 historical origins x 2 interval specifications')


if __name__=='__main__':main()

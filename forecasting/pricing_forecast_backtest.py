"""Evaluate actual Pricing Lead historical estimates + as-of forecasting factors.

This is a price-chain and budget-screening backtest, NOT Daniel's complete GP
recommender: no invented preferences, rental data or housing eligibility rules.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import numpy as np
import pandas as pd
from .compare_regional_location import load_features, BASE, FEATURES
from .optimisation_bridge import historical_forecast

ROOT=BASE.parent
OUT=BASE/'evidence/final'


def labels(values,bands):
    result=pd.Series('',index=values.index,dtype='object')
    for lo,hi,name in bands: result.loc[values.ge(lo)&values.lt(hi)]=name
    return result


def evaluation_ids(data,origin):
    """Match realised transactions to origin-date lease/MRT definitions."""
    path=str(ROOT/'src');sys.path.insert(0,path)
    try:
        spec=importlib.util.spec_from_file_location('features_for_evaluation',ROOT/'src/04_build_features.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    finally: sys.path.remove(path)
    blocks=pd.read_csv(BASE/'outputs/location_inputs/processed/block_features.csv')
    pts=pd.read_csv(BASE/'outputs/location_inputs/interim/amenity_points.csv')
    mrt=module.mrt_station_points(pts)
    distances,stations=module.block_station_distances(blocks,mrt)
    asof_distance=module.mrt_distance_at_sale(blocks,distances,stations,mrt,[origin]).set_index('address').dist_mrt_at_sale_m
    d=data.copy()
    date=pd.Timestamp(origin)
    lease=99-(date.year+(date.month-1)/12-d.lease_commence_date)
    lb=labels(lease,[(0,60,'<60'),(60,80,'60-79'),(80,100,'80+')])
    mb=labels(d.address.map(asof_distance),[(0,500,'<500m'),(500,1000,'500m-1km'),(1000,1e9,'>1km')])
    sb=labels(d.storey_mid,[(0,7,'1-6'),(7,13,'7-12'),(13,1000,'13+')])
    d['origin_profile_id']=d.town+'|'+d.flat_type+'|'+lb+'|'+mb+'|'+sb
    return d


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    data=load_features(); rows=[]; provenance=[]; decisions=[]
    for origin in ['2023-06','2024-12']:
        pricefile=ROOT/f'outputs/backtest/{origin}/prices.csv'
        prices=pd.read_csv(pricefile)
        prices=prices[prices.profile_id.str.split('|').str[1].eq('4 ROOM')].copy()
        prices['town']=prices.profile_id.str.split('|').str[0];prices['flat_type']='4 ROOM'
        prices['lease_band']=prices.profile_id.str.split('|').str[2]
        tx=evaluation_ids(data,origin)
        provenance.append(dict(origin=origin,pricing_sha256=hashlib.sha256(pricefile.read_bytes()).hexdigest(),profiles=len(prices)))
        for h in [6,12]:
            centre=pd.Timestamp(origin)+pd.DateOffset(months=h)
            window=tx[tx.month.between(centre-pd.DateOffset(months=1),centre+pd.DateOffset(months=1))]
            actual=window.groupby('origin_profile_id').resale_price.agg(realised_price='median',n_sales='size')
            for method in ['no_change','nominal','symmetric']:
                forecast=historical_forecast(origin,'nominal' if method=='no_change' else method)
                forecast=forecast[forecast.horizon_months.eq(h)]
                joined=prices.merge(forecast,on=['town','flat_type'],validate='many_to_one')
                if method=='no_change':
                    joined[['growth_factor','growth_factor_lower','growth_factor_upper']]=1.0
                joined=joined.merge(actual,left_on='profile_id',right_index=True,how='left',validate='one_to_one')
                joined['predicted_price']=joined.price*joined.growth_factor
                joined['lower']=joined.price*joined.growth_factor_lower
                joined['upper']=joined.price*joined.growth_factor_upper
                joined['origin']=origin;joined['horizon']=h;joined['method']=method
                rows.append(joined[['origin','horizon','method','profile_id','price','predicted_price','lower','upper','realised_price','n_sales']])
                # Controlled affordability screening comparison, deliberately not GP.
                for budget in [550000,650000,750000]:
                    feasible=joined[joined.upper.le(budget)&joined.lease_band.ne('<60')]
                    picks=feasible.sort_values(['predicted_price','profile_id']).drop_duplicates('town').head(5)
                    decisions.append(dict(origin=origin,horizon=h,method=method,budget=budget,
                        selected=len(picks),full_k=len(picks)==5,matched=int(picks.realised_price.notna().sum()),
                        within_budget=int((picks.realised_price.le(budget)&picks.realised_price.notna()).sum())))
        print(f'Completed price-chain backtest {origin}',flush=True)
    detail=pd.concat(rows,ignore_index=True)
    detail['APE_pct']=100*(detail.predicted_price/detail.realised_price-1).abs()
    detail['covered80']=detail.realised_price.between(detail.lower,detail.upper).where(detail.realised_price.notna())
    detail['upper90_covered']=detail.realised_price.le(detail.upper).where(detail.realised_price.notna())
    detail.to_csv(OUT/'profile_backtest_predictions.csv',index=False)
    summary=detail.groupby(['origin','horizon','method']).agg(profiles=('profile_id','size'),
        matched_profiles=('realised_price','count'),MAPE_pct=('APE_pct','mean'),median_APE_pct=('APE_pct','median'),
        coverage80=('covered80','mean'),upper90_coverage=('upper90_covered','mean'))
    # No-change has no probabilistic interval; do not present its point as a nominal band.
    summary.loc[summary.index.get_level_values('method')=='no_change',['coverage80','upper90_coverage']]=np.nan
    summary.to_csv(OUT/'profile_backtest_metrics.csv')
    pd.DataFrame(decisions).to_csv(OUT/'budget_screening_backtest.csv',index=False)
    (OUT/'profile_backtest_metadata.json').write_text(json.dumps(dict(pricing_inputs=provenance,
        feature_sha256=hashlib.sha256(FEATURES.read_bytes()).hexdigest(),
        realised_target='median recorded sale price in horizon minus/plus one month, with origin-date profile bands',
        limitations=['Only profiles with matching observed transactions contribute price errors; missing sales reported separately.',
                     'Existing Pricing Lead historical exports inherited as supplied; their code uses annual outlier flags and static amenities.',
                     'No claim that this completes the full preference/availability/GP recommender backtest.',
                     'Lease and MRT bands frozen to origin; approximate lease from commencement year like shared profile builder.',
                     'Selection is cheapest predicted price, five distinct towns, lease-band >=60, explicit budgets; not household utility.',
                     'Regional error bands omit profile valuation uncertainty; evaluate fine-cell coverage, not only regional coverage.']),indent=2),encoding='utf-8')
    print(summary.to_string())


if __name__=='__main__':main()

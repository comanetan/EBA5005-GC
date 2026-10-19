"""All-three-type price-chain checks and Punggol/Hougang controlled-profile pairs.

Uses real historical pricing exports; does not claim to reproduce final conjoint
or survival models. Matching-sale medians are retrospective outcomes, not listings.
"""
import json
import hashlib
import numpy as np
import pandas as pd
from .multitype_core import BASE, EVIDENCE, FLAT_TYPES, load_data
from .multitype_bridge import historical_forecast
from .pricing_forecast_backtest import evaluation_ids


def main():
    data=load_data();rows=[];sources=[]
    for origin in ['2023-06','2024-12']:
        path=BASE.parent/f'outputs/backtest/{origin}/prices.csv';prices=pd.read_csv(path)
        parts=prices.profile_id.str.split('|')
        prices=prices[parts.str[1].isin(FLAT_TYPES)].copy();parts=prices.profile_id.str.split('|')
        prices['town']=parts.str[0];prices['flat_type']=parts.str[1]
        tx=evaluation_ids(data,origin)
        sources.append(dict(origin=origin,pricing_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),profiles=len(prices)))
        for h in [6,12]:
            date=pd.Timestamp(origin)+pd.DateOffset(months=h)
            future=tx[tx.month.between(date-pd.DateOffset(months=1),date+pd.DateOffset(months=1))]
            actual=future.groupby('origin_profile_id').resale_price.agg(realised_price='median',n_sales='size')
            for method in ['no_change','nominal','symmetric']:
                f=historical_forecast(origin,'nominal' if method=='no_change' else method)
                f=f[f.horizon_months.eq(h)]
                if method=='no_change':f[['growth_factor','growth_factor_lower','growth_factor_upper']]=1.
                joined=prices.merge(f,on=['town','flat_type'],validate='many_to_one').merge(actual,left_on='profile_id',right_index=True,how='left',validate='one_to_one')
                joined['predicted_price']=joined.price*joined.growth_factor
                joined['lower']=joined.price*joined.growth_factor_lower;joined['upper']=joined.price*joined.growth_factor_upper
                joined['origin']=origin;joined['horizon']=h;joined['method']=method
                rows.append(joined[['origin','horizon','method','town','flat_type','profile_id','price','predicted_price','lower','upper','realised_price','n_sales']])
        print(f'Price-chain stress check complete: {origin}',flush=True)
    detail=pd.concat(rows,ignore_index=True)
    detail['APE_pct']=100*(detail.predicted_price/detail.realised_price-1).abs()
    detail['covered80']=detail.realised_price.between(detail.lower,detail.upper).where(detail.realised_price.notna())
    detail['upper90_covered']=detail.realised_price.le(detail.upper).where(detail.realised_price.notna())
    detail.to_csv(EVIDENCE/'profile_backtest_predictions.csv',index=False)
    def aggregate(groupcols):
        result=detail.groupby(groupcols).agg(profiles=('profile_id','size'),matched=('realised_price','count'),MAPE_pct=('APE_pct','mean'),
            coverage80=('covered80','mean'),upper90_coverage=('upper90_covered','mean')).reset_index()
        result.loc[result.method.eq('no_change'),['coverage80','upper90_coverage']]=np.nan
        return result
    aggregate(['origin','horizon','flat_type','method']).to_csv(EVIDENCE/'profile_backtest_metrics.csv',index=False)
    focused=detail[detail.town.isin(['PUNGGOL','HOUGANG'])]
    focus=focused.groupby(['origin','horizon','flat_type','town','method']).agg(profiles=('profile_id','size'),matched=('realised_price','count'),MAPE_pct=('APE_pct','mean')).reset_index()
    focus.to_csv(EVIDENCE/'estate_spotcheck_metrics.csv',index=False)
    pairs=[]
    for keys,g in focused[focused.method.eq('symmetric')].groupby(['origin','horizon','flat_type']):
        g=g.copy();g['attributes']=g.profile_id.str.split('|',n=1).str[1]
        a=g[g.town.eq('PUNGGOL')].set_index('attributes');b=g[g.town.eq('HOUGANG')].set_index('attributes')
        for key in a.index.intersection(b.index):
            x=a.loc[key];y=b.loc[key]
            base_ratio=x.price/y.price;predicted_ratio=x.predicted_price/y.predicted_price
            np.testing.assert_allclose(base_ratio,predicted_ratio,rtol=1e-12)
            pairs.append(dict(origin=keys[0],horizon=keys[1],flat_type=keys[2],attributes=key,
                base_ratio=base_ratio,predicted_ratio=predicted_ratio,
                actual_ratio=x.realised_price/y.realised_price if np.isfinite(x.realised_price) and np.isfinite(y.realised_price) else np.nan,
                predicted_gap_sgd=x.predicted_price-y.predicted_price,actual_gap_sgd=x.realised_price-y.realised_price))
    pairs=pd.DataFrame(pairs);pairs.to_csv(EVIDENCE/'estate_profile_pairs.csv',index=False)
    (EVIDENCE/'profile_stress_method.json').write_text(json.dumps(dict(sources=sources,
        estate_comparison='Punggol versus Hougang; compare same flat type/lease/MRT/storey profile attributes.',
        interpretation='Shared regional flat-type growth preserves the base-price ratio exactly; cannot learn separate town appreciation.',
        limitations=['Historical pricing exports inherit their supplied data-vintage/outlier/valuation limitations.',
            'Frozen origin lease/MRT bands and 3-month-window transaction medians; individual conditions unobserved.',
            'Missing matching sales excluded from price-error calculation and reported; not a successful purchase measure.',
            'Spot-check is a stress test of shared-growth assumption, not proof it holds or a causal town comparison.',
            'Nominal intervals and symmetric intervals are different assumptions; profile valuation uncertainty remains excluded.']),indent=2))


if __name__=='__main__':main()

"""Exact-origin historical forecast tables; no live forecast leakage into replays."""
import numpy as np
import pandas as pd
from scipy.stats import norm
from .multitype_api import MultiTypeForecaster, DEFAULT_BUNDLE
from .multitype_core import EVIDENCE


def historical_forecast(origin,method='symmetric',bundle=DEFAULT_BUNDLE):
    if method not in ['symmetric','nominal']:raise ValueError('Choose symmetric or nominal bounds')
    origin=pd.Timestamp(origin)
    if origin.day!=1:raise ValueError('Use an exact monthly observation label')
    api=MultiTypeForecaster(bundle)
    history=pd.read_csv(EVIDENCE/'quarterly_predictions.csv')
    chosen=history[history.apply(lambda row:row.model==api.metadata['segments'][row.segment]['model'],axis=1)]
    current=chosen[chosen.origin.eq(str(origin.date()))]
    if len(current)!=180:raise ValueError('No exact historical fit; never substitute a nearby/live forecast')
    if method=='symmetric':
        arrays=[]
        for o,g in chosen.groupby('origin'):
            if pd.Timestamp(o)+pd.DateOffset(months=12)>origin:continue
            matrix=g.pivot(index='horizon',columns='segment',values='log_error').reindex(index=range(1,13),columns=api.segment_ids)
            if matrix.isna().any().any() or len(g)!=180:raise ValueError('Incomplete historical calibration path')
            arrays.append(matrix.to_numpy())
        if not arrays:raise ValueError('No fully realised calibration paths at this origin')
        bank=np.stack(arrays);bounds=np.quantile(np.concatenate([bank,-bank]),[.1,.9],axis=0)
    rows=[]
    for town,region in api.metadata['town_to_region'].items():
        for ft in api.metadata['flat_types']:
            segment=f'{region}::{ft}';j=api.segment_ids.index(segment)
            for h in [6,12]:
                row=current[current.segment.eq(segment)&current.horizon.eq(h)].iloc[0]
                if method=='symmetric':lo,hi=row.growth_factor*np.exp(bounds[:,h-1,j])
                else:
                    if not np.isfinite(row.log_variance):raise ValueError('Selected model has no parametric interval')
                    lo,hi=row.growth_factor*np.exp(np.array([-1,1])*norm.ppf(.9)*np.sqrt(row.log_variance))
                rows.append(dict(town=town,flat_type=ft,horizon_months=h,growth_factor=row.growth_factor,
                    growth_factor_lower=lo,growth_factor_upper=hi,_source=f'Exact as-of {origin:%Y-%m}, {method}; retrospective selected-family reconstruction'))
    return pd.DataFrame(rows)

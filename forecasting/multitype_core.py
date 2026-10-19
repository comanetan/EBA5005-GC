"""Dated three-/four-/five-room indices and fixed candidate specifications.

All preprocessing coefficients are estimated at the forecast origin. Current
amenity, block and transaction vintages remain retrospective limitations.
"""
from pathlib import Path
import hashlib
import json
import warnings
import numpy as np
import pandas as pd
from scipy.linalg import qr
from scipy.stats import norm
from statsmodels.tsa.statespace.sarimax import SARIMAX
from .compare_sarimax_rates import DATES, design
from .compare_regional_location import FEATURES, CONTROLS, REGIONS
from .prepare_mas_rates import parse_mas, prepare_monthly, SOURCE

BASE=Path(__file__).resolve().parent
OUT=BASE/'outputs/multitype'
EVIDENCE=BASE/'evidence/multitype'
BUNDLE=BASE/'models/multitype'
FLAT_TYPES=['3 ROOM','4 ROOM','5 ROOM']
SEGMENTS=[f'{r}::{ft}' for ft in FLAT_TYPES for r in REGIONS]
POLICIES=[
    dict(announced='2021-12-15',effective='2021-12-16',monthly_activation='2022-01',
         source='https://www.hdb.gov.sg/business-partners/estate-agents-and-salespersons/letters-to-keos/measures-to-cool-the-property-market'),
    dict(announced='2022-09-29',effective='2022-09-30',monthly_activation='2022-10',
         source='https://www.hdb.gov.sg/hdb-pulse/news/2022/property-measures2022'),
    dict(announced='2024-08-18',effective='2024-08-20',monthly_activation='2024-09',
         source='https://www.hdb.gov.sg/hdb-pulse/news/2024/measures-to-cool-the-hdb-resale-market-and-provide-more-support-for-first-time-home-buyers'),
]
SPECS={
    'ARIMA_011_drift':((0,1,1),(0,0,0,0),'c',()),
    'ARIMA_111_drift':((1,1,1),(0,0,0,0),'c',()),
    'SARIMA_110_100':((1,1,0),(1,0,0,12),'n',()),
    'ARIMA_SORA':((0,1,1),(0,0,0,0),'c',('sora',)),
    'SARIMA_SORA':((1,1,0),(1,0,0,12),'n',('sora',)),
    'ARIMA_POLICY':((0,1,1),(0,0,0,0),'c',('policy',)),
    'ARIMA_SUPPLY':((0,1,1),(0,0,0,0),'c',('supply',)),
    'ARIMA_FULL':((0,1,1),(0,0,0,0),'c',('sora','policy','supply')),
    'SARIMA_FULL':((1,1,0),(1,0,0,12),'n',('sora','policy','supply')),
}


def load_data():
    OUT.mkdir(parents=True,exist_ok=True);EVIDENCE.mkdir(parents=True,exist_ok=True)
    d=pd.read_csv(FEATURES,low_memory=False)
    d['month']=pd.to_datetime(d.month)
    d=d[d.flat_type.isin(FLAT_TYPES)&d.month.between(DATES[0],DATES[-1])&d.flat_model.ne('Terrace')].copy()
    d['lease']=d.remaining_lease_yrs;d['lease2']=d.lease**2/100
    d['storey']=d.storey_mid;d['log_area']=np.log(d.floor_area_sqm)
    for target,source in [('log_dist_mrt','dist_mrt_at_sale_m'),('log_dist_hawker','dist_hawker_m'),('log_dist_park','dist_park_m')]:
        d[target]=np.log1p(d[source])
    valid=np.isfinite(d[['resale_price','log_area','lease','lease2','storey',*CONTROLS]]).all(axis=1)&d.resale_price.gt(0)
    audit=[]
    for segment in SEGMENTS:
        r,ft=segment.split('::');sub=d[d.region.eq(r)&d.flat_type.eq(ft)]
        counts=sub[valid.loc[sub.index]].groupby('month').size().reindex(DATES,fill_value=0)
        audit.append(dict(segment=segment,source_rows=len(sub),excluded_rows=int((~valid.loc[sub.index]).sum()),
                          months=len(counts),missing_months=int(counts.eq(0).sum()),minimum_monthly_sales=int(counts.min()),
                          median_monthly_sales=float(counts.median()),eligible=bool(counts.gt(0).all() and counts.iloc[:69].median()>=10)))
    audit=pd.DataFrame(audit);audit.to_csv(EVIDENCE/'data_coverage.csv',index=False)
    if not audit.eligible.all():raise ValueError('Some requested series lack sufficient history; inspect coverage')
    return d.loc[valid].copy()


def index_at_origin(frame,origin,end):
    """Train QR removes redundant controls; evaluation category exclusions explicit."""
    train=frame[frame.month<=origin]
    levels={c:sorted(train[c].unique()) for c in ['town','flat_model_group']}
    evaluation=frame[frame.month.between(origin+pd.offsets.MonthBegin(),end)].copy()
    supported=np.ones(len(evaluation),dtype=bool)
    for c,values in levels.items():supported &= evaluation[c].isin(values).to_numpy()
    excluded=int((~supported).sum());evaluation=evaluation.loc[supported]
    x=design(train,levels,CONTROLS)
    xd=(x-x.groupby(train.month).transform('mean')).to_numpy()
    _,rr,piv=qr(xd,mode='economic',pivoting=True)
    tolerance=np.finfo(float).eps*max(xd.shape)*max(abs(np.diag(rr)).max(),1.)
    rank=int((abs(np.diag(rr))>tolerance).sum());cols=sorted(piv[:rank])
    logp=pd.Series(np.log(train.resale_price),index=train.index)
    yd=logp-logp.groupby(train.month).transform('mean')
    beta=np.linalg.lstsq(xd[:,cols],yd,rcond=None)[0]
    alpha=pd.Series(logp.to_numpy()-x.to_numpy()[:,cols]@beta,index=train.index).groupby(train.month).mean()
    base=alpha.iloc[0]
    y=(100*np.exp(alpha-base)).reindex(pd.date_range(DATES[0],origin,freq='MS'))
    actual=pd.Series(dtype=float)
    if len(evaluation):
        adjusted=np.log(evaluation.resale_price)-design(evaluation,levels,CONTROLS).to_numpy()[:,cols]@beta
        actual=(100*np.exp(adjusted.groupby(evaluation.month).mean()-base)).reindex(pd.date_range(origin+pd.offsets.MonthBegin(),end,freq='MS'))
    if y.isna().any() or actual.isna().any():raise ValueError('Missing index month')
    return y,actual,dict(training_rows=len(train),excluded_future_categories=excluded,
                         candidate_controls=len(x.columns),retained_controls=rank,
                         dropped_controls=[c for i,c in enumerate(x.columns) if i not in cols])


def macro_inputs(data):
    rates=prepare_monthly(parse_mas(SOURCE));rates.index=pd.to_datetime(rates.month)
    raw=BASE.parent/'data/raw/HDBPropertyInformation.csv'
    blocks=pd.read_csv(raw);blocks['address']=blocks.blk_no.astype(str)+' '+blocks.street
    mapping=data[['address','region']].drop_duplicates()
    if mapping.address.duplicated().any():raise ValueError('Ambiguous block region')
    blocks=blocks.merge(mapping,on='address',how='left',validate='one_to_one')
    # Newer blocks may have no resale transaction yet. Infer their region from
    # the inventory's contract-town code, never from future price/sale counts.
    code_regions=blocks.dropna(subset=['region']).groupby('bldg_contract_town').region.agg(lambda x:sorted(set(x)))
    if code_regions.map(len).gt(1).any():raise ValueError('Ambiguous contract-town regional mapping')
    code_map={code:values[0] for code,values in code_regions.items()}
    address_mapped=int(blocks.region.notna().sum())
    blocks['region']=blocks.region.fillna(blocks.bldg_contract_town.map(code_map))
    rows=[]
    for ft in FLAT_TYPES:
        col=f'{ft[0]}room_sold'
        cohorts=blocks.groupby(['region','year_completed'])[col].sum()
        for r in REGIONS:
            for year in range(2016,2029):
                rows.append(dict(region=r,flat_type=ft,year=year,proxy_units=float(cohorts.get((r,year-5),0))))
    supply=pd.DataFrame(rows)
    supply.to_csv(EVIDENCE/'completion_cohort_proxy.csv',index=False)
    (EVIDENCE/'macro_sources.json').write_text(json.dumps(dict(
        policies=POLICIES,policy_definition='Cumulative selected HDB cooling-package indicators, active first full following month; events unknown at origin excluded from future path.',
        policy_interpretation='Predictive step regressor only; packages differ, are endogenous and include offsetting grants; no causal interpretation.',
        supply_definition='Units sold by flat type in current block inventory, grouped by region and year_completed + 5; log1p annual cohort count, lagged one month.',
        supply_limitations=['Not actual MOP completion or listing supply: key collection/occupation/exceptions unavailable.',
            'Current stock and address mapping, including survivor/revision bias; proxy experiment not vintage-correct supply forecast.',
            'Contract-town codes inferred from unambiguous regional addresses include newer untransacted blocks; unmapped codes outside team geography omitted.',
            'No within-year completion dates; no actual future transactions used to count supply.'],
        proxy_version='completion-cohort-contract-town-v2',address_mapped_blocks=address_mapped,
        contract_code_added_blocks=int(blocks.region.notna().sum())-address_mapped,
        contract_town_to_region=code_map,mapped_blocks=int(blocks.region.notna().sum()),unmapped_blocks=int(blocks.region.isna().sum()),
        mapped_sold_units={ft:int(blocks.loc[blocks.region.notna(),f'{ft[0]}room_sold'].sum()) for ft in FLAT_TYPES},
        property_information_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
        sora_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        mop_reference='https://www.hdb.gov.sg/managing-my-home/home-ownership/acquiring-private-property',
        dm_reference='https://www.sciencedirect.com/science/article/pii/S0169207096007194',
        dm_caution_reference='https://economics.sas.upenn.edu/sites/default/files/filevault/12-035.pdf'),indent=2))
    return rates,supply


def regressors(dates,origin,segment,rates,supply,rate_shift=0.,supply_multiplier=1.):
    r,ft=segment.split('::');origin=pd.Timestamp(origin)
    x=pd.DataFrame(index=dates)
    known=float(rates.loc[origin,'sora_3m_eom_pct_pa'])
    x['sora']=[rates.loc[t,'sora_3m_eom_lag1_pct_pa'] if t<=origin else known+(rate_shift if t>origin+pd.offsets.MonthBegin() else 0.) for t in dates]
    announced=[p for p in POLICIES if pd.Timestamp(p['announced'])<=origin+pd.offsets.MonthEnd()]
    x['policy']=[sum(t>=pd.Timestamp(p['monthly_activation']) for p in announced) for t in dates]
    counts=supply[supply.region.eq(r)&supply.flat_type.eq(ft)].set_index('year').proxy_units
    # completion cohort for t-1, not later observed transaction volume.
    x['supply']=[np.log1p(float(counts.loc[(t-pd.offsets.MonthBegin()).year])*(supply_multiplier if t>origin+pd.offsets.MonthBegin() else 1.)) for t in dates]
    return x


def fit_forecast(y,name,segment,rates,supply,rate_shift=0.,supply_multiplier=1.):
    dates=pd.date_range(y.index[-1]+pd.offsets.MonthBegin(),periods=12,freq='MS')
    z=np.log(y);origin=y.index[-1]
    if name in ['naive','seasonal_naive']:
        mu=np.repeat(z.iloc[-1],12) if name=='naive' else z.iloc[-12:].to_numpy()
        var=np.arange(1,13)*float(np.mean(z.diff().dropna()**2)) if name=='naive' else np.repeat(float(np.mean(z.diff(12).dropna()**2)),12)
        return mu,var,None,dict(converged=True,regressors=[])
    order,seasonal,trend,requested=SPECS[name]
    exog=regressors(y.index.append(dates),origin,segment,rates,supply,rate_shift,supply_multiplier)
    train=exog.loc[y.index];columns=[c for c in requested if train[c].std(ddof=0)>1e-8]
    means=train[columns].mean();scales=train[columns].std(ddof=0)
    x=(train[columns]-means)/scales if columns else None
    future=(exog.loc[dates,columns]-means)/scales if columns else None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        fit=SARIMAX(z,exog=x,order=order,seasonal_order=seasonal,trend=trend).fit(disp=False,maxiter=250)
        if not fit.mle_retvals.get('converged',False):fit=fit.model.fit(method='powell',disp=False,maxiter=500)
    if not fit.mle_retvals.get('converged',False):raise ValueError('Nonconvergent fit')
    fc=fit.get_forecast(12,exog=future)
    mu,var=np.asarray(fc.predicted_mean),np.asarray(fc.var_pred_mean)
    if not np.isfinite(mu).all() or not np.isfinite(var).all() or (var<0).any():raise ValueError('Invalid forecast')
    return mu,var,fit,dict(converged=True,regressors=columns,inactive_regressors=list(set(requested)-set(columns)),
        aic=float(fit.aic),warnings=[str(w.message) for w in caught],
        exog_mean=means.to_dict(),exog_scale=scales.to_dict())

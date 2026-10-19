"""Exploratory paired forecast comparisons with dependent multi-step losses.

The independent unit is a quarterly forecast origin, not a region-month row.
Positive DM statistics mean forecast A has larger absolute percentage loss.
"""
import json
import math
import numpy as np
import pandas as pd
from scipy.stats import t as student_t
from .multitype_core import EVIDENCE, SEGMENTS


def dm_test(loss_a,loss_b,horizon_months,origin_spacing_months=3):
    a=np.asarray(loss_a,float);b=np.asarray(loss_b,float)
    if a.shape!=b.shape or a.ndim!=1 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('Supply matched finite one-dimensional loss sequences')
    if horizon_months not in [6,12] or origin_spacing_months!=3:
        raise ValueError('This implementation is evaluated at six/twelve months on a quarterly grid')
    d=a-b;n=len(d);effective_h=int(math.ceil(horizon_months/origin_spacing_months));lag=effective_h-1
    result=dict(n_origins=n,mean_loss_difference=float(d.mean()),hac_lag=lag,effective_horizon=effective_h,
                statistic=None,p_value=None,status='insufficient_origins')
    if n<max(8,2*effective_h):return result
    centered=d-d.mean();lrv=float(centered@centered/n)
    for k in range(1,lag+1):lrv+=2*(1-k/(lag+1))*float(centered[k:]@centered[:-k]/n)
    result['long_run_variance']=lrv
    if lrv<=np.finfo(float).eps:
        result['status']='zero_loss_variance';return result
    correction=np.sqrt((n+1-2*effective_h+effective_h*(effective_h-1)/n)/n)
    statistic=float(d.mean()/np.sqrt(lrv/n)*correction)
    result.update(statistic=statistic,p_value=float(2*student_t.sf(abs(statistic),df=n-1)),status='exploratory')
    return result


def bh_adjust(pvalues):
    values=np.asarray(pvalues,float);result=np.full(len(values),np.nan)
    ids=np.flatnonzero(np.isfinite(values));ordered=ids[np.argsort(values[ids])]
    if not len(ordered):return result
    adjusted=values[ordered]*len(ordered)/np.arange(1,len(ordered)+1)
    result[ordered]=np.minimum(1,np.minimum.accumulate(adjusted[::-1])[::-1])
    return result


def export_comparisons(history,winners):
    rows=[]
    for segment,g in history.groupby('segment'):
        ft=segment.split('::')[1]
        for horizon in [6,12]:
            pivot=g[g.horizon.eq(horizon)].pivot(index='origin',columns='model',values='APE_pct').sort_index()
            if len(pivot)!=21:raise ValueError('DM requires complete chronological quarterly-origin pairs')
            for a,b in [('ARIMA_011_drift','pooled_LSTM'),('naive','pooled_LSTM'),(winners[ft],'pooled_LSTM')]:
                label='selected_vs_lstm' if a==winners[ft] else a+'_vs_lstm'
                rows.append(dict(segment=segment,horizon=horizon,comparison=label,model_a=a,model_b=b,
                                 **dm_test(pivot[a],pivot[b],horizon)))
    # Remove duplicate selected/ARIMA or selected/naive comparisons.
    result=pd.DataFrame(rows).drop_duplicates(['segment','horizon','model_a','model_b'])
    result['p_value_bh']=bh_adjust(pd.to_numeric(result.p_value,errors='coerce'))
    result.to_csv(EVIDENCE/'diebold_mariano.csv',index=False)
    aggregate=[]
    for horizon in [6,12]:
        h=history[history.horizon.eq(horizon)]
        for a,b in [('ARIMA_011_drift','pooled_LSTM'),('naive','pooled_LSTM'),('selected_by_flat_type','pooled_LSTM')]:
            if a=='selected_by_flat_type':
                lhs=h[h.apply(lambda row:row.model==winners[row.flat_type],axis=1)].groupby('origin').APE_pct.mean()
                rhs=h[h.model.eq(b)].groupby('origin').APE_pct.mean()
                by=pd.concat([lhs.rename(a),rhs.rename(b)],axis=1).sort_index()
            else:by=h[h.model.isin([a,b])].groupby(['origin','model']).APE_pct.mean().unstack('model').sort_index()
            aggregate.append(dict(horizon=horizon,model_a=a,model_b=b,**dm_test(by[a],by[b],horizon)))
    aggregate=pd.DataFrame(aggregate);aggregate['p_value_bh']=bh_adjust(pd.to_numeric(aggregate.p_value,errors='coerce'))
    aggregate.to_csv(EVIDENCE/'diebold_mariano_aggregate.csv',index=False)
    # Honest historical interval evaluation: calibration paths must be fully realised.
    selected=history[history.apply(lambda row:row.model==winners[row.flat_type],axis=1)]
    matrices={}
    for o,g in selected.groupby('origin'):
        matrix=g.pivot(index='horizon',columns='segment',values='log_error').reindex(index=range(1,13),columns=SEGMENTS)
        if len(g)!=180 or matrix.isna().any().any():raise ValueError('Incomplete selected path')
        matrices[o]=matrix.to_numpy()
    coverage=[]
    for origin in sorted(matrices):
        if pd.Timestamp(origin)<pd.Timestamp('2022-09'):continue
        prior=[e for o,e in matrices.items() if pd.Timestamp(o)+pd.DateOffset(months=12)<=pd.Timestamp(origin)]
        bank=np.stack(prior);bounds=np.quantile(np.concatenate([bank,-bank]),[.1,.9],axis=0)
        realised=matrices[origin]
        for j,segment in enumerate(SEGMENTS):
            coverage.append(dict(origin=origin,segment=segment,calibration_paths=len(bank),
                coverage80=float(((realised[:,j]>=bounds[0,:,j])&(realised[:,j]<=bounds[1,:,j])).mean()),
                upper90_coverage=float((realised[:,j]<=bounds[1,:,j]).mean()),
                mean_width_factor=float(np.mean(np.exp(bounds[1,:,j])-np.exp(bounds[0,:,j])))))
    pd.DataFrame(coverage).to_csv(EVIDENCE/'rolling_interval_coverage.csv',index=False)
    (EVIDENCE/'comparison_method.json').write_text(json.dumps(dict(
        loss='Absolute percentage error at horizon 6 or 12; paired within segment and origin.',
        origins='21 quarterly origins September 2020 to September 2025; same fifteen series.',
        variance='Bartlett/Newey-West long-run loss variance; lags ceil(horizon/3)-1.',
        finite_sample='Harvey-Leybourne-Newbold-style adjustment using horizon on quarterly grid; Student t, n-1 df.',
        multiplicity='BH-adjusted p-values across distinct segment comparisons; aggregate comparisons reported separately.',
        interpretation=['Exploratory forecast comparisons; no independent untouched test or proof of best model.',
            'Short, overlapping origins and retrospective specification/model selection limit p-value reliability.',
            'Region/flat-type errors share shocks: do not treat 15 series as 15 times more independent origins.',
            'Comparisons to a selected model inherit selection bias; BH does not remove selection bias.',
            'Zero loss variance or insufficient origins returns no p-value; non-rejection is not equivalence.'],
        references=['https://www.sciencedirect.com/science/article/pii/S0169207096007194',
                    'https://economics.sas.upenn.edu/sites/default/files/filevault/12-035.pdf']),indent=2))

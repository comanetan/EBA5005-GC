"""Reproducible scope expansion: coverage, ablations, pooled LSTM and joint errors.

Run in stages: --stage annual, rolling, export, or all. Model selection uses
the original three annual validation origins; quarterly checks are exploratory.
"""
import argparse
import hashlib
import json
import warnings
import numpy as np
import pandas as pd
from scipy.stats import norm
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from .multitype_core import *
from .compare_pooled_lstm import fit_predict, SEEDS

ANNUAL=pd.date_range('2022-09','2025-09',freq='12MS')
QUARTERLY=pd.date_range('2020-09','2025-09',freq='3MS')


def get_indices(data,origin):
    folder=OUT/'indices';folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'{origin:%Y-%m}.csv';meta=path.with_suffix('.json')
    fingerprint=hashlib.sha256(FEATURES.read_bytes()).hexdigest()
    if path.exists() and meta.exists():
        info=json.loads(meta.read_text())
        if info['source_sha256']!=fingerprint:raise ValueError('Cached index source changed; use a new output folder')
        return pd.read_csv(path),info['audit']
    rows=[];audit=[];end=min(origin+pd.DateOffset(months=12),DATES[-1])
    for segment in SEGMENTS:
        r,ft=segment.split('::');frame=data[data.region.eq(r)&data.flat_type.eq(ft)]
        y,actual,info=index_at_origin(frame,origin,end)
        audit.append(dict(segment=segment,origin=str(origin.date()),**info))
        for kind,series in [('training',y),('evaluation_frozen_coefficients',actual)]:
            rows.extend(dict(origin=str(origin.date()),region=segment,month=str(t.date()),kind=kind,index=float(v)) for t,v in series.items())
    result=pd.DataFrame(rows);result.to_csv(path,index=False)
    meta.write_text(json.dumps(dict(source_sha256=fingerprint,audit=audit),indent=2))
    return pd.read_csv(path),audit


def lstm_forecasts(frame,origin,save=True):
    import torch
    results=[];members=[]
    for seed in SEEDS:
        regions,growth,anchors,model,metadata=fit_predict(frame,seed)
        results.append(growth)
        if save:
            folder=OUT/'lstm';folder.mkdir(exist_ok=True)
            torch.save(dict(state_dict=model.state_dict(),metadata=metadata),folder/f'{origin:%Y-%m}_{seed}.pt')
        members.append(metadata)
    ensemble=np.mean(results,axis=0)
    return {segment:np.log(anchors[segment])+ensemble[i] for i,segment in enumerate(regions)},members


def records(frame,segment,name,mu,var,origin):
    actual=frame[frame.region.eq(segment)&frame.kind.eq('evaluation_frozen_coefficients')].sort_values('month')
    train=frame[frame.region.eq(segment)&frame.kind.eq('training')].sort_values('month')
    anchor=float(train['index'].iloc[-1]);r,ft=segment.split('::')
    result=[]
    for i,row in enumerate(actual.itertuples()):
        predicted=float(np.exp(mu[i]))
        if not np.isfinite(predicted) or predicted<=0:raise ValueError('Forecast overflow')
        result.append(dict(segment=segment,region=r,flat_type=ft,origin=str(origin.date()),month=row.month,horizon=i+1,
            model=name,actual_index=row.index,forecast_index=predicted,growth_factor=predicted/anchor,
            log_error=float(np.log(row.index)-mu[i]),log_variance=float(var[i]) if var is not None else np.nan,
            APE_pct=100*abs(predicted/row.index-1)))
    return result


def annual(data,rates,supply):
    all_rows=[];logs=[];audits=[]
    signature=hashlib.sha256((rates.to_csv(index=False)+supply.to_csv(index=False)+json.dumps(POLICIES,sort_keys=True)).encode()).hexdigest()
    for origin in ANNUAL:
        frame,audit=get_indices(data,origin);audits.extend(audit)
        # Cache completed origin predictions; cache fingerprint is checked by get_indices.
        cache=OUT/f'annual_{origin:%Y-%m}.csv';logfile=cache.with_suffix('.json')
        origin_rows=[];origin_logs=[]
        if cache.exists() and logfile.exists():
            cached=pd.read_csv(cache);oldlogs=json.loads(logfile.read_text())
            if any(x.get('cache_macro_sha256')==signature for x in oldlogs):
                all_rows.extend(cached.to_dict('records'));logs.extend(oldlogs);continue
            # Reuse purely univariate/LSTM results; refit changed macro inputs.
            reusable=['naive','seasonal_naive','ARIMA_011_drift','ARIMA_111_drift','SARIMA_110_100','pooled_LSTM']
            origin_rows.extend(cached[cached.model.isin(reusable)].to_dict('records'))
            origin_logs.extend(x for x in oldlogs if x.get('model') in reusable)
        for segment in SEGMENTS:
            tr=frame[frame.region.eq(segment)&frame.kind.eq('training')].sort_values('month')
            y=pd.Series(tr['index'].to_numpy(),index=pd.to_datetime(tr.month))
            for name in ['naive','seasonal_naive',*SPECS]:
                if sum(x['segment']==segment and x['model']==name for x in origin_rows)==12:continue
                try:
                    mu,var,_,info=fit_forecast(y,name,segment,rates,supply)
                    origin_rows.extend(records(frame,segment,name,mu,var,origin))
                    origin_logs.append(dict(origin=str(origin.date()),segment=segment,model=name,**info))
                except Exception as exc:origin_logs.append(dict(origin=str(origin.date()),segment=segment,model=name,error=str(exc)))
            print(f'Annual {origin:%Y-%m} {segment}: statistical candidates done',flush=True)
        if sum(x['model']=='pooled_LSTM' for x in origin_rows)!=180:
            forecasts,training=lstm_forecasts(frame,origin)
            for segment,mu in forecasts.items():origin_rows.extend(records(frame,segment,'pooled_LSTM',mu,None,origin))
            origin_logs.append(dict(origin=str(origin.date()),model='pooled_LSTM',training=training))
        origin_logs.append(dict(cache_macro_sha256=signature))
        pd.DataFrame(origin_rows).to_csv(cache,index=False);logfile.write_text(json.dumps(origin_logs,indent=2))
        all_rows.extend(origin_rows);logs.extend(origin_logs)
    predictions=pd.DataFrame(all_rows)
    predictions['stage']=np.where(predictions.origin.eq('2025-09-01'),'later_period_check','validation')
    predictions.to_csv(EVIDENCE/'annual_predictions.csv',index=False)
    pd.DataFrame(audits).to_csv(EVIDENCE/'index_audit.csv',index=False)
    (EVIDENCE/'fit_log.json').write_text(json.dumps(logs,indent=2))
    metric=predictions.groupby(['stage','flat_type','region','model']).agg(MAPE_pct=('APE_pct','mean'),n=('APE_pct','size')).reset_index()
    metric.to_csv(EVIDENCE/'metrics_by_segment.csv',index=False)
    summary=metric.groupby(['stage','flat_type','model']).agg(MAPE_pct=('MAPE_pct','mean'),regions=('region','nunique'),minimum_n=('n','min')).reset_index()
    summary.to_csv(EVIDENCE/'model_comparison.csv',index=False)
    candidates=summary[summary.stage.eq('validation')&summary.regions.eq(5)&summary.minimum_n.eq(36)]
    winners=candidates.sort_values(['flat_type','MAPE_pct','model']).groupby('flat_type').head(1)
    if len(winners)!=3:raise ValueError('No complete candidate for every flat type')
    winners.to_csv(EVIDENCE/'selected_models.csv',index=False)
    print('Selected by earlier validation:\n'+winners.to_string(index=False),flush=True)


def rolling(data,rates,supply):
    winners=pd.read_csv(EVIDENCE/'selected_models.csv').set_index('flat_type').model.to_dict()
    signature=hashlib.sha256((rates.to_csv(index=False)+supply.to_csv(index=False)+json.dumps(POLICIES,sort_keys=True)+json.dumps(winners,sort_keys=True)).encode()).hexdigest()
    stamp=OUT/'rolling_inputs.json'
    if stamp.exists() and json.loads(stamp.read_text())['inputs_sha256']!=signature:
        raise ValueError('Rolling cache inputs changed; archive/remove only outputs/multitype/quarterly_*.csv and rolling_inputs.json before refitting')
    stamp.write_text(json.dumps(dict(inputs_sha256=signature,selected_models=winners)))
    result=[];audits=[]
    for origin in QUARTERLY:
        frame,audit=get_indices(data,origin);audits.extend(audit)
        cache=OUT/f'quarterly_{origin:%Y-%m}.csv'
        origin_rows=[]
        if cache.exists():origin_rows=pd.read_csv(cache).to_dict('records')
        complete=all(sum(x['segment']==s and x['model']==name for x in origin_rows)==12
            for s in SEGMENTS for name in set(['naive','ARIMA_011_drift',winners[s.split('::')[1]],'pooled_LSTM']))
        if complete:result.extend(origin_rows);continue
        forecasts=None
        for segment in SEGMENTS:
            ft=segment.split('::')[1]
            tr=frame[frame.region.eq(segment)&frame.kind.eq('training')].sort_values('month')
            y=pd.Series(tr['index'].to_numpy(),index=pd.to_datetime(tr.month))
            for name in sorted(set(['naive','ARIMA_011_drift',winners[ft],'pooled_LSTM'])):
                if sum(x['segment']==segment and x['model']==name for x in origin_rows)==12:continue
                if name=='pooled_LSTM':
                    if forecasts is None:forecasts,_=lstm_forecasts(frame,origin)
                    mu,var=forecasts[segment],None
                else:mu,var,_,_=fit_forecast(y,name,segment,rates,supply)
                origin_rows.extend(records(frame,segment,name,mu,var,origin))
        pd.DataFrame(origin_rows).to_csv(cache,index=False);result.extend(origin_rows)
        print(f'Quarterly {origin:%Y-%m}: all fifteen series complete',flush=True)
    pred=pd.DataFrame(result);pred.to_csv(EVIDENCE/'quarterly_predictions.csv',index=False)
    pd.DataFrame(audits).to_csv(EVIDENCE/'quarterly_index_audit.csv',index=False)


def export(data,rates,supply):
    from .forecast_comparison import export_comparisons
    BUNDLE.mkdir(parents=True,exist_ok=True)
    winners=pd.read_csv(EVIDENCE/'selected_models.csv').set_index('flat_type').model.to_dict()
    history=pd.read_csv(EVIDENCE/'quarterly_predictions.csv')
    # Fit the scenario challenger at the same historical origins. Its uncertainty
    # must not silently borrow errors from a different selected model.
    challenger=[]
    signature=hashlib.sha256((rates.to_csv(index=False)+supply.to_csv(index=False)+json.dumps(POLICIES,sort_keys=True)).encode()).hexdigest()
    for origin in QUARTERLY:
        cache=OUT/f'scenario_errors_{origin:%Y-%m}.csv'
        stamp=cache.with_suffix('.json')
        if cache.exists() and stamp.exists() and json.loads(stamp.read_text()).get('macro_sha256')==signature:
            challenger.extend(pd.read_csv(cache).to_dict('records'));continue
        frame,_=get_indices(data,origin);part=[]
        for segment in SEGMENTS:
            tr=frame[frame.region.eq(segment)&frame.kind.eq('training')].sort_values('month')
            y=pd.Series(tr['index'].to_numpy(),index=pd.to_datetime(tr.month))
            mu,var,_,_=fit_forecast(y,'ARIMA_FULL',segment,rates,supply)
            part.extend(records(frame,segment,'ARIMA_FULL',mu,var,origin))
        pd.DataFrame(part).to_csv(cache,index=False);stamp.write_text(json.dumps(dict(macro_sha256=signature)));challenger.extend(part)
        print(f'Scenario challenger errors {origin:%Y-%m}: complete',flush=True)
    challenger=pd.DataFrame(challenger);challenger.to_csv(EVIDENCE/'scenario_challenger_predictions.csv',index=False)
    chosen=history[history.apply(lambda row:row.model==winners[row.flat_type],axis=1)].copy()
    arrays=[];labels=[]
    for origin,g in chosen.groupby('origin'):
        matrix=g.pivot(index='horizon',columns='segment',values='log_error').reindex(index=range(1,13),columns=SEGMENTS)
        if len(g)!=180 or matrix.isna().any().any():raise ValueError('Incomplete joint fifteen-series error path')
        arrays.append(matrix.to_numpy());labels.append(origin)
    errors=np.stack(arrays)
    if any(pd.Timestamp(o)+pd.DateOffset(months=12)>DATES[-1] for o in labels):raise ValueError('Unobserved calibration outcome')
    bounds=np.quantile(np.concatenate([errors,-errors]),[.1,.5,.9],axis=0)
    frame,_=get_indices(data,DATES[-1]);neural,_=lstm_forecasts(frame,DATES[-1])
    segments={};diagnostics=[];parameters=[];scenarios=[];scenario_segments={};challenger_diagnostics=[];scenario_parameters=[]
    for j,segment in enumerate(SEGMENTS):
        ft=segment.split('::')[1];name=winners[ft]
        tr=frame[frame.region.eq(segment)&frame.kind.eq('training')].sort_values('month')
        y=pd.Series(tr['index'].to_numpy(),index=pd.to_datetime(tr.month))
        # A documented refinement was compared rather than treating a residual
        # rejection as irrelevant. Diagnose it separately without changing the
        # validation-based selection rule after seeing full-history residuals.
        _,_,alternative,_=fit_forecast(y,'ARIMA_111_drift',segment,rates,supply)
        alt_resid=np.asarray(alternative.filter_results.standardized_forecasts_error[0])[12:]
        challenger_diagnostics.append(dict(segment=segment,model='ARIMA_111_drift',
            ljung_box_lag12_p=float(acorr_ljungbox(alt_resid,lags=[12],model_df=2,return_df=True).lb_pvalue.iloc[0]),
            arch_lag6_p=float(het_arch(alt_resid,nlags=6)[1])))
        fit=None
        if name=='pooled_LSTM':mu,var=neural[segment],None
        else:
            mu,var,fit,info=fit_forecast(y,name,segment,rates,supply)
            if fit is not None:
                fit.save(BUNDLE/(segment.replace('::','__').replace(' ','_')+'.pkl'))
                residual=np.asarray(fit.filter_results.standardized_forecasts_error[0])[12:]
                df=sum(p.startswith(('ar.','ma.')) for p in fit.param_names)
                lb=acorr_ljungbox(residual,lags=[12],model_df=df,return_df=True)
                diagnostics.append(dict(segment=segment,model=name,ljung_box_lag12_p=float(lb.lb_pvalue.iloc[0]),arch_lag6_p=float(het_arch(residual,nlags=6)[1])))
                parameters.extend(dict(segment=segment,parameter=p,value=float(v)) for p,v in zip(fit.param_names,fit.params))
        growth=np.exp(mu)/float(y.iloc[-1]);quantiles=growth[:,None]*np.exp(bounds[:,:,j].T)
        segments[segment]=dict(model=name,reference_index=float(y.iloc[-1]),log_mean=np.asarray(mu).tolist(),
            log_variance=np.asarray(var).tolist() if var is not None else None,
            growth_quantiles=quantiles.tolist(),training_months=len(y))
        # Sensitivity always uses a labelled full-regressor challenger, even if not selected.
        for label,shift,mult in [('base',0.,1.),('rate_minus_1pp',-1.,1.),('rate_plus_1pp',1.,1.),('cohort_minus20pct',0.,.8),('cohort_plus20pct',0.,1.2)]:
            smu,_,scenario_fit,scenario_info=fit_forecast(y,'ARIMA_FULL',segment,rates,supply,shift,mult)
            if label=='base':
                for column in scenario_info['regressors']:
                    scenario_parameters.append(dict(segment=segment,regressor=column,
                        coefficient_original_units=float(scenario_fit.params[column]/scenario_info['exog_scale'][column]),
                        interpretation='Predictive association in log-index equation, not a causal effect'))
            scenario_segments.setdefault(label,{})[segment]=dict(model='ARIMA_FULL_challenger',log_mean=smu.tolist(),reference_index=float(y.iloc[-1]))
            for h in [6,12]:scenarios.append(dict(segment=segment,model='ARIMA_FULL_challenger',scenario=label,horizon=h,growth_factor=float(np.exp(smu[h-1])/y.iloc[-1]),rate_shift_percentage_points=shift,cohort_multiplier=mult))
        print(f'Exported {segment}: {name}',flush=True)
    config=json.loads((BASE/'models/regional/manifest.json').read_text())
    fingerprint=hashlib.sha256(FEATURES.read_bytes()).hexdigest()
    manifest=dict(schema_version=3,model_version='multitype-v2-202609-'+fingerprint[:12]+'-'+signature[:8],origin='2026-09',
        training_start='2017-01',max_horizon_months=12,flat_types=FLAT_TYPES,segments=segments,scenario_segments=scenario_segments,town_to_region=config['town_to_region'],
        selection='One family per flat type, lowest equal-region MAPE across three earlier annual origins; retrospective specification expansion.',
        uncertainty='exploratory sign-symmetric joint historical log-error paths; marginal p10/p50/p90',
        features_sha256=fingerprint,macro_sha256=signature,selected_model_by_type=winners,status='prototype_exploratory_uncertainty',warnings=[
            'Selected using retrospective validation; later and quarterly periods are not pristine holdouts.',
            'Static amenities, current block inventory and data vintages limit historical availability claims.',
            'Supply is completion-cohort proxy, not actual MOP or listings; policy regressors are not causal effects.',
            '21 overlapping quarterly paths; sign mirroring assumes symmetry; no 90% affordability guarantee.',
            'All profiles within a regional flat-type segment share growth; individual valuation/availability uncertainty excluded.',
            'Scenario challenger is separate from selected model; scenarios are assumptions, not probabilities.',
            'Full-regressor challenger has sign-inconsistent economic responses; named macro scenarios are diagnostic only, not validated interventions.'])
    coefficients=pd.DataFrame(scenario_parameters)
    manifest['scenario_validation']=dict(status='diagnostic_only',positive_sora_coefficients=int(coefficients[coefficients.regressor.eq('sora')].coefficient_original_units.gt(0).sum()),
        total_segments=len(SEGMENTS),interpretation='Positive SORA associations in most segments; do not infer rate increases cause price increases.')
    (BUNDLE/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False))
    challenger_errors=[]
    for origin in labels:
        g=challenger[challenger.origin.eq(origin)]
        matrix=g.pivot(index='horizon',columns='segment',values='log_error').reindex(index=range(1,13),columns=SEGMENTS)
        if len(g)!=180 or matrix.isna().any().any():raise ValueError('Incomplete scenario challenger calibration')
        challenger_errors.append(matrix.to_numpy())
    (BUNDLE/'joint_errors.json').write_text(json.dumps(dict(origin='2026-09',features_sha256=fingerprint,macro_sha256=signature,selected_model_by_type=winners,segments=SEGMENTS,
        source_origins=labels,log_error_paths=errors.tolist(),scenario_log_error_paths=np.stack(challenger_errors).tolist()),indent=2,allow_nan=False))
    pd.DataFrame(diagnostics).to_csv(EVIDENCE/'selected_diagnostics.csv',index=False)
    pd.DataFrame(challenger_diagnostics).to_csv(EVIDENCE/'refinement_diagnostics.csv',index=False)
    pd.DataFrame(parameters).to_csv(EVIDENCE/'selected_parameters.csv',index=False)
    pd.DataFrame(scenarios).to_csv(EVIDENCE/'scenario_sensitivity.csv',index=False)
    pd.DataFrame(scenario_parameters).to_csv(EVIDENCE/'scenario_regressor_coefficients.csv',index=False)
    export_comparisons(history,winners)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['all','annual','rolling','export'],default='all')
    stage=parser.parse_args().stage
    data=load_data();rates,supply=macro_inputs(data)
    if stage in ['annual','all']:annual(data,rates,supply)
    if stage in ['rolling','all']:rolling(data,rates,supply)
    if stage in ['export','all']:export(data,rates,supply)


if __name__=='__main__':main()

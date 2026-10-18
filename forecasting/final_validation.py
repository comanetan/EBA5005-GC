"""Town robustness, historical-feature ablation and dated joint error paths.

Run python -m forecasting.final_validation. No deployment model is reselected.
New analyses are exploratory because their evaluation periods have been inspected.
"""
from pathlib import Path
import hashlib
import json
import warnings
import numpy as np
import pandas as pd
from .compare_regional_location import load_features, CONTROLS, REGIONS, FEATURES
from .compare_sarimax_rates import design, run_forecast, refit_index, DATES

BASE = Path(__file__).resolve().parent
OUT = BASE / 'evidence/final'
TOWNS = ['SENGKANG','HOUGANG','ANG MO KIO']
ORIGINS = pd.date_range('2020-09-01','2025-09-01',freq='3MS')


def frozen_town_indices(frame, origin, end):
    """Same frozen regional coefficients for both local and regional competitors."""
    train = frame[frame.month <= origin]
    levels = {c: sorted(train[c].unique()) for c in ['town','flat_model_group']}
    x = design(train, levels, CONTROLS)
    logp = pd.Series(np.log(train.resale_price),index=train.index)
    xd = x-x.groupby(train.month).transform('mean')
    yd = logp-logp.groupby(train.month).transform('mean')
    beta,_,rank,_ = np.linalg.lstsq(xd.to_numpy(), yd.to_numpy(),rcond=None)
    if rank != x.shape[1]: raise ValueError('Rank deficient regional hedonic fit')
    all_rows = frame[frame.month <= end].copy()
    all_rows['adjusted'] = np.log(all_rows.resale_price)-design(all_rows,levels,CONTROLS).to_numpy()@beta
    indices = {}
    for town in TOWNS:
        alpha = all_rows[all_rows.town.eq(town)].groupby('month').adjusted.mean()
        index = 100*np.exp(alpha-alpha.loc[DATES[0]])
        indices[town] = index.reindex(pd.date_range(DATES[0],end,freq='MS'))
        if indices[town].isna().any(): raise ValueError(f'Missing month: {town}')
    return indices


def available_error_paths(predictions, as_of):
    """Retain WHOLE jointly observed paths; every outcome must be known by as_of."""
    eligible = predictions[pd.to_datetime(predictions.origin)+pd.DateOffset(months=12) <= pd.Timestamp(as_of)]
    blocks, labels = [], []
    for origin, group in eligible.groupby('origin'):
        matrix = group.pivot(index='horizon',columns='region',values='log_error').reindex(index=range(1,13),columns=REGIONS)
        if matrix.isna().any().any() or len(group) != 60:
            raise ValueError('Incomplete or duplicate joint path')
        if pd.to_datetime(group.month).max() > pd.Timestamp(as_of):
            raise ValueError('Calibration outcome extends beyond origin')
        blocks.append(matrix.to_numpy()); labels.append(origin)
    if not blocks: raise ValueError('No fully observed historical error paths')
    return np.stack(blocks), labels


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    frame = load_features()
    audit=[]
    for town in TOWNS:
        sub=frame[frame.town.eq(town)]
        counts=sub.groupby('month').size().reindex(DATES,fill_value=0)
        audit.append(dict(town=town,rows=len(sub),months=len(counts),missing_months=int((counts==0).sum()),
                          minimum_monthly_sales=int(counts.min()),median_monthly_sales=float(counts.median())))
    pd.DataFrame(audit).to_csv(OUT/'town_data_audit.csv',index=False)
    paths=[]; town_predictions=[]; ablations=[]; logs=[]; support=[]
    rates=pd.DataFrame()  # no SORA models in this robustness exercise
    for origin in ORIGINS:
        end=origin+pd.DateOffset(months=12)
        for region in REGIONS:
            sub=frame[frame.region.eq(region)]
            train_rows=sub[sub.month<=origin]
            supported=np.ones(len(sub),dtype=bool)
            for col in ['town','flat_model_group']:
                supported &= sub[col].isin(train_rows[col].unique()).to_numpy()
            support.append(dict(region=region,origin=str(origin.date()),
                excluded_unseen_evaluation_rows=int(((sub.month>origin)&(sub.month<=end)&~supported).sum())))
            sub=sub.loc[supported]
            train,actual=refit_index(sub,origin,end,CONTROLS)
            forecast,info=run_forecast(train,rates,'ARIMA_011_drift',actual.index)
            logs.append(dict(region=region,origin=str(origin.date()),**info))
            for h,(month,row) in enumerate(forecast.iterrows(),1):
                paths.append(dict(region=region,origin=str(origin.date()),month=str(month.date()),horizon=h,
                                  actual_index=float(actual.loc[month]),forecast_index=row.forecast_index,
                                  log_error=float(np.log(actual.loc[month]/row.forecast_index)),
                                  growth_factor=row.forecast_index/train.iloc[-1],
                                  lower90=row.lower90,upper90=row.upper90))
            if origin.month==9 and origin.year>=2022:
                # Flat-only model and target are both rebuilt, so this is target sensitivity,
                # NOT a claim that two different index MAPEs measure identical targets.
                bare,actual_bare=refit_index(sub,origin,end)
                for name in ['naive','ARIMA_011_drift','SARIMA_110_100']:
                    pred,_=run_forecast(bare,rates,name,actual_bare.index)
                    ablations.append(dict(region=region,origin=str(origin.date()),model=name,
                                          MAPE_pct=float(100*(pred.forecast_index/actual_bare-1).abs().mean())))
                if region=='NORTH-EAST':
                    for town,index in frozen_town_indices(sub,origin,end).items():
                        ty=index.loc[:origin]; ay=index.loc[actual.index]
                        candidates={'regional_ARIMA':forecast.forecast_index/train.iloc[-1]*ty.iloc[-1]}
                        for name in ['naive','seasonal_naive','ARIMA_011_drift','SARIMA_110_100']:
                            candidates[name]=run_forecast(ty,rates,name,ay.index)[0].forecast_index
                        for name,pred in candidates.items():
                            for h,month in enumerate(ay.index,1):
                                town_predictions.append(dict(town=town,origin=str(origin.date()),month=str(month.date()),
                                    horizon=h,model=name,actual_index=float(ay.loc[month]),forecast_index=float(pred.loc[month])))
        print(f'Completed joint history {origin:%Y-%m}',flush=True)
    paths=pd.DataFrame(paths); paths.to_csv(OUT/'historical_errors.csv',index=False)
    pd.DataFrame(logs).to_csv(OUT/'fit_log.csv',index=False)
    pd.DataFrame(support).to_csv(OUT/'category_support.csv',index=False)
    town_predictions=pd.DataFrame(town_predictions)
    town_predictions['stage']=np.where(town_predictions.origin<'2025-09-01','validation_revisited','later_check_revisited')
    town_predictions['APE_pct']=100*(town_predictions.forecast_index/town_predictions.actual_index-1).abs()
    town_predictions.to_csv(OUT/'town_predictions.csv',index=False)
    town_metrics=[]
    for (town,stage,model),g in town_predictions.groupby(['town','stage','model']):
        for window,s in [('all_12_months',g),('month_6',g[g.horizon==6]),('month_12',g[g.horizon==12])]:
            town_metrics.append(dict(town=town,stage=stage,model=model,window=window,n=len(s),MAPE_pct=s.APE_pct.mean()))
    pd.DataFrame(town_metrics).to_csv(OUT/'town_metrics.csv',index=False)
    pd.DataFrame(ablations).to_csv(OUT/'flat_only_ablation.csv',index=False)
    finish_intervals(paths)


def finish_intervals(paths):
    coverage=[]
    for origin in ['2023-09-01','2024-09-01','2025-09-01']:
        bank,labels=available_error_paths(paths,origin)
        low,high=np.quantile(bank,[.1,.9],axis=0)
        symmetric_low,symmetric_high=np.quantile(np.concatenate([bank,-bank]),[.1,.9],axis=0)
        for ri,region in enumerate(REGIONS):
            test=paths[paths.origin.eq(origin)&paths.region.eq(region)].sort_values('horizon')
            nominal_sd=(np.log(test.upper90.to_numpy())-np.log(test.forecast_index.to_numpy()))/1.6448536269514722
            for method,lo,hi in [('nominal80',test.forecast_index.to_numpy()*np.exp(-1.2815515655446004*nominal_sd),
                                           test.forecast_index.to_numpy()*np.exp(1.2815515655446004*nominal_sd)),
                                 ('historical_error80',test.forecast_index.to_numpy()*np.exp(low[:,ri]),
                                                       test.forecast_index.to_numpy()*np.exp(high[:,ri])),
                                 ('symmetric_error80',test.forecast_index.to_numpy()*np.exp(symmetric_low[:,ri]),
                                                       test.forecast_index.to_numpy()*np.exp(symmetric_high[:,ri]))]:
                for h,(_,row) in enumerate(test.iterrows()):
                    coverage.append(dict(origin=origin,region=region,horizon=h+1,method=method,
                        calibration_paths=len(labels),latest_calibration_origin=labels[-1],
                        actual_index=row.actual_index,lower=lo[h],upper=hi[h],
                        covered=bool(lo[h]<=row.actual_index<=hi[h]),
                        below_upper=bool(row.actual_index<=hi[h]),width_pct=100*(hi[h]-lo[h])/row.actual_index))
    cover=pd.DataFrame(coverage);cover.to_csv(OUT/'interval_predictions.csv',index=False)
    cover.groupby(['origin','method']).agg(coverage80=('covered','mean'),upper90_coverage=('below_upper','mean'),
        mean_width_pct=('width_pct','mean'),n=('covered','size')).to_csv(OUT/'interval_metrics.csv')
    bank,labels=available_error_paths(paths,'2026-09-01')
    payload=dict(schema_version=1,origin='2026-09',regions=REGIONS,source_origins=labels,
                 log_error_paths=bank.tolist(),method='resample whole 12-month by five-region realised log-error arrays',
                 status='exploratory_historical_error_scenarios_not_a_probability_guarantee',
                 features_sha256=hashlib.sha256(FEATURES.read_bytes()).hexdigest(),
                 warnings=['Only 21 overlapping historical paths; repeated Monte Carlo draws are not new evidence.',
                           'Directional mode retains historical bias; symmetric mode mirrors entire error paths and assumes sign symmetry.',
                           'Depends on stable error distribution; regime shifts can invalidate coverage.',
                           'Regional market uncertainty only; no individual-flat valuation, availability or grant uncertainty.',
                           'Current data vintages/static amenities remain retrospective limitations.',
                           'Early evaluation excludes unseen flat-model categories; counts in category_support.csv.',
                           'Earlier histories predate original model selection; calibration analysis is exploratory, not untouched testing.'])
    (BASE/'models/regional/joint_errors.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
    (OUT/'audit.json').write_text(json.dumps(dict(features_sha256=payload['features_sha256'],
        monthly_source_rows=len(load_features()),joint_origins=len(labels),towns=TOWNS,
        calibration_rule='origin + 12 months <= as_of; same origin sampled across every region and horizon',
        scope='four-room only; no automatic model reselection',limitations=payload['warnings']),indent=2),encoding='utf-8')
    print(pd.read_csv(OUT/'interval_metrics.csv').to_string(index=False))


if __name__=='__main__':
    import sys
    if '--intervals-only' in sys.argv:
        finish_intervals(pd.read_csv(OUT/'historical_errors.csv'))
    else: main()

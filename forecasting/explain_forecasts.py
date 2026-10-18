"""ARIMA diagnostics and permutation Shapley explanations of the LSTM benchmark.

Shapley game: replace missing lag features with a sampled training window.
This is an interventional lag attribution, not a causal or economic sign test.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import torch
from statsmodels.tsa.statespace.sarimax import SARIMAXResults
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from .compare_pooled_lstm import SOURCE, PooledLSTM, training_arrays, SEEDS

BASE=Path(__file__).resolve().parent
OUT=BASE/'evidence/final'


def permutation_shap(predict,x,background,n_permutations=128,seed=42):
    rng=np.random.default_rng(seed)
    states=[]; orders=[]
    for _ in range(n_permutations):
        state=background[rng.integers(len(background))].copy()
        order=rng.permutation(len(x));orders.append(order)
        states.append(state.copy())
        for feature in order:
            state[feature]=x[feature];states.append(state.copy())
    output=predict(np.asarray(states)).reshape(n_permutations,len(x)+1,-1)
    samples=np.empty((n_permutations,len(x),output.shape[-1]))
    for i,order in enumerate(orders): samples[i,order,:]=np.diff(output[i],axis=0)
    phi=samples.mean(axis=0)
    base=output[:,0,:].mean(axis=0)
    target=output[:,-1,:].mean(axis=0)
    error=float(np.max(np.abs(base+phi.sum(axis=0)-target)))
    if error>1e-6: raise ValueError('Shapley additivity check failed')
    return phi,samples.std(axis=0,ddof=1)/np.sqrt(n_permutations),base,target,error


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    diag=[];params=[]
    for path in sorted((BASE/'models/regional').glob('*.pkl')):
        fit=SARIMAXResults.load(path)
        # Exclude diffuse initialisation and initial-year transient residuals.
        residual=np.asarray(fit.filter_results.standardized_forecasts_error[0])[12:]
        lb=acorr_ljungbox(residual,lags=[12],model_df=1,return_df=True)
        arch=het_arch(residual,nlags=6,ddof=2)
        diag.append(dict(region=path.stem,n_residuals=len(residual),
            ljung_box_lag12_p=float(lb.lb_pvalue.iloc[0]),arch_lag6_p=float(arch[1]),
            standardized_residual_mean=float(residual.mean()),standardized_residual_sd=float(residual.std(ddof=1))))
        for name,value in zip(fit.param_names,fit.params):
            params.append(dict(region=path.stem,parameter=name,value=float(value)))
    pd.DataFrame(diag).to_csv(OUT/'arima_diagnostics.csv',index=False)
    pd.DataFrame(params).to_csv(OUT/'arima_parameters.csv',index=False)
    frame=pd.read_csv(SOURCE);origin='2025-09-01'
    frame=frame[frame.origin.eq(origin)]
    background,_,latest,_=training_arrays(frame)
    torch.set_num_threads(1)
    members=[]
    for seed in SEEDS:
        checkpoint=torch.load(BASE/f'outputs/pooled_lstm/lstm_{origin}_{seed}.pt',map_location='cpu',weights_only=True)
        model=PooledLSTM();model.load_state_dict(checkpoint['state_dict']);model.eval()
        members.append((model,checkpoint['metadata']))
    def predict(x):
        predictions=[]
        with torch.no_grad():
            for model,m in members:
                xt=torch.tensor((x-m['input_mean'])/m['input_std'],dtype=torch.float32).unsqueeze(-1)
                result=[]
                for chunk in xt.split(512): result.append(model(chunk).numpy())
                predictions.append(np.concatenate(result)*np.asarray(m['target_std'])+np.asarray(m['target_mean']))
        return np.mean(predictions,axis=0)[:,[5,11]]
    rows=[];checks=[]
    for region,x in latest.items():
        phi,se,base,target,error=permutation_shap(predict,x,background)
        for j,horizon in enumerate([6,12]):
            checks.append(dict(region=region,horizon=horizon,base_log_growth=base[j],forecast_log_growth=target[j],
                               sum_contributions=float(phi[:,j].sum()),max_additivity_error=error))
            for i in range(12):
                rows.append(dict(region=region,origin=origin,horizon=horizon,lag_months=12-i,
                    observed_log_change=x[i],shap_log_growth=phi[i,j],monte_carlo_se=se[i,j]))
        print(f'Explained {region}',flush=True)
    pd.DataFrame(rows).to_csv(OUT/'lstm_shap_lags.csv',index=False)
    pd.DataFrame(checks).to_csv(OUT/'lstm_shap_additivity.csv',index=False)
    (OUT/'explanation_metadata.json').write_text(json.dumps(dict(method='permutation-sampled interventional Shapley values',
        reference='https://arxiv.org/abs/1705.07874',origin=origin,permutations=128,
        background='pooled training-only windows at September 2025; independent feature replacement game',
        outputs='6 and 12 month cumulative log growth of three-seed LSTM ensemble',
        limitations=['Correlated lag inputs mean interventions can create unusual histories.',
                     'Attributions depend on background and have Monte Carlo sampling error.',
                     'Explanations do not establish causality, economic plausibility or predictive superiority.',
                     'SORA and MRT are not LSTM inputs; no SHAP claim about them is possible.',
                     'ARIMA diagnostic p-values are exploratory and unadjusted for multiple testing.']),indent=2),encoding='utf-8')
    print(pd.DataFrame(diag).to_string(index=False))


if __name__=='__main__':main()

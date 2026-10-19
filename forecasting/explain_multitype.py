"""Training-background Shapley lag explanations for the 15-series LSTM benchmark."""
import json
import os
import numpy as np
import pandas as pd
import torch
from .multitype_core import BASE, OUT, EVIDENCE
from .compare_pooled_lstm import training_arrays, PooledLSTM, SEEDS
from .explain_forecasts import permutation_shap


def main():
    origin='2025-09';frame=pd.read_csv(OUT/f'indices/{origin}.csv')
    background,_,latest,_=training_arrays(frame)
    members=[];torch.set_num_threads(1)
    for seed in SEEDS:
        cp=torch.load(OUT/f'lstm/{origin}_{seed}.pt',map_location='cpu',weights_only=True)
        model=PooledLSTM();model.load_state_dict(cp['state_dict']);model.eval()
        members.append((model,cp['metadata']))
    def predict(x):
        values=[]
        with torch.no_grad():
            for model,m in members:
                xt=torch.tensor((x-m['input_mean'])/m['input_std'],dtype=torch.float32).unsqueeze(-1)
                output=np.concatenate([model(chunk).numpy() for chunk in xt.split(512)])
                values.append(output*np.asarray(m['target_std'])+np.asarray(m['target_mean']))
        return np.mean(values,axis=0)[:,[5,11]]
    rows=[];checks=[]
    for segment,x in latest.items():
        phi,se,base,target,error=permutation_shap(predict,x,background,n_permutations=128,seed=42)
        for j,h in enumerate([6,12]):
            checks.append(dict(segment=segment,horizon=h,base_log_growth=float(base[j]),forecast_log_growth=float(target[j]),
                sum_contributions=float(phi[:,j].sum()),max_additivity_error=error))
            for i in range(12):rows.append(dict(segment=segment,horizon=h,lag_months=12-i,
                shap_log_growth=float(phi[i,j]),monte_carlo_se=float(se[i,j]),observed_log_change=float(x[i])))
        print(f'Explained {segment}',flush=True)
    values=pd.DataFrame(rows);values.to_csv(EVIDENCE/'lstm_shap_lags.csv',index=False)
    pd.DataFrame(checks).to_csv(EVIDENCE/'lstm_shap_additivity.csv',index=False)
    (EVIDENCE/'explanation_method.json').write_text(json.dumps(dict(origin=origin,segments=len(latest),
        method='Permutation-sampled interventional Shapley values; custom estimator, not DeepSHAP/TreeSHAP.',
        background='Pooled training-only windows, same September 2025 origin.',permutations=128,
        limitations=['Explains lagged market changes, not direct SORA/lease/MRT effects or economic causality.',
            'Adjacent lags are correlated; independent replacement may create unusual histories.',
            'Fixed benchmark explanation at a historical origin; does not explain a different selected model.']),indent=2))
    os.environ.setdefault('MPLCONFIGDIR',str(OUT/'mplconfig'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    table=values[values.horizon.eq(12)].pivot(index='segment',columns='lag_months',values='shap_log_growth').sort_index()
    fig,ax=plt.subplots(figsize=(11,7),layout='constrained')
    limit=float(abs(table).max().max());img=ax.imshow(table.to_numpy()*100,cmap='RdBu_r',vmin=-limit*100,vmax=limit*100,aspect='auto')
    ax.set(xticks=range(12),xticklabels=table.columns,yticks=range(len(table)),yticklabels=table.index,
        xlabel='Monthly change lag (1 = most recent)',title='LSTM benchmark: lag contributions to 12-month log growth')
    fig.colorbar(img,ax=ax,label='Contribution in log-growth percentage points')
    fig.savefig(EVIDENCE/'lstm_shap_heatmap.png',dpi=160);plt.close(fig)


if __name__=='__main__':main()

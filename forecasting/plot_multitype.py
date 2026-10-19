"""Figures from saved expanded evaluation; no fitting or source-data changes."""
import os
import numpy as np
import pandas as pd
from .multitype_core import OUT, EVIDENCE, FLAT_TYPES
os.environ.setdefault('MPLCONFIGDIR',str(OUT/'mplconfig'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    table=pd.read_csv(EVIDENCE/'model_comparison.csv')
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(12,5),layout='constrained')
    candidates=[('ARIMA_011_drift','Plain ARIMA','#457b9d'),('ARIMA_POLICY','ARIMA + policy','#2a9d8f'),
                ('pooled_LSTM','Pooled LSTM','#e9a23b'),('naive','Unchanged price','#8d99ae')]
    for ax,stage,title in zip(axes,['validation','later_period_check'],['Earlier validation: three origins','Later-year check: one origin']):
        for i,(name,label,color) in enumerate(candidates):
            values=[float(table[(table.stage==stage)&(table.flat_type==ft)&(table.model==name)].MAPE_pct.iloc[0]) for ft in FLAT_TYPES]
            bars=ax.bar(np.arange(3)+(i-1.5)*.19,values,width=.18,label=label,color=color)
            ax.bar_label(bars,fmt='%.2f',fontsize=8,padding=3)
        ax.set(xticks=np.arange(3),xticklabels=FLAT_TYPES,ylabel='Mean regional MAPE (%)',title=title,ylim=(0,5))
    axes[0].legend(fontsize=8,loc='upper left')
    fig.suptitle('Fifteen regional flat-type series: model performance',fontweight='bold')
    fig.supxlabel('Retrospective evaluation. Regional errors do not measure individual-flat pricing accuracy.',fontsize=9)
    fig.savefig(EVIDENCE/'model_comparison.png',dpi=160);plt.close(fig)
    scenarios=pd.read_csv(EVIDENCE/'scenario_sensitivity.csv')
    scenarios=scenarios[scenarios.horizon.eq(12)].copy()
    scenarios['flat_type']=scenarios.segment.str.split('::').str[1]
    avg=scenarios.groupby(['flat_type','scenario']).growth_factor.mean()
    fig,ax=plt.subplots(figsize=(10,5),layout='constrained')
    names=['base','rate_minus_1pp','rate_plus_1pp','cohort_minus20pct','cohort_plus20pct']
    labels=['Base','Rate down 1 pp','Rate up 1 pp','Cohort down 20%','Cohort up 20%']
    for i,(name,label) in enumerate(zip(names,labels)):
        values=[100*(avg.loc[ft,name]-1) for ft in FLAT_TYPES]
        ax.bar(np.arange(3)+(i-2)*.15,values,width=.14,label=label)
    ax.axhline(0,color='#555',linewidth=.7)
    ax.set(xticks=np.arange(3),xticklabels=FLAT_TYPES,ylabel='Average 12-month growth (%)',
        title='Diagnostic scenarios: fitted associations, not causal effects')
    ax.legend(fontsize=8)
    fig.supxlabel('SORA signs are positive in 12/15 segments. Scenarios are diagnostic; cohort is a completion-year proxy.',fontsize=8)
    fig.savefig(EVIDENCE/'scenario_sensitivity.png',dpi=160);plt.close(fig)


if __name__=='__main__':main()

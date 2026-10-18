"""Reproduce the review figure from saved evidence; no fitting or data changes."""
from pathlib import Path
import os
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parent/'outputs/mplconfig'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np


def main():
    out=Path(__file__).resolve().parent/'evidence/final'
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(12,4.7),layout='constrained')
    intervals=pd.read_csv(out/'interval_metrics.csv')
    x=np.arange(3)
    for offset,method,label,color in [(-.18,'nominal80','Original ARIMA bounds','#457b9d'),(.18,'symmetric_error80','Mirrored historical errors','#e9a23b')]:
        d=intervals[intervals.method.eq(method)].sort_values('origin')
        bars=axes[0].bar(x+offset,d.coverage80*100,width=.34,label=label,color=color)
        axes[0].bar_label(bars,fmt='%.0f%%',padding=3)
    axes[0].axhline(80,color='#444444',linestyle='--',linewidth=1)
    axes[0].set(xticks=x,xticklabels=['Sep 2023','Sep 2024','Sep 2025'],ylim=(0,115),
        ylabel='Outcomes inside central 80% interval (%)',xlabel='Forecast origin',title='Wider scenarios improved regional coverage')
    axes[0].legend(loc='lower left',fontsize=9)
    profile=pd.read_csv(out/'profile_backtest_metrics.csv')
    for offset,method,label,color in [(-.18,'no_change','Keep current price','#8d99ae'),(.18,'nominal','Pricing + ARIMA growth','#457b9d')]:
        d=profile[profile.method.eq(method)].sort_values(['origin','horizon'])
        bars=axes[1].bar(np.arange(4)+offset,d.MAPE_pct,width=.34,label=label,color=color)
        axes[1].bar_label(bars,fmt='%.1f',padding=3)
    axes[1].set(xticks=np.arange(4),xticklabels=['Jun 23\n6 months','Jun 23\n12 months','Dec 24\n6 months','Dec 24\n12 months'],
        ylim=(0,8.5),ylabel='Mean absolute percentage error (%)',xlabel='Forecast origin / horizon',title='Forecast growth helped in 3 of 4 profile checks')
    axes[1].legend(fontsize=9)
    fig.suptitle('Four-room HDB forecasting: evidence and limits',fontsize=15,fontweight='bold')
    fig.supxlabel('Retrospective checks. Regional coverage is not a household affordability guarantee.',fontsize=9)
    fig.savefig(out/'forecast_review.png',dpi=160)
    plt.close(fig)


if __name__=='__main__':main()

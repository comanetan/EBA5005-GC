"""Plot delivered empirical quantiles and saved origin-specific history; no fitting."""
import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAXResults

BASE = Path(__file__).resolve().parent
OUT = BASE / 'outputs' / 'presentation'
os.environ.setdefault('MPLCONFIGDIR', str(OUT / 'mplconfig'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', default='NORTH-EAST')
    parser.add_argument('--flat-type', default='4 ROOM')
    parser.add_argument('--history-months', type=int, default=36)
    args = parser.parse_args()
    if args.history_months < 2:
        parser.error('--history-months must be at least 2')
    manifest = json.loads((BASE / 'models/multitype/manifest.json').read_text())
    key = f'{args.region}::{args.flat_type}'
    if key not in manifest['segments']:
        parser.error(f'Unsupported segment {key}; choose from {list(manifest["segments"])}')
    segment = manifest['segments'][key]
    origin = pd.Timestamp(manifest['origin'])
    # The committed fitted model retains its log-index training observations.
    # Loading this trusted project artifact avoids a dependency on ignored caches.
    source = BASE / 'models/multitype' / (key.replace('::', '__').replace(' ', '_') + '.pkl')
    fitted = SARIMAXResults.load(source)
    history = pd.DataFrame({'month': pd.to_datetime(fitted.model.data.dates),
                            'index': np.exp(np.asarray(fitted.model.endog).reshape(-1))})
    anchor = float(segment['reference_index'])
    if history.month.iloc[-1] != origin:
        raise ValueError('Saved model and manifest origins differ')
    np.testing.assert_allclose(history['index'].iloc[-1], anchor)
    quantiles = np.asarray(segment['growth_quantiles'], dtype=float) * anchor
    if quantiles.shape != (12, 3) or not np.isfinite(quantiles).all():
        raise ValueError('Expected twelve finite p10/p50/p90 rows')
    if (quantiles <= 0).any() or (np.diff(quantiles, axis=1) < 0).any():
        raise ValueError('Forecast quantiles must be positive and ordered')
    dates = pd.date_range(origin + pd.offsets.MonthBegin(), periods=12, freq='MS')
    forecast = pd.DataFrame(quantiles, columns=['p10', 'p50', 'p90'])
    forecast.insert(0, 'month', dates)
    OUT.mkdir(parents=True, exist_ok=True)
    name = f'{args.region.lower()}_{args.flat_type.lower().replace(" ", "_")}_forecast_fan'
    forecast.to_csv(OUT / f'{name}_data.csv', index=False)
    shown = history.tail(args.history_months)
    x = pd.DatetimeIndex([origin, *dates])
    y = np.vstack([[anchor] * 3, quantiles])
    plt.rcParams.update({'font.size': 12, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, ax = plt.subplots(figsize=(12, 6.5))
    fig.subplots_adjust(left=.09, right=.98, top=.83, bottom=.23)
    ax.axvspan(origin, dates[-1], color='#f4f7fb', zorder=0)
    ax.fill_between(x, y[:, 0], y[:, 2], color='#4a90c4', alpha=.23,
                    label='p10-p90: central 80% empirical interval')
    ax.plot(shown.month, shown['index'], color='#23354d', lw=2.3, label='Historical quality-adjusted index')
    ax.plot(x, y[:, 1], color='#087e8b', lw=2.5, label='Central forecast (p50)')
    ax.axvline(origin, color='#65758b', ls='--', lw=1)
    for h, label in [(6, '6 months'), (12, '12 months')]:
        ax.scatter(dates[h-1], quantiles[h-1, 1], color='#087e8b', s=35, zorder=5)
        ax.annotate(label, (dates[h-1], quantiles[h-1, 1]), xytext=(-10, 15),
                    textcoords='offset points', ha='right', fontsize=10, color='#075961')
    ax.set_ylabel('Quality-adjusted price index (Jan 2017 = 100)')
    ax.set_xlim(shown.month.iloc[0], dates[-1] + pd.DateOffset(months=1))
    ax.set_xticks(pd.date_range(shown.month.iloc[0], dates[-1], freq='6MS'))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax.grid(axis='y', alpha=.2)
    fig.suptitle(f'{args.region.title()} {args.flat_type.lower()}: 12-month resale index forecast',
                 x=.09, y=.96, ha='left', fontsize=20, fontweight='bold', color='#23354d')
    fig.text(.09, .895, f'Policy-augmented ARIMA(0,1,1) with drift | Forecast origin: {origin:%B %Y}',
             fontsize=11, color='#536275')
    ax.legend(loc='upper left', frameon=False, fontsize=10)
    fig.text(.09, .09, 'Market-index uncertainty conditional on the model; excludes individual-flat valuation error.\n'
             'Historical-error bounds use sign symmetry and overlapping paths; nominal coverage is not guaranteed.',
             fontsize=10, color='#536275', linespacing=1.5)
    for extension in ['png', 'svg']:
        fig.savefig(OUT / f'{name}.{extension}', dpi=240, facecolor='white')
    plt.close(fig)
    print(f'Chart: {OUT / (name + ".png")}')
    print(forecast.iloc[[5, 11]].to_string(index=False))


if __name__ == '__main__':
    main()

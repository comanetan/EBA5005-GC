"""Generate report figures from committed evidence and trusted model artifacts.

Run from repository root: python -m forecasting.plot_report_figures
No fitting, model selection, raw-data downloads or source-data changes occur.
Final-fit ACF/PACF figures are descriptive diagnostics, not historical selection
evidence. Outputs are ignored by Git; PNG/SVG and plotted CSVs support reporting.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
EVIDENCE = BASE / 'evidence' / 'multitype'
BUNDLE = BASE / 'models' / 'multitype'
os.environ.setdefault('MPLCONFIGDIR', str(BASE / '.mplconfig'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.graphics.tsaplots import plot_acf, plot_pacf
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.tsa.statespace.sarimax import SARIMAXResults
from statsmodels.tsa.stattools import acf, pacf

BLUE, TEAL, ORANGE = '#244D70', '#087E8B', '#E79B43'


def save(fig, folder, name):
    for ext in ('png', 'svg'):
        fig.savefig(folder / f'{name}.{ext}', dpi=220, facecolor='white')
    plt.close(fig)


def footer(fig, text):
    fig.text(.02, .015, text, fontsize=9, color='#52616B')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=BASE / 'outputs/report_figures')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    appendix = out / 'appendix'
    appendix.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size': 11, 'axes.spines.top': False,
                         'axes.spines.right': False, 'axes.titleweight': 'bold'})
    manifest = json.loads((BUNDLE / 'manifest.json').read_text())
    origin = pd.Timestamp(manifest['origin'])
    selected = pd.read_csv(EVIDENCE / 'selected_diagnostics.csv').set_index('segment')
    example = 'NORTH-EAST::4 ROOM'
    hashes = {}
    metrics = []
    histories = []
    for segment, info in manifest['segments'].items():
        stem = segment.replace('::', '__').replace(' ', '_')
        model_path = BUNDLE / f'{stem}.pkl'
        hashes[model_path.name] = hashlib.sha256(model_path.read_bytes()).hexdigest()
        fit = SARIMAXResults.load(model_path)
        dates = pd.DatetimeIndex(fit.model.data.dates)
        logs = np.asarray(fit.model.endog).reshape(-1)
        if dates[-1] != origin or len(logs) != info['training_months']:
            raise ValueError(f'History mismatch: {segment}')
        np.testing.assert_allclose(np.exp(logs[-1]), info['reference_index'])
        resid = np.asarray(fit.filter_results.standardized_forecasts_error[0])[12:]
        if not np.isfinite(resid).all():
            raise ValueError(f'Non-finite residuals: {segment}')
        model_df = sum(p.startswith(('ar.', 'ma.')) for p in fit.param_names)
        lb = float(acorr_ljungbox(resid, lags=[12], model_df=model_df).lb_pvalue.iloc[0])
        arch = float(het_arch(resid, nlags=6)[1])
        np.testing.assert_allclose([lb, arch], selected.loc[segment, ['ljung_box_lag12_p', 'arch_lag6_p']].to_numpy(float), rtol=1e-5, atol=1e-12)
        metrics.append({'segment': segment, 'ljung_box_p': lb, 'arch_p': arch})
        history = pd.DataFrame({'segment': segment, 'month': dates, 'index': np.exp(logs), 'log_index': logs})
        histories.append(history)
        change = np.diff(logs)
        fig, axes = plt.subplots(2, 2, figsize=(12, 7.5), layout='constrained')
        axes[0, 0].plot(dates, np.exp(logs), color=BLUE)
        axes[0, 0].set(title='Quality-adjusted price index', ylabel='Jan 2017 = 100')
        axes[0, 1].plot(dates[1:], 100 * change, color=TEAL)
        axes[0, 1].axhline(0, color='grey', linewidth=.7)
        axes[0, 1].set(title='First difference of log index', ylabel='100 × log change')
        plot_acf(change, lags=24, zero=False, ax=axes[1, 0], title='ACF of log changes', color=BLUE)
        plot_pacf(change, lags=24, method='ywm', zero=False, ax=axes[1, 1], title='PACF of log changes', color=TEAL)
        fig.suptitle(f'{segment.replace("::", " | ")}: index and temporal dependence', fontsize=16)
        fig.get_layout_engine().set(rect=(0, .07, 1, .92))
        footer(fig, f'Final-fit index through {origin:%b %Y}; descriptive only. Shading: pointwise approximate 95% bounds.\nACF/PACF of changes do not establish residual adequacy or retrospectively determine the selected order.')
        save(fig, out if segment == example else appendix, '01_index_acf_pacf' if segment == example else stem + '_index_acf_pacf')
        pd.DataFrame({'lag': np.arange(25), 'acf_log_change': acf(change, nlags=24),
                      'pacf_log_change': pacf(change, nlags=24, method='ywm')}).to_csv(appendix / f'{stem}_correlations.csv', index=False)
        fig, axes = plt.subplots(2, 2, figsize=(12, 7.5), layout='constrained')
        axes[0, 0].plot(dates[12:], resid, color=BLUE, linewidth=1)
        axes[0, 0].axhline(0, color='grey', linewidth=.7)
        axes[0, 0].set(title='Standardised one-step forecast errors', ylabel='Standardised error')
        plot_acf(resid, lags=24, zero=False, ax=axes[0, 1], title='Residual ACF', color=BLUE)
        stats.probplot(resid, dist='norm', plot=axes[1, 0])
        axes[1, 0].set_title('Normal Q–Q plot (descriptive)')
        plot_acf(resid**2, lags=24, zero=False, ax=axes[1, 1], title='Squared-residual ACF', color=TEAL)
        fig.suptitle(f'{segment.replace("::", " | ")}: selected ARIMAX residual checks', fontsize=16)
        fig.get_layout_engine().set(rect=(0, .07, 1, .92))
        footer(fig, f'Ljung–Box(12) p={lb:.3g}; ARCH(6) p={arch:.3g}. First 12 errors excluded; tests match saved evidence.\nShading: pointwise approximate 95% bounds. Final-fit diagnostics are not out-of-sample forecast accuracy.')
        save(fig, out if segment == example else appendix, '02_residual_diagnostics' if segment == example else stem + '_residuals')
        pd.DataFrame({'month': dates[12:], 'standardised_error': resid}).to_csv(appendix / f'{stem}_residuals.csv', index=False)

    history = pd.concat(histories, ignore_index=True)
    history.to_csv(out / 'index_history.csv', index=False)
    checks = pd.DataFrame(metrics).set_index('segment')
    checks.to_csv(out / 'diagnostic_values.csv')
    vals = -np.log10(np.maximum(checks.to_numpy(), 1e-16))
    fig, ax = plt.subplots(figsize=(8, 8), layout='constrained')
    heat = ax.imshow(vals, aspect='auto', cmap='YlOrRd', vmin=0, vmax=max(4, vals.max()))
    ax.set(yticks=np.arange(len(checks)), yticklabels=checks.index,
           xticks=[0, 1], xticklabels=['Ljung–Box (12 lags)', 'ARCH (6 lags)'],
           title='Residual diagnostics across all fifteen segments')
    for i in range(len(checks)):
        for j in range(2):
            p = checks.iloc[i, j]
            ax.text(j, i, f'{p:.2g}' + (' *' if p < .05 else ''), ha='center', va='center',
                    color='white' if vals[i, j] > vals.max()*.6 else '#172C3B', fontsize=10)
    fig.colorbar(heat, ax=ax, label='−log10(p): darker means stronger evidence against null')
    fig.get_layout_engine().set(rect=(0, .06, 1, .93))
    footer(fig, '* Individual p < 0.05 (unadjusted). Autocorrelation: 13/15 flagged; ARCH: 2/15.\nThe two tests address different properties; no claim that all residual checks passed.')
    save(fig, out, '03_all_segment_diagnostics')

    table = pd.read_csv(EVIDENCE / 'model_comparison.csv')
    names = ['naive', 'seasonal_naive', 'ARIMA_011_drift', 'ARIMA_111_drift', 'SARIMA_110_100',
             'ARIMA_SORA', 'SARIMA_SORA', 'ARIMA_POLICY', 'ARIMA_SUPPLY', 'ARIMA_FULL', 'SARIMA_FULL', 'pooled_LSTM']
    labels = ['Naïve', 'Seasonal naïve', 'ARIMA(0,1,1) + drift', 'ARIMA(1,1,1) + drift',
              'SARIMA(1,1,0)(1,0,0)12', 'ARIMA + SORA', 'SARIMA + SORA', 'ARIMA + policy',
              'ARIMA + supply', 'ARIMA + all X', 'SARIMA + all X', 'Pooled LSTM']
    fig, axes = plt.subplots(1, 2, figsize=(13, 8), layout='constrained')
    for ax, stage, title in zip(axes, ['validation', 'later_period_check'], ['Earlier validation: three origins', 'Later-period assessment: Sep 2025 origin']):
        matrix = table[table.stage.eq(stage)].pivot(index='model', columns='flat_type', values='MAPE_pct').reindex(index=names, columns=manifest['flat_types'])
        matrix.to_csv(out / f'{stage}_mape.csv')
        ax.imshow(matrix, cmap='Blues', vmin=0, vmax=8, aspect='auto')
        ax.set(xticks=range(3), xticklabels=manifest['flat_types'], yticks=range(12),
               yticklabels=labels, title=title)
        for i in range(12):
            for j in range(3):
                v = matrix.iloc[i, j]
                ax.text(j, i, f'{v:.3f}', ha='center', va='center', color='white' if v > 4 else '#172C3B')
    fig.suptitle('All twelve candidate specifications: MAPE (%)', fontsize=17)
    fig.get_layout_engine().set(rect=(0, .05, 1, .95))
    footer(fig, 'Equal-region averages across forecast months. Lower is better. Retrospective evaluation; not individual-flat pricing error.')
    save(fig, out, '04_model_comparison')

    fig, ax = plt.subplots(figsize=(12, 5.5), layout='constrained')
    start = pd.Timestamp('2017-01')
    for i, year in enumerate(range(2022, 2026)):
        cut = pd.Timestamp(f'{year}-10'); end = cut + pd.DateOffset(years=1); y = 3-i
        ax.barh(y, (cut-start).days, left=mdates.date2num(start), color=BLUE, height=.5, label='Training' if i == 0 else None)
        ax.barh(y, (end-cut).days, left=mdates.date2num(cut), color=ORANGE, height=.5, label='Evaluation' if i == 0 else None)
        ax.text(mdates.date2num(start)+70, y, f'Jan 2017–Sep {year}', va='center', color='white')
        ax.text(mdates.date2num(cut)+(end-cut).days/2, y, f'Oct {year}\nSep {year+1}', ha='center', va='center', fontsize=9)
    ax.set(yticks=[3, 2, 1, 0], yticklabels=['Selection 1', 'Selection 2', 'Selection 3', 'Later check'], title='Expanding-window evaluation')
    ax.xaxis.set_major_locator(mdates.YearLocator()); ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.legend(loc='upper left', bbox_to_anchor=(0, 1.14), ncol=2, frameon=False)
    fig.get_layout_engine().set(rect=(0, .1, 1, .89))
    footer(fig, 'Refit index adjustments, model parameters and scalers at each origin. Future targets remain outside training.\nCurrent data vintages and later-period inspection make this a retrospective evaluation.')
    save(fig, out, '05_expanding_windows')

    info = manifest['segments'][example]
    hist = history[history.segment.eq(example)].tail(36)
    quant = np.asarray(info['growth_quantiles']) * info['reference_index']
    forecast_dates = pd.date_range(origin + pd.offsets.MonthBegin(), periods=12, freq='MS')
    x = pd.DatetimeIndex([origin, *forecast_dates]); y = np.vstack([[info['reference_index']]*3, quant])
    fig, ax = plt.subplots(figsize=(11, 6), layout='constrained')
    ax.plot(hist.month, hist['index'], color=BLUE, label='Historical index')
    ax.plot(x, y[:, 1], color=TEAL, label='Central forecast (p50)')
    ax.fill_between(x, y[:, 0], y[:, 2], color=TEAL, alpha=.2, label='p10–p90: central 80% scenario range')
    ax.axvline(origin, color='grey', linestyle='--')
    ax.set(title=f'North-East 4-room forecast from {origin:%B %Y}', ylabel='Quality-adjusted index (Jan 2017 = 100)')
    ax.legend(frameon=False, fontsize=10)
    fig.get_layout_engine().set(rect=(0, .09, 1, .90))
    footer(fig, 'Empirical mirrored-error scenarios; coverage is not guaranteed. Individual-profile valuation uncertainty is excluded.')
    save(fig, out, '06_forecast_fan')
    pd.DataFrame({'month': forecast_dates, 'p10': quant[:, 0], 'p50': quant[:, 1], 'p90': quant[:, 2]}).to_csv(out / 'forecast_fan_values.csv', index=False)

    shap = pd.read_csv(EVIDENCE / 'lstm_shap_lags.csv')
    matrix = shap[shap.horizon.eq(12)].pivot(index='segment', columns='lag_months', values='shap_log_growth').sort_index().reindex(columns=range(1,13))*100
    matrix.to_csv(out / 'shap_heatmap_values.csv')
    fig, ax = plt.subplots(figsize=(12, 8), layout='constrained')
    limit = float(np.abs(matrix.to_numpy()).max())
    heat = ax.imshow(matrix, cmap='RdBu_r', aspect='auto', vmin=-limit, vmax=limit)
    ax.set(xticks=range(12), xticklabels=range(1,13), yticks=range(15), yticklabels=matrix.index,
           xlabel='Monthly change lag (1 = most recent)', title='LSTM: contributions to 12-month log-growth forecasts')
    fig.colorbar(heat, ax=ax, label='100 × Shapley contribution to log growth')
    fig.get_layout_engine().set(rect=(0, .08, 1, .91))
    footer(fig, 'September 2025 origin; pooled training background; 128 permutations. Explains the LSTM benchmark, not ARIMAX.\nLag replacement is interventional; correlated inputs and unusual replacement histories limit interpretation. No causal claim.')
    save(fig, out, '07_lstm_shap')

    coverage = pd.read_csv(EVIDENCE / 'rolling_interval_coverage.csv')
    avg = coverage.groupby('origin')[['coverage80', 'upper90_coverage']].mean()*100
    avg.to_csv(out / 'interval_coverage_values.csv')
    fig, ax = plt.subplots(figsize=(11, 5.5), layout='constrained')
    for col, label, color, nominal in [('coverage80', 'Central p10–p90 coverage', TEAL, 80), ('upper90_coverage', 'Below p90 upper bound', BLUE, 90)]:
        ax.plot(pd.to_datetime(avg.index), avg[col], marker='o', label=label, color=color)
        ax.axhline(nominal, color=color, linestyle='--', alpha=.65, label=f'{nominal}% nominal reference')
    ax.set(title='Historical scenario coverage using fully matured earlier paths', ylabel='Coverage across segments and horizons (%)', ylim=(65, 102))
    ax.legend(fontsize=9, frameon=False)
    fig.get_layout_engine().set(rect=(0, .08, 1, .91))
    footer(fig, 'High coverage indicates conservative bounds, not nominal calibration. Overlapping origins; retrospective model selection.')
    save(fig, out, '08_interval_coverage')
    for p in EVIDENCE.glob('*.csv'):
        if p.name in ['selected_diagnostics.csv', 'model_comparison.csv', 'lstm_shap_lags.csv', 'rolling_interval_coverage.csv']:
            hashes[str(p.relative_to(BASE))] = hashlib.sha256(p.read_bytes()).hexdigest()
    hashes['models/multitype/manifest.json'] = hashlib.sha256((BUNDLE/'manifest.json').read_bytes()).hexdigest()
    (out / 'figure_sources.json').write_text(json.dumps({'model_version': manifest['model_version'], 'origin': manifest['origin'], 'inputs_sha256': hashes, 'retraining': False}, indent=2))
    print(f'Saved report figures and all-segment diagnostic appendix to {out}', flush=True)


if __name__ == '__main__':
    main()

"""Offline refit of validation-selected regional model and dashboard handover."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX
from .compare_regional_location import load_features, FEATURES, REGIONS, CONTROLS
from .compare_sarimax_rates import refit_index, DATES, SPECS
from .regional_api import RegionalForecaster

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
BUNDLE = BASE / 'models/regional'


def main():
    BUNDLE.mkdir(parents=True, exist_ok=True)
    comparison = pd.read_csv(BASE / 'outputs/pooled_lstm/comparison.csv')
    ranked = comparison[(comparison.stage=='validation') & (comparison.regions==5)].sort_values('mean_region_MAPE_pct')
    winner = ranked.iloc[0].model
    if winner != 'ARIMA_011_drift':
        raise ValueError(f'Expected ARIMA without regressors; selection is {winner}. Review exporter before deployment.')
    # Prevent exporting a model with validation performed on stale feature data.
    experiment = json.loads((BASE / 'outputs/regional_location/manifest.json').read_text())
    feature_hash = hashlib.sha256(FEATURES.read_bytes()).hexdigest()
    if experiment['features_sha256'] != feature_hash:
        raise ValueError('Re-run regional and LSTM comparisons on the current features before export')
    lstm_manifest = json.loads((BASE / 'outputs/pooled_lstm/manifest.json').read_text())
    if lstm_manifest['source_sha256'] != hashlib.sha256((BASE / 'outputs/regional_location/origin_specific_indices.csv').read_bytes()).hexdigest():
        raise ValueError('LSTM comparison uses stale indices')
    data = load_features()
    segments = {}
    for region in REGIONS:
        series, _ = refit_index(data[data.region.eq(region)], DATES[-1], DATES[-1], CONTROLS)
        order, seasonal, trend = SPECS[winner]
        fit = SARIMAX(np.log(series), order=order, seasonal_order=seasonal, trend=trend).fit(disp=False,maxiter=500)
        if not fit.mle_retvals.get('converged',False):
            fit = fit.model.fit(method='powell',disp=False,maxiter=1000)
        if not fit.mle_retvals.get('converged',False):
            raise ValueError(f'Fit failed: {region}')
        forecast = fit.get_forecast(12)
        mean, variance = np.asarray(forecast.predicted_mean), np.asarray(forecast.var_pred_mean)
        if not np.isfinite(mean).all() or not np.isfinite(variance).all() or (variance<0).any():
            raise ValueError('Invalid forecast distribution')
        fit.save(BUNDLE / f'{region}.pkl')
        series.to_csv(BUNDLE / f'{region}_training_index.csv', index_label='month',header=['index'])
        segments[f'{region}::4 ROOM'] = dict(reference_index=float(series.iloc[-1]),
                                           log_mean=mean.tolist(),log_variance=variance.tolist(),
                                           training_months=len(series),converged=True)
    spec = importlib.util.spec_from_file_location('team_config', ROOT / 'src/config.py')
    config = importlib.util.module_from_spec(spec); spec.loader.exec_module(config)
    manifest = dict(schema_version=2, model=winner, model_version=f'regional-202609-{feature_hash[:12]}',
                    origin='2026-09', training_start='2017-01', max_horizon_months=12,
                    selection='lowest mean regional validation MAPE, all seven candidate families, three historical origins',
                    status='prototype_uncalibrated_uncertainty', segments=segments,
                    town_to_region={town:region for region,towns in config.REGIONS.items() for town in towns},
                    features_sha256=feature_hash, warnings=[
                        'Supports four-room profiles only; assumes each profile follows its regional index.',
                        'p10/p90 are conditional marginal model quantiles, not calibrated affordability guarantees.',
                        'Latest check had poor nominal 90% coverage; inspect models/regional/regional_metrics.csv.',
                        'Excludes profile valuation, hedonic-index estimation and model-selection uncertainty.',
                        'Static amenity snapshots and historical data vintages limit retrospective validity.',
                        'Legacy point adapter supplies marginal quantiles; use MultiTypeForecaster for current joint simulation.'])
    (BUNDLE / 'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False),encoding='utf-8')
    shutil.copyfile(BASE / 'outputs/pooled_lstm/comparison.csv', BUNDLE / 'evaluation_metrics.csv')
    shutil.copyfile(BASE / 'outputs/regional_location/metrics_by_region.csv', BUNDLE / 'regional_metrics.csv')
    pricing_path = ROOT / 'outputs/prices_today.csv'
    prices = pd.read_csv(pricing_path)
    supported = prices.profile_id.str.split('|').str[1].eq('4 ROOM')
    api = RegionalForecaster()
    handover = api.price_profiles(prices[supported], '2026-09')
    handover.to_csv(ROOT / 'outputs/price_paths.csv',index=False)
    audit = dict(base_price_month='2026-09', base_price_date_evidence='docs/model_validation.md: pricing as of Sep 2026',
                 pricing_sha256=hashlib.sha256(pricing_path.read_bytes()).hexdigest(),
                 included_profiles=int(supported.sum()), excluded_unsupported_profiles=int((~supported).sum()),
                 rows=len(handover),model_version=manifest['model_version'],
                 quantile_meaning='conditional marginal p10/p50/p90; central 80% interval, not joint paths',
                 warnings=manifest['warnings'])
    (ROOT / 'outputs/price_paths_metadata.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(json.dumps(audit,indent=2))


if __name__ == '__main__': main()

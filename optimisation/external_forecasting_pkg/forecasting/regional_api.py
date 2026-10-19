"""Portable, inference-only regional forecast adapter for the optimisation UI.

Loads exported log-forecast distributions; no raw data, fitting or PyTorch needed.
Legacy median-PSM API remains available in model_api.py.
"""
from pathlib import Path
import json
import math
import numpy as np
import pandas as pd
from scipy.stats import norm

DEFAULT_BUNDLE = Path(__file__).resolve().parent / 'models/regional/manifest.json'


class RegionalForecaster:
    def __init__(self, bundle=DEFAULT_BUNDLE):
        self.metadata = json.loads(Path(bundle).read_text(encoding='utf-8'))
        if self.metadata['schema_version'] != 2:
            raise ValueError('Unsupported bundle version')

    def available_segments(self):
        return sorted(self.metadata['segments'])

    def predict(self, region, flat_type='4 ROOM', horizon_months=12,
                base_price_sgd=None, base_price_month=None):
        m = self.metadata
        key = f'{region}::{flat_type}'
        if key not in m['segments']:
            raise ValueError(f'Unsupported segment {key}; available: {self.available_segments()}')
        if isinstance(horizon_months, bool) or not isinstance(horizon_months, int) or not 1 <= horizon_months <= 12:
            raise ValueError('horizon_months must be an integer from 1 to 12')
        if base_price_sgd is not None:
            if isinstance(base_price_sgd, bool) or not isinstance(base_price_sgd, (int,float)) or not math.isfinite(base_price_sgd) or base_price_sgd <= 0:
                raise ValueError('base_price_sgd must be finite and positive')
            if base_price_month != m['origin']:
                raise ValueError(f'base_price_month must equal {m["origin"]}')
        elif base_price_month is not None:
            raise ValueError('base_price_month requires base_price_sgd')
        segment = m['segments'][key]
        mu = np.asarray(segment['log_mean'][:horizon_months])
        sd = np.sqrt(np.maximum(segment['log_variance'][:horizon_months], 0))
        quantiles = np.exp(mu[:,None]+sd[:,None]*norm.ppf([.1,.5,.9]))
        factors = quantiles/segment['reference_index']
        dates = pd.date_range(pd.Timestamp(m['origin'])+pd.offsets.MonthBegin(), periods=horizon_months, freq='MS')
        records = []
        for i, date in enumerate(dates):
            row = dict(month=date.strftime('%Y-%m'), horizon=i+1)
            for j,q in enumerate(['p10','p50','p90']):
                row[f'index_{q}'] = float(quantiles[i,j])
                row[f'growth_factor_{q}'] = float(factors[i,j])
                if base_price_sgd is not None:
                    row[q] = float(base_price_sgd*factors[i,j])
            records.append(row)
        return dict(schema_version=2, model=m['model'], model_version=m['model_version'],
                    origin=m['origin'], segment_id=key, target='location_adjusted_hedonic_index',
                    status=m['status'], quantiles=[.1,.5,.9],
                    interval_type='central_80_percent_pointwise_conditional',
                    warnings=m['warnings'], forecasts=records)

    def price_profiles(self, prices, base_price_month, horizon_months=12):
        """Return the agreed profile_id,month,p10,p50,p90 contract; reject unsupported types.

        prices is a DataFrame with profile_id and price. Caller must explicitly
        filter to supported types; unsupported rows are never silently dropped.
        """
        if not {'profile_id','price'}.issubset(prices.columns) or prices.empty:
            raise ValueError('Provide nonempty profile_id and price columns')
        if prices.profile_id.duplicated().any():
            raise ValueError('Duplicate profile IDs')
        rows = []
        for row in prices.itertuples(index=False):
            parts = str(row.profile_id).split('|')
            if len(parts) != 5 or parts[0] not in self.metadata['town_to_region']:
                raise ValueError(f'Invalid profile_id: {row.profile_id}')
            if isinstance(row.price,(bool,np.bool_)):
                raise ValueError('Profile price must be numeric, not a boolean')
            try:
                price=float(row.price)
            except (TypeError,ValueError) as exc:
                raise ValueError('Profile price must be a finite positive number') from exc
            result = self.predict(self.metadata['town_to_region'][parts[0]], parts[1],
                                  horizon_months, price, base_price_month)
            rows.extend(dict(profile_id=row.profile_id, month=r['month'],
                             p10=r['p10'], p50=r['p50'], p90=r['p90']) for r in result['forecasts'])
        return pd.DataFrame(rows, columns=['profile_id','month','p10','p50','p90'])

    def simulate_paths(self, *args, **kwargs):
        raise NotImplementedError('Marginal quantiles are not joint Monte Carlo paths; joint simulation is not implemented.')

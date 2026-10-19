"""Inference-only fifteen-series forecasting and shared joint Monte Carlo paths.

No raw data, model fitting or PyTorch required. Price API shape matches the older
regional adapter; uncertainty is explicitly the exploratory mirrored-error model.
"""
from pathlib import Path
import json
import math
import numpy as np
import pandas as pd
from .regional_api import RegionalForecaster

DEFAULT_BUNDLE=Path(__file__).resolve().parent/'models/multitype/manifest.json'


class MultiTypeForecaster(RegionalForecaster):
    def __init__(self,bundle=DEFAULT_BUNDLE):
        bundle_path=Path(bundle);self.metadata=json.loads(bundle_path.read_text())
        if self.metadata['schema_version']!=3:raise ValueError('Unsupported multitype schema')
        errors=json.loads(bundle_path.with_name('joint_errors.json').read_text())
        if errors['origin']!=self.metadata['origin'] or errors['features_sha256']!=self.metadata['features_sha256']:
            raise ValueError('Point/scenario data origins or fingerprints differ')
        if errors.get('macro_sha256')!=self.metadata.get('macro_sha256') or errors.get('selected_model_by_type')!=self.metadata.get('selected_model_by_type'):
            raise ValueError('Point/scenario macro inputs or model selections differ')
        self.scenario_metadata=errors;self.segment_ids=errors['segments']
        if len(set(self.segment_ids))!=len(self.segment_ids) or set(self.segment_ids)!=set(self.metadata['segments']):
            raise ValueError('Scenario segments differ from model segments')
        self.errors=np.asarray(errors['log_error_paths'],float)
        if self.errors.shape!=(len(errors['source_origins']),12,len(self.segment_ids)) or not np.isfinite(self.errors).all():
            raise ValueError('Invalid joint error bank')
        self.scenario_errors=np.asarray(errors['scenario_log_error_paths'],float)
        if self.scenario_errors.shape!=self.errors.shape or not np.isfinite(self.scenario_errors).all():
            raise ValueError('Invalid scenario challenger error bank')
        if any(pd.Timestamp(o)+pd.DateOffset(months=12)>pd.Timestamp(errors['origin']) for o in errors['source_origins']):
            raise ValueError('Error bank contains unobserved future outcomes')

    def predict(self,region,flat_type='4 ROOM',horizon_months=12,base_price_sgd=None,base_price_month=None):
        m=self.metadata;key=f'{region}::{flat_type}'
        if key not in m['segments']:raise ValueError(f'Unsupported segment {key}')
        if isinstance(horizon_months,bool) or not isinstance(horizon_months,int) or not 1<=horizon_months<=12:
            raise ValueError('horizon_months must be an integer from 1 to 12')
        if base_price_sgd is not None:
            if isinstance(base_price_sgd,bool) or not isinstance(base_price_sgd,(int,float)) or not math.isfinite(base_price_sgd) or base_price_sgd<=0:
                raise ValueError('Base price must be positive and finite')
            if base_price_month!=m['origin']:raise ValueError('Base price and forecast origin must match')
        elif base_price_month is not None:raise ValueError('A base-price date requires a base price')
        segment=m['segments'][key];factors=np.asarray(segment['growth_quantiles'])[:horizon_months]
        dates=pd.date_range(pd.Timestamp(m['origin'])+pd.offsets.MonthBegin(),periods=horizon_months,freq='MS')
        rows=[]
        for i,date in enumerate(dates):
            row=dict(month=date.strftime('%Y-%m'),horizon=i+1)
            for j,q in enumerate(['p10','p50','p90']):
                row[f'growth_factor_{q}']=float(factors[i,j]);row[f'index_{q}']=float(factors[i,j]*segment['reference_index'])
                if base_price_sgd is not None:row[q]=float(base_price_sgd*factors[i,j])
            rows.append(row)
        return dict(schema_version=3,model=segment['model'],model_version=m['model_version'],origin=m['origin'],
            segment_id=key,target='location_adjusted_hedonic_index',status=m['status'],quantiles=[.1,.5,.9],
            interval_type='central_80_percent_exploratory_symmetric_errors',warnings=m['warnings'],forecasts=rows)

    def draw_market_paths(self,n_scenarios=2000,horizon_months=12,seed=42,scenario='selected'):
        for value,label,minimum,maximum in [(n_scenarios,'n_scenarios',1,100000),(horizon_months,'horizon_months',1,12),(seed,'seed',0,2**32-2)]:
            if isinstance(value,bool) or not isinstance(value,int) or not minimum<=value<=maximum:raise ValueError(f'Invalid {label}')
        rng=np.random.default_rng(seed);chosen=rng.integers(len(self.errors),size=n_scenarios)
        signs=rng.choice([-1,1],size=n_scenarios)
        if scenario=='selected':segments=self.metadata['segments'];errors=self.errors
        elif scenario in self.metadata['scenario_segments']:
            segments=self.metadata['scenario_segments'][scenario];errors=self.scenario_errors
        else:raise ValueError('Unknown scenario; use selected or a named challenger sensitivity scenario')
        base=np.column_stack([np.exp(segments[s]['log_mean'])/segments[s]['reference_index'] for s in self.segment_ids])
        growth=base[None,:horizon_months,:]*np.exp(signs[:,None,None]*errors[chosen,:horizon_months,:])
        return dict(origin=self.metadata['origin'],scenario=scenario,scenario_status='selected_prototype' if scenario=='selected' else 'diagnostic_only',segments=self.segment_ids,scenario_ids=np.arange(n_scenarios),
            months=pd.date_range(pd.Timestamp(self.metadata['origin'])+pd.offsets.MonthBegin(),periods=horizon_months,freq='MS').strftime('%Y-%m').tolist(),
            sampled_error_origins=np.asarray(self.scenario_metadata['source_origins'])[chosen],error_signs=signs,growth_factors=growth,warnings=self.metadata['warnings'])

    def simulate_paths(self,prices,base_price_month,n_scenarios=2000,horizon_months=12,seed=42,scenario='selected'):
        self.price_profiles(prices,base_price_month,horizon_months)  # Shared strict validation.
        if len(prices)*n_scenarios*horizon_months>2_000_000:raise ValueError('Request smaller batches: maximum two million rows')
        batch=self.draw_market_paths(n_scenarios,horizon_months,seed,scenario);rows=[]
        for row in prices.itertuples(index=False):
            town,ft,*_=row.profile_id.split('|');key=self.metadata['town_to_region'][town]+'::'+ft
            j=self.segment_ids.index(key)
            rows.append(pd.DataFrame(dict(profile_id=row.profile_id,scenario_id=np.repeat(batch['scenario_ids'],horizon_months),
                month=np.tile(batch['months'],n_scenarios),price_sgd=(float(row.price)*batch['growth_factors'][:,:,j]).reshape(-1),
                source_error_origin=np.repeat(batch['sampled_error_origins'],horizon_months),error_sign=np.repeat(batch['error_signs'],horizon_months))))
        result=pd.concat(rows,ignore_index=True)
        result.attrs.update(scenario=scenario,scenario_status=batch['scenario_status'],warnings=batch['warnings'])
        return result

    def town_forecast(self):
        rows=[]
        for town,region in self.metadata['town_to_region'].items():
            for ft in self.metadata['flat_types']:
                result=self.predict(region,ft)['forecasts']
                for h in [6,12]:
                    row=result[h-1]
                    rows.append(dict(town=town,flat_type=ft,horizon_months=h,growth_factor=row['growth_factor_p50'],
                        growth_factor_lower=row['growth_factor_p10'],growth_factor_upper=row['growth_factor_p90'],
                        _source=f"Trained {ft}; {self.metadata['model_version']}; exploratory joint-error bounds"))
        return pd.DataFrame(rows)


def run_joint_monte_carlo(shortlist,n_scenarios=2000,seed=42,base_price_month='2026-09',bundle=DEFAULT_BUNDLE,scenario='selected'):
    required={'profile_id','town','flat_type','price_today','survival_prob_6m','survival_prob_12m'}
    if not required.issubset(shortlist.columns) or shortlist.empty or shortlist.profile_id.duplicated().any():
        raise ValueError('Supply a nonempty unique shortlist with price and cumulative availability probabilities')
    if len(shortlist)*n_scenarios>2_000_000:raise ValueError('Request a smaller batch')
    api=MultiTypeForecaster(bundle)
    if base_price_month!=api.metadata['origin']:raise ValueError('Base prices must match the model origin')
    batch=api.draw_market_paths(n_scenarios,12,seed,scenario);rng=np.random.default_rng(seed+2);tables=[]
    for row in shortlist.itertuples(index=False):
        town=row.town.replace('KALLANG-WHAMPOA','KALLANG/WHAMPOA')
        region=api.metadata['town_to_region'].get(town);key=f'{region}::{row.flat_type}'
        if key not in api.segment_ids:raise ValueError(f'Unsupported profile segment {key}')
        price=float(row.price_today);p6=float(row.survival_prob_6m);p12=float(row.survival_prob_12m)
        if not np.isfinite(price) or price<=0 or not 0<=p6<=p12<=1:raise ValueError('Invalid price or cumulative availability')
        j=api.segment_ids.index(key);arrival=rng.random(n_scenarios)
        tables.append(pd.DataFrame(dict(profile_id=row.profile_id,scenario_id=batch['scenario_ids'],regime='joint_multitype_'+scenario,
            buy_now_price=price,buy_now_available=arrival<1-(1-p6)**.25,
            wait6_price=price*batch['growth_factors'][:,5,j],wait6_available=arrival<p6,
            wait12_price=price*batch['growth_factors'][:,11,j],wait12_available=arrival<p12,
            source_error_origin=batch['sampled_error_origins'],error_sign=batch['error_signs'])))
    result=pd.concat(tables,ignore_index=True)
    result.attrs['limitations']=api.metadata['warnings']+['Availability assumed independent of market shocks and between profiles; transaction proxy is not a successful purchase probability.']
    result.attrs['scenario_status']=batch['scenario_status']
    return result


def main():
    from .multitype_core import EVIDENCE
    # python -m executes this file as __main__; pickle must name the importable
    # package class, not __main__.MultiTypeForecaster in a transient exporter.
    from forecasting.multitype_api import MultiTypeForecaster as CallableModel
    import pickle
    api=CallableModel();api.town_forecast().to_csv(EVIDENCE/'price_forecast.csv',index=False)
    with DEFAULT_BUNDLE.with_name('forecast_model.pkl').open('wb') as stream:pickle.dump(api,stream,protocol=pickle.HIGHEST_PROTOCOL)
    path=Path(__file__).resolve().parents[1]/'outputs/prices_today.csv';prices=pd.read_csv(path)
    supported=prices.profile_id.str.split('|').str[1].isin(api.metadata['flat_types'])
    api.price_profiles(prices[supported],api.metadata['origin']).to_csv(EVIDENCE/'price_paths.csv',index=False)
    (EVIDENCE/'price_paths_metadata.json').write_text(json.dumps(dict(base_price_month=api.metadata['origin'],
        model_version=api.metadata['model_version'],included_profiles=int(supported.sum()),excluded_unsupported_profiles=int((~supported).sum()),
        pricing_sha256=__import__('hashlib').sha256(path.read_bytes()).hexdigest(),quantiles='p10/p50/p90; central 80%; exploratory symmetric errors',warnings=api.metadata['warnings']),indent=2))


if __name__=='__main__':main()

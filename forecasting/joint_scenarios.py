"""Joint regional market scenarios from complete historical forecast-error paths.

This is an empirical scenario model, not an affordability guarantee. It preserves
observed cross-region and cross-horizon dependence by sampling entire error arrays.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from .regional_api import RegionalForecaster, DEFAULT_BUNDLE


class JointScenarioForecaster:
    def __init__(self, bundle=DEFAULT_BUNDLE, errors=None, mode='symmetric'):
        if mode not in ['symmetric','directional']:
            raise ValueError('mode must be symmetric or directional')
        self.mode=mode
        self.point_model=RegionalForecaster(bundle)
        path=Path(errors) if errors is not None else Path(bundle).with_name('joint_errors.json')
        self.metadata=json.loads(path.read_text(encoding='utf-8'))
        m=self.point_model.metadata
        if self.metadata['origin'] != m['origin'] or self.metadata['features_sha256'] != m['features_sha256']:
            raise ValueError('Scenario and point-model origins/source hashes differ')
        self.regions=list(self.metadata['regions'])
        self.errors=np.asarray(self.metadata['log_error_paths'],float)
        if self.errors.shape != (len(self.metadata['source_origins']),12,len(self.regions)) or not np.isfinite(self.errors).all():
            raise ValueError('Invalid historical joint error array')
        if any(pd.Timestamp(s)+pd.DateOffset(months=12)>pd.Timestamp(m['origin']) for s in self.metadata['source_origins']):
            raise ValueError('Calibration includes unobserved outcomes')

    def _base_growth(self):
        m=self.point_model.metadata
        return np.column_stack([np.exp(m['segments'][f'{r}::4 ROOM']['log_mean']) /
                                m['segments'][f'{r}::4 ROOM']['reference_index'] for r in self.regions])

    def draw(self,n_scenarios=2000,horizon_months=12,seed=42):
        if isinstance(n_scenarios,bool) or not isinstance(n_scenarios,int) or not 1<=n_scenarios<=100000:
            raise ValueError('n_scenarios must be an integer from 1 to 100000')
        if isinstance(horizon_months,bool) or not isinstance(horizon_months,int) or not 1<=horizon_months<=12:
            raise ValueError('horizon_months must be an integer from 1 to 12')
        if isinstance(seed,bool) or not isinstance(seed,int) or seed<0:
            raise ValueError('seed must be a nonnegative integer')
        chosen=np.random.default_rng(seed).integers(0,len(self.errors),size=n_scenarios)
        signs=np.random.default_rng(seed+1).choice([-1,1],n_scenarios) if self.mode=='symmetric' else np.ones(n_scenarios)
        growth=self._base_growth()[None,:horizon_months,:]*np.exp(self.errors[chosen,:horizon_months,:]*signs[:,None,None])
        return dict(origin=self.metadata['origin'],regions=self.regions,
                    months=pd.date_range(pd.Timestamp(self.metadata['origin'])+pd.offsets.MonthBegin(),
                                         periods=horizon_months,freq='MS').strftime('%Y-%m').tolist(),
                    scenario_ids=np.arange(n_scenarios),sampled_error_origins=np.asarray(self.metadata['source_origins'])[chosen],
                    error_signs=signs,mode=self.mode,growth_factors=growth,status=self.metadata['status'],warnings=self.metadata['warnings'])

    def profile_paths(self,prices,base_price_month,n_scenarios=2000,horizon_months=12,seed=42):
        # Validate scope/prices/dates through the existing strict interface first.
        self.point_model.price_profiles(prices,base_price_month,horizon_months)
        if len(prices)*n_scenarios*horizon_months>2_000_000:
            raise ValueError('Request selected profiles or smaller batches (maximum 2 million rows)')
        batch=self.draw(n_scenarios,horizon_months,seed)
        records=[]
        for row in prices.itertuples(index=False):
            town=row.profile_id.split('|')[0]
            ri=self.regions.index(self.point_model.metadata['town_to_region'][town])
            records.append(pd.DataFrame(dict(profile_id=row.profile_id,
                scenario_id=np.repeat(batch['scenario_ids'],horizon_months),
                month=np.tile(batch['months'],n_scenarios),
                source_error_origin=np.repeat(batch['sampled_error_origins'],horizon_months),
                error_sign=np.repeat(batch['error_signs'],horizon_months),
                price_sgd=(row.price*batch['growth_factors'][:,:,ri]).reshape(-1))))
        return pd.concat(records,ignore_index=True)

    def summary(self):
        """Log-space empirical quantiles, consistent with historical evaluation."""
        errors=np.concatenate([self.errors,-self.errors]) if self.mode=='symmetric' else self.errors
        quantiles=self._base_growth()[None,:,:]*np.exp(np.quantile(errors,[.1,.5,.9],axis=0))
        rows=[]
        for town,region in self.point_model.metadata['town_to_region'].items():
            ri=self.regions.index(region)
            for h in [6,12]:
                rows.append(dict(town=town,flat_type='4 ROOM',horizon_months=h,
                    growth_factor=float(quantiles[1,h-1,ri]),
                    growth_factor_lower=float(quantiles[0,h-1,ri]),
                    growth_factor_upper=float(quantiles[2,h-1,ri]),
                    _source=f'EXPLORATORY {self.mode} joint historical errors; origin {self.metadata["origin"]}; regional market uncertainty only'))
        return pd.DataFrame(rows)


def main():
    model=JointScenarioForecaster()
    out=Path(__file__).resolve().parent/'evidence/final'
    out.mkdir(parents=True,exist_ok=True)
    model.summary().to_csv(out/'price_forecast_joint_candidate.csv',index=False)
    batch=model.draw()
    np.savez_compressed(out/'joint_growth_sample.npz',growth_factors=batch['growth_factors'],
        regions=np.asarray(batch['regions']),months=np.asarray(batch['months']),
        error_signs=batch['error_signs'],
        sampled_error_origins=batch['sampled_error_origins'])
    print(f'Exported {batch["growth_factors"].shape}: scenarios x months x regions')


if __name__=='__main__':main()

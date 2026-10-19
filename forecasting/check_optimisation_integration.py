"""Contract smoke test against an unchanged snapshot of Daniel's real code.

Fixtures are SYNTHETIC and prove software compatibility only, not recommendation
accuracy. See replay_optimisation.py for the separate real-data reconstruction.
"""
from pathlib import Path
from unittest.mock import patch
import importlib.util
import json
import hashlib
import os
import argparse
import numpy as np
import pandas as pd
from .joint_scenarios import JointScenarioForecaster
from .optimisation_bridge import run_joint_monte_carlo

BASE=Path(__file__).resolve().parent


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def main(multitype=False):
    ref=BASE/'outputs/team_replay/Project/notebooks/optimization_lead'
    rv=load_module('daniel_recommender',ref/'recommender_v2.py')
    mc=load_module('daniel_monte_carlo',ref/'monte_carlo.py')
    towns=['SENGKANG','HOUGANG','ANG MO KIO','TAMPINES','WOODLANDS']
    profiles=pd.DataFrame(dict(town=towns,flat_type='4 ROOM',lease_band='80+',storey_band='Mid',mrt_band='Near',
        profile_id=[f'{t}::4ROOM::80+::Mid::Near' for t in towns],
        median_price=[500000,520000,540000,560000,480000],txn_count_12m=20,
        median_remaining_lease=85.,hedonic_gap=0.,dist_mrt_exit_km_p50=.3,
        dist_hawker_km_p50=.4,dist_supermarket_km_p50=.3,dist_chas_clinic_km_p50=.4,dist_park_km_p50=.5,
        essentials_score=4.,share_elite_primary_1km=.5,share_elite_primary_2km=.8,share_primary_1km=1.))
    betas={key:-.02 for key in rv.ATTR_BETA_KEY.values()}
    rent=profiles[['town','flat_type']].assign(monthly_rent=3000.)
    scenario_function=run_joint_monte_carlo
    forecast=JointScenarioForecaster().summary()
    supported=['4 ROOM']
    if multitype:
        from .multitype_api import MultiTypeForecaster, run_joint_monte_carlo as expanded_mc
        supported=['3 ROOM','4 ROOM','5 ROOM'];parts=[]
        for ft,factor in zip(supported,[.8,1.,1.15]):
            p=profiles.copy();p['flat_type']=ft
            p['profile_id']=p.profile_id.str.replace('4ROOM',ft.replace(' ',''),regex=False)
            p['median_price']*=factor;parts.append(p)
        profiles=pd.concat(parts,ignore_index=True)
        rent=profiles[['town','flat_type']].assign(monthly_rent=3000.)
        forecast=MultiTypeForecaster().town_forecast();scenario_function=expanded_mc
    query=rv.HouseholdQuery2(budget=700000,flat_types=supported,k=3)
    # Only data-loading is replaced; actual assemble, scoring and CBC solver execute.
    factory=rv.pulp.PULP_CBC_CMD
    def solver(**kwargs):
        instance=factory(**kwargs)
        # CBC 2.10 parses unquoted temp paths poorly on Windows with spaces.
        if os.name=='nt':
            import ctypes
            folder=BASE/'outputs/solver_tmp';folder.mkdir(parents=True,exist_ok=True)
            buffer=ctypes.create_unicode_buffer(32768)
            if not ctypes.windll.kernel32.GetShortPathNameW(str(folder),buffer,len(buffer)):
                raise OSError('Cannot obtain space-free solver temporary path')
            instance.tmpDir=buffer.value
        return instance
    with patch.object(rv,'load_inputs',return_value=(profiles,betas,forecast,rent)), patch.object(rv.pulp,'PULP_CBC_CMD',side_effect=solver):
        result=rv.solve(query,profiles=profiles)
        poisoned=forecast.copy();poisoned['growth_factor_upper']=100
        override_result=rv.solve(query,profiles=profiles,fcast_override=poisoned)
    if result['status']!='Optimal' or len(result['shortlist'])!=3: raise AssertionError('Solver contract failed')
    factors=forecast[forecast.horizon_months.eq(12)].set_index(['town','flat_type']).growth_factor_upper
    selected=result['shortlist']
    np.testing.assert_allclose(selected.price_upper,selected.price_today*factors.reindex(pd.MultiIndex.from_frame(selected[['town','flat_type']])).to_numpy())
    scenarios=scenario_function(selected,n_scenarios=500)
    summary=mc.summarize_strategies(scenarios,query.budget)
    if len(summary)!=3:raise AssertionError('Monte Carlo summarizer schema mismatch')
    probabilities=[c for c in summary if 'p_success' in c]
    if not summary[probabilities].apply(lambda x:x.between(0,1)).all().all():raise AssertionError('Invalid probabilities')
    report=dict(status='passed',fixture=f'synthetic five-town profiles, types {supported}; not a real-data performance test',
        optimisation_commit=json.loads((BASE/'evidence/final/replay_sources.json').read_text())['optimisation_commit'],
        recommender_sha256=hashlib.sha256((ref/'recommender_v2.py').read_bytes()).hexdigest(),
        solver_status=result['status'],selected_profiles=len(selected),scenario_rows=len(scenarios),
        tested=[f'actual assemble/score/CBC solve accepts {len(forecast)}-row town forecast schema',
                'price_upper equals price_today times supplied upper factor',
                'actual summarize_strategies consumes joint scenario output'],
        fcast_override_deterministic_path_ignored=bool(override_result['shortlist'].profile_id.tolist()==selected.profile_id.tolist()),
        remaining_integration=['Load dated forecast table through load_inputs for historical deterministic runs; fcast_override alone does not update price_upper.',
            'Opt in to run_joint_monte_carlo; replacing only marginal bounds does not replace independent price draws.',
            f'Only {supported} supported; never relabel other existing stubs as trained forecasts.',
            'Real-data replay needs the additional shared-folder sources listed in replay_sources.json; it is separate from this synthetic contract check.',
            'PuLP 3.3.0 tested; PuLP 4 removes PULP_CBC_CMD used by current optimiser.'])
    destination=BASE/('evidence/multitype' if multitype else 'evidence/final')
    (destination/'optimisation_contract_check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--multitype',action='store_true')
    main(parser.parse_args().multitype)

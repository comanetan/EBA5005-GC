"""Retrospective four-room forecast integration with Daniel's actual GP solver.

Runs untouched team code in the isolated layout created by prepare_team_replay.
Dated loaders replace current inputs; this is not a reproduction of the live UI,
nor an evaluation of the team's final conjoint / Comane survival model.
"""
from pathlib import Path
from unittest.mock import patch
import ctypes
import json
import os
import sys
import argparse
import numpy as np
import pandas as pd
from .optimisation_bridge import historical_forecast
from .prepare_team_replay import CODE, PROJECT, BASE


def summarise():
    dest=BASE/'evidence/final'
    picks=pd.read_csv(dest/'optimisation_replay_picks.csv')
    runs=pd.read_csv(dest/'optimisation_replay_runs.csv')
    report=picks.groupby('method').agg(picks=('profile_id','size'),matched=('matched','sum'),
        within_budget_count=('within_budget','sum'),within_budget_rate=('within_budget','mean'),
        mean_mrt_km=('mrt_distance','mean'))
    grouped=runs.groupby('method')
    report['household_runs']=grouped.size()
    report['full_five_pick_shortlists']=grouped.selected.apply(lambda x:int(x.eq(5).sum()))
    report['empty_shortlists']=grouped.selected.apply(lambda x:int(x.eq(0).sum()))
    report['requested_picks']=report.household_runs*5
    report['returned_share']=report.picks/report.requested_picks
    report.to_csv(dest/'optimisation_replay_summary.csv')
    print(report.to_string())


def main():
    sys.path.insert(0,str(CODE))
    import recommender_v2 as rv
    import housing_profiles_v2 as hp
    import hedonic_value as hv
    import block_analysis as ba
    tx=ba.load_transactions_with_access()
    rentals=pd.read_csv(PROJECT/'data/processed/hdb_rental_town_flattype_month.csv',parse_dates=['month'])
    rentals['flat_type']=rentals.flat_type.str.replace('-',' ')
    factory=rv.pulp.PULP_CBC_CMD
    def solver(**kwargs):
        instance=factory(**kwargs)
        if os.name=='nt':
            folder=BASE/'outputs/solver_tmp';folder.mkdir(exist_ok=True)
            buffer=ctypes.create_unicode_buffer(32768)
            if not ctypes.windll.kernel32.GetShortPathNameW(str(folder),buffer,len(buffer)):
                raise OSError('No space-free CBC temporary path')
            instance.tmpDir=buffer.value
        return instance
    rows=[];runs=[];fit_meta=[]
    origins=pd.date_range('2022-12-01','2025-06-01',freq='3MS')
    households={
        'transit_550k':dict(budget=550000,min_lease_yrs=60,target_mrt_km=.4,multipliers={'mrt':1.5}),
        'family_750k':dict(budget=750000,min_lease_yrs=65,needs_primary_school=True),
        'budget_450k':dict(budget=450000,min_lease_yrs=55,target_mrt_km=1.,multipliers={'mrt':.5},target_essentials=3.),
    }
    keys=['town','flat_type','lease_band','storey_band','mrt_band']
    for origin in origins:
        fitted={}
        original=hv.fit_hedonic
        def capture(*args,**kwargs):
            model,last=original(*args,**kwargs)
            fitted['betas']=hv.market_wtp_coefficients(model)
            fitted['rows']=int(model.nobs)
            return model,last
        # Current empirically calibrated MRT correction was learned after these
        # origins. Remove it for this historical reconstruction, don't backdate it.
        with patch.object(hv,'MRT_SPATIAL_CORRECTION',1.),patch.object(hv,'fit_hedonic',side_effect=capture):
            profiles,_=hp.build_profiles_v2(as_of=str(origin.date()),write=False)
        profiles=profiles[profiles.flat_type.eq('4 ROOM')].copy()
        rent=rentals[(rentals.month<=origin)&(rentals.month>origin-pd.DateOffset(months=12))]
        rent=rent.groupby(['town','flat_type']).median_rent.median().rename('monthly_rent').reset_index()
        if rent.empty:raise ValueError('No dated rental evidence')
        fit_meta.append(dict(origin=str(origin.date()),hedonic_rows=fitted['rows'],profiles=len(profiles),
                             rental_latest=str(rentals.loc[rentals.month<=origin,'month'].max().date())))
        future=tx[(tx.month>=origin+pd.DateOffset(months=11))&(tx.month<=origin+pd.DateOffset(months=13))]
        future=ba.network_as_of(future,origin)
        # Track origin lease band, so a crossing boundary doesn't change the target cell.
        elapsed=(future.month.dt.year-origin.year)*12+future.month.dt.month-origin.month
        future['lease_band']=ba.lease_band(future.remaining_lease_yrs+elapsed/12)
        actual=future.groupby(keys,observed=True).resale_price.agg(['median','size']).reset_index()
        for method in ['naive','nominal','symmetric']:
            forecast=historical_forecast(origin,'nominal' if method=='naive' else method)
            if method=='naive':
                forecast[['growth_factor','growth_factor_lower','growth_factor_upper']]=1.
            for name,settings in households.items():
                query=rv.HouseholdQuery2(k=5,flat_types=['4 ROOM'],name=name,**settings)
                with patch.object(rv,'load_inputs',return_value=(profiles,fitted['betas'],forecast,rent)),patch.object(rv.pulp,'PULP_CBC_CMD',side_effect=solver):
                    result=rv.solve(query,profiles=profiles)
                selected=result['shortlist']
                runs.append(dict(origin=str(origin.date()),method=method,household=name,status=result['status'],selected=len(selected)))
                if selected.empty:continue
                expected=forecast[forecast.horizon_months.eq(12)].set_index('town').growth_factor_upper
                np.testing.assert_allclose(selected.price_upper,selected.price_today*selected.town.map(expected))
                selected=selected.merge(actual,on=keys,how='left')
                for row in selected.itertuples():
                    matched=np.isfinite(row.median)
                    rows.append(dict(origin=str(origin.date()),method=method,household=name,profile_id=row.profile_id,
                        budget=query.budget,price_today=row.price_today,price_upper=row.price_upper,
                        realised_median=row.median,matched_sales=0 if not matched else int(row.size),
                        within_budget=float(row.median<=query.budget) if matched else np.nan,
                        matched=matched,mrt_distance=row.dist_mrt_exit_km_p50))
        print(f'{origin:%Y-%m}: {len(profiles)} profiles, {len(runs)} solver runs complete',flush=True)
    dest=BASE/'evidence/final'
    picks=pd.DataFrame(rows);picks.to_csv(dest/'optimisation_replay_picks.csv',index=False)
    pd.DataFrame(runs).to_csv(dest/'optimisation_replay_runs.csv',index=False)
    (dest/'optimisation_replay_metadata.json').write_text(json.dumps(dict(
        status='completed',solver_runs=len(runs),origins=[str(x.date()) for x in origins],fits=fit_meta,
        scope='Actual weighted-goal-programming solver; three fixed four-room household scenarios; 12-month outcomes',
        limitations=[
            'Retrospective integration sensitivity test: ARIMA family and symmetric uncertainty choice were selected using overlapping evaluation periods.',
            'Uses Daniel dated profile median prices and dated interim hedonic valuation; not the final Comane pricing or conjoint/survival pipeline.',
            'Current block/amenity snapshots and latest transaction/rental data vintages remain; historical releases are not reconstructed.',
            'Availability is Daniel historical transaction-count stub; matching sales do not measure a buyer successfully securing a listing.',
            'Future matching uses origin rail network and approximate origin lease years; outcomes are 3-month-window medians, not actual offers.',
            'Repeated households and overlapping dates are dependent; aggregate rates have no independent-binomial confidence interpretation.',
            'Current empirically learned MRT correction disabled historically; this reconstructed model is not identical to live defaults.',
            'Naive uses zero growth and zero uncertainty; comparison is decision sensitivity, not equal-risk model accuracy.'
        ]),indent=2))
    summarise()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--summary-only',action='store_true')
    if parser.parse_args().summary_only:summarise()
    else:main()

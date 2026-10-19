"""A small editable example of Daniel consuming the frozen forecasting model.

Run from repository root: python -m forecasting.demo_consumer
Inputs below are illustrative; outputs do not represent an actual listing.
"""
from pathlib import Path
import argparse
import pickle
import pandas as pd
from .multitype_api import DEFAULT_BUNDLE, run_joint_monte_carlo


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--town',default='HOUGANG')
    parser.add_argument('--flat-type',default='4 ROOM')
    parser.add_argument('--price',type=float,default=600000)
    parser.add_argument('--horizon',type=int,default=12)
    parser.add_argument('--base-month',default='2026-09')
    parser.add_argument('--seed',type=int,default=42)
    args=parser.parse_args()

    # 1. Load once. The PKL points to forecasting.multitype_api, not this script.
    with DEFAULT_BUNDLE.with_name('forecast_model.pkl').open('rb') as stream:
        model=pickle.load(stream)

    # 2. Map Daniel's town input to the team's regional group.
    if args.town not in model.metadata['town_to_region']:
        raise ValueError(f'Unsupported town: {args.town}')
    region=model.metadata['town_to_region'][args.town]

    # 3. Supply the current valuation and its date; never use budget as price.
    result=model.predict(region,args.flat_type,args.horizon,args.price,args.base_month)
    forecast=pd.DataFrame(result['forecasts'])

    # 4. The town/type table goes into the optimiser's deterministic constraints.
    town_table=model.town_forecast()

    # 5. Demonstrate its Monte Carlo input. Replace these illustrative cumulative
    # probabilities with the Availability Lead's values in the real application.
    shortlist=pd.DataFrame([dict(profile_id='demo-profile',town=args.town,flat_type=args.flat_type,
        price_today=args.price,survival_prob_6m=.5,survival_prob_12m=.8)])
    scenarios=run_joint_monte_carlo(shortlist,n_scenarios=500,seed=args.seed,base_price_month=args.base_month)

    # Generated examples stay separate from committed evaluation evidence/models.
    out=Path(__file__).resolve().parent/'outputs/consumer_demo'
    out.mkdir(parents=True,exist_ok=True)
    forecast.to_csv(out/'forecast.csv',index=False)
    town_table.to_csv(out/'town_forecast.csv',index=False)
    scenarios.to_csv(out/'monte_carlo.csv',index=False)
    print(f"Model: {result['model']} | version: {result['model_version']}")
    print(f'Town: {args.town} | region: {region} | type: {args.flat_type}')
    print(f'Illustrative base valuation: SGD {args.price:,.0f} at {args.base_month}')
    print(forecast[['month','p10','p50','p90']].round(2).to_string(index=False))
    print(f'PASS: {len(forecast)} forecast rows; {len(town_table)} town-table rows; {len(scenarios)} scenario rows.')
    print(f'Generated examples: {out}')
    print('These are central-80% exploratory bounds; example availability is synthetic.')


if __name__=='__main__':main()

"""Owner's repeatable code-freeze checks; default includes the forecasting tests.

python -m forecasting.check_freeze --with-optimiser
Writes an ignored JSON report and does not refit or replace model/evidence files.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import numpy as np
import pandas as pd
from .consumer_check import check
from .multitype_api import MultiTypeForecaster

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'forecasting'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--with-optimiser',action='store_true')
    args=parser.parse_args()
    report=dict(status='running',python=sys.version,python_executable=sys.executable,checks={})
    out=BASE/'outputs/freeze_check';out.mkdir(parents=True,exist_ok=True)
    try:
        result=subprocess.run([sys.executable,'-m','unittest','discover','-s','forecasting','-t','.', '-p','test_*.py'],cwd=ROOT,check=False)
        if result.returncode:raise AssertionError('Forecasting tests failed; resolve the traceback before freezing')
        report['checks']['forecasting_tests']='passed'
        report['checks']['consumer_contract']=check()

        api=MultiTypeForecaster()
        metadata=json.loads((BASE/'evidence/multitype/price_paths_metadata.json').read_text())
        pricefile=ROOT/'outputs/prices_today.csv'
        if digest(pricefile)!=metadata['pricing_sha256']:
            raise AssertionError('Pricing export changed since handover. Confirm its as-of date and re-export forecasting handover intentionally.')
        if api.metadata['model_version']!=metadata['model_version'] or api.metadata['origin']!=metadata['base_price_month']:
            raise AssertionError('Model and exported pricing handover versions/dates differ')
        prices=pd.read_csv(pricefile)
        supported=prices.profile_id.str.split('|').str[1].isin(api.metadata['flat_types'])
        actual=api.price_profiles(prices[supported],metadata['base_price_month'])
        saved=pd.read_csv(BASE/'evidence/multitype/price_paths.csv')
        keys=['profile_id','month']
        actual=actual.sort_values(keys).reset_index(drop=True);saved=saved.sort_values(keys).reset_index(drop=True)
        pd.testing.assert_frame_equal(actual,saved,rtol=1e-10,atol=1e-7)
        assert len(actual)==int(supported.sum())*12
        report['checks']['real_pricing_export']=dict(status='passed',supported_profiles=int(supported.sum()),
            excluded_unsupported_profiles=int((~supported).sum()),profile_month_rows=len(actual))
        print(f'PASS: all {int(supported.sum())} supported pricing profiles reproduce the committed handover.')

        if args.with_optimiser:
            required=BASE/'outputs/team_replay/Project/notebooks/optimization_lead/recommender_v2.py'
            if not required.exists():raise FileNotFoundError('Isolated optimiser snapshot absent; see MULTITYPE_HANDOVER.md reproduction instructions')
            subprocess.run([sys.executable,'-m','forecasting.check_optimisation_integration','--multitype',
                            '--report-path',str(out/'optimiser_contract.json')],cwd=ROOT,check=True)
            report['checks']['actual_optimiser_contract']='passed: synthetic input, actual solver and summarizer'
        else:report['checks']['actual_optimiser_contract']='not run; use --with-optimiser when the isolated snapshot is available'
        for name in ['manifest.json','joint_errors.json','forecast_model.pkl']:
            report.setdefault('model_file_sha256',{})[name]=digest(BASE/'models/multitype'/name)
        for name in ['multitype_api.py','regional_api.py','consumer_check.py','check_freeze.py']:
            report.setdefault('source_file_sha256',{})[name]=digest(BASE/name)
        report['git_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        report['working_tree_dirty']=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
        report['status']='passed'
        report['limits']=['Passing checks does not prove zero bugs or statistical model adequacy.',
            'Synthetic solver check is not acceptance of Daniel final UI or final pricing/preference/survival versions.',
            'Record the final clean Git commit when announcing forecasting code freeze.']
        print('FREEZE CHECKS PASSED. Read the model limitations and record the final Git commit.')
    except Exception as exc:
        report['status']='failed';report['error']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        path=out/'freeze_report.json';path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(f'Check report: {path}')


if __name__=='__main__':main()

"""Copy the minimal inference handover into an isolated, ignored folder.

This intentionally omits raw data, evidence, training modules and fitted audit
PKLs, so consumer_check can demonstrate the runtime's actual dependencies.
"""
from pathlib import Path
import hashlib
import json
import shutil


def main():
    base=Path(__file__).resolve().parent
    destination=base/'outputs/consumer_package'
    sources=['__init__.py','regional_api.py','multitype_api.py','consumer_check.py','demo_consumer.py',
             'requirements-inference.txt','models/multitype/manifest.json',
             'models/multitype/joint_errors.json','models/multitype/forecast_model.pkl']
    hashes={}
    for name in sources:
        target=destination/'forecasting'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(base/name,target)
        hashes[name]=hashlib.sha256(target.read_bytes()).hexdigest()
    (destination/'package_manifest.json').write_text(json.dumps(dict(files=hashes,
        omitted=['raw data','training features','Torch checkpoints','statistical-model audit PKLs','optimisation sources']),indent=2))
    print(f'Consumer package: {destination}')
    print('Run python -m forecasting.consumer_check from this folder using a minimal inference environment.')


if __name__=='__main__':main()

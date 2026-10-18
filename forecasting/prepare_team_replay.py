"""Rebuild an isolated optimisation snapshot from existing, attributed local data.

Does not download data or modify the optimisation workstream. Paths to the team
OneDrive dataset are supplied explicitly; generated inputs stay under outputs/.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
import pandas as pd

BASE = Path(__file__).resolve().parent
REPO = BASE.parent
PROJECT = BASE / 'outputs/team_replay/Project'
CODE = PROJECT / 'notebooks/optimization_lead'


def main(shared):
    archive = BASE / 'outputs/optimisation_latest.zip'
    CODE.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if name.endswith('/'):
                continue
            relative = Path(name).relative_to('optimisation')
            dest = CODE / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(name))
    spec = importlib.util.spec_from_file_location('sync_replay', CODE/'sync_shared_repo_raw_data.py')
    sync = importlib.util.module_from_spec(spec); spec.loader.exec_module(sync)
    sync.sync(str(REPO))
    records = []
    def copy(src, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        records.append(dict(source=str(src.relative_to(shared)), destination=str(dest.relative_to(PROJECT)),
                            sha256=hashlib.sha256(src.read_bytes()).hexdigest()))
    geo = PROJECT/'data/geospatial'; proc = PROJECT/'data/processed'
    for name in ['LTA_MRT_Station_Exit.geojson', 'MasterPlan2019_Subzone_Boundary_NoSea.geojson']:
        copy(shared/'1. raw/daniel_add'/name, geo/name)
    copy(shared/'2. interim/daniel_add/hdb_rental_town_flattype_month.csv',
         proc/'hdb_rental_town_flattype_month.csv')
    for kind in ['schools', 'supermarkets']:
        src = shared/f'2. interim/daniel_add/{kind}_geocoded.csv'
        df = pd.read_csv(src)
        cols = (['postal_code'] if kind == 'schools' else []) + ['latitude', 'longitude']
        out = df[cols].dropna(subset=['latitude', 'longitude']).copy()
        out['status'] = 'OK'  # Valid supplied coordinates, not a new geocoder response.
        out.to_csv(proc/f'{kind}_geocoded_v2.csv', index=False)
        records.append(dict(source=str(src.relative_to(shared)), sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
                            transformation='retain supplied coordinates; mark nonmissing pairs OK', rows=len(out)))
    cache = pd.read_csv(CODE/'data/geocode_cache_optimisation.csv')
    blocks = cache[cache.kind.eq('block')].rename(columns={'key':'query','lat':'latitude','lon':'longitude'})
    blocks = blocks.dropna(subset=['latitude','longitude'])
    blocks[['query','latitude','longitude']].assign(status='OK').to_csv(proc/'hdb_blocks_geocoded.csv',index=False)
    stations = pd.read_csv(geo/'mrt_station_openings.csv').dropna(subset=['lat','lon'])
    features = [dict(type='Feature', properties={'NAME':r.station.upper()+' MRT STATION'},
                     geometry=dict(type='Point',coordinates=[r.lon,r.lat])) for r in stations.itertuples()]
    (geo/'MRT_exits_patch_onemap.geojson').write_text(json.dumps(dict(type='FeatureCollection',features=features)))
    evidence = BASE/'evidence/final'; evidence.mkdir(parents=True,exist_ok=True)
    revision = subprocess.check_output(['git','rev-parse','origin/optimisation'],cwd=REPO,text=True).strip()
    (evidence/'replay_sources.json').write_text(json.dumps(dict(optimisation_commit=revision,sources=records,
        transformations=['block coordinates from committed geocode cache',
                         'station point patch from team station-opening CSV; these are station points, not measured exit coordinates'],
        limitations=['Static amenity and block inventories are current snapshots, not historical vintages.']),indent=2))
    subprocess.run([sys.executable,'-c','from block_accessibility import build_block_accessibility; build_block_accessibility()'],cwd=CODE,check=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--shared-data',type=Path,required=True)
    main(parser.parse_args().shared_data)

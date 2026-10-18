# -*- coding: utf-8 -*-
"""
Geocodes the Pricing & Availability Lead's real polyclinics.csv (main branch, data/raw/ --
26 polyclinics, name + postal_code, hand-made from SingHealth/NHGP/NUP lists) via OneMap's
public search endpoint, replacing this pipeline's current dist_polyclinic_km source
(Vaccination_Polyclinics.geojson -- only 8 COVID-vaccination sites, a real undercount).
See DATA_LAYOUT.md and OPTIMISER_METHODOLOGY_REPORT.md Sec. 15 for why.
"""
import os
import time

import pandas as pd

from geocode_robust import geocode_query

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "data", "external_handovers", "polyclinics_main.csv")
OUT = os.path.join(HERE, "data", "polyclinics_geocoded.csv")


def run():
    d = pd.read_csv(SRC)
    rows = []
    for _, r in d.iterrows():
        lat, lon, status = geocode_query(str(r["postal_code"]))
        rows.append({"name": r["name"], "query": r["postal_code"], "lat": lat, "lon": lon, "status": status})
        time.sleep(0.25)
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    return out


if __name__ == "__main__":
    out = run()
    ok = (out["status"] == "OK").sum()
    print(f"Geocoded {ok}/{len(out)} polyclinics")
    print(out.to_string(index=False))

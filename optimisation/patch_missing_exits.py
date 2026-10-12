# -*- coding: utf-8 -*-
"""
LTA's MRT exit layer (last updated 17 Jul 2026) omits some operating stations
(confirmed: Punggol Coast, Hume). Check every Master-Plan station that is NOT
in the LTA layer against OneMap: if OneMap returns "<NAME> MRT/LRT STATION
EXIT n" points, the station is operating -> add its exits to a patch file.
Output: data/geospatial/MRT_exits_patch_onemap.geojson (merged in by
block_accessibility.py).
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../Project, portable across machines
GEO = os.path.join(ROOT, "data", "geospatial")


def onemap(q):
    url = ("https://www.onemap.gov.sg/api/common/elastic/search?"
           + urllib.parse.urlencode({"searchVal": q, "returnGeom": "Y", "getAddrDetails": "N", "pageNum": "1"}))
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as r:
                return json.loads(r.read())["results"]
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return []


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from block_accessibility import load_amenity_layers
    _, meta = load_amenity_layers()
    planned = meta["planned_station_names"]

    feats, report = [], []
    for name in planned:
        hits = []
        for kind in ["MRT", "LRT"]:
            res = onemap(f"{name} {kind} STATION EXIT")
            hits += [r for r in res if re.fullmatch(rf"{re.escape(name)} {kind} STATION EXIT \w+", r["SEARCHVAL"].strip())]
            time.sleep(0.35)
        report.append({"station": name, "exits_found": len(hits)})
        for r in hits:
            feats.append({"type": "Feature",
                          "geometry": {"type": "Point", "coordinates": [float(r["LONGITUDE"]), float(r["LATITUDE"])]},
                          "properties": {"STATION_NA": r["SEARCHVAL"].rsplit(" EXIT", 1)[0],
                                         "EXIT_CODE": "Exit " + r["SEARCHVAL"].rsplit("EXIT ", 1)[1],
                                         "SOURCE": "OneMap search (patch for LTA layer gap)"}})
    json.dump({"type": "FeatureCollection", "name": "MRT_EXITS_PATCH", "features": feats},
              open(os.path.join(GEO, "MRT_exits_patch_onemap.geojson"), "w", encoding="utf-8"), indent=1)
    found = [r for r in report if r["exits_found"]]
    print(f"Checked {len(report)} Master-Plan stations absent from the LTA layer.")
    print("Operating (exits found on OneMap):", found)
    print("Still not operating / no exits on OneMap:", [r["station"] for r in report if not r["exits_found"]])

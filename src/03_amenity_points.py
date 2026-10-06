"""Step 3 (offline): pull point locations out of the GeoJSON downloads into one tidy table.
Output: data/interim/amenity_points.csv  (type, name, lat, lon)
Primary schools are added in step 4, from the geocode cache (they only have postcodes)."""
import json, re
import pandas as pd
from config import MRT_CODE_NAMES, MRT_EXITS, HAWKERS, CHAS, PRESCHOOLS, AMENITY_POINTS, RAW, PARKS_GLOB

def features(path):
    return json.load(open(path, encoding="utf-8"))["features"]

def html_attrs(desc):
    """data.gov.sg KML-converted files hide attributes in an HTML table in 'Description'."""
    return dict(re.findall(r"<th>(.*?)</th>\s*<td>(.*?)</td>", desc or ""))

rows = []
for f in features(MRT_EXITS):
    p, (lon, lat) = f["properties"], f["geometry"]["coordinates"][:2]
    name = p["STATION_NA"]
    if name in MRT_CODE_NAMES:                                  # some stations are listed by code, e.g. DT4 = Hume
        name = MRT_CODE_NAMES[name] + " MRT STATION"
    kind = "lrt_exit" if "LRT" in name else "mrt_exit"
    rows.append((kind, name.title(), lat, lon))
for f in features(HAWKERS):
    p, (lon, lat) = f["properties"], f["geometry"]["coordinates"][:2]
    if p.get("STATUS", "").startswith("Existing") or p.get("STATUS") == "Interim Centre":   # drop under construction
        rows.append(("hawker", p["NAME"], lat, lon))
for path, kind, name_key in [(CHAS, "chas_clinic", "HCI_NAME"), (PRESCHOOLS, "preschool", "CENTRE_NAME")]:
    for f in features(path):
        a, (lon, lat) = html_attrs(f["properties"].get("Description")), f["geometry"]["coordinates"][:2]
        rows.append((kind, a.get(name_key, ""), lat, lon))

for path in RAW.glob(PARKS_GLOB):                       # optional: NParks parks
    for f in features(path):
        g, p = f["geometry"], f["properties"]
        ring = g["coordinates"] if g["type"] == "Point" else None
        if ring is None:                                     # polygon -> mean of its vertices
            flat = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
            ring = [sum(c[0] for c in flat) / len(flat), sum(c[1] for c in flat) / len(flat)]
        name = p.get("NAME") or html_attrs(p.get("Description")).get("NAME", "")
        rows.append(("park", name, ring[1], ring[0]))

pts = pd.DataFrame(rows, columns=["type", "name", "lat", "lon"])
bad = ~pts["lat"].between(1.15, 1.48) | ~pts["lon"].between(103.6, 104.1)     # outside Singapore = data error
pts = pts[~bad]
# Same centre listed more than once (same type, location and name) -> keep one. Different businesses that share a
# building (e.g. two clinics in one mall) have different names and are kept.
name_key = pts["name"].fillna("").str.lower().str.replace(r"[^a-z0-9]", "", regex=True).str[:30]
repeat = pts.assign(_k=name_key).duplicated(["type", "lat", "lon", "_k"])
pts = pts[~repeat]
print(f"(removed {repeat.sum()} repeat listings of the same centre)")
pts.to_csv(AMENITY_POINTS, index=False)
print(pts["type"].value_counts().to_string(), f"\n(dropped {bad.sum()} points outside Singapore)\n-> {AMENITY_POINTS.name}")

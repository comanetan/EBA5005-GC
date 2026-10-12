# -*- coding: utf-8 -*-
"""
Consolidates this pipeline's own OneMap-geocoded results into the SAME schema as the
team's shared data/interim/geocode_cache.csv (comanetan/EBA5005-GC, main branch):

    key, kind, lat, lon, postal, matched_blk, onemap_address, match_quality

Kept as a SEPARATE file (geocode_cache_optimisation.csv), not merged into their
geocode_cache.csv directly -- different author, and this pipeline's own geocoding
captured less detail per lookup than theirs (see caveats below), so merging would
silently degrade some of their already-richer rows.

Honest caveats, not papered over:
  - This pipeline's own geocode_query() (geocode_robust.py) only ever kept lat/lon/
    status from each OneMap response -- it discarded postal/address/block-number
    detail at the time. Backfilling those properly means re-querying OneMap for
    every already-geocoded row (13,000+ for blocks alone), which was NOT done here
    (that's hours of API calls for a schema-cosmetics change, not a new result) --
    `postal` is filled only where the key/query already WAS a postal code (schools/
    supermarkets/childcare, geocoded by postal code to begin with); `matched_blk`
    and `onemap_address` are left blank throughout.
  - `match_quality`: this pipeline's own status field is coarser than theirs
    (OK / NOT_FOUND / HTTP_xxx / ERROR_xxx, not exact/postcode/none/manual) --
    mapped as OK -> "exact" (approximate: most queries here were already a specific
    postal code or an exact block+street address, so "exact" is the closest honest
    label, not a literal re-derivation of OneMap's own match confidence) and
    everything else -> "none".
  - New `kind` values not in the team's vocabulary (block/supermarket/school/
    polyclinic): `flood_prone`, `job_node`, `childcare` -- extensions, not a
    redefinition of their existing kinds.
"""
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # .../Project, portable across machines
PROC = os.path.join(ROOT, "data", "processed")
OUT = os.path.join(HERE, "data")

COLUMNS = ["key", "kind", "lat", "lon", "postal", "matched_blk", "onemap_address", "match_quality"]


def _quality(status_series):
    return status_series.map(lambda s: "exact" if s == "OK" else "none")


def _from_postal_file(path, kind, prefix):
    d = pd.read_csv(path)
    out = pd.DataFrame({
        "key": prefix + " " + d["postal_code"].astype(str).str.zfill(6),
        "kind": kind, "lat": d["latitude"], "lon": d["longitude"],
        "postal": d["postal_code"].astype(str).str.zfill(6),
        "matched_blk": "", "onemap_address": "", "match_quality": _quality(d["status"]),
    })
    return out[out["lat"].notna()]


def build():
    pieces = []

    # blocks: key = query (block + street), matching the team's own block key format exactly
    blocks = pd.read_csv(os.path.join(PROC, "hdb_blocks_geocoded.csv"))
    pieces.append(pd.DataFrame({
        "key": blocks["query"], "kind": "block", "lat": blocks["latitude"], "lon": blocks["longitude"],
        "postal": "", "matched_blk": "", "onemap_address": "", "match_quality": _quality(blocks["status"]),
    })[lambda d: d["lat"].notna()])

    # postal-code-keyed entities, same "{PREFIX} {postal}" key convention as the team's cache
    pieces.append(_from_postal_file(os.path.join(PROC, "schools_geocoded_v2.csv"), "school", "SCH"))
    pieces.append(_from_postal_file(os.path.join(PROC, "supermarkets_geocoded_v2.csv"), "supermarket", "SUP"))
    pieces.append(_from_postal_file(os.path.join(PROC, "childcare_postal_geocoded_v2.csv"), "childcare", "CHC"))

    # this pipeline's own new kinds (job nodes, flood-prone locations) -- not in the team's
    # vocabulary at all, extended rather than shoe-horned into an existing kind
    jn = pd.read_csv(os.path.join(OUT, "job_nodes.csv"))
    pieces.append(pd.DataFrame({
        "key": "JOB " + jn["node"], "kind": "job_node", "lat": jn["lat"], "lon": jn["lon"],
        "postal": "", "matched_blk": "", "onemap_address": jn["query"], "match_quality": _quality(jn["status"]),
    })[lambda d: d["lat"].notna()])

    fp = pd.read_csv(os.path.join(OUT, "flood_prone_geocoded.csv"))
    pieces.append(pd.DataFrame({
        "key": "FLOOD " + fp.index.astype(str).str.zfill(2), "kind": "flood_prone",
        "lat": fp["latitude"], "lon": fp["longitude"], "postal": "", "matched_blk": "",
        "onemap_address": fp["location"], "match_quality": _quality(fp["status"]),
    })[lambda d: d["lat"].notna()])

    cache = pd.concat(pieces, ignore_index=True)[COLUMNS]
    out_path = os.path.join(OUT, "geocode_cache_optimisation.csv")
    cache.to_csv(out_path, index=False)
    return cache, out_path


if __name__ == "__main__":
    cache, out_path = build()
    print(f"{len(cache)} rows -> {out_path}")
    print(cache["kind"].value_counts())
    print(cache["match_quality"].value_counts())

# daniel_add — geocoded/derived interim data, not already in `data/interim/`

Same category as this folder's existing `geocode_cache.csv` (real OneMap/API time spent,
kept out of `.gitignore`'s `data/interim/*` rule deliberately). Note `geocode_cache.csv`
already has independently-geocoded `school`/`supermarket`/`polyclinic`/`block` entries —
not cross-checked against the equivalents below yet (different schema: single cache file
with a `kind` column vs. one file per entity type here). Flagging as a possible future
consolidation, not done now.

| File | What it is | How it was produced |
|---|---|---|
| `hdb_carpark_latlon.csv` | `../../raw/daniel_add/HDBCarparkInformation.csv`'s SVY21 `x_coord`/`y_coord` reprojected to WGS84 lat/lon | `pyproj.Transformer.from_crs('EPSG:3414','EPSG:4326')` |
| `childcare_postal_geocoded_v2.csv` | `../../raw/daniel_add/Childcare_Kindergarten_Centres_ECDA.csv` geocoded by postal code | OneMap search API |
| `flood_prone_geocoded.csv` | PUB's 36 named flood-prone locations, geocoded | OneMap search API, free-text location names cleaned to their first road segment |
| `expressway_points.csv` | 20,831 sampled vertices along every Singapore motorway/trunk/motorway_link/trunk_link way | OSM via `osmnx.features_from_place('Singapore', {'highway': [...]})` |
| `job_nodes.csv` | 5 decentralised employment nodes (Raffles Place, Jurong East, Punggol Coast, one-north, Woodlands Regional Centre) | OneMap search API |

Full pipeline + how these are used: `optimisation/block_accessibility.py`,
`optimisation/multigen_profiles.py`.

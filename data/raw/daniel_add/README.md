# daniel_add — raw sources the Optimisation pipeline needed, not already in `data/raw/`

Added 2026-10-12 while reconciling the `optimisation` branch's pipeline against this
repo's shared `data/raw/` and `data/interim/` (see `optimisation/README.md`). Each file
below was checked against the existing `data/raw/` first — these are genuinely new, not
duplicates under a different name. (Files that WERE duplicates — e.g. the resale
transactions CSV, `HDBPropertyInformation.csv`, school/CHAS/hawker/park/supermarket
sources — were left alone and the `optimisation` branch now reads this repo's existing
copies instead of its own, including switching to the more complete resale CSV here:
241,921 rows vs. the 236,387 the optimisation branch had been using.)

| File | Used for | Source |
|---|---|---|
| `HDBCarparkInformation.csv` | Carpark distance / night-parking access per block | data.gov.sg dataset `d_23f946fa557947f93a8043bbef41dd09` |
| `PUB_Flood_Prone_Areas_2025.pdf` | Flood-prone-area flag (36 named locations, geocoded — see `data/interim/daniel_add/flood_prone_geocoded.csv`) | PUB, "List of Flood Prone Areas in Singapore (Updated as of 2 Apr 2025)" |
| `LTA_Bus_Stop.geojson` | Bus-stop count within 400m (a hedonic control feature) | LTA DataMall |
| `MasterPlan2019_Rail_Station_Layer.geojson` | Planned-but-not-yet-operating rail stations (`dist_planned_rail_km`) | URA Master Plan 2019 |
| `Community_Clubs.geojson` | Distance to nearest community club (computed, not currently priced) | data.gov.sg |
| `Childcare_Kindergarten_Centres_ECDA.csv` | Childcare/preschool distance (geocoded by postal code — see `data/interim/daniel_add/childcare_postal_geocoded_v2.csv`) | ECDA. Note: this repo's `data/raw/PreSchoolsLocation.geojson` looks like the same underlying ECDA dataset in a different, pre-geocoded format — not reconciled yet, see Daniel if useful to consolidate. |
| `Vaccination_Polyclinics.geojson` | Polyclinic distance (already geocoded, unlike `data/raw/polyclinics.csv` which has no coordinates yet) | MOH |

Full pipeline + how these are used: `optimisation/block_accessibility.py`.

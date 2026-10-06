# Geocoding and feature validation report

| Check | Result | Detail |
|---|---|---|
| Every resale block has coordinates | PASS |  |
| All coordinates inside Singapore | PASS |  |
| Block match quality | NOTE | exact 9,749, manual 6 |
| No unresolved fallback / none matches | PASS |  |
| No two blocks share identical coordinates | PASS |  |
| School postcodes geocoded | NOTE | 182/182; 0 returned a different postcode (nearest match used) |
| Polyclinic postcodes geocoded | NOTE | 27/27; 0 returned a different postcode (nearest match used) |
| Supermarket postcodes geocoded | NOTE | 421/444; 23 returned a different postcode (nearest match used) |
| Amenity points | NOTE | preschool 1,928, chas_clinic 1,189, mrt_exit 541, park 462, hawker 123, lrt_exit 72; 437 share a location with another of the same type (different businesses in one building, kept; repeat listings were removed in step 3) |
| Amenity points inside Singapore | PASS |  |
| No negative distances | PASS |  |
| Nearest MRT within 5 km for every block | PASS |  |
| Blocks > 2 km from an MRT | NOTE | 89 (Sengkang 68, Serangoon 18, Pasir Ris 3). Mostly LRT-served areas: decide whether LRT counts for the MRT band |
| Blocks > 4 km from their town's centre | NOTE | 10: CHANGI VILLAGE RD, EMPRESS RD, FARRER RD, QUEEN'S RD (checked: genuine outlying parts of Bukit Timah and Pasir Ris towns) |
| Blocks matched to HDB Property Information | NOTE | 9,754/9,755 |
| No rows lost from the clean file | PASS |  |
| Every in-scope sale has a profile | PASS |  |
| MRT distance at sale is never shorter than today's | PASS |  |
| Sales whose nearest MRT opened after the sale | NOTE | 3.3% (their MRT distance at time of sale is longer than today's) |
| Missing location features (in-scope sales) | NOTE | none |
| Profile IDs unique | PASS |  |
| Profiles with 5+ sales in the last 12 months | NOTE | 55% of 1,927 profiles, covering 95% of recent sales |
| Profiles with 10+ sales in the last 12 months | NOTE | 37% of 1,927 profiles, covering 86% of recent sales |

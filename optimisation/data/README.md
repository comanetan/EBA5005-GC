# Adapter outputs (generated data, kept here deliberately — small, high-value results)

Everything else this pipeline generates (`housing_profiles_v2_full.csv`,
`block_accessibility.csv`, the walk-network graphs, geocoding caches, etc.) is NOT
committed — see the main `optimisation/README.md`. These files are the exception: small
(under 2.5MB total), and they're the actual result of integrating the other leads' real
models, not just regenerable intermediate output.

| File | What it is | Built by |
|---|---|---|
| `pricing_today.csv`, `availability.csv` | Real pricing/availability, crosswalked from the Pricing & Availability Lead's `main` branch. 96.2% profile coverage (681/708) | `pricing_availability_adapter.py` |
| `*_provenance.csv` | Same as above, plus `n_source_profiles` (how many of their profiles were aggregated into each row) | same |
| `price_forecast_live.csv` | Real 4-ROOM forecast (all 26 towns) blended with the existing stub for every other flat type | `forecasting_adapter.py` |
| `price_forecast_4room_provenance.csv` | The 4-ROOM real rows only, before merging into the blend above | same |
| `geocode_cache_optimisation.csv` | This pipeline's own OneMap-geocoded results, reformatted to match `data/interim/geocode_cache.csv`'s schema (key, kind, lat, lon, postal, matched_blk, onemap_address, match_quality) | `build_geocode_cache.py` |
| `external_handovers/` | Point-in-time snapshots of the other leads' real output files this adapter was built against (`main`'s `outputs/prices_today.csv` etc., `forecasting`'s `outputs/price_paths.csv`). **Re-fetch and re-run the adapters if their branches have moved on** — these are not auto-refreshing. |

See `OPTIMISER_METHODOLOGY_REPORT.md` §10 for the full crosswalk methodology, the two
correctness issues found and fixed while building this (look-ahead-bias gating,
hedonic-basis mismatch), and what's still needed from the other leads.

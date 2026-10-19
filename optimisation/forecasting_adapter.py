# -*- coding: utf-8 -*-
"""
Adapter: Forecasting Lead's real deliverable (comanetan/EBA5005-GC, forecasting branch,
snapshotted into data/external_handovers/) -> this pipeline's price_forecast.csv schema
(town, flat_type, horizon_months, growth_factor, growth_factor_lower, growth_factor_upper).

2026-10-19 UPDATE (OPTIMISER_METHODOLOGY_REPORT.md Sec. 23): superseded by the "multitype"
handover (MULTITYPE_HANDOVER.md on their branch) -- real coverage is now 3 ROOM, 4 ROOM and
5 ROOM (fifteen regional flat-type series), all 26 towns, up from 4-ROOM-only. This
pipeline's own flat_type universe was aligned to match (2 ROOM, EXECUTIVE dropped
end-to-end -- see housing_profiles_v2.py, backtest_v2.py, backtest.py), so after this
change every surviving flat type has a real forecast; only 1 ROOM (2 profiles, negligible,
not asked to be removed) and MULTI-GENERATION (already excluded from profiles entirely)
remain stub.

Their evidence/multitype/price_forecast.csv is ALREADY pre-aggregated to exactly this
pipeline's (town, flat_type, horizon_months) grain -- no per-profile crosswalk needed this
time (unlike the old 4-ROOM-only handover, which was profile-level and needed
profile_crosswalk.py to bring down to this grain). This REPLACES the old crosswalk-based
approach for 3/4/5 ROOM outright.

Per MULTITYPE_HANDOVER.md's own explicit integration warning: "In the tested optimiser
commit, fcast_override alone does not recompute deterministic price_upper" -- confirmed in
recommender_v2.py: assemble() computes price_upper from load_inputs()'s own fcast BEFORE
_prepare() ever sees fcast_override, so fcast_override only reaches the chance-constraint
branch, never the deterministic budget filter. The correct integration point is therefore
exactly what this adapter already does: write the real values into price_forecast_live.csv
on disk, so load_inputs() -> assemble() picks them up from the start. No recommender_v2.py
change was needed.

This writes ONLY price_forecast_live.csv (the live/production path -- see
recommender_v2.py::load_inputs()'s own live=True/False split). price_forecast.csv (the
backtest's stub-only, time-invariant file) is deliberately left untouched: the Forecasting
Lead's multitype model has a single current snapshot (base month 2026-09), not dated
as-of-cutoff snapshots the way their earlier 4-ROOM "final" evidence did (evidence/final/
as_of/<date>/...) -- using it for historical cutoffs would leak 2026-09 model knowledge
into e.g. a 2023-01 backtest, exactly the look-ahead bias load_inputs()'s live=False path
exists to prevent. Net effect: this change improves the LIVE recommender's price bound
immediately; the walk-forward backtest's reliability number is unaffected by it (the
backtest change, if any, comes entirely from the flat-type-scope alignment, not this file).
"""
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
EXT = os.path.join(DATA, "external_handovers")

REAL_FLAT_TYPES = ["3 ROOM", "4 ROOM", "5 ROOM"]


def build_price_forecast(write=True):
    meta = json.load(open(os.path.join(EXT, "price_paths_metadata_multitype.json")))
    real = pd.read_csv(os.path.join(EXT, "price_forecast_multitype.csv"))
    assert sorted(real["flat_type"].unique()) == sorted(REAL_FLAT_TYPES), \
        f"multitype handover's flat_type coverage changed: {sorted(real['flat_type'].unique())}"
    assert real["town"].nunique() == 26, f"multitype handover covers {real['town'].nunique()}/26 towns"

    real = real.copy()
    real["_source"] = ("REAL (Forecasting Lead, regional ARIMA(0,1,1)+drift, validation-selected) -- "
                        f"3/4/5 ROOM, base month {meta['base_price_month']}, model {meta['model_version']}")

    stub = pd.read_csv(os.path.join(DATA, "price_forecast.csv"))
    kept = stub[~stub["flat_type"].isin(REAL_FLAT_TYPES)]
    combined = pd.concat([kept, real[["town", "flat_type", "horizon_months", "growth_factor",
                                      "growth_factor_lower", "growth_factor_upper", "_source"]]],
                         ignore_index=True)

    if write:
        combined.to_csv(os.path.join(DATA, "price_forecast_live.csv"), index=False)
        real.to_csv(os.path.join(DATA, "price_forecast_multitype_provenance.csv"), index=False)
    return combined, real


if __name__ == "__main__":
    combined, real = build_price_forecast()
    n_towns = real["town"].nunique()
    remaining_stub = sorted(combined.loc[~combined["flat_type"].isin(REAL_FLAT_TYPES), "flat_type"].unique())
    print(f"3/4/5-ROOM real coverage: {n_towns}/26 towns, {len(real)} rows (2 horizons x towns x 3 types)")
    print(f"Remaining stub-only flat types in price_forecast_live.csv: {remaining_stub}")
    for h in (6, 12):
        med = real[real.horizon_months == h]["growth_factor"].median()
        print(f"  horizon={h}mo: median growth_factor {med:.4f} (stub was flat 1.00)")
    print(combined[combined["flat_type"].isin(REAL_FLAT_TYPES)].head(6).to_string(index=False))

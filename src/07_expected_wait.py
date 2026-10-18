"""Step 7: survival model (Cox, stratified by block age) -> expected wait for a matching flat, per profile.
    python src/07_expected_wait.py             # latest complete month -> outputs/expected_wait.csv (hand-over file)
    python src/07_expected_wait.py 2023-06     # backtest -> outputs/backtest/2023-06/expected_wait.csv
Waits are calibrated by flat type and blended with each profile's own recent sales (src/homefit/survival.py).
Also writes the Optimisation Lead's availability.csv (his profile IDs) to <out>/optimisation/.
Notebook 03 documents the analysis behind this model; this script is the production version."""
import sys, time, warnings
warnings.filterwarnings("ignore")
import numpy as np
import config as C
from homefit import survival as S, common as K

t0 = time.time()
latest = K.latest_complete_month()
as_of = sys.argv[1] if len(sys.argv) > 1 else latest
out_dir = C.OUTPUTS if as_of == latest else C.OUTPUTS / "backtest" / as_of
(out_dir / "optimisation").mkdir(parents=True, exist_ok=True)

if as_of == latest:
    ev = S.evaluate(as_of, test_from_year=2023)
    print(f"C-index · train (spells before 2023): {ev['c_index_train']:.3f} · test (2023+): {ev['c_index_test']:.3f}")
cph = S.fit(as_of)
waits, detail = S.profile_waits(cph, as_of)
waits.to_csv(out_dir / "expected_wait.csv", index=False)
print("Calibration (actual / model sales, last 12 months):",
      detail.groupby("flat_type")["calib"].first().round(2).to_dict())

# Optimisation Lead's schema (optimisation/INTERFACE_SPEC.md): P(a matching flat comes up within h months) from the
# profile's sale rate, treating sales as a Poisson process (the same assumption behind wait = 12 / rate).
w, d = S.profile_waits(cph, as_of, scheme="optimisation")
rate = d.set_index("profile_id")["sales_per_year"].reindex(w["profile_id"]).to_numpy() / 12
w = w.rename(columns={"wait_months": "expected_wait_months"})
w["survival_prob_6m"] = (1 - np.exp(-6 * rate)).round(3)
w["survival_prob_12m"] = (1 - np.exp(-12 * rate)).round(3)
w["hazard_ratio"] = np.nan
w[["profile_id", "expected_wait_months", "survival_prob_6m", "survival_prob_12m", "hazard_ratio", "scarce"]].to_csv(
    out_dir / "optimisation" / "availability.csv", index=False)
print(f"-> {out_dir.relative_to(C.ROOT)}/expected_wait.csv: {len(waits):,} profiles as of {as_of}, "
      f"{waits['scarce'].sum()} scarce · optimisation/availability.csv: {len(w):,} profiles · {time.time() - t0:.0f}s")

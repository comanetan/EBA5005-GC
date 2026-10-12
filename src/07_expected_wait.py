"""Step 7: survival model (Cox, stratified by block age) -> expected wait for a matching flat, per profile.
    python src/07_expected_wait.py             # latest complete month -> outputs/expected_wait.csv (hand-over file)
    python src/07_expected_wait.py 2023-06     # backtest -> outputs/backtest/2023-06/expected_wait.csv
Notebook 03 documents the analysis behind this model; this script is the production version."""
import sys, time, warnings
warnings.filterwarnings("ignore")
import config as C
from homefit import survival as S, common as K

t0 = time.time()
latest = K.latest_complete_month()
as_of = sys.argv[1] if len(sys.argv) > 1 else latest
out_dir = C.OUTPUTS if as_of == latest else C.OUTPUTS / "backtest" / as_of
out_dir.mkdir(parents=True, exist_ok=True)

if as_of == latest:
    ev = S.evaluate(as_of, test_from_year=2023)
    print(f"C-index · train (spells before 2023): {ev['c_index_train']:.3f} · test (2023+): {ev['c_index_test']:.3f}")
cph = S.fit(as_of)
waits, _ = S.profile_waits(cph, as_of)
waits.to_csv(out_dir / "expected_wait.csv", index=False)
print(f"-> {out_dir.relative_to(C.ROOT)}/expected_wait.csv: {len(waits):,} profiles as of {as_of}, "
      f"{waits['scarce'].sum()} scarce (capped at 120 months) · {time.time() - t0:.0f}s")

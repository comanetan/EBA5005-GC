"""Step 6: hedonic model (LightGBM) -> profile prices.
    python src/06_hedonic_prices.py            # latest complete month -> outputs/prices_today.csv (hand-over file)
    python src/06_hedonic_prices.py 2023-06    # backtest: as of a past month -> outputs/backtest/2023-06/prices.csv
Also writes the hold-out validation (20% of blocks never seen in training) to docs/hedonic_validation.csv."""
import sys, time, warnings
warnings.filterwarnings("ignore")
import config as C
from homefit import hedonic as H, common as K

t0 = time.time()
latest = K.latest_complete_month()
as_of = sys.argv[1] if len(sys.argv) > 1 else latest
out_dir = C.OUTPUTS if as_of == latest else C.OUTPUTS / "backtest" / as_of
out_dir.mkdir(parents=True, exist_ok=True)

if as_of == latest:
    res, _, _ = H.evaluate(as_of)
    res.round(4).to_csv(C.ROOT / "docs" / "hedonic_validation.csv")
    print("Hold-out on unseen blocks:\n" + res.round(4).to_string())
model = H.fit(as_of)
prices, _ = H.price_profiles(model, as_of)
name = "prices_today.csv" if as_of == latest else "prices.csv"
prices.to_csv(out_dir / name, index=False)
if as_of == latest:
    model.save_model(str(C.PROCESSED / "hedonic_model.txt"))
print(f"-> {out_dir.relative_to(C.ROOT)}/{name}: {len(prices):,} profiles priced as of {as_of} "
      f"({model.rounds_} trees, {time.time() - t0:.0f}s)")

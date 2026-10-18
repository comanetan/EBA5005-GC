"""Step 6: hedonic model (LightGBM) -> profile prices.
    python src/06_hedonic_prices.py            # latest complete month -> outputs/prices_today.csv (hand-over file)
    python src/06_hedonic_prices.py 2023-06    # backtest: as of a past month -> outputs/backtest/2023-06/prices.csv
Also writes the hold-out validation (20% of blocks never seen in training) to docs/hedonic_validation.csv, and the same
prices on the Optimisation Lead's profile IDs to <out>/optimisation/pricing_today.csv."""
import sys, time, warnings
warnings.filterwarnings("ignore")
import pandas as pd
import config as C
from homefit import hedonic as H, common as K

t0 = time.time()
latest = K.latest_complete_month()
as_of = sys.argv[1] if len(sys.argv) > 1 else latest
out_dir = C.OUTPUTS if as_of == latest else C.OUTPUTS / "backtest" / as_of
(out_dir / "optimisation").mkdir(parents=True, exist_ok=True)

val_path = C.ROOT / "docs" / "hedonic_validation.csv"
if as_of == latest:
    res, _, _ = H.evaluate(as_of)
    res.round(4).to_csv(val_path)
    print("Hold-out on unseen blocks:\n" + res.round(4).to_string())
model = H.fit(as_of)
prices, _ = H.price_profiles(model, as_of)
name = "prices_today.csv" if as_of == latest else "prices.csv"
prices.to_csv(out_dir / name, index=False)
if as_of == latest:
    model.save_model(str(C.PROCESSED / "hedonic_model.txt"))

# Optimisation Lead's profile IDs (town x flat type x storey x MRT, no lease band), schema from optimisation/INTERFACE_SPEC.md.
# price_today_se = typical error of a single-flat prediction on unseen blocks (hold-out RMSE of log price) x price.
rmse = float(pd.read_csv(val_path, index_col=0).loc["lightgbm", "RMSE_log"])
opt, _ = H.price_profiles(model, as_of, scheme="optimisation")
opt = opt.rename(columns={"price": "price_today"})
opt["price_today_se"] = (opt["price_today"] * rmse).round(-2)
opt[["profile_id", "price_today", "price_today_se", "price_low", "price_high"]].to_csv(
    out_dir / "optimisation" / "pricing_today.csv", index=False)
print(f"-> {out_dir.relative_to(C.ROOT)}/{name}: {len(prices):,} profiles priced as of {as_of} "
      f"({model.rounds_} trees); optimisation/pricing_today.csv: {len(opt):,} profiles · {time.time() - t0:.0f}s")

# Model validation: pricing and availability (as of Sep 2026)

Produced by `src/06_hedonic_prices.py`, `src/07_expected_wait.py` and `notebooks/04_hedonic.ipynb`. Code: `src/homefit/`.
Data: 241,920 HDB resale sales, Jan 2017 – Oct 2026; Oct 2026 is partial, so models use sales up to Sep 2026.

## 1 · Profiles (`outputs/profiles.csv`)
| Item | Value |
|---|---|
| Definition | town × flat type × lease band × MRT band × storey band, for flats that **exist today** (blocks past their 5-year MOP) |
| Profiles | 1,828 (from 9,746 blocks; 41,842 block × flat type × storey band rows) |
| With 5+ sales in the last 12 months | 1,052 (58%), covering 95% of recent sales |
| With no sale in the last 12 months | 275 (mostly Executive and 2-room); priced by the model |
| Change from the old list (built from past sales) | 246 profiles that no longer exist removed (leases have aged into a lower band, or new MRT stations moved blocks into a nearer band); 147 that exist today added |

## 2 · Hedonic price model (`outputs/prices_today.csv`)
LightGBM on log price; monotone in floor area, remaining lease and storey; MRT distance as at the sale date.

**Hold-out: 20% of blocks never seen in training** (193,708 training sales, 47,565 test sales in 1,942 blocks)

| Model | MAPE | Median APE | Within 10% | R² (log price) | MAPE, last 12 months |
|---|---|---|---|---|---|
| LightGBM | **3.90%** | 3.0% | **94.0%** | **0.977** | 3.82% |
| Linear time-dummy regression (benchmark) | 6.63% | 5.4% | 78.0% | 0.937 | 6.56% |

- Error is similar across flat types (MAPE 3.7–4.3%). The hardest towns are older central estates (Geylang, Queenstown, Bukit Merah: about 5.5%), where renovation and unit condition vary most.
- SHAP: the MRT effect averages +4.9% for <500m and −4.6% for >1km, relative to the average flat. Market timing, flat type, floor area and town carry most of the explanatory weight.

**Profile prices against what buyers actually paid** (1,052 profiles with 5+ sales in the last 12 months)

| Check | Value |
|---|---|
| Median absolute difference from the median price paid | 2.0% |
| Profiles within 10% | 98% |
| Correlation | 0.993 |
| Spread within a profile (`price_high` / `price_low`, 90th / 10th percentile across blocks) | median 1.10 |

The largest gaps are in profiles with fewer than 60 years of lease left in central towns, where a few sales of renovated or unusual units move the median.

**Backtest: priced as of Jun 2023 using only data up to then, compared with Jul 2023 – Jun 2024 sales** (1,007 profiles with 5+ sales)

| Method | Median actual / predicted | 10th–90th percentile | Median error | Error after removing market drift |
|---|---|---|---|---|
| Hedonic model | 1.032 | 0.988 – 1.082 | **3.5%** | 2.0% |
| Naive: median of the previous 12 months | 1.050 | 1.000 – 1.104 | 5.1% | 2.1% |

- Prices kept rising after Jun 2023, so both methods under-predict by about 3–5%. Adding that trend is the job of the forecasting layer (`price_paths.csv`).
- The model is the better level estimate.
- Once the drift is removed, the two methods rank profiles about equally well (2.0% against 2.1%). The model's main advantage is that it prices the profiles with no recent sales, which the naive method cannot do.

## 3 · Survival model (`outputs/expected_wait.csv`)
The model is Cox proportional hazards (`lifelines`), estimated at the level of block × flat type. Each spell is the time from one resale to the next. Block age is a stratum, because it violates the proportional-hazards assumption.

| Check | Value |
|---|---|
| Spells | 244,672 |
| Concordance index: train (spells before 2023) / test (2023 onwards) | 0.689 / 0.678 |
| Expected wait for a matching flat, median across profiles | 1.7 months |
| Rank correlation (Spearman) of predicted availability with actual sales in the last 12 months | 0.757 |
| Predicted sales over 12 months against actual | 27,406 against 24,635 (+11%) |
| Scarce profiles (wait capped at 120 months) | 9 |

A profile's wait is computed in three steps:

1. For each block in the profile, find its expected gap between sales (the area under its survival curve up to 120 months).
2. Turn each gap into a sale rate (1 ÷ gap), weighted by the block's share of the profile.
3. Add the rates across blocks and take 1 ÷ the total.

The result is the time until **any** flat in the profile comes up for sale. A 0.689 concordance index is moderate: the model ranks blocks better than chance, but it is not precise for an individual block. Use it to compare profiles, not to promise dates.

## 4 · Backtest readiness
Every function takes `as_of`. When you re-run at a past month:

- only sales up to that month are used
- lease band and MRT band are worked out at that date (only stations open then count)
- only blocks past MOP by then are included

The full chain (profiles → prices → waits) takes about one minute per month: `python src/06_hedonic_prices.py 2023-06 && python src/07_expected_wait.py 2023-06`.

## 5 · Limitations
- Renovation, facing, view and unit condition are not observed. This is the main source of error in older central estates.
- Expected waits assume the pace of resales seen in 2017–2026. A policy change (for example, a shorter MOP or new cooling measures) would shift them.
- Prices are "today" prices as of the latest complete month. Price paths over the buyer's horizon come from the forecasting layer.
- 275 profiles have no recent sales. The model prices them from block features; treat their `price_low`–`price_high` range as the uncertainty.

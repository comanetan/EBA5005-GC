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

## 3 · Availability model (`outputs/expected_wait.csv`)
The model has two parts:

1. A Cox proportional-hazards survival model (`lifelines`), estimated at the level of block × flat type. Each spell is the time from one resale to the next, and block age is a stratum because it violates the proportional-hazards assumption. The model explains what drives turnover: units of that type in the block, block age, the post-2020 market, flat type and region.
2. A calibration and blending step that turns the model into a profile-level wait.

| Check | Value |
|---|---|
| Spells | 244,672 |
| Concordance index: train (spells before 2023) / test (2023 onwards) | 0.689 / 0.678 |
| Expected wait for a matching flat, median across profiles | 1.9 months |
| Scarce profiles (wait capped at 120 months) | 113 of 1,828 |

**Why there is a calibration and blending step (12 Oct → 17 Oct).** The first version took the profile wait straight from the Cox model. Tested out-of-sample (model as of Jun 2023, compared with sales from Jul 2023 to Jun 2024), its total was close (+6%), but that hid large errors that cancelled out by flat type:

| Flat type | 2-room | 3-room | 4-room | 5-room | Executive |
|---|---|---|---|---|---|
| Cox model alone: predicted ÷ actual sales, next 12 months | −36% | −43% | −21% | +41% | +278% |

A plain count of each profile's sales in the previous 12 months also predicted the next 12 months better than the Cox model alone. The production method therefore:

1. **Takes the Cox model's sale rate** for each profile: the sum, over its blocks, of the block's share of the profile ÷ the expected gap between sales.
2. **Calibrates by flat type.** Each flat type is scaled so its total matches its actual sales in the 12 months up to the as-of date. The current factors are 2-room 1.25, 3-room 1.39, 4-room 1.36, 5-room 0.62 and Executive 0.28.
3. **Blends with the profile's own recent sales** (empirical Bayes, Poisson–gamma): rate = (sales in the last 12 months + 0.25 × model rate) ÷ 1.25. Observed sales dominate where there are many; the model fills in for profiles with few. The 0.25 weight was chosen on the Jun 2023 backtest from {0.25, 0.5, 1, 2} combined with 1, 2 or 3 years of history.
4. **Converts to a wait:** wait = 12 ÷ rate months, capped at 120 months, with capped profiles flagged `scarce`.

**Out-of-sample results** (as of Jun 2023, scored on Jul 2023 – Jun 2024 sales; all inputs use data up to Jun 2023 only):

| Method | Rank correlation | Mean abs. error (sales per profile) | Total error |
|---|---|---|---|
| Cox model alone | 0.752 | 9.9 | +11% |
| Cox, calibrated by flat type | 0.831 | 7.3 | +4% |
| Naive: last 12 months' count | 0.912 | 4.1 | +4% |
| **Production: calibrated Cox + recent sales** | **0.916** | **4.0** | **+4%** |

The same method on the Optimisation Lead's profiles had a rank correlation of 0.951. On average the model predicted that 86.5% of those profiles would see at least one sale within 12 months; 86.2% actually did. Of the profiles flagged scarce, 84% had no sale in the following year.

**How to describe this in the report.** The survival model is the explanatory layer: it shows what drives availability and gives a prior for profiles with few sales. On its own it ranks profiles worse than recent sales history does, and saying so is part of the evaluation. The production estimate combines the two and beats both.

## 3b · Files keyed to the Optimisation Lead's profiles (`outputs/optimisation/`)
The Optimisation Lead's profile is town × flat type × storey band × MRT band, with no lease band:

- **Storey bands:** Low 1–6, Mid 7–15, High 16+, by the lower floor of the storey range.
- **MRT bands:** Near <400m, Mid 400–800m, Far >800m.
- **ID format:** `TAMPINES::4ROOM::Mid::Near`.

Steps 6 and 7 price and time these profiles **directly**, using the same models, rather than crosswalking the 5-part IDs. Lease therefore enters each profile's price through its actual mix of blocks, weighted by units, rather than through a median across lease bands. There are 952 profiles in his format today. 713 of them have 3+ sales in the last 12 months, against his 712, so his list should be fully covered; any ID missing from these files is a boundary case where his distance data and ours differ.

| File | Columns |
|---|---|
| `pricing_today.csv` | profile_id, price_today, price_today_se, price_low, price_high |
| `availability.csv` | profile_id, expected_wait_months, survival_prob_6m, survival_prob_12m, hazard_ratio (blank), scarce |

- **`price_today_se`** = price × 0.052, the hold-out RMSE of log price on unseen blocks. It is the typical error of a single-flat prediction, not a standard error of the profile mean.
- **`survival_prob_h`** = P(at least one matching flat comes up within h months) = 1 − exp(−h × rate ÷ 12), treating sales as a Poisson process (the same assumption behind wait = 12 ÷ rate).
- **Backtest versions** are written to `outputs/backtest/<as_of>/optimisation/`.

## 4 · Backtest readiness
Every function takes `as_of`. When you re-run at a past month:

- only sales up to that month are used
- lease band and MRT band are worked out at that date (only stations open then count)
- only blocks past MOP by then are included

The full chain (profiles → prices → waits) takes about one minute per month: `python src/06_hedonic_prices.py 2023-06 && python src/07_expected_wait.py 2023-06`.

## 5 · Limitations
- Renovation, facing, view and unit condition are not observed. This is the main source of error in older central estates.
- Expected waits are calibrated to the last 12 months' pace of resales. A policy change (for example, a shorter MOP or new cooling measures) would shift them.
- Prices are "today" prices as of the latest complete month. Price paths over the buyer's horizon come from the forecasting layer.
- 275 profiles have no recent sales. The model prices them from block features; treat their `price_low`–`price_high` range as the uncertainty.

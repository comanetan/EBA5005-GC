# Resale data validation report

Source: `ResaleflatpricesbasedonregistrationdatefromJan2017onwards.csv`  
Rows: 241,920 · Months: 2017-01 to 2026-10 · Towns: 26

| Check | Result | Detail |
|---|---|---|
| Columns as expected | PASS |  |
| No missing values | PASS |  |
| Month format YYYY-MM | PASS |  |
| Remaining lease parsed for every row | PASS |  |
| Storey range parsed for every row | PASS |  |
| Remaining lease vs lease start + 99 yrs | NOTE | 100.00% within 1.5 yrs (HDB counts from registration date); 1 row(s) differ by > 2 yrs and are flagged |
| Prices positive and plausible (S$50k-S$3m) | PASS |  |
| Floor areas plausible (20-400 sqm) | PASS |  |
| Lease start between 1960 and sale year | PASS |  |
| Storey 1-60 | PASS |  |
| Every flat model mapped to a family | PASS |  |
| Every town mapped to a region | PASS |  |
| Exact duplicate rows | NOTE | 318 repeats (635 rows involved). Kept: without a unit number they may be different flats sold in the same month at the same price |
| Latest month | NOTE | 2026-10: 212 sales vs typical 2,084 -> flagged partial, excluded from in_scope |
| Price-per-sqm outliers (> 5 robust SD within flat type x year) | NOTE | 143 rows flagged for review, not removed. Most common flat models among them: {'Model A': 62, 'Premium Apartment': 36, 'Type S2': 22} |
| In scope for profiles and the index | NOTE | 241,407 of 241,920 rows. Excluded: 178 1-room/multi-generation, 123 Terrace, 212 partial-month |
| No rows lost | PASS |  |

Output: `data/interim/resale_clean.csv` with flags `in_scope`, `partial_month`, `is_exact_dup`, `lease_mismatch`, `psm_outlier`.

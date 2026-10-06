"""Step 1b (offline): clean and validate the raw resale data.
Raw file is never edited. Output: data/interim/resale_clean.csv (all rows kept, with flags) + docs/validation_report.md

Rows are FLAGGED, not deleted, so every exclusion is visible and reversible:
  in_scope        False for 1-room, multi-generation and Terrace units, and the partial latest month
  partial_month   True for the latest month if it is still being filled (registration data arrives daily)
  is_exact_dup    True for rows identical to another row. No unit number exists, so these may be genuinely
                  different flats (same block, storey band, size and price, same month); kept, but flagged
  lease_mismatch  True where remaining lease disagrees with lease start + 99 years by more than 2 years
  psm_outlier     True where price per sqm is > 5 robust SDs from its flat type x year median (review, don't drop)
Validation checks stop the script with a clear message if the raw data breaks an assumption."""
import pandas as pd, numpy as np
import config as C

EXPECTED_COLS = ["month", "town", "flat_type", "block", "street_name", "storey_range", "floor_area_sqm",
                 "flat_model", "lease_commence_date", "remaining_lease", "resale_price"]
checks = []                                            # (check, result, detail) for the report

def check(name, ok, detail=""):
    checks.append((name, "PASS" if ok else "FAIL", "" if ok else detail))
    if not ok:
        raise SystemExit(f"VALIDATION FAILED: {name}. {detail}")

def note(name, detail):
    checks.append((name, "NOTE", detail))

df = pd.read_csv(C.RESALE, dtype={"block": str})
n0 = len(df)

# ---------- 1. Structure
check("Columns as expected", list(df.columns) == EXPECTED_COLS, f"got {list(df.columns)}")
check("No missing values", df.isna().sum().sum() == 0, str(df.isna().sum()[df.isna().sum() > 0].to_dict()))
check("Month format YYYY-MM", df["month"].str.fullmatch(r"\d{4}-\d{2}").all())

# ---------- 2. Standardise text
for c in ["town", "flat_type", "block", "street_name", "storey_range"]:
    df[c] = df[c].str.strip().str.upper().str.replace(r"\s+", " ", regex=True)
df["flat_model"] = df["flat_model"].str.strip()
df["address"] = df["block"] + " " + df["street_name"]

# ---------- 3. Parse lease and storey
yrs = df["remaining_lease"].str.extract(r"(\d+)\s*year").astype(float)[0]
mths = df["remaining_lease"].str.extract(r"(\d+)\s*month").astype(float)[0].fillna(0)
df["remaining_lease_yrs"] = (yrs + mths / 12).round(3)
check("Remaining lease parsed for every row", df["remaining_lease_yrs"].notna().all())
lo_hi = df["storey_range"].str.extract(r"(\d+)\s*TO\s*(\d+)").astype(float)
check("Storey range parsed for every row", lo_hi.notna().all().all())
df["storey_lo"], df["storey_hi"] = lo_hi[0], lo_hi[1]
df["storey_mid"] = lo_hi.mean(1)

sale_t = df["month"].str[:4].astype(int) + (df["month"].str[5:7].astype(int) - 1) / 12
df["flat_age_yrs"] = (sale_t - df["lease_commence_date"]).round(2)
gap = df["remaining_lease_yrs"] - (99 - df["flat_age_yrs"])
df["lease_mismatch"] = gap.abs() > 2
note("Remaining lease vs lease start + 99 yrs",
     f"{(gap.abs() <= 1.5).mean():.2%} within 1.5 yrs (HDB counts from registration date); "
     f"{df['lease_mismatch'].sum()} row(s) differ by > 2 yrs and are flagged")

# ---------- 4. Ranges
check("Prices positive and plausible (S$50k-S$3m)", df["resale_price"].between(5e4, 3e6).all(),
      f"range {df['resale_price'].min():,.0f}-{df['resale_price'].max():,.0f}")
check("Floor areas plausible (20-400 sqm)", df["floor_area_sqm"].between(20, 400).all())
check("Lease start between 1960 and sale year", (df["lease_commence_date"].between(1960, 2030)).all())
check("Storey 1-60", df["storey_hi"].between(1, 60).all())
df["price_psm"] = (df["resale_price"] / df["floor_area_sqm"]).round(1)

# ---------- 5. Categories
unknown = set(df["flat_model"]) - set(C.FLAT_MODEL_GROUPS)
check("Every flat model mapped to a family", not unknown, f"unmapped: {unknown} (add to FLAT_MODEL_GROUPS in config.py)")
df["flat_model_group"] = df["flat_model"].map(C.FLAT_MODEL_GROUPS)
town_region = {t: r for r, ts in C.REGIONS.items() for t in ts}
unknown_towns = set(df["town"]) - set(town_region)
check("Every town mapped to a region", not unknown_towns, f"unmapped: {unknown_towns} (add to REGIONS in config.py)")
df["region"] = df["town"].map(town_region)

# ---------- 6. Flags
df["is_exact_dup"] = df.duplicated(EXPECTED_COLS, keep=False)
note("Exact duplicate rows", f"{df.duplicated(EXPECTED_COLS).sum()} repeats ({df['is_exact_dup'].sum()} rows involved). "
     "Kept: without a unit number they may be different flats sold in the same month at the same price")

counts = df["month"].value_counts().sort_index()
last, typical = counts.index[-1], counts.iloc[-13:-1].median()
df["partial_month"] = (df["month"] == last) & (counts.iloc[-1] < 0.6 * typical)
note("Latest month", f"{last}: {counts.iloc[-1]:,} sales vs typical {typical:,.0f} -> "
     f"{'flagged partial, excluded from in_scope' if df['partial_month'].any() else 'complete'}")

logp = np.log(df["price_psm"])
grp = [df["flat_type"], df["month"].str[:4]]
med = logp.groupby(grp).transform("median")
mad = (logp - med).abs().groupby(grp).transform("median") * 1.4826
df["psm_outlier"] = ((logp - med) / mad).abs() > 5
note("Price-per-sqm outliers (> 5 robust SD within flat type x year)",
     f"{df['psm_outlier'].sum()} rows flagged for review, not removed. "
     f"Most common flat models among them: {df.loc[df['psm_outlier'], 'flat_model'].value_counts().head(3).to_dict()}")

df["in_scope"] = (~df["flat_type"].isin(C.OUT_OF_SCOPE_FLAT_TYPES) & ~df["flat_model"].isin(C.OUT_OF_SCOPE_FLAT_MODELS)
                  & ~df["partial_month"])
note("In scope for profiles and the index",
     f"{df['in_scope'].sum():,} of {n0:,} rows. Excluded: "
     f"{df['flat_type'].isin(C.OUT_OF_SCOPE_FLAT_TYPES).sum()} 1-room/multi-generation, "
     f"{df['flat_model'].isin(C.OUT_OF_SCOPE_FLAT_MODELS).sum()} Terrace, {df['partial_month'].sum()} partial-month")

check("No rows lost", len(df) == n0)
df.to_csv(C.RESALE_CLEAN, index=False)

# ---------- report
lines = [f"# Resale data validation report", "",
         f"Source: `{C.RESALE.name}`  ",
         f"Rows: {n0:,} · Months: {df['month'].min()} to {df['month'].max()} · Towns: {df['town'].nunique()}", "",
         "| Check | Result | Detail |", "|---|---|---|"]
lines += [f"| {c} | {r} | {d} |" for c, r, d in checks]
lines += ["", f"Output: `data/interim/{C.RESALE_CLEAN.name}` with flags "
          "`in_scope`, `partial_month`, `is_exact_dup`, `lease_mismatch`, `psm_outlier`."]
C.VALIDATION_REPORT.write_text("\n".join(lines) + "\n")
print("\n".join(f"{r:5}  {c}: {d}" for c, r, d in checks))
print(f"\n-> {C.RESALE_CLEAN.name} ({len(df):,} rows), report -> docs/{C.VALIDATION_REPORT.name}")

"""Inspect the pricing-to-forecasting handover without editing shared outputs.

Run: python -m forecasting.audit_hedonic_index
This is a data-readiness audit, not a leakage-free forecast evaluation.
"""
from pathlib import Path
import json
import hashlib
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/price_index_v1.csv"
DEST = Path(__file__).resolve().parent / "outputs/hedonic_audit"
START, CUTOFF = "2017-01", "2026-09"


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(SOURCE)
    required = {"month", "region", "flat_type", "index", "n_sales", "median_price"}
    if not required.issubset(df.columns):
        raise ValueError(f"Missing columns: {required - set(df.columns)}")
    df["month"] = pd.to_datetime(df.month, errors="raise")
    if not df.month.dt.is_month_start.all():
        raise ValueError("Monthly timestamps must be month starts.")
    if df.duplicated(["region", "flat_type", "month"]).any():
        raise ValueError("Duplicate segment-month rows.")
    for col in ["index", "n_sales", "median_price"]:
        df[col] = pd.to_numeric(df[col], errors="raise")
        if not np.isfinite(df[col]).all() or not df[col].gt(0).all():
            raise ValueError(f"Invalid non-positive/non-finite {col}.")
    excluded = int(df.month.gt(pd.Timestamp(CUTOFF)).sum())
    df = df[df.month.between(pd.Timestamp(START), pd.Timestamp(CUTOFF))].copy()
    dates = pd.date_range(START, CUTOFF, freq="MS")
    rows = []
    for (region, flat), g in df.groupby(["region", "flat_type"]):
        s = g.set_index("month").reindex(dates)
        missing = s["index"].isna()
        initial = s.iloc[:-48]  # Same initial window as preliminary forecasting.
        rows.append(dict(region=region, flat_type=flat, segment_id=f"{region}::{flat}",
                         observed_months=int((~missing).sum()), missing_months=int(missing.sum()),
                         missing_month_list=";".join(dates[missing].strftime("%Y-%m")),
                         minimum_monthly_sales=int(g.n_sales.min()),
                         median_monthly_sales=float(g.n_sales.median()),
                         months_below_10=int(s.n_sales.fillna(0).lt(10).sum()),
                         initial_training_missing=int(initial["index"].isna().sum()),
                         initial_training_median_sales=float(initial.n_sales.median()),
                         initial_coverage_screen_pass=bool(region != "ALL" and initial["index"].notna().all()
                             and initial.n_sales.median() >= 10),
                         first_observed_month=g.month.min().strftime("%Y-%m"),
                         last_observed_month=g.month.max().strftime("%Y-%m")))
    coverage = pd.DataFrame(rows)
    coverage.to_csv(DEST / "index_coverage.csv", index=False)
    panel = df.rename(columns={"index": "index_value"})
    panel["segment_id"] = panel.region + "::" + panel.flat_type
    panel["index_vintage"] = "full_sample_supplied_not_origin_refitted"
    panel.to_csv(DEST / "index_panel_for_inspection.csv", index=False)
    summary = dict(source=str(SOURCE.relative_to(ROOT)), source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                   cutoff=CUTOFF, expected_months=len(dates), segments=len(coverage),
                   regional_segments=int(coverage.region.ne("ALL").sum()),
                   segments_with_no_missing_months=int(coverage.missing_months.eq(0).sum()),
                   regional_segments_passing_initial_screen=int(coverage.initial_coverage_screen_pass.sum()),
                   excluded_rows_after_cutoff=excluded,
                   fit_for_historical_forecast_claims=False,
                   reason="Supplied time-dummy index estimates characteristic coefficients using full history.")
    (DEST / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(coverage[["region", "flat_type", "missing_months", "minimum_monthly_sales",
                    "median_monthly_sales", "initial_coverage_screen_pass"]].to_string(index=False))


if __name__ == "__main__":
    main()

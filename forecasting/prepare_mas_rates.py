"""Parse MAS daily export; preserve raw file and prepare publication-dated features.

Run from repo root: python -m forecasting.prepare_mas_rates
Historical download is a current vintage, not proof of pre-2020 real-time availability.
"""
from pathlib import Path
import csv
import hashlib
import json
import re
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/macro/Domestic Interest Rates.csv"
OUT = Path(__file__).resolve().parent / "outputs/macro"
URL = "https://eservices.mas.gov.sg/statistics/dir/DomesticInterestRates.aspx"


def parse_mas(path):
    rows = csv.reader(path.read_text(encoding="utf-8-sig").splitlines())
    header = None
    year = month = None
    records = []
    for row in rows:
        if not row:
            continue
        if row[0].strip() == "SORA Value Date":
            if header is not None and row != header:
                raise ValueError("Header changed inside export.")
            header = row
            continue
        if header is None or len(row) != len(header) or not row[2].strip().isdigit():
            continue  # Preamble, blank rows, repeated labels and footer prose.
        if row[0].strip():
            if not re.fullmatch(r"\d{4}", row[0].strip()):
                raise ValueError(f"Unexpected year: {row[0]}")
            year = row[0].strip()
        if row[1].strip():
            month = row[1].strip()
        if not year or not month:
            raise ValueError("Date continuation appears before year/month.")
        value_date = pd.to_datetime(f"{row[2].strip()} {month} {year}", format="%d %b %Y")
        publication_date = pd.to_datetime(row[3].strip(), format="%d %b %Y")
        if publication_date <= value_date:
            raise ValueError("Unexpected publication/value-date ordering.")
        record = dict(sora_value_date=value_date, publication_date=publication_date)
        for label, val in zip(header[4:], row[4:]):
            if label.strip() != "Compound SORA - 3 month":
                raise ValueError(f"New rate column {label!r}: update explicit mapping before using.")
            record["sora_3m_pct_pa"] = pd.to_numeric(val.strip().replace(",", ""), errors="coerce")
        records.append(record)
    if not records:
        raise ValueError("No daily rate records found.")
    df = pd.DataFrame(records).sort_values("publication_date")
    if df.publication_date.duplicated().any():
        raise ValueError("Duplicate publication dates; investigate rather than average.")
    if np.isinf(df.sora_3m_pct_pa).any():
        raise ValueError("Infinite rate value.")
    return df


def prepare_monthly(daily):
    rows = []
    for month in pd.date_range("2016-01", "2026-09", freq="MS"):
        end = month + pd.offsets.MonthEnd(0)
        available = daily.loc[daily.publication_date.between(month, end)]
        nonmissing = available.dropna(subset=["sora_3m_pct_pa"])
        if nonmissing.empty:
            raise ValueError(f"No published observations in {month:%Y-%m}; no silent filling.")
        last = nonmissing.iloc[-1]
        rows.append(dict(month=month.strftime("%Y-%m"), forecast_origin_date=end.strftime("%Y-%m-%d"),
                         sora_3m_eom_pct_pa=float(last.sora_3m_pct_pa),
                         last_publication_date=last.publication_date.strftime("%Y-%m-%d"),
                         source_value_date=last.sora_value_date.strftime("%Y-%m-%d"),
                         mean_published_3m_rate_pct_pa=float(nonmissing.sora_3m_pct_pa.mean()),
                         published_observations=len(available), missing_rate_observations=int(available.sora_3m_pct_pa.isna().sum())))
    monthly = pd.DataFrame(rows)
    # Row t carries month t-1's last published rate; no future backfill.
    monthly["sora_3m_eom_lag1_pct_pa"] = monthly.sora_3m_eom_pct_pa.shift(1)
    monthly["lag1_last_publication_date"] = monthly.last_publication_date.shift(1)
    return monthly


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    daily = parse_mas(SOURCE)
    monthly = prepare_monthly(daily)
    daily.to_csv(OUT / "mas_sora_3m_daily_clean.csv", index=False)
    monthly.to_csv(OUT / "mas_sora_3m_monthly.csv", index=False)
    summary = dict(source=str(SOURCE.relative_to(ROOT)), source_url=URL,
                   source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                   series="3-month compounded SORA", overnight_sora_present=False,
                   units="percent per annum; 1.2312 means 1.2312%, not 123.12%",
                   daily_rows=len(daily), missing_rates=int(daily.sora_3m_pct_pa.isna().sum()),
                   first_value_date=str(daily.sora_value_date.min().date()),
                   last_value_date=str(daily.sora_value_date.max().date()),
                   first_publication_date=str(daily.publication_date.min().date()),
                   last_publication_date=str(daily.publication_date.max().date()),
                   monthly_rows=len(monthly),
                   rows_published_after_september=int(daily.publication_date.gt("2026-09-30").sum()),
                   limitations=["Source retrieval date was not supplied; filesystem date is not assumed to be retrieval date.",
                                "Current historical vintage; original availability of reconstructed historical compounded rates needs review.",
                                "Publication-date filtering alone does not establish vintage-correct historical data.",
                                "Monthly mean is mean of published 3-month rates, not a newly compounded monthly rate.",
                                "Future external regressors beyond known lags require explicit scenarios/forecasts."])
    (OUT / "mas_rate_audit.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    assert (pd.to_datetime(monthly.last_publication_date) <= pd.to_datetime(monthly.forecast_origin_date)).all()
    lag = monthly.dropna(subset=["lag1_last_publication_date"])
    assert (pd.to_datetime(lag.lag1_last_publication_date) < pd.to_datetime(lag.month)).all()
    assert monthly.month.nunique() == 129
    assert monthly.iloc[-1].last_publication_date == "2026-09-30"
    print(json.dumps(summary, indent=2))
    print(monthly.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()

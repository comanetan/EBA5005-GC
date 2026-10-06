"""Step 1 (offline): list every distinct block address in the resale data, plus primary-school postcodes.
Output: data/interim/unique_addresses.csv, data/interim/primary_schools.csv"""
import pandas as pd
from config import RESALE, SCHOOLS, UNIQUE_ADDR, PRIMARY_SCHOOLS, INTERIM

INTERIM.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(RESALE, dtype={"block": str})          # keep block as text: "10A", not 10.0
for c in ["block", "street_name", "town"]:
    df[c] = df[c].str.strip().str.upper().str.replace(r"\s+", " ", regex=True)
df["address"] = df["block"] + " " + df["street_name"]

addr = (df.groupby(["address", "block", "street_name", "town"]).size()
          .reset_index(name="n_transactions")
          .sort_values("n_transactions", ascending=False))
addr.to_csv(UNIQUE_ADDR, index=False)

sch = pd.read_csv(SCHOOLS, dtype={"postal_code": str})
prim = sch[sch["mainlevel_code"].str.contains("PRIMARY|P1", case=False, na=False)].copy()
prim["postal_code"] = prim["postal_code"].str.zfill(6)
prim[["school_name", "address", "postal_code", "mainlevel_code"]].to_csv(PRIMARY_SCHOOLS, index=False)

print(f"{len(df):,} resale rows ({df['month'].min()} to {df['month'].max()})")
print(f"{len(addr):,} unique block addresses -> {UNIQUE_ADDR.name}")
print(f"{len(prim):,} primary (incl. mixed P1-S4) schools -> {PRIMARY_SCHOOLS.name}")

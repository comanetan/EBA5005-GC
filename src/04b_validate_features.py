"""Step 4b (offline, after step 4): validate the geocoded (interim) and feature (processed) layers.
Hard checks stop the script if a rule is broken; notes record judgement calls for the report.
Output: docs/validation_report_features.md"""
import re, numpy as np, pandas as pd
import config as C

checks = []
def check(name, ok, detail=""):
    checks.append((name, "PASS" if ok else "FAIL", "" if ok else detail))
    if not ok:
        raise SystemExit(f"VALIDATION FAILED: {name}. {detail}")
def note(name, detail):
    checks.append((name, "NOTE", detail))
in_sg = lambda lat, lon: lat.between(1.15, 1.48) & lon.between(103.6, 104.1)

# ---------- Interim: geocoding
geo = pd.read_csv(C.GEOCODE_CACHE, dtype={"key": str, "postal": str})
blk = geo[geo["kind"] == "block"]
addr = pd.read_csv(C.UNIQUE_ADDR, dtype=str)
check("Every resale block has coordinates", addr["address"].isin(blk.loc[blk["lat"].notna(), "key"]).all(),
      f"{(~addr['address'].isin(blk.loc[blk['lat'].notna(), 'key'])).sum()} missing")
check("All coordinates inside Singapore", in_sg(geo["lat"].dropna(), geo["lon"].dropna()).all())
note("Block match quality", ", ".join(f"{k} {v:,}" for k, v in blk["match_quality"].value_counts().items()))
check("No unresolved fallback / none matches", not blk["match_quality"].isin(["fallback", "none"]).any(),
      blk.loc[blk["match_quality"].isin(["fallback", "none"]), "key"].tolist()[:10])
check("No two blocks share identical coordinates", not blk.duplicated(["lat", "lon"]).any())
for kind in ["school", "polyclinic", "supermarket"]:
    g = geo[geo["kind"] == kind]
    if len(g):
        note(f"{kind.title()} postcodes geocoded", f"{g['lat'].notna().sum()}/{len(g)}; "
             f"{(g['postal'] != g['key'].str.split(' ').str[1]).sum()} returned a different postcode (nearest match used)")
    else:
        note(f"{kind.title()} postcodes geocoded", "not yet: re-run step 2")

# ---------- Interim: amenity points
pts = pd.read_csv(C.AMENITY_POINTS)
dup = pts.duplicated(["type", "lat", "lon"])
note("Amenity points", ", ".join(f"{k} {v:,}" for k, v in pts["type"].value_counts().items())
     + f"; {dup.sum()} share a location with another of the same type (different businesses in one building, kept; repeat listings were removed in step 3)")
check("Amenity points inside Singapore", in_sg(pts["lat"], pts["lon"]).all())

# ---------- Processed: block features
b = pd.read_csv(C.PROCESSED / "block_features.csv")
dist_cols = [c for c in b.columns if c.startswith("dist_")]
check("No negative distances", (b[dist_cols] >= 0).all().all())
check("Nearest MRT within 5 km for every block", (b["dist_mrt_now_m"] <= 5000).all(), str(b["dist_mrt_now_m"].max()))
far = b[b["dist_mrt_now_m"] > 2000]
note("Blocks > 2 km from an MRT", f"{len(far)} ({', '.join(f'{t.title()} {n}' for t, n in far['town'].value_counts().head(3).items())}). "
     "Mostly LRT-served areas: decide whether LRT counts for the MRT band")
centre = b.groupby("town")[["lat", "lon"]].transform("median")
km = np.hypot((b["lat"] - centre["lat"]) * 111, (b["lon"] - centre["lon"]) * 111)
note("Blocks > 4 km from their town's centre", f"{(km > 4).sum()}: " + ", ".join(sorted(b.loc[km > 4, 'address'].str.split(' ', n=1).str[1].unique()))
     + " (checked: genuine outlying parts of Bukit Timah and Pasir Ris towns)")
note("Blocks matched to HDB Property Information", f"{b['year_completed'].notna().sum():,}/{len(b):,}")

# ---------- Processed: transaction features
d = pd.read_csv(C.PROCESSED / "resale_features.csv", low_memory=False)
check("No rows lost from the clean file", len(d) == len(pd.read_csv(C.RESALE_CLEAN, usecols=["month"])))
ins = d[d["in_scope"]]
check("Every in-scope sale has a profile", ins["profile_id"].notna().all(), f"{ins['profile_id'].isna().sum()} missing")
check("MRT distance at sale is never shorter than today's", (d["dist_mrt_at_sale_m"] >= d["dist_mrt_now_m"] - 1).all())
note("Sales whose nearest MRT opened after the sale", f"{(d['dist_mrt_at_sale_m'] > d['dist_mrt_now_m'] + 1).mean():.1%} "
     "(their MRT distance at time of sale is longer than today's)")
nulls = ins[[c for c in d.columns if c.startswith(("dist_", "n_"))]].isna().sum()
note("Missing location features (in-scope sales)", "none" if nulls.sum() == 0 else nulls[nulls > 0].to_dict())

# ---------- Outputs: profiles
p = pd.read_csv(C.OUTPUTS / "profiles.csv")
check("Profile IDs unique", p["profile_id"].is_unique)
for k in [5, 10]:
    note(f"Profiles with {k}+ sales in the last 12 months",
         f"{(p['n_last12'] >= k).mean():.0%} of {len(p):,} profiles, covering {p.loc[p['n_last12'] >= k, 'n_last12'].sum() / p['n_last12'].sum():.0%} of recent sales")

lines = ["# Geocoding and feature validation report", "",
         "| Check | Result | Detail |", "|---|---|---|"] + [f"| {c} | {r} | {d_} |" for c, r, d_ in checks]
(C.ROOT / "docs" / "validation_report_features.md").write_text("\n".join(lines) + "\n")
print("\n".join(f"{r:5}  {c}: {d_}" for c, r, d_ in checks))
print("\n-> docs/validation_report_features.md")

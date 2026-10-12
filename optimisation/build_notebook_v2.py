# -*- coding: utf-8 -*-
"""Builds Optimisation_Lead_Pipeline_v2_BlockLevel.ipynb."""
import os

import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []
md = lambda t: cells.append(nbf.v4.new_markdown_cell(t))
code = lambda t: cells.append(nbf.v4.new_code_cell(t))

md("""# Optimisation Lead — v2: Block-Level Accessibility
### From town centroids to every HDB block: does it change the recommendation?

v1 described every flat in a town with one set of accessibility numbers (the town's centroid).
This notebook re-does the prescriptive layer with **every HDB block individually geocoded** and asks,
with evidence at each step:

1. **Coverage** — what was geocoded, and how reliably
2. **Block accessibility** — true per-block distances to 12 amenity layers
3. **Does block-level matter?** — within-town variation; hedonic price effect beyond town; out-of-time test
4. **Granularity decision** — town vs town × MRT band vs pure block
5. **v2 profiles** — with block distributions and a block drill-down layer
6. **Recommender v2** — reformulated objective (hedonic value gap + household preference tilt)
7. **Monte Carlo** — buy now vs wait, on a simulator calibrated at the new granularity
8. **Sensitivity** — monotonicity, preference sweep, "price of insisting on Near-MRT"
9. **Backtest** — 6 cutoffs × 3 households, v2 vs v1 vs naive, across two iterations
10. **Iteration log, limitations, and handoff notes**
""")

md("""## Iteration log (what changed, and why)
| # | Finding | Change |
|---|---|---|
| 0 | Geocoding "failed" at ~5% | Root cause was HTTP 429 rate-limiting silently swallowed as "not found". Fixed with explicit 429 handling, backoff, pacing, per-area checkpoints → 13,356/13,357 blocks, 1,699/1,703 childcare, 439/444 supermarkets, 335/337 schools |
| 1 | Master Plan 2019 rail layer includes **unopened** stations (Jurong Region Line, Cross Island Line) | Current access uses LTA's operating station-exit layer; planned stations kept as a separate *future-access* feature |
| 2 | Market already prices MRT proximity (~1%/100m) | Objective rebuilt: surplus = shrunk hedonic value gap + household-vs-market preference tilt (raw attribute value would double-count what the price already reflects) |
| 3 | Budget-monotonicity check **failed** | Cardinality was `min(k, feasible towns)`, so more budget forced extra negative-value picks. Fixed: k held fixed; "fewer than k towns feasible" reported as its own outcome |
| 4 | Backtest iter 1: v2 within-budget 95.3% vs v1 100% | Stub ±15% band was sized for town-level volatility; finer cells move more. Replaced with an empirical, granularity-aware 90% band → 98.8% |
| 5 | v1 availability stub divided by an arbitrary "20 units" | Replaced with the buyer-relevant quantity: arrival rate of matching sales (sales/12 per month) |
| 6 | LTA's exit layer is missing **5 operating stations** (Punggol Coast, Hume, and the 3 CCL6 stations Keppel / Cantonment / Prince Edward Rd); 2,141 sales were credited with stations not yet open | Exits patched from OneMap; distance is now **date-aware** for all 40 stations opened since 2017 (DTL3, Canberra, TEL1–4, the patched 5): each sale is measured against the network open *in its own month* |
| 7 | "Primary school" layer contained 11 secondary/JC schools (filter matched "MIXED LEVEL"); linear school distance had a counter-intuitive sign | P1-only filter (182 schools); school access re-specified as **MOE-style tiers** (within 1km / 1–2km / beyond 2km). SAP/GEP tiers carry a clean +2.5–3% premium; "any primary" is saturated (97% within 1km) |
| 8 | Distances were straight-line | Built the full OSM pedestrian network (566k nodes) and computed walking distance for every block; tested whether it explains price better (it does not — see §3.4) |
| 9 | "~5% of picks see no matching sale" was unexplained | Calibration check: the availability stub predicted it (every >30%-risk pick came up empty; none of the 66 picks rated <1% did) — §7.1 |
""")

code("""import warnings; warnings.filterwarnings("ignore")
import json, os
import numpy as np, pandas as pd
import matplotlib.pyplot as plt, matplotlib.ticker as mticker

import block_accessibility as ba
import block_analysis as ban
import housing_profiles_v2 as hp2
import recommender_v2 as rv2
import recommender as rv1
import monte_carlo as mc
import sensitivity_v2 as sv2
import empirical_bands as eb

plt.rcParams.update({"figure.figsize": (10, 4.5), "axes.grid": True, "grid.alpha": 0.3})
pd.set_option("display.max_columns", 60); pd.set_option("display.width", 180)
DATA = rv2.DATA
kfmt = mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}k")""")

# ---------------- 1 coverage
md("## 1. Geocoding coverage")
code("""PROC = os.path.join(ba.ROOT, "data", "processed")
cov = []
for label, f in [("HDB blocks", "hdb_blocks_geocoded.csv"), ("Primary/secondary schools", "schools_geocoded_v2.csv"),
                 ("Childcare & kindergartens", "childcare_postal_geocoded_v2.csv"), ("Supermarkets", "supermarkets_geocoded_v2.csv")]:
    d = pd.read_csv(os.path.join(PROC, f))
    cov.append({"layer": label, "attempted": len(d), "geocoded_ok": int((d["status"] == "OK").sum())})
cov = pd.DataFrame(cov); cov["success_pct"] = cov["geocoded_ok"] / cov["attempted"] * 100
cov""")

# ---------------- 2 accessibility
md("""## 2. Block-level accessibility
Straight-line (haversine) distance from each block to the nearest feature, plus counts within walking radii.
**Rail uses LTA's operating station-exit layer** (closer to real walking access than a station centroid),
**patched with 5 operating stations missing from it** (Punggol Coast, Hume, Keppel, Cantonment, Prince Edward Road —
exits from OneMap, opening dates verified). **Distances are date-aware**: the 40 stations that opened during the
2017+ resale window (DTL3 Oct 2017, Canberra 2019, TEL stages 2020–2024, the 5 patched) only count for sales after
they opened. Master Plan stations not yet operating are a separate *future-access* feature.""")
code("""blocks = pd.read_csv(os.path.join(DATA, "block_accessibility.csv"))
res = blocks[blocks["residential"] == "Y"]
_, meta = ba.load_amenity_layers()
print(f"Residential blocks: {len(res):,} | operating MRT stations: {meta['n_operating_mrt_stations']} | "
      f"LRT: {meta['n_operating_lrt_stations']} | planned/not-in-operating-layer: {len(meta['planned_station_names'])}")
dcols = [c for c in res.columns if c.startswith("dist_")]
(res[dcols].describe(percentiles=[.1, .5, .9]).T[["mean", "10%", "50%", "90%", "max"]] * 1000).round(0).rename(
    columns=lambda c: c + " (m)")""")

code("""pg = json.load(open(os.path.join(ba.GEO, "MRT_exits_patch_onemap.geojson")))
patched = pd.DataFrame([f["properties"] for f in pg["features"]])
patched["opened"] = patched["STATION_NA"].map(ba.OPENING_DATES)
display(patched.groupby(["STATION_NA", "opened"]).size().rename("exits_patched").reset_index())
tx0 = ban.load_transactions_with_access()
moved = tx0[tx0["dist_mrt_exit_km_at_sale"] > tx0["dist_mrt_exit_km"] + 1e-6]
print(f"Sales measured against the network open at sale date: {len(moved):,} sales get a LONGER distance than "
      f"today's network (station not yet open when they sold); {(tx0['mrt_band_at_sale'] != tx0['mrt_band']).sum():,} change band.")""")

code("""layers, _ = ba.load_amenity_layers()
fig, axes = plt.subplots(1, 2, figsize=(15, 6.5))
sc = axes[0].scatter(res["lon"], res["lat"], c=res["dist_mrt_exit_km"].clip(upper=1.5), cmap="RdYlGn_r", s=3)
axes[0].scatter(layers["mrt_exit"]["lon"], layers["mrt_exit"]["lat"], s=4, c="black", label="operating MRT exit")
axes[0].set_title("Every HDB block, coloured by distance to nearest operating MRT exit")
plt.colorbar(sc, ax=axes[0], label="km (capped 1.5)"); axes[0].legend(loc="lower right")
sc2 = axes[1].scatter(res["lon"], res["lat"], c=(res["dist_planned_rail_km"] - res["dist_mrt_exit_km"]).clip(-2, 0),
                      cmap="Blues_r", s=3)
axes[1].scatter(layers["planned_rail"]["lon"], layers["planned_rail"]["lat"], marker="x", c="red", s=25,
                label="planned / not-yet-operating station")
axes[1].set_title("Future access upside: how much closer a planned station will be")
plt.colorbar(sc2, ax=axes[1], label="km closer (negative = gain)"); axes[1].legend(loc="lower right")
for a in axes: a.set_xticks([]); a.set_yticks([])
plt.tight_layout(); plt.show()""")

# ---------------- 3 does it matter
md("""## 3. Does block-level accessibility matter?
### 3.1 How much variation do town centroids throw away?
Share of each feature's variance (across blocks) that lies **within** towns — invisible to a town-level feature.""")
code("""tx = ban.load_transactions_with_access()
tx["price_psm"] = tx["resale_price"] / tx["floor_area_sqm"]
vd = ban.variance_decomposition(tx, ban.ACCESS_FEATURES)
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.barh(vd["feature"], vd["within_town_share"] * 100, color="#2f5496", label="within town")
ax.barh(vd["feature"], vd["between_town_share"] * 100, left=vd["within_town_share"] * 100, color="#c9c9c9", label="between towns")
ax.set_xlabel("% of variance"); ax.set_title("Accessibility variance: within vs between towns"); ax.legend()
plt.tight_layout(); plt.show()
vd.round(3)""")

code("""order = res.groupby("bldg_contract_town")["dist_mrt_exit_km"].median().sort_values().index
fig, ax = plt.subplots(figsize=(12, 4.5))
res.boxplot(column="dist_mrt_exit_km", by="bldg_contract_town", ax=ax, positions=range(len(order)), showfliers=False)
ax.set_xticklabels(order, rotation=90, fontsize=7); plt.suptitle("")
ax.set_title("Within-town spread of MRT distance (one box per HDB town code)"); ax.set_ylabel("km")
plt.tight_layout(); plt.show()""")

md("""### 3.2 Hedonic test: does it explain price beyond the town?
Both models include month, flat type, flat model, storey, floor area, lease (quadratic) and **town fixed effects**.
Model B adds block accessibility. Standard errors clustered by block. 80k-transaction sample.""")
code("""d, m_a, m_b = ban.hedonic_models(tx, sample_n=80_000)
print(f"Adj R²  town FE only: {m_a.rsquared_adj:.4f}  |  + block accessibility: {m_b.rsquared_adj:.4f}")
print(f"Residual SE (log pts): {np.sqrt(m_a.mse_resid):.4f} -> {np.sqrt(m_b.mse_resid):.4f} "
      f"({(1-np.sqrt(m_b.mse_resid)/np.sqrt(m_a.mse_resid))*100:.1f}% lower)")
coef = ban.coefficient_table(m_b); coef.round(3)""")

code("""c = coef[coef["feature"].str.startswith("dist_")].copy()
fig, ax = plt.subplots(figsize=(9, 4))
colors = ["#2f5496" if v > 0 else "#c00000" for v in c["pct_per_100m_closer"]]
ax.barh(c["feature"], c["pct_per_100m_closer"], color=colors)
ax.axvline(0, color="black", lw=0.8)
ax.set_xlabel("% price change per 100m CLOSER (within town, all else equal)")
ax.set_title("Market-implied value of proximity (red = counter-intuitive sign, not used as WTP)")
plt.tight_layout(); plt.show()""")

md("""**Reading the coefficients.** MRT dominates: ≈ **+1.1% price per 100m closer** to an MRT exit (measured on the network open at each sale date),
tight confidence interval. Supermarket, hawker, clinic and park proximity are smaller but correctly signed.
**Linear primary-school and childcare distance come out counter-intuitive** (closer = slightly cheaper).
A *linear* distance is the wrong specification: almost every HDB block has some primary school within 1km,
and what buyers pay for is **P1 ballot priority at a popular school**, which MOE allocates in straight-line
distance *tiers*. §3.3 re-specifies school access that way.""")

code("""grad = ban.mrt_distance_gradient(tx)
fig, ax = plt.subplots(figsize=(9, 4))
ax.errorbar(grad["band"], grad["pct_vs_<200m"], yerr=[grad["pct_vs_<200m"] - grad["ci_low"], grad["ci_high"] - grad["pct_vs_<200m"]],
            fmt="o-", color="#2f5496", capsize=4)
ax.axhline(0, color="gray", lw=0.8); ax.set_ylabel("% vs <200m (same town)")
ax.set_title("Within-town price gradient by distance to MRT exit")
plt.tight_layout(); plt.show()
grad.round(2)""")

code("""oot = ban.out_of_time_test(tx)
print("Train on 2017-2024, test on 2025-2026 (unseen period):")
oot.round(3)""")

md("""### 3.3 School and childcare access as tiers (1km / 2km / beyond)
MOE's Primary 1 registration gives priority by **straight-line** home–school distance: *within 1km*, then
*1–2km*, then *beyond 2km*. Tiers therefore stay straight-line by design (walking distance would mis-assign them).
- **Any primary school**: tier of the nearest P1 school (182 schools; secondary/JC excluded).
- **SAP / GEP primary** (20 schools): the oversubscribed schools where the 1km priority actually decides a ballot —
  our proxy for "popular school" until a popularity / balloting dataset is added.
- **Childcare**: the 1km/2km cut is saturated (every block has one within 1km), so it is also cut finer:
  within 200m / 200–500m / beyond 500m.""")
code("""tiers = pd.concat({c: res[c].value_counts(normalize=True).mul(100).round(1)
                   for c in ["primary_tier", "elite_primary_tier", "childcare_tier", "childcare_band"]}, axis=1)
print("Share of residential blocks in each tier (%):"); display(tiers)
m_st, st, st_mrt = ban.school_tier_test(tx)
print("Hedonic with tiers (town FE, clustered by block); % price effect vs the reference level:")
st.round(3)""")

code("""fig, ax = plt.subplots(figsize=(9, 3.8))
y = st["term"].str.replace("elite_primary_tier", "SAP/GEP primary").str.replace("primary_tier", "any primary").str.replace(
    "childcare_band", "childcare")
ax.errorbar(st["pct_effect"], y, xerr=[st["pct_effect"] - st["ci_low"], st["ci_high"] - st["pct_effect"]], fmt="o",
            color="#2f5496", capsize=4)
ax.axvline(0, color="gray", lw=0.8); ax.set_xlabel("% price vs reference tier (95% CI)")
ax.set_title("What the market pays for school / childcare tiers (within town)")
plt.tight_layout(); plt.show()""")

md("""**Reading it.**
- **SAP/GEP within 1km or 1–2km ≈ +2.5–3%** vs beyond 2km, clean and significant: this is the P1-priority premium,
  and it is now used as the market rate for the "needs primary school" goal (`elite_primary_1_2km` in
  `market_wtp_coefficients.json`).
- **"Any primary"** carries no usable signal — 97% of blocks are within 1km, so the comparison level is tiny
  and noisy. It is kept as a descriptive share only.
- **Childcare**: blocks within 200m or 200–500m of a centre trade ~3% *below* the few blocks beyond 500m
  (borderline significance). With childcare this ubiquitous, the "beyond 500m" group is mostly newer, less dense
  estates — the sign reflects estate type, not a dislike of childcare. It is reported, not optimised on.

In the recommender a household picks `school_goal` = `elite_1km` / `elite_2km` / `any_1km`; the shortfall is
priced at the market tier premium × the household's school multiplier.""")

md("""### 3.4 Straight-line vs walking distance — can we track the real walk?
We downloaded the full OpenStreetMap pedestrian network for Singapore (footpaths, linkways, overhead bridges,
walkable roads; **566k nodes, unsimplified**) and ran one multi-source Dijkstra per amenity layer, giving the
network walking distance from every HDB block to its nearest MRT exit, hawker centre, supermarket, etc.

Two versions: **raw OSM**, and **OSM + 25m connectors** — every pair of path nodes within 25m that OSM does not
join gets an edge, standing in for unmapped zebra crossings, void-deck walk-throughs and covered linkways.""")
code("""walk_raw = pd.read_csv(os.path.join(DATA, "block_walk_distances.csv"))
walk_con = pd.read_csv(os.path.join(DATA, "block_walk_distances_connect25m.csv"))
r_ = res[["query", "dist_mrt_exit_km", "dist_bus_stop_km", "dist_supermarket_km"]]
fig, axes = plt.subplots(1, 2, figsize=(14, 4.5))
for ax, (lbl, w) in zip(axes, [("raw OSM", walk_raw), ("OSM + 25m connectors", walk_con)]):
    m = r_.merge(w, on="query")
    for k, col in [("mrt_exit", "#2f5496"), ("bus_stop", "#c00000"), ("supermarket", "#548235")]:
        s, wk = m[f"dist_{k}_km"], m[f"walk_{k}_km"]
        ok = (s > 0.05) & wk.notna()
        ax.hist((wk[ok] / s[ok]).clip(upper=5), bins=80, histtype="step", lw=1.5, color=col,
                label=f"{k}: median {(wk[ok]/s[ok]).median():.2f}x")
    ax.axvline(1.3, color="black", ls="--", lw=0.8, label="typical urban detour ≈1.2–1.4x")
    ax.set_title(f"Detour ratio = walk / straight-line ({lbl})"); ax.set_xlabel("ratio (capped at 5)"); ax.legend(fontsize=8)
plt.tight_layout(); plt.show()""")

code("""ex_q = "153 JALAN TECK WHYE" if (res["query"] == "153 JALAN TECK WHYE").any() else res["query"].iloc[0]
print("Example (traced route):", ex_q)
display(r_[r_["query"] == ex_q].merge(walk_raw, on="query")[["dist_bus_stop_km", "walk_bus_stop_km"]].join(
    r_[r_["query"] == ex_q].merge(walk_con, on="query")[["walk_bus_stop_km"]].rename(columns={"walk_bus_stop_km": "walk_bus_stop_km_connected"})))
cmp_ = pd.read_csv(os.path.join(DATA, "walk_variant_comparison.csv"))
cmp_.pivot(index="metric", columns="variant", values="value").round(4)""")
md("""**Reading it (AIC is comparable only within a variant — the usable sample differs).**
- **Raw OSM is not trustworthy for HDB estates**: median detour 1.6× to MRT and 2.1× to a bus stop (typical
  urban networks are 1.2–1.4×); 64% of blocks have a >1.5× detour. Route traces show why — e.g. a bus stop 107m
  away routed ~1.3km round a block because OSM is missing the crossing / void-deck path. Using it would push
  ~4,900 blocks into a farther MRT band.
- **Bridging ≤25m gaps** brings the MRT detour to a plausible **1.34×** and halves the >1.5× share (29%).
- **Price test**: even the corrected walking distance does **not** explain resale price better than straight-line
  (adj R² 0.9213 vs 0.9219); with both in the model, straight-line carries most of the effect.

**Decision.** Straight-line stays the model and profile input (it is also what MOE's P1 tiers use). The
gap-corrected walking distances are merged as `walk_*_km` columns and shown in the block drill-down, so a household
sees "~870m walk" as well as "620m away". To validate further, a sample of blocks can be checked against
OneMap's routing API (needs a free account token).""")

# ---------------- 4 granularity
md("""## 4. Granularity decision
A profile must be (a) **thick enough** to price and forecast (≥3 sales in 12 months) and
(b) **homogeneous enough** that its accessibility number describes the flats in it.""")
code("""gran = ban.granularity_comparison(tx)
fig, ax1 = plt.subplots(figsize=(9, 4.5))
x = np.arange(len(gran))
ax1.bar(x - 0.2, gran["pct_txn_in_usable_cells"], 0.4, color="#2f5496", label="% of sales in usable cells")
ax2 = ax1.twinx()
ax2.bar(x + 0.2, gran["median_within_cell_MRT_sd_m"], 0.4, color="#c00000", label="within-profile MRT spread (m)")
ax1.set_xticks(x); ax1.set_xticklabels(["G1 town", "G2 town × MRT band", "G3 block"])
ax1.set_ylabel("% of sales covered"); ax2.set_ylabel("MRT distance SD within profile (m)")
fig.legend(loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.02)); plt.tight_layout(); plt.show()
gran.round(2)""")

md("""**Decision: G2 = town × flat type × storey band × MRT band** (Near ≤400m / Mid 400–800m / Far >800m).
- **vs G1 (town)**: same coverage (99.3% vs 99.9%), but within-profile MRT spread falls **266m → 102m** and price
  dispersion falls (CV 11.3% → 9.9%). The 400m/800m cut-offs sit on the observed price gradient and match
  ~5- and ~10-minute walks.
- **vs G3 (pure block)**: G3 is perfectly homogeneous but only **28.5%** of sales sit in cells with enough data —
  unforecastable for most of the market.
- **Blocks are not discarded**: every G2 profile carries its block distribution (p10/p50/p90) and the list of
  blocks behind it, so the dashboard can drill down to actual addresses.""")

# ---------------- 5 profiles
md("## 5. v2 profiles")
code("""prof = pd.read_csv(os.path.join(DATA, "housing_profiles_v2_full.csv"))
print(f"{len(prof)} profiles | {prof['town'].nunique()} towns | bands: {prof['mrt_band'].value_counts().to_dict()}")
prof[["profile_id", "median_price", "txn_count_12m", "n_blocks", "dist_mrt_exit_km_p10", "dist_mrt_exit_km_p50",
      "dist_mrt_exit_km_p90", "essentials_score", "share_primary_1km", "annual_turnover_pct", "hedonic_value",
      "hedonic_gap"]].sample(10, random_state=3).round(3)""")

code("""t = prof[(prof["town"] == "TAMPINES") & (prof["flat_type"] == "4 ROOM")].sort_values(["storey_band", "mrt_band"])
fig, ax = plt.subplots(figsize=(9, 4))
for band, col in [("Near", "#548235"), ("Mid", "#bf8f00"), ("Far", "#c00000")]:
    s = t[t["mrt_band"] == band]
    ax.scatter(s["storey_band"], s["median_price"], s=s["txn_count_12m"] * 3, color=col, label=band, alpha=0.8)
ax.yaxis.set_major_formatter(kfmt); ax.legend(title="MRT band")
ax.set_title("Tampines 4-Room: one town, now split by storey AND MRT band (bubble = sales/12mo)")
plt.tight_layout(); plt.show()""")

code("""drill = pd.read_csv(os.path.join(DATA, "profile_block_drilldown.csv"))
tb = drill[(drill["town"] == "TAMPINES") & (drill["flat_type"] == "4 ROOM")]
fig, ax = plt.subplots(figsize=(8, 6))
for band, col in [("Near", "#548235"), ("Mid", "#bf8f00"), ("Far", "#c00000")]:
    s = tb[tb["mrt_band"] == band]
    ax.scatter(s["lon"], s["lat"], s=s["sales_12m"] * 12, color=col, label=f"{band} ({s['query'].nunique()} blocks)", alpha=0.7)
mx = layers["mrt_exit"]; mx = mx[(mx["lon"].between(tb["lon"].min()-.01, tb["lon"].max()+.01)) & (mx["lat"].between(tb["lat"].min()-.01, tb["lat"].max()+.01))]
ax.scatter(mx["lon"], mx["lat"], marker="^", c="black", s=40, label="MRT exit")
ax.legend(); ax.set_xticks([]); ax.set_yticks([])
ax.set_title("Block drill-down: Tampines 4-Room blocks behind each MRT-band profile")
plt.tight_layout(); plt.show()""")

# ---------------- 6 recommender
md("""## 6. Recommender v2
**Objective (SGD):** maximise Σ x_p · (surplus_p − goal deviation_p)

- **surplus = shrunk hedonic value gap + preference tilt.** The gap is how far a profile trades below what its
  attributes are worth, shrunk by n/(n+10) so thin cells can't dominate (a "cheap" profile may also have
  unmeasured negatives — noise, orientation, condition). The tilt values attributes at
  *(household multiplier − 1) × market rate*: a household valuing MRT access exactly like the market gets
  **zero** surplus from it, because the price already reflects it.
- **goal deviations:** MRT distance beyond target (priced at the market MRT rate × multiplier), walkable-essentials
  shortfall, school-tier shortfall (if needed: share of the profile's blocks *not* within 1km/2km of a SAP/GEP
  primary, priced at the market tier premium), storey below target, and expected wait beyond target —
  **waiting priced at the real median HDB rent** for that town and flat type.
- **hard constraints (proposal):** budget ≥ upper price band (empirical, granularity-aware 90%), lease ≥ minimum,
  **≤ 1 profile per town**, exactly k.""")

code("""bands12 = eb.empirical_growth_bands(tx[tx["flat_type"] != "MULTI-GENERATION"], horizon=12)
bands6 = eb.empirical_growth_bands(tx[tx["flat_type"] != "MULTI-GENERATION"], horizon=6)
archetypes = {
    "Young couple, transit-reliant": dict(budget=600_000, min_lease_yrs=60, flat_types=["3 ROOM", "4 ROOM"],
                                           target_mrt_km=0.4, multipliers={"mrt": 1.5}),
    "Family, needs primary school": dict(budget=800_000, min_lease_yrs=65, flat_types=["4 ROOM", "5 ROOM"],
                                          target_mrt_km=0.6, needs_primary_school=True, target_storey="Mid"),
    "Budget-first, car owner": dict(budget=480_000, min_lease_yrs=55, target_mrt_km=1.0,
                                     multipliers={"mrt": 0.5}, target_essentials=3.0),
}
results = {}
for name, a in archetypes.items():
    r = rv2.solve(rv2.HouseholdQuery2(k=5, name=name, **a), upper_factors=bands12)
    results[name] = r
    print(f"\\n=== {name} — {r['status']}, {r['n_candidates']} candidates, {r['n_feasible_towns']} towns ===")
    display(r["shortlist"][["rank", "profile_id", "price_today", "price_upper", "dist_mrt_exit_km_p50",
                            "essentials_score", "share_elite_primary_2km", "expected_wait_months",
                            "p_no_matching_sale_3m", "surplus",
                            "goal_deviation_total", "net_objective_value"]].round(2))""")

code("""fig, axes = plt.subplots(1, 3, figsize=(17, 4.5), sharey=False)
devs = ["dev_mrt", "dev_essentials", "dev_school", "dev_storey", "dev_wait"]
for ax, (name, r) in zip(axes, results.items()):
    sl = r["shortlist"].set_index("profile_id")
    bottom = np.zeros(len(sl))
    for dcol, col in zip(devs, ["#2f5496", "#548235", "#bf8f00", "#7030a0", "#c00000"]):
        ax.barh(sl.index.str.replace("::", " "), -sl[dcol], left=-bottom, color=col, label=dcol.replace("dev_", ""))
        bottom += sl[dcol].values
    ax.barh(sl.index.str.replace("::", " "), sl["surplus"], color="#a9d18e", label="surplus", alpha=0.7)
    ax.axvline(0, color="black", lw=0.8); ax.set_title(name, fontsize=9); ax.tick_params(labelsize=7)
axes[0].legend(fontsize=7)
plt.suptitle("What drives each pick: surplus (right) vs dollar-weighted goal shortfalls (left)")
plt.tight_layout(); plt.show()""")

md("### Block drill-down for each shortlist (actual addresses behind each recommended profile)")
code("""for name, r in results.items():
    print(f"\\n{name}")
    display(rv2.block_drilldown(r["shortlist"], top_n=2).round(3))""")

md("""### v1 vs v2 for the same household
Same budget, lease, flat types and k. v1 only knows town-level accessibility; we measure what MRT distance
its picks *actually* deliver using the block data.""")
code("""recent = tx[tx["month"] > tx["month"].max() - pd.DateOffset(months=12)]
cmp_rows = []
for name, a in archetypes.items():
    q1 = rv1.HouseholdQuery(budget=a["budget"], min_lease_yrs=a["min_lease_yrs"], horizon_months=12, k=5,
                            flat_types=a.get("flat_types"), target_mrt_km=a["target_mrt_km"])
    r1 = rv1.solve_recommender(q1)["shortlist"]
    for _, p in r1.iterrows():
        cell = recent[(recent["town"] == p["town"]) & (recent["flat_type"] == p["flat_type"]) & (recent["storey_band"] == p["storey_band"])]
        cmp_rows.append({"household": name, "version": "v1 town-level", "profile": p["profile_id"],
                         "price": p["price_today"], "actual_mrt_km": cell["dist_mrt_exit_km"].median()})
    for _, p in results[name]["shortlist"].iterrows():
        cmp_rows.append({"household": name, "version": "v2 block-informed", "profile": p["profile_id"],
                         "price": p["price_today"], "actual_mrt_km": p["dist_mrt_exit_km_p50"]})
cmp = pd.DataFrame(cmp_rows)
summ = cmp.groupby(["household", "version"]).agg(median_mrt_km=("actual_mrt_km", "median"), mean_price=("price", "mean")).unstack()
summ.round(3)""")

# ---------------- 7 MC
md("""## 7. Monte Carlo: buy now vs wait (granularity-calibrated simulator)
Price paths now come from the **empirical 6/12-month bands for each pick's (flat type, MRT band)** — historical
median drift ≈ +4–7%/yr, not the old stub's 0%. Availability uses the arrival rate of matching sales.""")
code("""mc_tables = {}
for name, r in results.items():
    sl = r["shortlist"]
    fc = eb.fcast_for_shortlist(sl, bands6, bands12)
    sc = mc.run_monte_carlo(sl, fc, n_scenarios=3000, seed=42)
    mc_tables[name] = mc.summarize_strategies(sc, budget=archetypes[name]["budget"]).merge(
        sl[["profile_id", "expected_wait_months"]], on="profile_id")
fig, axes = plt.subplots(1, 3, figsize=(17, 4.5))
for ax, (name, s) in zip(axes, mc_tables.items()):
    xx = np.arange(len(s)); w = 0.27
    ax.bar(xx - w, s["buy_now_p_success_within_budget"], w, label="buy now", color="#2f5496")
    ax.bar(xx, s["wait_6m_p_success_within_budget"], w, label="wait 6m", color="#bf8f00")
    ax.bar(xx + w, s["wait_12m_p_success_within_budget"], w, label="wait 12m", color="#c00000")
    ax.set_xticks(xx); ax.set_xticklabels([f"{p.split('::')[0][:10]}\\n{p.split('::')[1]}\\nwait {wt:.1f}m"
                                           for p, wt in zip(s["profile_id"], s["expected_wait_months"])], fontsize=6)
    ax.set_ylim(0, 1.05); ax.set_title(name, fontsize=9)
axes[0].set_ylabel("P(matching flat found AND within budget)"); axes[0].legend(fontsize=7)
plt.tight_layout(); plt.show()
pd.concat({k: v[["profile_id", "expected_wait_months", "buy_now_p_success_within_budget", "wait_6m_p_success_within_budget",
                 "wait_12m_p_success_within_budget", "recommended_strategy"]] for k, v in mc_tables.items()}).round(3)""")

md("""**Reading it.** Liquid profiles (a matching sale every few weeks) → **buy now**: waiting only adds price risk.
Thinner profiles → buying within a ~6-week search often fails, so **waiting ~6 months** raises the chance of a
match before price drift erodes the budget; 12 months tends to be worse than 6. This is the
"how readily does it come up for sale" business objective made decision-relevant.""")

md("""### 7.1 "About 5% of picks saw no matching sale" — was that predictable?
**What it means.** The backtest checks each pick by looking for actual resales *of that exact profile*
(same town, flat type, storey band and MRT band) in months 11–13 after the cutoff. For ~4–5% of v2 picks there
were **none** — not a bad recommendation, simply no flat of that kind changed hands in that 3-month window, so
a buyer would have had to wait. The coarser v1 (town-level) profiles almost never hit this because each covers
more flats.

**The test.** The availability stub models matching sales as a Poisson arrival process: a profile with n sales
in the past 12 months produces n/12 per month, so P(no sale in 3 months) = exp(−3n/12). If the model is
honest, picks it flagged as risky should be the ones that came up empty.""")
code("""from backtest_v2 import availability_calibration
bt_raw = pd.read_csv(os.path.join(DATA, "backtest_v2_results_iter2.csv"))
cal_d, cal = availability_calibration(bt_raw, tx)
print(f"Expected no-sale picks: {cal_d['p_no_sale_pred'].sum():.1f}  |  observed: {cal_d['no_sale_observed'].sum()} of {len(cal_d)}")
display(cal.round(3))
cal_d[cal_d["no_sale_observed"] == 1][["cutoff", "household", "profile", "sales_prev_12m", "p_no_sale_pred"]].round(3)""")
md("""**Reading it.** Expected and observed counts are close in aggregate (printed above), and the misses
are concentrated where the model said they would be: every pick with >30% predicted no-sale risk came up empty;
the 66 picks rated <1% never did. So this is a *known, priced risk*, not a hidden failure — the shortlist
now shows `p_no_matching_sale_3m` beside each pick, and the Monte Carlo turns it into "buy now vs wait".
The Pricing & Availability Lead's survival model should beat this stub on the same table.""")

# ---------------- 8 sensitivity
md("## 8. Sensitivity")
code("""base = dict(budget=600_000, min_lease_yrs=60, k=5, flat_types=["3 ROOM", "4 ROOM"], target_mrt_km=0.5)
bs = sv2.sweep(base, "budget", range(450_000, 1_000_001, 25_000), upper_factors=bands12)
ls = sv2.sweep(base, "min_lease_yrs", range(40, 96, 5), upper_factors=bands12)
ok_b, _ = sv2.monotonic(bs, "objective", "budget", True); ok_l, _ = sv2.monotonic(ls, "objective", "min_lease_yrs", False)
print("Budget monotonicity (comparable full-k solutions):", "PASS" if ok_b else "FAIL")
print("Min-lease monotonicity:", "PASS" if ok_l else "FAIL")
fig, axes = plt.subplots(1, 2, figsize=(14, 4.5))
axes[0].plot(bs["budget"], bs["objective"], "o-", color="#2f5496"); axes[0].xaxis.set_major_formatter(kfmt)
axes[0].set_title("Objective vs budget (blank = fewer than k towns feasible)")
axes[1].plot(ls["min_lease_yrs"], ls["objective"], "o-", color="#c00000"); axes[1].set_title("Objective vs minimum lease")
plt.tight_layout(); plt.show()""")

code("""ps = sv2.mrt_preference_sweep(base, multipliers=(0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0), upper_factors=bands12)
fig, ax = plt.subplots(figsize=(9, 4))
ax.bar(ps["mrt_multiplier"].astype(str), ps["share_Near"], color="#548235", label="Near")
ax.bar(ps["mrt_multiplier"].astype(str), ps["share_Mid"], bottom=ps["share_Near"], color="#bf8f00", label="Mid")
ax.bar(ps["mrt_multiplier"].astype(str), ps["share_Far"], bottom=ps["share_Near"] + ps["share_Mid"], color="#c00000", label="Far")
ax.set_xlabel("household MRT preference multiplier (1.0 = market average)"); ax.set_ylabel("share of shortlist")
ax.set_title("Shortlists change sensibly as preferences vary (GP evaluation criterion)"); ax.legend()
plt.tight_layout(); plt.show()
ps.drop(columns=["picks", "objective"]).round(3)""")

md("""### Price of insisting
The proposal asks what insisting on a requirement *costs*. With MRT bands this is now answerable directly:
**the minimum budget at which the household can still get a full shortlist of k options**, with and without
the requirement.""")
code("""def min_budget_for_k(extra):
    sw = sv2.sweep({**base, **extra}, "budget", range(400_000, 1_200_001, 10_000), upper_factors=bands12)
    ok = sw[sw["k_satisfied"]]
    return ok["budget"].min() if len(ok) else np.nan
rows = []
for label, extra in [("baseline (MRT, lease as soft goals)", {}), ("insist on Mid or better (≤800m)", {"max_mrt_band": "Mid"}),
                     ("insist on Near (≤400m)", {"max_mrt_band": "Near"}), ("insist on lease ≥ 80 yrs", {"min_lease_yrs": 80}),
                     ("insist on Near AND lease ≥ 80", {"max_mrt_band": "Near", "min_lease_yrs": 80})]:
    rows.append({"requirement": label, "min_budget_for_5_options": min_budget_for_k(extra)})
poi = pd.DataFrame(rows)
poi["price_of_insisting_sgd"] = poi["min_budget_for_5_options"] - poi["min_budget_for_5_options"].iloc[0]
poi""")

# ---------------- 9 backtest
md("""## 9. Backtest — 6 cutoffs × 3 households
At each cutoff (2023-01 … 2025-07) profiles **and the hedonic** are rebuilt from data available then; picks are
scored on what actually happened 12 months later. Results come from `backtest_v2.py` (≈25 min to regenerate:
`python backtest_v2.py`, then `run_v2_variant(...)` for iteration 2).""")
code("""bt = pd.read_csv(os.path.join(DATA, "backtest_v2_results_iter2.csv"))
label = {"naive_cheapest_towns": "naive", "v1_town_level": "v1 town", "v2_block_informed": "v2 iter1 (stub band)",
         "v2_block_informed_empirical_band": "v2 iter2 (empirical band)"}
bt["strategy"] = bt["strategy"].map(label)
from backtest_v2 import summarise
s = summarise(bt); s""")

code("""fig, axes = plt.subplots(1, 2, figsize=(15, 4.5))
wb = bt.groupby(["household", "strategy"])["within_budget"].mean().unstack()
wb.plot(kind="bar", ax=axes[0], color=["#8497b0", "#2f5496", "#f4b183", "#c00000"])
axes[0].set_ylim(0.8, 1.01); axes[0].set_title("Share of picks still within budget 12 months later"); axes[0].tick_params(axis="x", rotation=10)
mk = bt.groupby(["household", "strategy"])["pick_mrt_km"].median().unstack()
mk.plot(kind="bar", ax=axes[1], color=["#8497b0", "#2f5496", "#f4b183", "#c00000"], legend=False)
axes[1].set_title("Median MRT distance of picks (km)"); axes[1].tick_params(axis="x", rotation=10)
plt.tight_layout(); plt.show()""")

code("""bt["realised_chg_pct"] = (bt["realised_price"] / bt["price_at_cutoff"] - 1) * 100
bt["price_to_budget"] = bt["price_at_cutoff"] / bt["budget"]
print("Remaining / earlier failures:")
bt[bt["within_budget"] == 0][["cutoff", "household", "strategy", "profile", "price_to_budget", "realised_chg_pct",
                              "matched_sales_in_window"]].round(3)""")

code("""b_all = eb.empirical_growth_bands(tx[tx["flat_type"] != "MULTI-GENERATION"], horizon=12)
b_all = b_all[b_all["n_obs"] >= 100]
fig, ax = plt.subplots(figsize=(9, 4))
for band, col in [("Near", "#548235"), ("Mid", "#bf8f00"), ("Far", "#c00000")]:
    s = b_all[b_all["mrt_band"].astype(str) == band]
    ax.plot(s["flat_type"], (s["growth_factor_upper"] - 1) * 100, "o-", color=col, label=f"{band}: empirical p90")
ax.axhline(15, color="black", ls="--", label="stub band (+15%)")
ax.set_ylabel("12-month upper band (%)"); ax.legend(fontsize=8)
ax.set_title("Why iteration 2 was needed: finer cells move more than the town-level stub assumed")
plt.tight_layout(); plt.show()""")

# ---------------- 10
md("""## 10. Conclusions, limitations, handoff notes

**What block-level geocoding bought us**
- 63–96% of accessibility variation is within towns; town centroids discarded most of it.
- Block accessibility explains price beyond town (adj R² 0.918 → 0.935; out-of-time MAPE 16.1% → 15.6%);
  MRT proximity is worth ≈1.1% per 100m within a town, with a clean monotone gradient.
- At the recommender level: for a transit-reliant household, picks are **~60% closer to MRT** than v1's,
  at the same budget, with **lower price dispersion** for the buyer — and v2 correctly does *not* buy MRT
  access for a car owner.
- The cost: finer profiles are noisier. With a granularity-aware price band (iteration 2), within-budget
  robustness recovers to 98.8% (v1: 100%); ~5% of finer profiles see no matching sale within the window —
  predicted by the availability model (§7.1) and surfaced as `p_no_matching_sale_3m` / expected wait.
- School access as MOE tiers: SAP/GEP within 2km ≈ +2.5–3%, now the market rate for the school goal.

**Limitations**
- Hedonic and profile distances are straight-line. OSM walking distances were computed for every block, but
  OSM under-maps HDB-estate crossings/linkways, and walking distance did not explain price better (§3.4).
  They are kept as `walk_*` columns for display and robustness, not as the model input.
- Rail access is date-aware at month resolution (a station opening mid-month counts from the next month);
  interchange stations are treated as open throughout because their older line was already running.
- SAP/GEP is a proxy for "popular school"; P1 balloting data would be better.
- The hedonic is an interim stand-in for the Pricing & Availability Lead's model; linear school/childcare
  distance coefficients are not used.
- Availability is still a stub (Poisson arrival of matching sales), pending KM/Cox PH.

**Handoff notes**
- *Pricing & Availability:* `transactions_block_access.parquet` already joins every sale to block accessibility;
  `housing_profiles_v2_full.csv` carries dwelling-unit exposure per profile for the survival model.
- *Forecasting:* please report interval coverage at **G2 granularity**; `empirical_bands.py` is the benchmark
  your SARIMAX intervals should beat (target: ≥90% coverage, narrower than the empirical band).
- *Preference:* conjoint WTP plugs in as household multipliers relative to `market_wtp_coefficients.json`
  (revealed WTP) — the gap between stated and revealed WTP is itself a reportable finding.
""")

nb["cells"] = cells
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Optimisation_Lead_Pipeline_v2_BlockLevel.ipynb")
nbf.write(nb, open(out_path, "w", encoding="utf-8"))
print("written", len(cells), "cells")

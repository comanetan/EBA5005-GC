"""Five-region, 4-room location-adjusted comparison. Retrospective v1-style experiment.

Static amenity snapshots are an explicit limitation, not historical as-of features.
No production/UI model or shared handover is replaced.
"""
from pathlib import Path
import json
import hashlib
import numpy as np
import pandas as pd
from .compare_sarimax_rates import DATES, SPECS, refit_index, run_forecast
from .prepare_mas_rates import parse_mas, prepare_monthly, SOURCE

BASE = Path(__file__).resolve().parent
FEATURES = BASE / "outputs/location_inputs/processed/resale_features.csv"
OUT = BASE / "outputs/regional_location"
REGIONS = ["NORTH", "NORTH-EAST", "EAST", "WEST", "CENTRAL"]
CONTROLS = ["log_dist_mrt", "log_dist_hawker", "log_dist_park", "n_primary_1km", "n_chas_500m", "n_preschool_500m"]


def load_features():
    d = pd.read_csv(FEATURES, low_memory=False)
    d["month"] = pd.to_datetime(d.month)
    d = d[d.flat_type.eq("4 ROOM") & d.month.between(DATES[0],DATES[-1]) & ~d.flat_model.eq("Terrace")].copy()
    # Deliberately ignore psm_outlier: generated with full-year information.
    d["lease"] = d.remaining_lease_yrs
    d["storey"] = d.storey_mid
    d["lease2"] = d.lease**2 / 100
    d["log_area"] = np.log(d.floor_area_sqm)
    for target, source in [("log_dist_mrt","dist_mrt_at_sale_m"), ("log_dist_hawker","dist_hawker_m"),
                           ("log_dist_park","dist_park_m")]:
        d[target] = np.log1p(d[source])
    required = ["lease", "storey", "log_area", "resale_price", *CONTROLS]
    good = np.isfinite(d[required]).all(axis=1) & d.resale_price.gt(0)
    audit = d.assign(complete_location_features=good).groupby("region").agg(
        transaction_rows=("month","size"), complete_rows=("complete_location_features","sum"))
    audit["excluded_rows"] = audit.transaction_rows-audit.complete_rows
    audit.to_csv(OUT / "feature_coverage.csv")
    return d.loc[good].copy()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    d=load_features()
    rates=prepare_monthly(parse_mas(SOURCE)); rates.index=pd.to_datetime(rates.month)
    models=["naive","seasonal_naive",*SPECS,*(m+"_SORA" for m in SPECS)]
    predictions=[]; logs=[]; indices=[]; eligibility=[]
    for region in REGIONS:
        frame=d[d.region.eq(region)]
        counts=frame.groupby("month").size().reindex(DATES,fill_value=0)
        eligible=bool(counts.iloc[:69].gt(0).all() and counts.iloc[:69].median()>=10)
        eligibility.append(dict(region=region,eligible=eligible,initial_median_n=float(counts.iloc[:69].median()),
                                full_minimum_n=int(counts.min()),missing_months=int(counts.eq(0).sum())))
        if not eligible: continue
        for end_i in [69,81,93,105]:
            origin,end=DATES[end_i-1],DATES[end_i+11]
            stage="validation" if end_i<105 else "later_period_check"
            try: train,actual=refit_index(frame,origin,end,extra_controls=CONTROLS)
            except Exception as exc:
                logs.append(dict(region=region,origin=str(origin.date()),model="INDEX",error=str(exc)))
                continue
            for kind,series in [("training",train),("evaluation_frozen_coefficients",actual)]:
                indices.extend(dict(region=region,origin=str(origin.date()),month=str(date.date()),kind=kind,index=float(value))
                               for date,value in series.items())
            for name in models:
                print(f"{region} {origin:%Y-%m}: {name}",flush=True)
                try:
                    forecast,info=run_forecast(train,rates,name,actual.index)
                    logs.append(dict(region=region,origin=str(origin.date()),model=name,**info))
                    for h,(month,row) in enumerate(forecast.iterrows(),1):
                        predictions.append(dict(region=region,flat_type="4 ROOM",stage=stage,model=name,origin=str(origin.date()),
                                                month=str(month.date()),horizon=h,actual_index=float(actual.loc[month]),**row.to_dict()))
                except Exception as exc: logs.append(dict(region=region,origin=str(origin.date()),model=name,error=str(exc)))
            # Save incremental progress, so interrupted work is inspectable.
            pd.DataFrame(predictions).to_csv(OUT / "predictions.csv",index=False)
            pd.DataFrame(logs).to_csv(OUT / "fit_log.csv",index=False)
    pd.DataFrame(eligibility).to_csv(OUT / "segment_eligibility.csv",index=False)
    pd.DataFrame(indices).to_csv(OUT / "origin_specific_indices.csv",index=False)
    pred=pd.DataFrame(predictions)
    metrics=[]
    for (region,stage,model),g in pred.groupby(["region","stage","model"]):
        for window,s in [("months_1_to_12",g),("month_6",g[g.horizon==6]),("month_12",g[g.horizon==12])]:
            error=(s.forecast_index-s.actual_index).abs()
            metrics.append(dict(region=region,stage=stage,model=model,window=window,n=len(s),
                                MAPE_pct=float((error/s.actual_index).mean()*100),
                                coverage90_pct=float(s.actual_index.between(s.lower90,s.upper90).mean()*100),
                                interval_width_pct=float(((s.upper90-s.lower90)/s.actual_index).mean()*100)))
    metrics=pd.DataFrame(metrics);metrics.to_csv(OUT / "metrics_by_region.csv",index=False)
    complete=metrics[(metrics.stage=="validation") & (metrics.window=="months_1_to_12") & metrics.n.eq(36)]
    selected=complete.sort_values(["region","MAPE_pct","model"]).groupby("region").head(1)
    selected.to_csv(OUT / "validation_selected_models.csv",index=False)
    full=metrics[metrics.window.eq("months_1_to_12")].copy()
    full["expected_n"]=np.where(full.stage.eq("validation"),36,12)
    matched=full[full.n.eq(full.expected_n)]
    aggregate=matched.groupby(["stage","model"]).agg(regions=("region","nunique"),
             mean_region_MAPE_pct=("MAPE_pct","mean"), mean_region_coverage90_pct=("coverage90_pct","mean"))
    aggregate["all_five_regions_complete"]=aggregate.regions.eq(5)
    aggregate.to_csv(OUT / "aggregate_metrics.csv")
    manifest=dict(target="origin-refitted location-adjusted regional 4-room index",controls=CONTROLS,
                  features_sha256=hashlib.sha256(FEATURES.read_bytes()).hexdigest(),
                  source_rate_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                  limitations=["Static current amenity snapshots held fixed historically; not a fully as-of feature set.",
                               "MRT is opening-date aware but depends on supplied opening dates/current exit coordinates.",
                               "Raw data historical vintages and original compounded-rate publication history not reconstructed.",
                               "Time-dummy coefficients refitted at each origin; no full-year outlier exclusions.",
                               "Last known interest rate held constant in future forecasts; interval omits rate-scenario uncertainty.",
                               "Same recent year seen earlier; not a pristine final project holdout.",
                               "Only 4-room flats across five regions. No LSTM, joint paths or UI deployment in this stage."])
    (OUT / "manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    assert (pd.to_datetime(pred.month)>pd.to_datetime(pred.origin)).all()
    assert (pred.lower90<=pred.forecast_index).all() and (pred.forecast_index<=pred.upper90).all()
    print(aggregate.to_string());print("Selected by validation:");print(selected[["region","model","MAPE_pct"]].to_string(index=False))


if __name__=="__main__":main()

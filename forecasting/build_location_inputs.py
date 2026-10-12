"""Reuse team feature engineering with ALL generated files redirected locally.

No shared data/processed or outputs files are overwritten. No geocoding/network calls.
"""
from pathlib import Path
import importlib.util
import runpy
import sys
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
LOCAL = Path(__file__).resolve().parent / "outputs/location_inputs"


def main():
    LOCAL.mkdir(parents=True, exist_ok=True)
    shared = list((ROOT / "outputs").glob("*"))
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in shared if p.is_file()}
    spec = importlib.util.spec_from_file_location("config", ROOT / "src/config.py")
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    config.INTERIM = LOCAL / "interim"
    config.PROCESSED = LOCAL / "processed"
    config.OUTPUTS = LOCAL / "unused_team_outputs"
    for folder in [config.INTERIM, config.PROCESSED, config.OUTPUTS]: folder.mkdir(exist_ok=True)
    for attribute, name in [("UNIQUE_ADDR", "unique_addresses.csv"), ("PRIMARY_SCHOOLS", "primary_schools.csv"),
                            ("AMENITY_POINTS", "amenity_points.csv"), ("RESALE_CLEAN", "resale_clean.csv")]:
        setattr(config, attribute, config.INTERIM / name)
    config.VALIDATION_REPORT = LOCAL / "validation_report.md"
    # Keep the original shared geocode cache as a read-only input.
    previous = sys.modules.get("config")
    sys.modules["config"] = config
    try:
        for script in ["01_unique_addresses.py", "01b_clean_resale.py", "03_amenity_points.py", "04_build_features.py"]:
            print(f"Building local copy: {script}", flush=True)
            runpy.run_path(str(ROOT / "src" / script), run_name="__main__")
    finally:
        if previous is None: sys.modules.pop("config", None)
        else: sys.modules["config"] = previous
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in shared if p.is_file()}
    if before != after: raise RuntimeError("Shared files changed unexpectedly.")
    manifest = {"shared_outputs_unchanged": True,
                "features": str(config.PROCESSED / "resale_features.csv"),
                "limitations": ["Static amenity snapshots are not historical opening/closure histories.",
                                "MRT opening dates and current exit geometry inherit team source assumptions.",
                                "Year-based psm_outlier flags are generated but MUST NOT be used in historical fits."]}
    (LOCAL / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Local feature build complete; shared outputs unchanged.")


if __name__ == "__main__": main()

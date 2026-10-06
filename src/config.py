"""Shared paths and constants. Every script imports from here, so file names live in one place."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW, INTERIM, PROCESSED, OUTPUTS = (ROOT / "data" / "raw", ROOT / "data" / "interim",
                                    ROOT / "data" / "processed", ROOT / "outputs")

# Raw downloads (names exactly as downloaded from data.gov.sg)
RESALE      = RAW / "ResaleflatpricesbasedonregistrationdatefromJan2017onwards.csv"
PROPINFO    = RAW / "HDBPropertyInformation.csv"
SCHOOLS     = RAW / "Generalinformationofschools.csv"
MRT_EXITS   = RAW / "LTAMRTStationExitGEOJSON.geojson"
HAWKERS     = RAW / "HawkerCentresGEOJSON.geojson"
CHAS        = RAW / "CHASClinics.geojson"
PRESCHOOLS  = RAW / "PreSchoolsLocation.geojson"
MRT_OPENINGS = RAW / "mrt_station_openings.csv"     # hand-made: stations opened since 2017 (+ ones missing from the exit file)
POLYCLINICS = RAW / "polyclinics.csv"               # hand-made: name, postal_code
SUPERMARKETS_GLOB = "*upermarket*.csv"              # data.gov.sg supermarket listing (any file name containing "supermarket")
PARKS_GLOB = "Parks*.geojson"                       # data.gov.sg NParks "Parks" (GEOJSON)

# Interim files produced by the pipeline
UNIQUE_ADDR      = INTERIM / "unique_addresses.csv"
PRIMARY_SCHOOLS  = INTERIM / "primary_schools.csv"
GEOCODE_CACHE    = INTERIM / "geocode_cache.csv"
AMENITY_POINTS   = INTERIM / "amenity_points.csv"

# Processed outputs
RESALE_FEATURES  = PROCESSED / "resale_features.csv"
BLOCK_FEATURES   = PROCESSED / "block_features.csv"
PROFILES         = OUTPUTS / "profiles.csv"          # shared handover file (see README)

# Profile bands agreed in the proposal (edit here only, everyone reads them from this file)
LEASE_BANDS  = [(0, 60, "<60"), (60, 80, "60-79"), (80, 100, "80+")]          # remaining lease, years
MRT_BANDS    = [(0, 500, "<500m"), (500, 1000, "500m-1km"), (1000, 1e9, ">1km")]  # metres to nearest exit
STOREY_BANDS = [(0, 7, "1-6"), (7, 13, "7-12"), (13, 1e3, "13+")]               # storey-range midpoint
SCHOOL_RADIUS_M = 1000
AMENITY_RADIUS_M = 500

# Cleaned resale data + validation report (step 1b)
RESALE_CLEAN = INTERIM / "resale_clean.csv"
VALIDATION_REPORT = ROOT / "docs" / "validation_report.md"

# Regions used for the price index (URA planning regions, grouped by HDB town)
REGIONS = {
    "NORTH": ["SEMBAWANG", "WOODLANDS", "YISHUN"],
    "NORTH-EAST": ["ANG MO KIO", "HOUGANG", "PUNGGOL", "SENGKANG", "SERANGOON"],
    "EAST": ["BEDOK", "PASIR RIS", "TAMPINES"],
    "WEST": ["BUKIT BATOK", "BUKIT PANJANG", "CHOA CHU KANG", "CLEMENTI", "JURONG EAST", "JURONG WEST"],
    "CENTRAL": ["BISHAN", "BUKIT MERAH", "BUKIT TIMAH", "CENTRAL AREA", "GEYLANG", "KALLANG/WHAMPOA",
                "MARINE PARADE", "QUEENSTOWN", "TOA PAYOH"],
}

# Flat-model families (rare variants folded into their parent design)
FLAT_MODEL_GROUPS = {
    "Model A": "Model A", "Model A2": "Model A", "Improved": "Improved", "New Generation": "New Generation",
    "Simplified": "Simplified", "Standard": "Standard", "Premium Apartment": "Premium Apartment",
    "Premium Apartment Loft": "Premium Apartment", "Apartment": "Apartment", "DBSS": "DBSS",
    "Maisonette": "Maisonette", "Model A-Maisonette": "Maisonette", "Improved-Maisonette": "Maisonette",
    "Premium Maisonette": "Maisonette", "Type S1": "Type S", "Type S2": "Type S", "2-room": "2-room",
    "Adjoined flat": "Adjoined", "Terrace": "Terrace", "Multi Generation": "Multi-generation", "3Gen": "Multi-generation",
}

# Out of scope for profiles and the index: too rare, or not comparable to ordinary flats
OUT_OF_SCOPE_FLAT_TYPES = ["1 ROOM", "MULTI-GENERATION"]
OUT_OF_SCOPE_FLAT_MODELS = ["Terrace"]

# LTA's exit file lists some stations by code instead of name (checked against exit coordinates, 3 Oct 2026)
MRT_CODE_NAMES = {"CC30": "KEPPEL", "CC31": "CANTONMENT", "CC32": "PRINCE EDWARD ROAD", "CC9": "PAYA LEBAR",
                  "DT18": "TELOK AYER", "DT4": "HUME", "NE18": "PUNGGOL COAST"}

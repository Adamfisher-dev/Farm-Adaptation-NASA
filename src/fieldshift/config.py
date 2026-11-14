"""Project settings: region, paths, years, NASA POWER parameters and thresholds.

No Streamlit here. Every other module reads its settings from this file,
so a value is changed in one place only.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (repo root = two levels above src/fieldshift/)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"          # gitignored: full downloads
POWER_DIR = DATA_RAW / "power"
SAMPLE_DIR = ROOT / "sample_data"         # committed: copies for demo fields
CONTENT_DIR = ROOT / "content"

# ---------------------------------------------------------------------------
# Region: Story County, Iowa
# ---------------------------------------------------------------------------
COUNTY = {
    "name": "Story County, Iowa",
    "fips": "19169",
    "ssurgo_area": "IA169",                # (verify)
}
# Approximate bounding box (lon_min, lat_min, lon_max, lat_max).
# Replace with the TIGER boundary's total_bounds once downloaded.
COUNTY_BBOX = (-93.70, 41.86, -93.23, 42.21)

EXAMPLE_POINTS = {                         # from CLAUDE.md, Appendix A
    "centre": (42.03, -93.47),
    "nw": (42.18, -93.66),
    "se": (41.89, -93.26),
}

# ---------------------------------------------------------------------------
# Years
# ---------------------------------------------------------------------------
START_YEAR = 1981
END_YEAR = 2025          # last complete year; POWER advises ending trend work
                         # about 2 months behind real time
RECENT_YEARS = 15        # snapshot "recent climate" window

# ---------------------------------------------------------------------------
# NASA POWER
# ---------------------------------------------------------------------------
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_COMMUNITY = "AG"
POWER_PARAMETERS = [
    "T2M", "T2M_MAX", "T2M_MIN", "T2MDEW", "RH2M", "WS2M", "PS",
    "PRECTOTCORR", "ALLSKY_SFC_SW_DWN", "CLRSKY_SFC_SW_DWN",
    "GWETTOP", "GWETROOT",
]
# Parameters per API call. If POWER rejects a call, lower this number.
POWER_MAX_PARAMS_PER_CALL = 10
POWER_FILL_VALUE = -999.0

# Units we expect for the AG community. load_power() compares these with the
# units in the response metadata and warns on any mismatch. (verify)
EXPECTED_UNITS = {
    "T2M": "C", "T2M_MAX": "C", "T2M_MIN": "C", "T2MDEW": "C",
    "RH2M": "%", "WS2M": "m/s", "PS": "kPa",
    "PRECTOTCORR": "mm/day",
    "ALLSKY_SFC_SW_DWN": "MJ/m^2/day", "CLRSKY_SFC_SW_DWN": "MJ/m^2/day",
    "GWETTOP": "1", "GWETROOT": "1",
}

# POWER meteorology comes from the MERRA-2 grid: 0.5 deg latitude x 0.625 deg
# longitude. We assume cell centres sit on multiples of those steps. (verify by
# fetching two nearby points and checking whether their values are identical)
MERRA2_LAT_STEP = 0.5
MERRA2_LON_STEP = 0.625

# ---------------------------------------------------------------------------
# Snapshot indicator thresholds (starting values: check against Iowa State
# Extension and cite the one used)
# ---------------------------------------------------------------------------
GDD_BASE_C = 10.0        # corn method: base 10 C (50 F)
GDD_CAP_C = 30.0         # cap 30 C (86 F); both Tmax and Tmin clipped to [10, 30]
FROST_C = 0.0            # frost day: Tmin <= 0 C
DRY_DAY_MM = 1.0         # dry day: < 1 mm
HOT_DAY_C = 30.0         # hot day: Tmax > 30 C
HEAVY_RAIN_MM = 25.0     # heavy-rain day: > 25 mm

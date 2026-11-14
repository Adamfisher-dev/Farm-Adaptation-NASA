"""terrain.py - slope for one field from NASA SRTM 1 arc-second elevation (~30 m).

Inputs : SRTM GL1 tiles in data/raw/srtm (.hgt, .hgt inside .zip, or .tif)
Method : mosaic tiles -> slope per cell (metres per metre from elevation differences,
         cell size converted from degrees to metres at the field's latitude)
         -> mean and 90th percentile slope inside the field
Output : dict with slope_pct_mean, slope_pct_p90, slope class, erosion_prone, rusle_s

    from fieldshift.data.terrain import field_slope
    slope = field_slope(field_polygon_wgs84)

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np

from fieldshift import config

ROOT = Path(__file__).resolve().parents[3]
RAW = getattr(config, "DATA_RAW", ROOT / "data" / "raw")
SRTM_DIR = RAW / "srtm"

# NRCS-style slope classes used in SSURGO map-unit names (A 0-2 %, B 2-5 %, C 5-9 %, D 9 %+)
SLOPE_CLASSES = [(2.0, "A: nearly level (0-2%)"), (5.0, "B: gently sloping (2-5%)"),
                 (9.0, "C: moderately sloping (5-9%)"), (float("inf"), "D+: strongly sloping (9%+)")]
EROSION_PRONE_P90_PCT = 5.0    # flag when the steeper 10% of the field is over 5 % (starting value, verify)


def _tile_paths(folder: Path = SRTM_DIR):
    paths = []
    for p in sorted(folder.glob("*")):
        if p.suffix.lower() in (".hgt", ".tif", ".tiff"):
            paths.append(str(p))
        elif p.suffix.lower() == ".zip":
            import zipfile
            with zipfile.ZipFile(p) as z:
                inner = [n for n in z.namelist() if n.lower().endswith(".hgt")]
            paths += [f"zip://{p}!/{n}" for n in inner]
    if not paths:
        raise FileNotFoundError(f"No SRTM tiles in {folder}. Run scripts/prefetch_field_data.py.")
    return paths


@lru_cache(maxsize=1)
def load_dem(folder: str = str(SRTM_DIR)):
    """Mosaic of all tiles: (elevation array with NaN for voids, affine transform)."""
    import rasterio
    from rasterio.merge import merge
    sources = [rasterio.open(p) for p in _tile_paths(Path(folder))]
    try:
        mosaic, transform = merge(sources)
        nodata = sources[0].nodata
    finally:
        for s in sources:
            s.close()
    dem = mosaic[0].astype(float)
    if nodata is not None:
        dem[dem == nodata] = np.nan
    dem[dem < -1000] = np.nan                      # SRTM void value is -32768
    return dem, transform


def slope_percent(dem, transform, lat_deg):
    """Slope [%] per cell for a DEM in geographic coordinates (degrees)."""
    m_per_deg_lat = 110_540.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat_deg))
    dx = abs(transform.a) * m_per_deg_lon
    dy = abs(transform.e) * m_per_deg_lat
    dz_dy, dz_dx = np.gradient(dem, dy, dx)
    return np.hypot(dz_dx, dz_dy) * 100.0


def slope_class(pct):
    for limit, label in SLOPE_CLASSES:
        if pct < limit:
            return label
    return SLOPE_CLASSES[-1][1]


def rusle_s_factor(pct):
    """RUSLE slope-steepness factor S (McCool et al. 1987). Verify before quoting."""
    theta = math.atan(pct / 100.0)
    return 10.8 * math.sin(theta) + 0.03 if pct < 9 else 16.8 * math.sin(theta) - 0.50


def field_slope(field_geom, dem=None, transform=None):
    """Slope summary inside a field polygon (shapely, WGS84)."""
    from rasterio.features import geometry_mask
    if dem is None:
        dem, transform = load_dem()
    slope = slope_percent(dem, transform, field_geom.centroid.y)
    inside = ~geometry_mask([field_geom.__geo_interface__], out_shape=dem.shape,
                            transform=transform, all_touched=True)
    values = slope[inside & np.isfinite(slope)]
    if values.size == 0:
        raise ValueError("Field is outside the downloaded SRTM tiles (or all cells are voids).")
    mean, p90 = float(values.mean()), float(np.percentile(values, 90))
    return {
        "slope_pct_mean": round(mean, 2),
        "slope_pct_p90": round(p90, 2),
        "slope_class": slope_class(mean),
        "erosion_prone": p90 > EROSION_PRONE_P90_PCT,
        "rusle_s": round(rusle_s_factor(mean), 3),
        "n_cells": int(values.size),
        "source": "NASA SRTM GL1 v003 (1 arc-second, ~30 m)",
    }

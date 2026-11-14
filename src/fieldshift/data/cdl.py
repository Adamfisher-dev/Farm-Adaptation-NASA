"""cdl.py - what was grown on a field each year, from the USDA Cropland Data Layer (CDL).

Inputs : county CDL GeoTIFFs in data/raw/cdl, named cdl_{year}_{fips}.tif (30 m crop classes)
Method : majority crop class inside the field polygon, per year
Output : crop history {year: crop} + a guessed rotation in crops.py format for the farmer to confirm

    from fieldshift.data.cdl import crop_history, guess_rotation
    hist = crop_history(field_polygon_wgs84)          # {"2019": "corn", "2020": "soybean", ...}
    rotation, text = guess_rotation(hist)              # [["corn"], ["soybean"]], "We see corn, soybean, ..."

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from fieldshift import config

ROOT = Path(__file__).resolve().parents[3]
RAW = getattr(config, "DATA_RAW", ROOT / "data" / "raw")
CDL_DIR = RAW / "cdl"
_county = getattr(config, "COUNTY", None)
FIPS = _county.get("fips", "19169") if isinstance(_county, dict) else "19169"   # Story County, Iowa

# CDL class codes -> names used in crops.py (verify against the CDL legend)
CDL_TO_CROP = {
    1: "corn", 5: "soybean", 24: "winter_wheat", 27: "cereal_rye", 28: "oats",
    36: "alfalfa", 37: "other_hay", 26: "winter_wheat_then_soybean",
    61: "fallow", 176: "grass_pasture",
}
NON_FIELD = {111, 121, 122, 123, 124, 141, 142, 143, 190, 195}   # water, developed, forest, wetlands
CDL_FILE = re.compile(r"cdl_(\d{4})_(\d+)\.tif$", re.I)


def available_years(folder: Path = CDL_DIR, fips: str = FIPS):
    years = {}
    for p in folder.glob("*.tif"):
        m = CDL_FILE.search(p.name)
        if m and m.group(2) == fips:
            years[int(m.group(1))] = p
    if not years:
        raise FileNotFoundError(f"No CDL files cdl_<year>_{fips}.tif in {folder}. "
                                "Run scripts/prefetch_field_data.py.")
    return dict(sorted(years.items()))


def majority_class(path, field_geom):
    """(most common CDL code inside the field, its share of the field's cells)."""
    import geopandas as gpd
    import rasterio
    from rasterio.mask import mask
    with rasterio.open(path) as src:
        geom = gpd.GeoSeries([field_geom], crs="EPSG:4326").to_crs(src.crs).iloc[0]
        data, _ = mask(src, [geom.__geo_interface__], crop=True, all_touched=True, filled=False)
    values = data[0].compressed() if np.ma.isMaskedArray(data[0]) else data[0].ravel()
    values = values[values > 0]
    if values.size == 0:
        return None, 0.0
    codes, counts = np.unique(values, return_counts=True)
    i = int(np.argmax(counts))
    return int(codes[i]), float(counts[i] / counts.sum())


def crop_history(field_geom, years=None, folder: Path = CDL_DIR, fips: str = FIPS):
    """{year (str): crop name} plus a details list with code and share, newest last."""
    files = available_years(folder, fips)
    years = years or list(files)
    history, details = {}, []
    for y in years:
        if y not in files:
            continue
        code, share = majority_class(files[y], field_geom)
        name = CDL_TO_CROP.get(code, "not_cropland" if code in NON_FIELD else f"other_{code}")
        history[str(y)] = name
        details.append({"year": y, "code": code, "crop": name, "share": round(share, 2)})
    return history, details


def guess_rotation(history, last_n=6):
    """Guess the existing rotation from recent years, in crops.py format, plus a sentence to confirm.

    Recognises corn-soybean (either order), continuous corn and corn-corn-soybean;
    anything else is returned year by year for the farmer to correct.
    """
    items = sorted(history.items())[-last_n:]
    recent = [crop for _, crop in items]
    if not recent:
        return None, "What do you grow on this field now?"
    text = f"We see {', '.join(recent)} ({items[0][0]}-{items[-1][0]}). Is that right?"
    known = {"corn", "soybean", "oats", "winter_wheat", "alfalfa"}
    if any(c not in known for c in recent):
        return None, text + " Some years are not crops we model - please enter your rotation."

    def matches(pattern):
        n = len(pattern)
        return any(all(recent[i] == pattern[(i + k) % n] for i in range(len(recent))) for k in range(n))

    for pattern in (["corn", "soybean"], ["corn", "corn", "soybean"], ["corn"]):
        if matches(pattern):
            return [[c] for c in pattern], text
    return [[c] for c in recent[-3:]], text + " The pattern is irregular - please check the rotation."

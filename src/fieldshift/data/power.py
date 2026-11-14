"""NASA POWER daily weather for one POWER grid cell: fetch, clean, cache, load.

Getting and cleaning data only. No analysis here (that lives in model/).

Main entry point:

    from fieldshift.data.power import load_power
    df, meta = load_power(42.03, -93.47)

`df`   : one row per day (DatetimeIndex), one column per POWER parameter,
         missing values as NaN.
`meta` : dict with the POWER cell, units per parameter, unit warnings,
         where the data came from, and the share of missing values.
"""

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

from fieldshift import config


# ---------------------------------------------------------------------------
# The POWER grid cell a point falls in
# ---------------------------------------------------------------------------

def power_cell(lat, lon):
    """Centre, bounds and id of the MERRA-2 cell containing (lat, lon).

    Every field in the same cell gets identical weather. The bounds are used
    to draw the cell outline on the map.
    """
    lat_step, lon_step = config.MERRA2_LAT_STEP, config.MERRA2_LON_STEP
    c_lat = round(round(lat / lat_step) * lat_step, 4)
    c_lon = round(round(lon / lon_step) * lon_step, 4)
    bounds = [c_lon - lon_step / 2, c_lat - lat_step / 2, c_lon + lon_step / 2, c_lat + lat_step / 2]
    return {
        "centre": [c_lat, c_lon],
        "bounds": [round(b, 4) for b in bounds],   # [lon_min, lat_min, lon_max, lat_max]
        "id": f"{c_lat:.3f}_{c_lon:.3f}",
    }


def _paths(cell_id, folder):
    return folder / f"power_{cell_id}.csv", folder / f"power_{cell_id}_meta.json"


# ---------------------------------------------------------------------------
# Fetch from the API
# ---------------------------------------------------------------------------

def _fetch_batch(lat, lon, parameters, start, end):
    params = {
        "parameters": ",".join(parameters),
        "community": config.POWER_COMMUNITY,
        "latitude": lat,
        "longitude": lon,
        "start": f"{start}0101",
        "end": f"{end}1231",
        "format": "JSON",
    }
    r = requests.get(config.POWER_URL, params=params, timeout=600)
    if r.status_code != 200:
        # A bad parameter name shows up here: print r.text to see why.
        raise requests.HTTPError(f"POWER returned {r.status_code}: {r.text[:300]}")
    return r.json()


def fetch_power(lat, lon, start=config.START_YEAR, end=config.END_YEAR,
                parameters=config.POWER_PARAMETERS):
    """Download daily data from NASA POWER, in batches. Returns (df, meta)."""
    size = config.POWER_MAX_PARAMS_PER_CALL
    frames, units, longnames, geometry = [], {}, {}, None
    for i in range(0, len(parameters), size):
        batch = parameters[i:i + size]
        js = _fetch_batch(lat, lon, batch, start, end)
        frames.append(pd.DataFrame(js["properties"]["parameter"]))
        for name, info in js.get("parameters", {}).items():
            units[name] = info.get("units")
            longnames[name] = info.get("longname")
        geometry = geometry or js.get("geometry")

    df = pd.concat(frames, axis=1)
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df.index.name = "date"
    meta = {
        "requested_point": [lat, lon],
        "units": units,
        "longnames": longnames,
        "geometry": geometry,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "NASA POWER daily point API, community AG "
                  "(meteorology from GMAO MERRA-2; solar from CERES)",
    }
    return df, meta


# ---------------------------------------------------------------------------
# Clean and check
# ---------------------------------------------------------------------------

def _norm_unit(text):
    return (str(text).lower().replace("°", "").replace(" ", "")
            .replace("degrees", "").replace("deg", "").replace("**", "^"))


def check_units(units):
    """Compare response units with config.EXPECTED_UNITS. Returns warning strings."""
    warnings = []
    for name, expected in config.EXPECTED_UNITS.items():
        got = units.get(name)
        if got is None:
            warnings.append(f"{name}: no units in metadata")
        elif _norm_unit(got) != _norm_unit(expected):
            warnings.append(f"{name}: expected {expected}, got {got} - check before use")
    return warnings


def clean(df, start=config.START_YEAR, end=config.END_YEAR):
    """Fill value -999 -> NaN, full daily index, numeric types."""
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.mask(np.isclose(df, config.POWER_FILL_VALUE))
    full = pd.date_range(f"{start}-01-01", f"{end}-12-31", freq="D", name="date")
    return df.sort_index().reindex(full)


# ---------------------------------------------------------------------------
# Cache and load
# ---------------------------------------------------------------------------

def save(df, meta, folder=config.POWER_DIR):
    folder.mkdir(parents=True, exist_ok=True)
    csv_path, meta_path = _paths(meta["cell"]["id"], folder)
    df.to_csv(csv_path)
    meta_path.write_text(json.dumps(meta, indent=2))
    return csv_path


def _read(folder, cell_id):
    csv_path, meta_path = _paths(cell_id, folder)
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path, index_col="date", parse_dates=True)
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"units": {}}
    return df, meta


def load_power(lat, lon, allow_download=True):
    """Daily POWER data for the cell containing (lat, lon).

    Order: data/raw/power (full cache) -> sample_data (committed copy of real POWER downloads)
    -> NASA POWER API (only if allow_download). Downloads are saved to the cache.
    """
    cell = power_cell(lat, lon)
    found, origin = None, None
    for folder, label in [(config.POWER_DIR, "saved download"), (config.SAMPLE_DIR, "saved download, committed")]:
        found = _read(folder, cell["id"])
        if found:
            origin = label
            break

    if found is None:
        if not allow_download:
            raise FileNotFoundError(
                f"No cached POWER data for cell {cell['id']}. "
                "Run scripts/prefetch_power.py or allow_download=True.")
        df, meta = fetch_power(cell["centre"][0], cell["centre"][1])
        meta["cell"] = cell
        save(df, meta)
        found, origin = (df, meta), "NASA POWER API"

    df, meta = found
    df = clean(df)
    meta["cell"] = cell
    meta["loaded_from"] = origin
    meta["unit_warnings"] = check_units(meta.get("units", {}))
    meta["missing_share"] = {c: round(float(df[c].isna().mean()), 4) for c in df.columns}
    return df, meta

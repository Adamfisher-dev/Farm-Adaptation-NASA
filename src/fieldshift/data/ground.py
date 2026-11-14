"""ground.py - ground measurements near the example fields, for validation (playbook 6.11).

Source: Iowa Environmental Mesonet (IEM, Iowa State University), free, no login.
  ISU Soil Moisture Network station AEEI4 (Ames - Horticulture ISU-RDF), daily since 2013-11:
      soil moisture at 30, 60 and 127 cm (12, 24, 50 inch probes), Vol %
  NWS cooperative climate station IA0203 (Ames 5 SE) via IEM Climodat, daily since 1900:
      max / min air temperature (degF), precipitation (inch)
Downloaded by scripts/prefetch_field_data.py ground into data/raw/ground/ (committed, small).

Output matches model/validation.py:
    from fieldshift.data.ground import load_station_weather, load_soil_moisture
    station = load_station_weather()          # tmax_c, tmin_c, precip_mm  (DatetimeIndex)
    obs = load_soil_moisture("60cm")          # Series, m3/m3, frozen-soil days removed
    validation.compare_weather(power_df, station)
    validation.compare_soil(daily["wetness_root"], obs, name="ISU probe 60 cm")

A probe measures one spot in one field ~10 km away; compare anomalies (wetter/drier than
normal), not absolute values (playbook 7.4).

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd

from fieldshift import config

ISUSM_FILE = config.GROUND_DIR / f"isusm_{config.ISUSM_STATION['id']}_daily.csv"
CLIMATE_FILE = config.GROUND_DIR / f"climate_{config.CLIMATE_STATION['id']}_daily.csv"
SOURCE = {
    "soil": f"ISU Soil Moisture Network station {config.ISUSM_STATION['id']} "
            f"({config.ISUSM_STATION['name']}), via Iowa Environmental Mesonet",
    "weather": f"NWS cooperative station {config.CLIMATE_STATION['id']} "
               f"({config.CLIMATE_STATION['name']}), via Iowa Environmental Mesonet Climodat",
}
FROZEN_F = 32.0        # probe temperature at or below freezing -> reading unreliable (liquid water only)
VWC_VALID = (0.0, 0.6)  # m3/m3


def _f_to_c(f):
    return (pd.to_numeric(f, errors="coerce") - 32.0) * 5.0 / 9.0


# --- Download (used by scripts/prefetch_field_data.py) ----------------------------------
def fetch_isusm(start=None, end=None, path: Path = ISUSM_FILE) -> Path:
    import requests
    st = config.ISUSM_STATION
    start = start or st["start"]
    end = end or f"{config.END_YEAR + 1}-01-01"
    r = requests.get(f"{config.IEM_URL}/isusm.py", timeout=300, params={
        "station": st["id"], "mode": "daily", "sts": f"{start}T00:00Z", "ets": f"{end}T00:00Z",
        "format": "comma", "missing": "M"})
    r.raise_for_status()
    if not r.text.startswith("station,"):
        raise ValueError(f"Unexpected IEM soil-moisture response: {r.text[:200]!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(r.text, encoding="utf-8")
    return path


def fetch_climate(first_year=config.START_YEAR, last_year=config.END_YEAR, path: Path = CLIMATE_FILE) -> Path:
    import requests
    st = config.CLIMATE_STATION
    r = requests.get(f"{config.IEM_URL}/coop.py", timeout=300, params={
        "station": st["id"], "network": st["network"], "year1": first_year, "month1": 1, "day1": 1,
        "year2": last_year, "month2": 12, "day2": 31, "what": "view", "delim": "comma",
        "vars": ["high", "low", "precip"]})
    r.raise_for_status()
    if "station" not in r.text[:2000]:
        raise ValueError(f"Unexpected IEM climate response: {r.text[:200]!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(r.text, encoding="utf-8")
    return path


# --- Parsing ------------------------------------------------------------------------------
def parse_climate(text: str) -> pd.DataFrame:
    """IEM Climodat CSV (comment lines start with '#') -> tmax_c, tmin_c, precip_mm per day."""
    body = "\n".join(line for line in text.splitlines() if line and not line.startswith("#"))
    raw = pd.read_csv(io.StringIO(body), na_values=["M", ""])
    idx = pd.to_datetime(raw["day"], format="%Y/%m/%d")
    out = pd.DataFrame({
        "tmax_c": _f_to_c(raw["high"]).to_numpy(),
        "tmin_c": _f_to_c(raw["low"]).to_numpy(),
        "precip_mm": (pd.to_numeric(raw["precip"], errors="coerce") * 25.4).to_numpy(),
    }, index=idx)
    out.loc[out["precip_mm"] < 0, "precip_mm"] = np.nan
    out.loc[out["precip_mm"] < 0.01, "precip_mm"] = 0.0           # trace (0.0001 inch) -> 0
    return out.sort_index().rename_axis("date")


def parse_isusm(text: str) -> pd.DataFrame:
    """IEM ISUSM daily CSV -> soil moisture (m3/m3) per depth, NaN on frozen or implausible days,
    plus the station's own tmax_c / tmin_c / precip_mm."""
    raw = pd.read_csv(io.StringIO(text), na_values=["M", ""])
    idx = pd.to_datetime(raw["valid"])
    out = pd.DataFrame(index=idx)
    for depth, (vwc_col, t_col) in config.ISUSM_DEPTHS.items():
        vwc = pd.to_numeric(raw.get(vwc_col), errors="coerce") / 100.0            # Vol % -> m3/m3
        temp = pd.to_numeric(raw.get(t_col), errors="coerce")
        ok = vwc.between(*VWC_VALID) & (temp.isna() | (temp > FROZEN_F))
        out[f"vwc_{depth}"] = vwc.where(ok).to_numpy()
    out["tmax_c"] = _f_to_c(raw["high"]).to_numpy()
    out["tmin_c"] = _f_to_c(raw["low"]).to_numpy()
    out["precip_mm"] = (pd.to_numeric(raw["precip"], errors="coerce") * 25.4).to_numpy()
    return out.sort_index().rename_axis("date")


# --- Loading -------------------------------------------------------------------------------
def _read(path: Path, step: str) -> str:
    if not Path(path).exists():
        raise FileNotFoundError(f"{path} not found. Run: python scripts/prefetch_field_data.py {step}")
    return Path(path).read_text(encoding="utf-8")


# NWS cooperative observers read their instruments once a day, often around 7 am. The "high" and
# the 24-hour rain written on a date then belong mostly to the PREVIOUS calendar day; the "low" is
# that morning's. Checked against NASA POWER (calendar days) for IA0203, 1981-2025: moving high and
# rain back one day raises daily rain correlation from 0.32 to 0.77 and lowers the Tmax error from
# 3.9 to 3.3 C; the low fits best unshifted. The automated ISU station needs no shift.
COOP_SHIFT_DAYS = {"tmax_c": -1, "precip_mm": -1, "tmin_c": 0}


def load_station_weather(path: Path = CLIMATE_FILE, align_to_calendar_day: bool = True) -> pd.DataFrame:
    """Daily tmax_c, tmin_c, precip_mm at the Ames 5 SE climate station (for compare_weather).
    align_to_calendar_day: undo the morning observation time (see COOP_SHIFT_DAYS)."""
    df = parse_climate(_read(path, "ground")).asfreq("D")
    if align_to_calendar_day:
        for col, days in COOP_SHIFT_DAYS.items():
            df[col] = df[col].shift(days)
    return df


def load_isusm_weather(path: Path = ISUSM_FILE) -> pd.DataFrame:
    """Daily tmax_c, tmin_c, precip_mm from the automated ISU station (calendar days, since 2013)."""
    return parse_isusm(_read(path, "ground"))[["tmax_c", "tmin_c", "precip_mm"]].asfreq("D")


def load_soil_moisture(depth: str = "60cm", path: Path = ISUSM_FILE) -> pd.Series:
    """Daily volumetric soil moisture (m3/m3) at one probe depth: '30cm', '60cm' or '127cm'."""
    if depth not in config.ISUSM_DEPTHS:
        raise ValueError(f"depth must be one of {list(config.ISUSM_DEPTHS)}")
    table = parse_isusm(_read(path, "ground"))
    return table[f"vwc_{depth}"].asfreq("D").rename(f"isusm_{depth}")

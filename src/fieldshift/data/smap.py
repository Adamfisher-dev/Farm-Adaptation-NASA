"""smap.py - NASA SMAP soil moisture at the example points (from AppEEARS CSVs).

Inputs : AppEEARS point-sample CSVs in data/raw/appeears/smap (scripts/prefetch_field_data.py)
           SPL3SMP_E.006  enhanced L3 radiometer retrieval, 9 km, daily AM + PM, top ~5 cm
           SPL4SMGP.008   L4 model + SMAP assimilation, 9 km, 3-hourly, surface and 0-100 cm
Method : drop fill values and out-of-range values; keep L3 retrievals only when
         retrieval_qual_flag bit 0 = 0 (recommended quality); average AM/PM (L3) and
         the 3-hourly steps (L4) to one value per day
Output : compact daily table sample_data/smap_daily.csv (committed, small):
           point_id, date, sm_surface_l3, sm_surface_l4, sm_rootzone_l4   [m3/m3]

    from fieldshift.data.smap import load_smap, seasonal_anomaly
    df = load_smap("flat_tiled")             # DatetimeIndex, one column per series
    anom = seasonal_anomaly(df["sm_rootzone_l4"])

What SMAP is and is not: a 9 km satellite footprint (L3) or model estimate constrained by
satellite data (L4), not a reading of one field. Use it to check whether the water model
gets wet and dry periods at the right time (anomaly correlation), not absolute values.

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from fieldshift import config
from fieldshift.data.appeears import find_column

RAW_DIR = config.APPEEARS_DIR / "smap"
SERIES = ["sm_surface_l3", "sm_surface_l4", "sm_rootzone_l4"]
SOURCE = (f"NASA SMAP {config.SMAP_L3} and {config.SMAP_L4} (9 km), "
          "via NASA AppEEARS point extraction")


# --- Reading AppEEARS CSVs ----------------------------------------------------------
def _clean_sm(values: pd.Series) -> pd.Series:
    v = pd.to_numeric(values, errors="coerce")
    lo, hi = config.SMAP_VALID
    return v.where((v != config.SMAP_FILL) & (v >= lo) & (v <= hi))


def _good_quality(flag: pd.Series) -> pd.Series:
    f = pd.to_numeric(flag, errors="coerce")
    ok = (f.notna() & (f != 65534)).to_numpy()          # 65534 = flag fill value
    bits = f.fillna(0).to_numpy().astype(np.int64)
    good = ((bits >> config.SMAP_QUAL_RECOMMENDED_BIT) & 1) == 0
    return pd.Series(ok & good, index=flag.index)


def parse_raw(csv_paths) -> pd.DataFrame:
    """Raw AppEEARS CSVs (any mix of L3 and L4 files) -> compact daily long table."""
    parts = []
    for path in csv_paths:
        raw = pd.read_csv(path)
        pid = raw[find_column(raw, "ID")].astype(str)
        day = pd.to_datetime(raw[find_column(raw, "Date")]).dt.normalize()
        cols = {}
        l3 = []
        for sm_layer, qa_layer in config.SMAP_L3_LAYERS.values():
            sm_col = find_column(raw, sm_layer, required=False)
            if sm_col is None:
                continue
            qa_col = find_column(raw, qa_layer, required=False)
            sm = _clean_sm(raw[sm_col])
            if qa_col is not None:
                sm = sm.where(_good_quality(raw[qa_col]))
            l3.append(sm)
        if l3:
            cols["sm_surface_l3"] = pd.concat(l3, axis=1).mean(axis=1)   # AM/PM mean
        for out_name, layer in config.SMAP_L4_LAYERS.items():
            col = find_column(raw, layer, required=False)
            if col is not None:
                cols[out_name] = _clean_sm(raw[col])
        if cols:
            parts.append(pd.DataFrame({"point_id": pid, "date": day, **cols}))
    if not parts:
        raise ValueError("No SMAP soil-moisture layers found in the AppEEARS CSVs.")
    long = pd.concat(parts, ignore_index=True)
    daily = long.groupby(["point_id", "date"]).mean(numeric_only=True).reset_index()
    for c in SERIES:
        if c not in daily:
            daily[c] = np.nan
    return daily[["point_id", "date"] + SERIES].sort_values(["point_id", "date"])


def build_compact(raw_dir: Path = RAW_DIR, out: Path = config.SMAP_DAILY_CSV, points=None) -> pd.DataFrame:
    """points: keep only these point ids (e.g. config.EXAMPLE_POINTS) - drops results of older requests."""
    paths = sorted(Path(raw_dir).glob("*.csv"))
    if not paths:
        raise FileNotFoundError(f"No AppEEARS SMAP CSVs in {raw_dir}. Run scripts/prefetch_field_data.py smap.")
    daily = parse_raw(paths)
    if points is not None:
        daily = daily[daily["point_id"].isin(list(points))]
    out.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(out, index=False, float_format="%.4f", date_format="%Y-%m-%d")
    return daily


# --- Using the compact table -----------------------------------------------------------
def load_smap(point_id: str = config.DEFAULT_POINT, path: Path = config.SMAP_DAILY_CSV) -> pd.DataFrame:
    """Daily SMAP series for one example point (DatetimeIndex; NaN = no good value)."""
    if not Path(path).exists():
        raise FileNotFoundError(f"{path} not found. Run scripts/prefetch_field_data.py smap.")
    df = pd.read_csv(path, parse_dates=["date"], dtype={"point_id": str})
    sel = df[df["point_id"] == point_id]
    if sel.empty:
        raise ValueError(f"No SMAP data for point {point_id!r}; have {sorted(df['point_id'].unique())}")
    return sel.set_index("date")[SERIES].asfreq("D")


def nearest_point(lat, lon, points=None) -> str:
    """Example point closest to (lat, lon); SMAP cells are 9 km, so only meaningful nearby."""
    points = points or config.EXAMPLE_POINTS
    return min(points, key=lambda k: (points[k][0] - lat) ** 2 + (points[k][1] - lon) ** 2)


def seasonal_anomaly(series: pd.Series, window_days: int = 31) -> pd.Series:
    """Departure from the mean for the same time of year (smoothed day-of-year climatology).
    Use for comparing with the water model: timing of wet/dry spells, not absolute levels."""
    s = series.astype(float)
    doy = np.minimum(s.index.day_of_year.to_numpy(), 365)
    clim = s.groupby(doy).mean().reindex(range(1, 366))
    wrapped = pd.concat([clim.iloc[-window_days:], clim, clim.iloc[:window_days]])
    smooth = wrapped.rolling(window_days, center=True, min_periods=5).mean().iloc[window_days:-window_days]
    return s - smooth.reindex(doy).to_numpy()

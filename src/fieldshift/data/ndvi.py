"""ndvi.py - field greenness (NDVI) from NASA HLS at the example fields (AppEEARS CSVs).

Inputs : AppEEARS point-sample CSVs in data/raw/appeears/hls (scripts/prefetch_field_data.py)
           HLSL30.020  Harmonized Landsat 8/9, 30 m   red B04, NIR B05,  Fmask
           HLSS30.020  Harmonized Sentinel-2,  30 m   red B04, NIR B8A,  Fmask
         Each example field is sampled at a 3 x 3 grid of pixels (sample_points()).
Method : drop pixels flagged in Fmask as cloud, adjacent to cloud, cloud shadow,
         snow/ice or water, or with high aerosol; NDVI = (NIR - red) / (NIR + red);
         a date counts for a field only if most of its pixels are clear, and the
         field value is the median of the clear pixels
Output : compact table sample_data/hls_ndvi.csv (committed, small):
           field, date, sensor, ndvi, n_clear

    from fieldshift.data.ndvi import load_ndvi, dekadal
    obs = load_ndvi("centre")          # one row per clear date
    ten_day = dekadal(obs["ndvi"])     # 10-day maximum-value composite

NDVI reads roughly 0.1-0.2 over bare soil and 0.7-0.9 over a dense crop canopy. It shows
when the field is green; it does not tell crop type, yield or soil health on its own.

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from fieldshift import config
from fieldshift.data.appeears import find_column

RAW_DIR = config.APPEEARS_DIR / "hls"
SOURCE = ("NASA Harmonized Landsat Sentinel-2 (HLS) v2.0, HLSL30 + HLSS30 (30 m), "
          "via NASA AppEEARS point extraction")


def sample_points(fields=None, n=config.HLS_GRID, spacing_m=config.HLS_SAMPLE_SPACING_M):
    """[(point_id, field, lat, lon)]: an n x n grid centred on each example field."""
    fields = fields or config.EXAMPLE_POINTS
    out = []
    offsets = [(i - (n - 1) / 2) * spacing_m for i in range(n)]
    for name, (lat, lon) in fields.items():
        k = 0
        for dy in offsets:
            for dx in offsets:
                out.append((f"{name}_{k}", name,
                            round(lat + dy / 110_540.0, 6),
                            round(lon + dx / (111_320.0 * math.cos(math.radians(lat))), 6)))
                k += 1
    return out


def clear_mask(fmask: pd.Series) -> pd.Series:
    """True where Fmask says the pixel is usable (bits checked against AppEEARS decoding)."""
    f = pd.to_numeric(fmask, errors="coerce")
    ok = (f.notna() & (f != config.HLS_FMASK_FILL)).to_numpy().copy()
    bits = f.fillna(0).to_numpy().astype(np.int64)
    for b in config.HLS_FMASK_BAD_BITS:
        ok &= ((bits >> b) & 1) == 0
    if config.HLS_DROP_HIGH_AEROSOL:
        ok &= ((bits >> 6) & 3) != 3
    return pd.Series(ok, index=fmask.index)


def _product_columns(raw: pd.DataFrame, product: str, layers):
    prefix = product.split(".")[0].lower()
    cols = []
    for layer in layers:
        hits = [c for c in raw.columns
                if prefix in c.lower() and c.lower().endswith("_" + layer.lower())]
        if len(hits) != 1:
            return None
        cols.append(hits[0])
    return cols


def parse_raw(csv_paths, min_clear_share: float = 0.5) -> pd.DataFrame:
    rows = []
    for path in csv_paths:
        raw = pd.read_csv(path)
        for product, layers in config.HLS_PRODUCTS.items():
            cols = _product_columns(raw, product, layers)
            if cols is None:
                continue
            red = pd.to_numeric(raw[cols[0]], errors="coerce")
            nir = pd.to_numeric(raw[cols[1]], errors="coerce")
            ok = clear_mask(raw[cols[2]]) & (red > 0) & (nir > 0)    # fill is -9999
            ndvi = ((nir - red) / (nir + red)).where(ok)              # scale factor cancels
            cat = find_column(raw, "Category", required=False)
            pid = raw[find_column(raw, "ID")].astype(str)
            fld = raw[cat].astype(str) if cat else pid.str.rsplit("_", n=1).str[0]
            rows.append(pd.DataFrame({
                "field": fld, "point_id": pid,
                "date": pd.to_datetime(raw[find_column(raw, "Date")]).dt.normalize(),
                "sensor": "Landsat" if product.startswith("HLSL") else "Sentinel-2",
                "ndvi": ndvi.clip(-1, 1),
            }))
    if not rows:
        raise ValueError("No HLS red/NIR/Fmask columns found in the AppEEARS CSVs.")
    px = pd.concat(rows, ignore_index=True)
    g = px.groupby(["field", "date", "sensor"])
    out = g["ndvi"].agg(ndvi="median", n_clear="count").reset_index()
    out["n_total"] = g["point_id"].nunique().to_numpy()
    out = out[out["n_clear"] >= np.ceil(min_clear_share * out["n_total"])]
    return out.drop(columns="n_total").sort_values(["field", "date", "sensor"]).reset_index(drop=True)


def build_compact(raw_dir: Path = RAW_DIR, out: Path = config.HLS_NDVI_CSV) -> pd.DataFrame:
    paths = sorted(Path(raw_dir).glob("*.csv"))
    if not paths:
        raise FileNotFoundError(f"No AppEEARS HLS CSVs in {raw_dir}. Run scripts/prefetch_field_data.py hls.")
    obs = parse_raw(paths)
    out.parent.mkdir(parents=True, exist_ok=True)
    obs.to_csv(out, index=False, float_format="%.4f", date_format="%Y-%m-%d")
    return obs


def load_ndvi(field: str = "centre", path: Path = config.HLS_NDVI_CSV) -> pd.DataFrame:
    """Clear-sky field NDVI observations for one example field (DatetimeIndex)."""
    if not Path(path).exists():
        raise FileNotFoundError(f"{path} not found. Run scripts/prefetch_field_data.py hls.")
    df = pd.read_csv(path, parse_dates=["date"])
    sel = df[df["field"] == field]
    if sel.empty:
        raise ValueError(f"No HLS NDVI for field {field!r}; have {sorted(df['field'].unique())}")
    return sel.set_index("date")[["sensor", "ndvi", "n_clear"]]


def dekadal(ndvi: pd.Series) -> pd.Series:
    """10-day maximum-value composite (days 1-10, 11-20, 21-end of each month).
    Taking the maximum suppresses leftover cloud and haze, which lower NDVI."""
    idx = ndvi.index
    start_day = np.select([idx.day <= 10, idx.day <= 20], [1, 11], 21)
    key = pd.to_datetime({"year": idx.year, "month": idx.month, "day": start_day})
    return ndvi.groupby(key.to_numpy()).max().rename_axis("dekad_start")

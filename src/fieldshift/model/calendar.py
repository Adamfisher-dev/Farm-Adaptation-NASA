"""
calendar.py - The field calendar (playbook section 4 and idea L): what is in the field in each
half-month of each year of a rotation, with risk marks from this field's weather and water model.

Grid: one row per calendar year of the rotation (labelled with the crop harvested that year),
24 half-month columns (1st-15th, 16th-end). A cover crop sown after corn shows at the end of the
corn row and the start of the next row - how a farmer describes it ("rye over winter before beans").

Each cell:
  state      bare | cover | crop_partial | crop_full   (majority of days; full = Kc >= crop_full_kc)
  crop       crop in the field (most days), or "bare"
  greenness  mean crop coefficient Kc (0.3 bare ... 1.2 full corn canopy)
  risk marks (content/calendar.yaml), each with the share of past years it happened:
    erosion       soil exposed (bare or thin cover) in a half-month when erosive storms are common
    drought       the crop's yield-sensitive window, with how often it was water-stressed there
    waterlogging  waterlogged days in that half-month in many years (mostly untiled fields)
    frost         frost in the first weeks after planting a summer crop

"What is in the field" comes from the typical cycle (crops.daily_crop_table). The risk shares
come from 1984-2025: weather-only risks (erosive storms, frost) from NASA POWER; water risks
(stress, waterlogging) from running the water model for every phase, so each weather year is
seen with each crop of the rotation.

No Streamlit calls in this file (project rule): the app draws the grid (e.g. a Plotly heatmap).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import calendar as _cal
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from fieldshift import config
from fieldshift.model import crops as crops_mod
from fieldshift.model import water_balance as wb

CALENDAR_PATH = config.CONTENT_DIR / "calendar.yaml"
MONTHS = [_cal.month_abbr[m] for m in range(1, 13)]
PERIODS = [(m, h) for m in range(1, 13) for h in (1, 2)]          # 24 half-months


@lru_cache(maxsize=2)
def _load_cached(path: str, mtime: float) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_settings(path: str | Path | None = None) -> dict:
    p = Path(path) if path else CALENDAR_PATH
    return _load_cached(str(p), p.stat().st_mtime)


def period_index(dates: pd.DatetimeIndex) -> np.ndarray:
    """0..23: (month - 1) * 2 + (0 for days 1-15, 1 for 16-end)."""
    return (dates.month.to_numpy() - 1) * 2 + (dates.day.to_numpy() > 15)


def period_label(p: int) -> str:
    m, h = PERIODS[p]
    last = _cal.monthrange(2001, m)[1]
    return f"{MONTHS[m - 1]} {'1-15' if h == 1 else f'16-{last}'}"


def _row_of(dates: pd.DatetimeIndex, start_year: int, phase: int, n: int) -> np.ndarray:
    """Rotation row (0..n-1) of each date: calendar years cycle through the plan's entries."""
    return (dates.year.to_numpy() - start_year + phase) % n


# --- What is in the field: the typical cycle -------------------------------------------------------
def typical_cycle(plan, crops: pd.DataFrame | None = None, settings: dict | None = None) -> pd.DataFrame:
    """One row per (row, period): state, crop, greenness, exposed share, frost-sensitive share,
    sensitive share - from the middle of three cycles (so crops crossing 1 January are complete)."""
    crops = crops_mod.default_crop_table() if crops is None else crops
    settings = settings or load_settings()
    n, start = len(plan), 2001
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t = crops_mod.daily_crop_table(plan, start, start + 3 * n - 1, crops=crops)
    t = t[(t.index.year >= start + n) & (t.index.year < start + 2 * n)].copy()
    t["row"] = t.index.year - (start + n)
    t["period"] = period_index(t.index)
    full_kc = settings["crop_full_kc"]
    t["state"] = np.select([t["role"] == "bare", t["role"] == "cover", t["kc"] >= full_kc],
                           ["bare", "cover", "crop_full"], "crop_partial")
    e = settings["risks"]["erosion"]
    kinds = t["crop"].map(lambda c: crops.loc[c, "kind"] if c in crops.index else "bare")
    young_annual = (t["role"] == "cash") & (kinds != "perennial") & (t["kc"] < e["exposed_kc"])
    young_cover = (t["role"] == "cover") & (t["days_since_start"] < e.get("cover_establish_days", 30))
    t["exposed"] = (t["role"] == "bare") | young_annual | young_cover
    days_after = settings["risks"]["frost"]["days_after_planting"]
    t["frost_sensitive"] = (t["role"] == "cash") & (kinds == "summer_annual") & \
                           (t["days_since_start"] >= 0) & (t["days_since_start"] <= days_after)
    g = t.groupby(["row", "period"])
    cells = pd.DataFrame({
        "state": g["state"].agg(lambda s: s.value_counts().idxmax()),
        "crop": g["crop"].agg(lambda s: s.value_counts().idxmax()),
        "greenness": g["kc"].mean().round(2),
        "exposed_share": g["exposed"].mean(),
        "frost_sensitive_share": g["frost_sensitive"].mean(),
        "sensitive_share": g["sensitive"].mean(),
    })
    return cells


# --- Risk shares from the weather and the water model --------------------------------------------------
def weather_shares(weather: pd.DataFrame, settings: dict | None = None,
                   start_year: int = config.WATER_START_YEAR, end_year: int = config.WATER_END_YEAR) -> pd.DataFrame:
    """Per half-month (0..23): share of years with >= 1 erosive storm, and with >= 1 frost."""
    settings = settings or load_settings()
    w = weather.loc[str(start_year):str(end_year)]
    rk = settings["risks"]
    df = pd.DataFrame({"year": w.index.year, "period": period_index(w.index),
                       "storm": w["PRECTOTCORR"] > rk["erosion"]["rain_mm"],
                       "frost": w["T2M_MIN"] <= rk["frost"]["tmin_c"]})
    per_year = df.groupby(["period", "year"])[["storm", "frost"]].any()
    return per_year.groupby("period").mean().rename(columns={"storm": "storm_share", "frost": "frost_share"})


def water_shares(plan, precip: pd.Series, et0: pd.Series, awc_mm_per_m: float, tile_drained: bool,
                 crops: pd.DataFrame | None = None, start_year: int = config.WATER_START_YEAR,
                 end_year: int = config.WATER_END_YEAR) -> pd.DataFrame:
    """Per (row, period): share of years with >= 1 water-stressed day in the sensitive window,
    and with >= 1 waterlogged day. Every phase is run, so every year is seen in every row."""
    n = len(plan)
    parts = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for phase, ct in crops_mod.all_phases(plan, start_year, end_year, crops=crops).items():
            d = wb.run_water_balance(precip, et0, ct, awc_mm_per_m, tile_drained)
            parts.append(pd.DataFrame({
                "row": _row_of(d.index, start_year, phase, n), "period": period_index(d.index),
                "year": d.index.year, "stressed": d["stressed"] & d["sensitive"],
                "waterlogged": d["waterlogged"]}))
    df = pd.concat(parts, ignore_index=True)
    per_year = df.groupby(["row", "period", "year"])[["stressed", "waterlogged"]].any()
    return per_year.groupby(["row", "period"]).mean().rename(
        columns={"stressed": "stress_share", "waterlogged": "waterlog_share"})


# --- The calendar -------------------------------------------------------------------------------------------
def field_calendar(plan, weather: pd.DataFrame, et0: pd.Series, awc_mm_per_m: float, tile_drained: bool,
                   crops: pd.DataFrame | None = None, settings: dict | None = None) -> dict:
    """Calendar for one rotation on one field.

    Returns {"rows": [{"year_in_rotation", "label"}],
             "cells": [{year_in_rotation, period (1-24), month, half, label, state, crop, greenness,
                        risk: [...], erosion_share, drought_share, waterlog_share, frost_share}],
             "summary": {bare_days_per_year, living_cover_halfmonths, exposed_stormy_halfmonths,
                         risk_halfmonths: {risk: count}}}
    """
    settings = settings or load_settings()
    rk = settings["risks"]
    crops = crops_mod.default_crop_table() if crops is None else crops
    n = len(plan)
    cyc = typical_cycle(plan, crops, settings)
    ws = weather_shares(weather, settings)
    wat = water_shares(plan, weather["PRECTOTCORR"], et0, awc_mm_per_m, tile_drained, crops)

    cells = []
    for (row, p), c in cyc.iterrows():
        storm = float(ws.loc[p, "storm_share"]) if p in ws.index else np.nan
        frost = float(ws.loc[p, "frost_share"]) if p in ws.index else np.nan
        stress = float(wat.loc[(row, p), "stress_share"]) if (row, p) in wat.index else np.nan
        wlog = float(wat.loc[(row, p), "waterlog_share"]) if (row, p) in wat.index else np.nan
        risk = []
        if c["exposed_share"] >= rk["erosion"]["min_exposed_share"] and storm >= rk["erosion"]["min_share"]:
            risk.append("erosion")
        if c["sensitive_share"] > 0 and stress >= rk["drought"]["min_share"]:
            risk.append("drought")
        if wlog >= rk["waterlogging"]["min_share"]:
            risk.append("waterlogging")
        if c["frost_sensitive_share"] > 0 and frost >= rk["frost"]["min_share"]:
            risk.append("frost")
        m, h = PERIODS[p]
        cells.append({
            "year_in_rotation": int(row) + 1, "period": int(p) + 1, "month": m, "half": h,
            "label": period_label(p), "state": c["state"], "crop": c["crop"], "greenness": float(c["greenness"]),
            "risk": risk,
            "erosion_share": round(storm, 2) if "erosion" in risk else None,
            "drought_share": round(stress, 2) if "drought" in risk else None,
            "waterlog_share": round(wlog, 2) if "waterlogging" in risk else None,
            "frost_share": round(frost, 2) if "frost" in risk else None,
        })

    rows = [{"year_in_rotation": i + 1, "label": " + ".join(e.replace("_", " ") for e in plan[i])}
            for i in range(n)]
    states = [c["state"] for c in cells]
    risk_counts = {r: sum(r in c["risk"] for c in cells) / n for r in rk}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t = crops_mod.daily_crop_table(plan, 2001 + n, 2001 + 2 * n - 1, crops=crops)
    summary = {
        "bare_days_per_year": round(float((t["role"] == "bare").sum() / n), 0),
        "living_cover_halfmonths_per_year": round(sum(s != "bare" for s in states) / n, 1),
        "exposed_stormy_halfmonths_per_year": round(risk_counts["erosion"], 1),
        "risk_halfmonths_per_year": {r: round(v, 1) for r, v in risk_counts.items()},
    }
    return {"rows": rows, "cells": cells, "summary": summary}


# --- Helpers for the app and for checking ------------------------------------------------------------------------
def grid(cal: dict, value: str = "state") -> pd.DataFrame:
    """Rows = rotation years, columns = 24 half-month labels; values = state / crop / greenness.
    Ready for a Plotly heatmap (map states to numbers/colours in the app)."""
    df = pd.DataFrame(cal["cells"])
    g = df.pivot(index="year_in_rotation", columns="period", values=value)
    g.columns = [period_label(p - 1) for p in g.columns]
    g.index = [f"Year {r['year_in_rotation']}: {r['label']}" for r in cal["rows"]]
    return g


def as_text(cal: dict, settings: dict | None = None) -> str:
    """Plain-text grid (for logs, tests and quick checks). Two characters per half-month:
    state symbol, then the first risk symbol (or a space)."""
    settings = settings or load_settings()
    sym = {k: v["symbol"] for k, v in settings["states"].items()}
    rsym = {"erosion": "!", "drought": "d", "waterlogging": "w", "frost": "f"}       # ASCII in text view
    head = " " * 22 + "".join(f"{m:<4}" for m in MONTHS)
    lines = [head]
    by_row = {}
    for c in cal["cells"]:
        by_row.setdefault(c["year_in_rotation"], {})[c["period"]] = c
    for r in cal["rows"]:
        cells = by_row[r["year_in_rotation"]]
        body = "".join(sym[cells[p]["state"]] + (rsym[cells[p]["risk"][0]] if cells[p]["risk"] else " ")
                       for p in range(1, 25))
        lines.append(f"Year {r['year_in_rotation']} {r['label'][:14]:<15}{body}")
    lines.append("  " + "  ".join(f"{v} {settings['states'][k]['label']}" for k, v in sym.items())
                 + "   ! erosion  d drought-sensitive  w waterlogging  f frost")
    return "\n".join(lines)


# --- Self-check on real data ---------------------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    from fieldshift.model.et0 import et0_from_power

    warnings.simplefilter("ignore")
    cell = "42.000_-93.750"
    weather = pd.read_csv(config.SAMPLE_DIR / f"power_{cell}.csv", index_col="date", parse_dates=True)
    weather = weather.replace(config.POWER_FILL_VALUE, np.nan)
    meta = json.loads((config.SAMPLE_DIR / f"power_{cell}_meta.json").read_text())
    et0 = et0_from_power(weather, meta["requested_point"][0], meta["geometry"]["coordinates"][2])

    for name, plan, tiled in [("Corn-soybean, tiled", [["corn"], ["soybean"]], True),
                              ("Corn-soybean + rye, tiled", [["corn", "cereal_rye"], ["soybean", "cereal_rye"]], True),
                              ("Corn-soybean, NOT tiled", [["corn"], ["soybean"]], False),
                              ("Marsden 4-year", [["corn"], ["soybean"], ["oats+alfalfa"], ["alfalfa"]], True)]:
        cal = field_calendar(plan, weather, et0, 183.0, tiled)
        print(f"\n{name}   summary: {cal['summary']}")
        print(as_text(cal))
        assert len(cal["cells"]) == 24 * len(plan)

    cs = field_calendar([["corn"], ["soybean"]], weather, et0, 183.0, True)
    by = {(c["year_in_rotation"], c["label"]): c for c in cs["cells"]}
    assert by[(1, "Jul 16-31")]["crop"] == "corn" and "drought" in by[(1, "Jul 16-31")]["risk"]
    assert by[(1, "Jan 1-15")]["state"] == "bare"
    rye = field_calendar([["corn", "cereal_rye"], ["soybean"]], weather, et0, 183.0, True)
    byr = {(c["year_in_rotation"], c["label"]): c for c in rye["cells"]}
    assert byr[(2, "Jan 1-15")]["state"] == "cover"          # rye over winter before soybean, in the soybean row
    assert rye["summary"]["bare_days_per_year"] < cs["summary"]["bare_days_per_year"]
    print("\nOK - checks passed.")

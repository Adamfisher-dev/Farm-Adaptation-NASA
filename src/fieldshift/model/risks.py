"""
risks.py - Field-specific risk flags (playbook 6.3, "not scored, shown as flags"): how often each
risk happened on this field in 1984-2025, and what it means. They do not change the ranking;
they fill the "risks" part of the cards with numbers instead of generic text.

Flags (thresholds in content/risks.yaml; frost settings shared with content/calendar.yaml):
  cover_establishment      warmth (growing degree days, base 0 C) from the cash crop's harvest
                           (+ seeding delay) to the end of autumn growth, vs what the cover crop needs
  frost_after_planting     frost within ~30 days of the usual planting date
  heat_at_sensitive_stage  hot days during the crop's yield-sensitive window (crops.csv)
  wet_planting             too wet to plant on time: many rain days, or waterlogged soil (water model),
                           in the two weeks from the usual planting date

Each flag: {key, crop, label, n, of, share, level (warn | watch | info), sentence, facts, verified}.
Dates are the crop table's typical dates (no year-to-year planting decisions) - a simplification.

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from fieldshift import config
from fieldshift.model import calendar as calendar_mod
from fieldshift.model import crops as crops_mod

RISKS_PATH = config.CONTENT_DIR / "risks.yaml"


@lru_cache(maxsize=2)
def _load_cached(path: str, mtime: float) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_settings(path: str | Path | None = None) -> dict:
    p = Path(path) if path else RISKS_PATH
    return _load_cached(str(p), p.stat().st_mtime)


def _level(share: float, s: dict) -> str:
    if share >= s["levels"]["warn"]:
        return "warn"
    return "watch" if share >= s["levels"]["watch"] else "info"


def _date(year: int, md: str) -> pd.Timestamp:
    return pd.Timestamp(f"{year}-{md}")


def _pretty(c: str) -> str:
    return c.replace("_", " ")


def _flag(key, crop, label, n, of, s, sentence, facts, verified):
    share = n / of if of else np.nan
    return {"key": key, "crop": crop, "label": label, "n": int(n), "of": int(of), "share": round(share, 3),
            "level": _level(share, s) if of else "info", "sentence": sentence, "facts": facts,
            "verified": bool(verified)}


# --- The four flags -------------------------------------------------------------------------------
def cover_establishment(plan, weather: pd.DataFrame, crops: pd.DataFrame, s: dict) -> list:
    """For each cover crop in the plan: years with enough warmth between seeding and the first hard freeze."""
    cfg = s["cover_establishment"]
    years = sorted(set(weather.index.year))
    tmean = (weather["T2M_MAX"] + weather["T2M_MIN"]) / 2.0
    gdd_day = (tmean - cfg["gdd_base_c"]).clip(lower=0)
    out = []
    for i, year_entry in enumerate(plan):
        cash, _, _under = year_entry[0].partition("+")
        cover = year_entry[1] if len(year_entry) > 1 else None
        if cover not in cfg["covers"]:
            continue
        harvest_md = crops.loc[cash, "harvest_md"]
        if not isinstance(harvest_md, str):
            continue
        gdds, freeze_gaps = [], []
        for y in years:
            seed = _date(y, harvest_md) + pd.Timedelta(days=crops_mod.COVER_SEED_DELAY_DAYS + 1)
            after = weather.loc[seed:f"{y}-12-31"]
            if after.empty:
                continue
            freeze_days = after.index[after["T2M_MIN"] <= cfg["hard_freeze_c"]]
            first_freeze = freeze_days[0] if len(freeze_days) else pd.Timestamp(f"{y}-12-31")
            end = _date(y, cfg.get("growth_end_md", "12-31"))
            gdds.append(float(gdd_day.loc[seed:end].sum()))
            freeze_gaps.append((first_freeze - seed).days)
        if not gdds:
            continue
        gdds = np.array(gdds)
        n_ok = int((gdds >= cfg["required_gdd"]).sum())
        facts = {"seeding": f"{harvest_md} + {crops_mod.COVER_SEED_DELAY_DAYS} days",
                 "median_gdd": round(float(np.median(gdds)), 0), "required_gdd": cfg["required_gdd"],
                 "median_days_to_hard_freeze": int(np.median(freeze_gaps))}
        n_fail = len(gdds) - n_ok
        sentence = (f"{_pretty(cover).capitalize()} sown after {_pretty(cash)} harvest gets enough autumn warmth to "
                    f"establish in {n_ok} of {len(gdds)} years (median {facts['median_gdd']:.0f} degree-days by the end of "
                    f"the year; first hard freeze typically {facts['median_days_to_hard_freeze']} days after seeding).")
        if n_fail / len(gdds) >= s["levels"]["watch"]:
            sentence += " In the other years it may give little winter cover - drill it right after harvest."
        out.append(_flag("cover_establishment", cover, f"{_pretty(cover).capitalize()} establishment after {_pretty(cash)}",
                         n_fail, len(gdds), s, sentence, facts, cfg.get("verified", False)))
    return out


def frost_after_planting(plan, weather: pd.DataFrame, crops: pd.DataFrame, s: dict, cal_settings: dict) -> list:
    fr = cal_settings["risks"]["frost"]
    tolerant = set(s["frost_after_planting"].get("tolerant", []))
    years = sorted(set(weather.index.year))
    out, seen = [], set()
    for year_entry in plan:
        cash = year_entry[0].split("+")[0]
        if cash in seen or crops.loc[cash, "kind"] != "summer_annual":
            continue
        seen.add(cash)
        plant = crops.loc[cash, "plant_md"]
        hits = 0
        for y in years:
            p = _date(y, plant)
            win = weather.loc[p:p + pd.Timedelta(days=fr["days_after_planting"]), "T2M_MIN"]
            hits += bool((win <= fr["tmin_c"]).any())
        sentence = (f"Frost in the {fr['days_after_planting']} days after the usual {_pretty(cash)} planting date "
                    f"({plant}) in {hits} of {len(years)} years.")
        if cash in tolerant:
            sentence += f" {_pretty(cash).capitalize()} usually tolerates light frost."
        f = _flag("frost_after_planting", cash, f"Frost after planting {_pretty(cash)}", hits, len(years), s, sentence,
                  {"planting": plant, "tmin_c": fr["tmin_c"]}, s["frost_after_planting"].get("verified", False))
        if cash in tolerant:
            f["level"] = "info"
        out.append(f)
    return out


def heat_at_sensitive_stage(plan, weather: pd.DataFrame, crops: pd.DataFrame, s: dict) -> list:
    cfg = s["heat_at_sensitive_stage"]
    years = sorted(set(weather.index.year))
    out, seen = [], set()
    for year_entry in plan:
        cash = year_entry[0].split("+")[0]
        if cash in seen or cash not in cfg["crops"]:
            continue
        seen.add(cash)
        a, b = crops.loc[cash, "sensitive_start_md"], crops.loc[cash, "sensitive_end_md"]
        if not (isinstance(a, str) and isinstance(b, str)):
            continue
        counts = np.array([int((weather.loc[_date(y, a):_date(y, b), "T2M_MAX"] > cfg["heat_c"]).sum()) for y in years])
        hits = int((counts >= cfg["min_hot_days"]).sum())
        worst = [int(y) for y in pd.Series(counts, index=years).nlargest(3).index if counts[years.index(y)] > 0]
        sentence = (f"{_pretty(cash).capitalize()} sensitive stage ({a} to {b}) had {cfg['min_hot_days']}+ days above "
                    f"{cfg['heat_c']:.0f} C in {hits} of {len(years)} years"
                    + (f" (most: {', '.join(map(str, worst))})." if worst else "."))
        out.append(_flag("heat_at_sensitive_stage", cash, f"Heat at {_pretty(cash)} sensitive stage", hits, len(years),
                         s, sentence, {"window": f"{a} to {b}", "heat_c": cfg["heat_c"],
                                       "median_hot_days": float(np.median(counts))}, cfg.get("verified", False)))
    return out


@lru_cache(maxsize=1)
def calibrated_wet_day_mm() -> tuple[float, str]:
    """POWER rain-day threshold whose frequency matches the ground gauge's >= gauge_wet_day_mm days
    (calibration_months, overlapping years). Falls back to risks.yaml wet_day_mm without ground data."""
    cfg = load_settings()["wet_planting"]
    try:
        from fieldshift.data import ground
        from fieldshift.data.power import load_power
        cs = config.CLIMATE_STATION
        gauge = ground.load_station_weather()["precip_mm"]
        power, _ = load_power(cs["lat"], cs["lon"], allow_download=False)
        both = pd.concat([power["PRECTOTCORR"], gauge], axis=1, keys=["power", "gauge"]).dropna()
        both = both[both.index.month.isin(cfg.get("calibration_months", [4, 5, 6]))]
        f_gauge = float((both["gauge"] >= cfg.get("gauge_wet_day_mm", 1.0)).mean())
        thr = float(np.quantile(both["power"], 1 - f_gauge))
        return round(thr, 2), (f"POWER >= {thr:.2f} mm, calibrated so POWER has as many rain days as the "
                               f"{cs['name']} gauge (>= {cfg.get('gauge_wet_day_mm', 1.0):g} mm) in "
                               f"{both.index.year.min()}-{both.index.year.max()}")
    except Exception:                               # no ground data / POWER copy: stored calibration
        return float(cfg["wet_day_mm"]), f"POWER >= {cfg['wet_day_mm']} mm (stored calibration against the Ames gauge)"


def wet_planting(plan, weather: pd.DataFrame, crops: pd.DataFrame, s: dict, dailies: dict | None = None) -> list:
    cfg = s["wet_planting"]
    wet_mm, wet_basis = calibrated_wet_day_mm()
    years = sorted(set(weather.index.year))
    waterlogged = None
    if dailies:                                  # any phase's run: waterlogging depends on soil + weather mostly
        waterlogged = pd.concat([d["waterlogged"] for d in dailies.values()], axis=1).any(axis=1)
    out, seen = [], set()
    for year_entry in plan:
        cash = year_entry[0].split("+")[0]
        if cash in seen or cash not in cfg["crops"]:
            continue
        seen.add(cash)
        plant = crops.loc[cash, "plant_md"]
        hits, wl_years, wet_years = 0, 0, 0
        for y in years:
            p = _date(y, plant)
            win = slice(p, p + pd.Timedelta(days=cfg["window_days"] - 1))
            rainy = int((weather.loc[win, "PRECTOTCORR"] >= wet_mm).sum())
            wl = bool(waterlogged.loc[win].any()) if waterlogged is not None else False
            wet_years += rainy >= cfg["min_wet_days"]
            wl_years += wl
            hits += (rainy >= cfg["min_wet_days"]) or wl
        sentence = (f"Too wet to plant {_pretty(cash)} on time in {hits} of {len(years)} years "
                    f"({cfg['min_wet_days']}+ rain days in the {cfg['window_days']} days from {plant}"
                    + (f", or waterlogged soil: {wl_years} years" if waterlogged is not None and wl_years else "") + ").")
        out.append(_flag("wet_planting", cash, f"Wet planting season ({_pretty(cash)})", hits, len(years), s, sentence,
                         {"planting": plant, "rain_day_years": int(wet_years), "waterlogged_years": int(wl_years),
                          "rain_day": wet_basis},
                         cfg.get("verified", False)))
    return out


# --- All flags for one rotation ---------------------------------------------------------------------
def risk_flags(plan, weather: pd.DataFrame, dailies: dict | None = None, crops: pd.DataFrame | None = None,
               start_year: int = config.WATER_START_YEAR, end_year: int = config.WATER_END_YEAR) -> list:
    """All risk flags for one rotation on one field, most serious first.
    weather: daily POWER (the weather the model used); dailies: {phase: daily water-model output with
    'waterlogged'} from simulate_rotation(keep_daily=True), for waterlogging at planting."""
    crops = crops_mod.default_crop_table() if crops is None else crops
    s = load_settings()
    cal = calendar_mod.load_settings()
    w = weather.loc[str(start_year):str(end_year)]
    flags = (cover_establishment(plan, w, crops, s) + frost_after_planting(plan, w, crops, s, cal)
             + heat_at_sensitive_stage(plan, w, crops, s) + wet_planting(plan, w, crops, s, dailies))
    order = {"warn": 0, "watch": 1, "info": 2}
    return sorted(flags, key=lambda f: (order[f["level"]], -f["share"]))


def unverified_note(flags: list) -> str:
    keys = sorted({f["key"] for f in flags if not f["verified"]})
    return ("Thresholds not yet checked against Iowa State guidance: " + ", ".join(keys) + ".") if keys else ""


# --- Self-check on real data ---------------------------------------------------------------------------
if __name__ == "__main__":
    import warnings
    warnings.simplefilter("ignore")
    from fieldshift.model.et0 import et0_from_power
    from fieldshift.model.water_balance import simulate_rotation

    cell = "42.000_-93.750"
    weather = pd.read_csv(config.SAMPLE_DIR / f"power_{cell}.csv", index_col="date", parse_dates=True)
    weather = weather.replace(config.POWER_FILL_VALUE, np.nan)
    et0 = et0_from_power(weather, 42.0, 310.0)
    icon = {"warn": "!!", "watch": "! ", "info": "  "}
    results = {}
    for name, plan, tiled in [("C-S + rye, tiled", [["corn", "cereal_rye"], ["soybean", "cereal_rye"]], True),
                              ("C-S, NOT tiled", [["corn"], ["soybean"]], False),
                              ("C-S-oats/clover + rye before soy", [["corn", "cereal_rye"], ["soybean"], ["oats+red_clover"]], True),
                              ("C-S-wheat + rye", [["corn", "cereal_rye"], ["soybean"], ["winter_wheat", "cereal_rye"]], True)]:
        t = simulate_rotation(plan, weather["PRECTOTCORR"], et0, 183.0, tiled, 1984, 2025, keep_daily=True)
        flags = risk_flags(plan, weather, t.attrs["daily"])
        results[name] = {f["label"]: f for f in flags}
        print(f"\n{name}")
        for f in flags:
            print(f"  {icon[f['level']]} [{f['level']:<5}] {f['sentence']}")
        print("  ", unverified_note(flags))

    r = results["C-S + rye, tiled"]
    after_corn = r["Cereal rye establishment after corn"]
    after_soy = r["Cereal rye establishment after soybean"]
    assert after_corn["facts"]["median_gdd"] < after_soy["facts"]["median_gdd"]   # corn harvested later -> less warmth
    assert results["C-S, NOT tiled"]["Wet planting season (corn)"]["n"] >= r["Wet planting season (corn)"]["n"]
    oats_frost = results["C-S-oats/clover + rye before soy"]["Frost after planting oats"]
    assert oats_frost["level"] == "info"                                             # oats tolerate light frost
    assert oats_frost["n"] >= results["C-S, NOT tiled"]["Frost after planting corn"]["n"]   # April vs May planting
    print("\nOK - checks passed.")

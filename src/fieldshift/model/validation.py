"""
validation.py - Check the tool's numbers against independent measurements (playbook 6.11).

Three comparisons:
  1. compare_weather   NASA POWER (~50 km cell) vs a ground weather station near the field:
                       daily Tmax/Tmin (bias, RMSE, correlation) and MONTHLY rain totals
                       (a 50 km average cannot match one rain gauge day by day).
  2. compare_soil      our water model vs SMAP satellite soil moisture (top ~5 cm, 9 km), and
  3. compare_soil      our water model vs ISU Soil Moisture Network probes (point, 30-60 cm).
                       The three measure different depths and areas, so absolute values are not
                       comparable: we compare ANOMALIES - how much wetter or drier than normal for
                       that day of the year each one says the soil is (playbook 7.4).

For 2-3 the water model is run with the crops actually grown (CDL history), not a candidate
rotation: run_actual_crops().

Inputs are plain pandas objects with a DatetimeIndex (one row per day). Reading and cleaning
the raw files (quality flags, units, depths) belongs in data/smap.py and data/ground.py:
    station weather  DataFrame columns tmax_c, tmin_c, precip_mm      (degC, mm/day)
    soil moisture    Series of volumetric water content (m3/m3), already quality-filtered;
                     frozen-soil / snow days removed if the product flags them.

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from fieldshift.model import crops as crops_mod
from fieldshift.model import water_balance as wb

GROWING_SEASON = (4, 10)        # April-October: avoids frozen soil and snow (SMAP flags them; our
                                # model treats snow as rain), when soil moisture matters for crops
CLIMATOLOGY_WINDOW_DAYS = 31    # smoothing of the day-of-year normal used for anomalies
MIN_PAIRS = 30                  # fewer overlapping days than this -> no statistics

# CDL classes we do not model, simulated with the nearest modelled crop (flagged as a gap)
CDL_PROXIES = {"other_hay": "alfalfa", "grass_pasture": "alfalfa", "winter_wheat_then_soybean": "winter_wheat"}


# --- Generic statistics -----------------------------------------------------------------
def metrics(model: pd.Series, obs: pd.Series) -> dict:
    """Paired statistics on the days both series have: n, bias (model - obs), RMSE, MAE,
    Pearson r, and the overlap period."""
    both = pd.concat([pd.Series(model, dtype=float), pd.Series(obs, dtype=float)], axis=1,
                     keys=["model", "obs"]).dropna()
    n = len(both)
    if n < MIN_PAIRS:
        return {"n": n, "bias": np.nan, "rmse": np.nan, "mae": np.nan, "r": np.nan,
                "period": None, "note": f"only {n} overlapping values (need {MIN_PAIRS})"}
    d = both["model"] - both["obs"]
    return {
        "n": int(n),
        "bias": round(float(d.mean()), 3),
        "rmse": round(float(np.sqrt((d ** 2).mean())), 3),
        "mae": round(float(d.abs().mean()), 3),
        "r": round(float(both["model"].corr(both["obs"])), 3),
        "period": [str(both.index.min().date()), str(both.index.max().date())],
    }


def daily_anomaly(series: pd.Series, window: int = CLIMATOLOGY_WINDOW_DAYS, standardise: bool = True) -> pd.Series:
    """Departure from the normal for that day of the year: (x - mean_doy) / sd_doy.
    The day-of-year normal is smoothed with a circular moving window so short records
    (SMAP has ~10 years) still give a stable normal."""
    s = pd.Series(series, dtype=float).dropna()
    doy = s.index.dayofyear.where(s.index.dayofyear <= 365, 365)
    by_doy = s.groupby(doy)
    mean = by_doy.mean().reindex(range(1, 366))
    sd = by_doy.std().reindex(range(1, 366))
    half = window // 2

    def smooth(x):
        padded = pd.concat([x.iloc[-half:], x, x.iloc[:half]])          # wrap around the year
        return padded.rolling(window, center=True, min_periods=1).mean().iloc[half:-half]

    mean, sd = smooth(mean), smooth(sd)
    anom = s - mean.loc[doy].to_numpy()
    if standardise:
        anom = anom / sd.loc[doy].to_numpy()
    return anom.replace([np.inf, -np.inf], np.nan)


def _season(s: pd.Series, months=GROWING_SEASON) -> pd.Series:
    if months is None:
        return s
    m = s.index.month
    return s[(m >= months[0]) & (m <= months[1])]


# --- 1. Weather ---------------------------------------------------------------------------
def compare_weather(power: pd.DataFrame, station: pd.DataFrame) -> dict:
    """POWER vs ground station. power: T2M_MAX, T2M_MIN, PRECTOTCORR; station: tmax_c, tmin_c, precip_mm.
    Returns {"tmax", "tmin": daily metrics, "rain_monthly": monthly-total metrics,
             "rain_daily": daily metrics (expect a low r - see representativeness error)}."""
    for col in ("tmax_c", "tmin_c", "precip_mm"):
        if col not in station:
            raise KeyError(f"station data needs column {col!r} (degC / mm per day)")
    out = {
        "tmax": metrics(power["T2M_MAX"], station["tmax_c"]),
        "tmin": metrics(power["T2M_MIN"], station["tmin_c"]),
        "rain_daily": metrics(power["PRECTOTCORR"], station["precip_mm"]),
    }
    both = pd.concat([power["PRECTOTCORR"], station["precip_mm"]], axis=1, keys=["model", "obs"]).dropna()
    monthly = both.resample("MS").agg(["sum", "count"])
    full = monthly[("model", "count")] >= 25                           # months with >= 25 paired days
    out["rain_monthly"] = metrics(monthly.loc[full, ("model", "sum")], monthly.loc[full, ("obs", "sum")])
    return out


# --- Model run with the crops actually grown ------------------------------------------------
def actual_crop_plan(crop_history: dict, crops: pd.DataFrame | None = None) -> tuple[list, list]:
    """CDL history {year: crop} -> (plan in crops.py format, one entry per year, notes on proxies).
    Unmodelled classes use CDL_PROXIES; anything else raises ValueError."""
    crops = crops_mod.default_crop_table() if crops is None else crops
    plan, notes = [], []
    for y in sorted(crop_history, key=int):
        c = crop_history[y]
        if c in CDL_PROXIES:
            notes.append(f"{y}: {c} simulated as {CDL_PROXIES[c]}")
            c = CDL_PROXIES[c]
        if c not in crops.index or crops.loc[c, "kind"] == "cover":
            raise ValueError(f"{y}: CDL class {c!r} cannot be simulated - pick another point or year range")
        plan.append([c])
    return plan, notes


def run_actual_crops(precip_mm: pd.Series, et0_mm: pd.Series, crop_history: dict, awc_mm_per_m: float,
                     tile_drained: bool, crops: pd.DataFrame | None = None) -> pd.DataFrame:
    """Daily water balance for the CDL years with the crops that were really grown.
    Adds 'wetness_root' (root-zone water / capacity, 0-1) and 'wetness_profile' (top 1 m)."""
    plan, notes = actual_crop_plan(crop_history, crops)
    years = sorted(int(y) for y in crop_history)
    if years != list(range(years[0], years[-1] + 1)):
        raise ValueError("crop history must cover consecutive years")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        table = crops_mod.daily_crop_table(plan, years[0], years[-1], phase=0, crops=crops)
    daily = wb.run_water_balance(precip_mm, et0_mm, table, awc_mm_per_m, tile_drained)
    daily["wetness_root"] = (daily["sw_root"] / daily["taw"]).clip(0, 1.5)
    daily["wetness_profile"] = daily["storage"] / (awc_mm_per_m * wb.PROFILE_DEPTH_M)
    daily.attrs["notes"] = notes
    return daily


# --- 2/3. Soil moisture -------------------------------------------------------------------------
def compare_soil(model_wetness: pd.Series, obs: pd.Series, months=GROWING_SEASON, name: str = "observed") -> dict:
    """Anomaly comparison of modelled wetness with observed soil moisture.

    Returns {"daily_anomaly": metrics on standardised daily anomalies (the headline r),
             "monthly_anomaly": metrics on monthly means of those anomalies,
             "raw": metrics on the raw series (r only meaningful; units differ),
             "name", "months"}.
    """
    am, ao = daily_anomaly(model_wetness), daily_anomaly(obs)
    am, ao = _season(am, months), _season(ao, months)
    both = pd.concat([am, ao], axis=1, keys=["m", "o"]).dropna()
    monthly = both.resample("MS").mean().dropna()
    raw = metrics(_season(pd.Series(model_wetness, dtype=float), months), _season(pd.Series(obs, dtype=float), months))
    return {
        "name": name,
        "months": months,
        "daily_anomaly": metrics(both["m"], both["o"]),
        "monthly_anomaly": metrics(monthly["m"], monthly["o"]),
        "raw": {"n": raw["n"], "r": raw["r"], "period": raw["period"]},
    }


def sentence(result: dict) -> str:
    """Plain-language line for the evidence page."""
    r = result["daily_anomaly"]["r"]
    n = result["daily_anomaly"]["n"]
    if r is None or np.isnan(r):
        return f"Not enough overlapping data with {result['name']} to compare yet."
    strength = ("closely" if r >= 0.7 else "reasonably well" if r >= 0.5 else "loosely" if r >= 0.3 else "poorly")
    return (f"Our modelled soil wetness rises and falls {strength} with {result['name']} "
            f"(correlation of day-to-day departures from normal: {r:.2f}, {n} days, April-October).")


def weather_sentence(result: dict) -> str:
    t, rm = result["tmax"], result["rain_monthly"]
    return (f"NASA POWER daily maximum temperature differs from the ground station by {t['bias']:+.1f} C on "
            f"average (typical error {t['rmse']:.1f} C, r = {t['r']:.2f}); monthly rain totals agree with "
            f"r = {rm['r']:.2f} (bias {rm['bias']:+.0f} mm per month). Daily rain agrees less well "
            f"(r = {result['rain_daily']['r']:.2f}) because a 50 km average cannot match one rain gauge.")


# --- Self-check on synthetic observations ----------------------------------------------------------
if __name__ == "__main__":
    import json
    from fieldshift import config
    from fieldshift.model.et0 import et0_from_power

    cell = "42.000_-93.750"
    power = pd.read_csv(config.SAMPLE_DIR / f"power_{cell}.csv", index_col="date", parse_dates=True)
    power = power.replace(config.POWER_FILL_VALUE, np.nan)
    meta = json.loads((config.SAMPLE_DIR / f"power_{cell}_meta.json").read_text())
    et0 = et0_from_power(power, meta["requested_point"][0], meta["geometry"]["coordinates"][2])
    rng = np.random.default_rng(7)

    # 1) Weather: fake station = POWER + known bias + noise
    station = pd.DataFrame({
        "tmax_c": power["T2M_MAX"] - 0.8 + rng.normal(0, 1.5, len(power)),
        "tmin_c": power["T2M_MIN"] + 0.5 + rng.normal(0, 1.5, len(power)),
        "precip_mm": (power["PRECTOTCORR"] * rng.lognormal(0, 0.8, len(power))).where(rng.random(len(power)) > 0.2, 0),
    }, index=power.index)
    w = compare_weather(power.loc["1984":], station.loc["1984":])
    print("Weather:", {k: {m: v[m] for m in ("bias", "rmse", "r")} for k, v in w.items()})
    assert abs(w["tmax"]["bias"] - 0.8) < 0.1 and abs(w["tmin"]["bias"] + 0.5) < 0.1
    assert w["rain_monthly"]["r"] > w["rain_daily"]["r"]
    print(weather_sentence(w))

    # 2) Soil: run the model with an actual-crops history, then make fake SMAP from its anomalies
    hist = {str(y): ("corn" if y % 2 == 0 else "soybean") for y in range(2008, 2026)}
    hist["2013"] = "other_hay"                                     # exercises the proxy
    daily = run_actual_crops(power["PRECTOTCORR"], et0, hist, 200, True)
    print("\nModel run with actual crops:", daily.index.min().date(), "-", daily.index.max().date(),
          "| notes:", daily.attrs["notes"])
    model_wet = daily["wetness_root"]
    truth = daily_anomaly(model_wet)
    smap = (0.25 + 0.05 * truth + rng.normal(0, 0.04, len(truth))).loc["2015-04-01":]
    smap = smap[rng.random(len(smap)) > 0.5]                       # satellite overpass gaps
    good = compare_soil(model_wet, smap, name="SMAP (synthetic)")
    noise = compare_soil(model_wet, pd.Series(rng.normal(0.25, 0.05, len(smap)), index=smap.index), name="noise")
    print("vs related obs:", good["daily_anomaly"], "\nvs pure noise: r =", noise["daily_anomaly"]["r"])
    print(sentence(good))
    assert good["daily_anomaly"]["r"] > 0.5 and abs(noise["daily_anomaly"]["r"]) < 0.1
    assert abs(daily_anomaly(model_wet).mean()) < 0.1
    print("\nOK - checks passed.")

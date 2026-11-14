"""Climate snapshot indicators from daily NASA POWER weather (CLAUDE.md 6.14).

Display and validation outputs only: they do not change the scoring.

    from fieldshift.data.power import load_power
    from fieldshift.model.indicators import yearly_indicators, snapshot, notable_years

    df, meta = load_power(42.03, -93.47)
    yearly = yearly_indicators(df)          # one row per year
    snap = snapshot(yearly)                 # contract "snapshot" block
    notes = notable_years(yearly)           # shortlist for hard-year replay

Units are SI (C, mm, days). Convert to F / inches in the app, not here.
"""

import numpy as np
import pandas as pd

from fieldshift import config

# What each snapshot key means, for labels and the evidence page.
INDICATORS = {
    "gdd": ("Heat units (growing degree days), Apr-Oct", "degree C days"),
    "frost_free_days": ("Frost-free season", "days"),
    "growing_season_rain_mm": ("Growing-season rain, May-Sep", "mm"),
    "longest_dry_spell_days": ("Longest dry spell, Jun-Aug", "days"),
    "hot_days": ("Hot days above 30 C, Jul-Aug", "days"),
    "heavy_rain_days": ("Heavy-rain days above 25 mm, Mar-Jun", "days"),
    "last_spring_frost_doy": ("Last spring frost", "day of year"),
    "first_autumn_frost_doy": ("First autumn frost", "day of year"),
    "root_wetness_spring": ("Root-zone wetness, Apr-May (modelled)", "0-1"),
    "root_wetness_summer": ("Root-zone wetness, Jul-Aug (modelled)", "0-1"),
}
SNAPSHOT_KEYS = ["gdd", "frost_free_days", "growing_season_rain_mm",
                 "longest_dry_spell_days", "hot_days", "heavy_rain_days"]


# ---------------------------------------------------------------------------
# Daily and yearly building blocks
# ---------------------------------------------------------------------------

def daily_gdd(tmax, tmin):
    """Corn GDD: both temperatures clipped to [base, cap], so never negative."""
    lo, hi = config.GDD_BASE_C, config.GDD_CAP_C
    return (tmax.clip(lo, hi) + tmin.clip(lo, hi)) / 2 - lo


def longest_run(flags):
    """Longest run of True in a row."""
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def frost_dates(tmin):
    """Last spring (before 1 July) and first autumn (from 1 July) frost, as day of year."""
    frost = tmin <= config.FROST_C
    doy = tmin.index.dayofyear
    spring = tmin.index[frost & (doy < 182)]
    autumn = tmin.index[frost & (doy >= 182)]
    last_spring = spring[-1].dayofyear if len(spring) else np.nan
    first_autumn = autumn[0].dayofyear if len(autumn) else np.nan
    return last_spring, first_autumn


def indicators_for_year(d):
    """All indicators for one calendar year of daily data."""
    m = d.index.month
    tmax, tmin, rain = d["T2M_MAX"], d["T2M_MIN"], d["PRECTOTCORR"]
    root = d["GWETROOT"] if "GWETROOT" in d else pd.Series(np.nan, index=d.index)
    last_spring, first_autumn = frost_dates(tmin)
    summer = (m >= 6) & (m <= 8)
    return {
        "gdd": daily_gdd(tmax, tmin)[(m >= 4) & (m <= 10)].sum(),
        "last_spring_frost_doy": last_spring,
        "first_autumn_frost_doy": first_autumn,
        "frost_free_days": first_autumn - last_spring - 1,
        "growing_season_rain_mm": rain[(m >= 5) & (m <= 9)].sum(),
        "longest_dry_spell_days": longest_run(rain[summer] < config.DRY_DAY_MM),
        "hot_days": int((tmax[(m >= 7) & (m <= 8)] > config.HOT_DAY_C).sum()),
        "heavy_rain_days": int((rain[(m >= 3) & (m <= 6)] > config.HEAVY_RAIN_MM).sum()),
        "root_wetness_spring": root[(m >= 4) & (m <= 5)].mean(),
        "root_wetness_summer": root[(m >= 7) & (m <= 8)].mean(),
    }


def yearly_indicators(df, max_missing=0.05):
    """One row per complete year; years with > max_missing gaps in T or rain are skipped."""
    core = ["T2M_MAX", "T2M_MIN", "PRECTOTCORR"]
    rows = []
    for year, d in df.groupby(df.index.year):
        if len(d) < 365 or d[core].isna().mean().max() > max_missing:
            continue
        rows.append({"year": int(year), **indicators_for_year(d)})
    return pd.DataFrame(rows).set_index("year")


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------

def trend(series):
    """Theil-Sen slope per decade + Mann-Kendall p-value (Kendall's tau vs year).

    The p-value assumes years are independent; treat it as a guide, not proof.
    """
    from fieldshift.model.trends import trend as _trend      # one trend method for the whole tool
    t = _trend(series)
    return {"trend_per_decade": t["trend_per_decade"], "p_value": t["p_value"], "n_years": int(t["n_years"])}


# ---------------------------------------------------------------------------
# Outputs for the app
# ---------------------------------------------------------------------------

def snapshot(yearly, recent_years=config.RECENT_YEARS, keys=SNAPSHOT_KEYS):
    """Contract 'snapshot' block: per indicator, recent mean/range and trend since the first year."""
    recent = yearly.tail(recent_years)
    out = {}
    for key in keys:
        label, unit = INDICATORS[key]
        out[key] = {
            "label": label,
            "unit": unit,
            "recent_mean": recent[key].mean(),
            "recent_min": recent[key].min(),
            "recent_max": recent[key].max(),
            "recent_years": [int(recent.index.min()), int(recent.index.max())],
            **trend(yearly[key]),
        }
    return to_json_safe(out)


def notable_years(yearly, n=3):
    """Shortlist of hard years for the replay picker. Confirm 2012 appears before demoing it."""
    picks = {
        "driest_summers": yearly["growing_season_rain_mm"].nsmallest(n),
        "longest_dry_spells": yearly["longest_dry_spell_days"].nlargest(n),
        "wettest_springs": yearly["heavy_rain_days"].nlargest(n),
        "hottest_summers": yearly["hot_days"].nlargest(n),
    }
    return {name: [int(y) for y in s.index] for name, s in picks.items()}


def series_for_charts(yearly):
    """Yearly values as a list of dicts, for plotly charts and the evidence page."""
    return to_json_safe([{"year": int(y), **row} for y, row in yearly.to_dict("index").items()])


def to_json_safe(value, digits=2):
    """NaN -> None, numpy -> Python, floats rounded. Safe for st.json and FastAPI."""
    if isinstance(value, dict):
        return {k: to_json_safe(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(v, digits) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if np.isnan(value) else round(float(value), digits)
    return value

"""
trends.py - Long-term trends in the weather record and in the model's results (playbook 6.9),
and optional temperature detrending so past years represent today's climate.

1. Trend tests on yearly series (one value per year):
     Theil-Sen slope   median of all pairwise slopes - robust to odd years; with a 95 % range
     Mann-Kendall test is there a monotonic trend at all? (normal approximation, tie-corrected)
   The p-value assumes years are independent; with ~40 years treat it as a guide, not proof.

2. Trend table for the farmer: every climate indicator (indicators.yearly_indicators) plus
   annual mean temperatures and rain, each with a plain-language sentence.

3. detrend_temperature(): if (and only if) the annual-mean temperature trend is significant,
   shift every day of year y by slope x (end_year - y), so all ~42 seasons are "today's
   temperatures with that year's weather pattern". Dew point gets the same shift as mean
   temperature, which keeps relative humidity about constant (so vapour pressure deficit, and
   ET0, change a little - list as a simplification). Rain is NOT detrended unless asked and
   clearly significant (playbook 6.9).

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

ALPHA = 0.05                    # significance level for "the trend is likely real"
RAIN_ALPHA = 0.01               # stricter for rain ("clearly significant", playbook 6.9)
MIN_YEARS = 10

TEMP_COLUMNS = {"T2M_MAX": "T2M_MAX", "T2M_MIN": "T2M_MIN", "T2M": "T2M"}   # each detrended by its own trend
DEWPOINT_FOLLOWS = "T2M"        # T2MDEW gets the mean-temperature shift (RH roughly constant)


# --- 1. Trend tests ------------------------------------------------------------------------
def mann_kendall(values) -> dict:
    """Mann-Kendall trend test. Returns S, z, p (two-sided), tau, n.
    Variance corrected for tied values (Kendall 1975)."""
    x = np.asarray(pd.Series(values, dtype=float).dropna(), dtype=float)
    n = len(x)
    if n < 3:
        return {"S": 0, "z": np.nan, "p": np.nan, "tau": np.nan, "n": n}
    diff = np.sign(x[None, :] - x[:, None])
    s = float(np.triu(diff, 1).sum())
    _, counts = np.unique(x, return_counts=True)
    ties = counts[counts > 1]
    var = (n * (n - 1) * (2 * n + 5) - np.sum(ties * (ties - 1) * (2 * ties + 5))) / 18.0
    z = 0.0 if s == 0 else (s - np.sign(s)) / math.sqrt(var)
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return {"S": s, "z": z, "p": float(p), "tau": s / (n * (n - 1) / 2), "n": n}


def trend(series: pd.Series, per: int = 10, alpha: float = ALPHA) -> dict:
    """Theil-Sen slope (per `per` years, default per decade) with 95 % range, Mann-Kendall p,
    and the change implied over the record. series: index = year (int), values = yearly measure."""
    s = pd.Series(series, dtype=float).dropna()
    n = len(s)
    if n < MIN_YEARS:
        return {"trend_per_decade": np.nan, "low": np.nan, "high": np.nan, "p_value": np.nan,
                "significant": False, "n_years": n, "change_over_record": np.nan, "intercept": np.nan}
    years = s.index.to_numpy(dtype=float)
    slope, intercept, lo, hi = stats.theilslopes(s.to_numpy(), years, 0.95)
    mk = mann_kendall(s.to_numpy())
    return {
        "trend_per_decade": slope * per, "low": lo * per, "high": hi * per,
        "p_value": mk["p"], "significant": bool(mk["p"] < alpha), "n_years": n,
        "change_over_record": slope * (years.max() - years.min()),
        "intercept": intercept, "first_year": int(years.min()), "last_year": int(years.max()),
    }


def describe(label: str, unit: str, t: dict, decimals: int = 1) -> str:
    """Plain sentence, e.g. 'Hot days (Jul-Aug) have risen by about 1.2 days per decade since 1981
    - likely a real change (p = 0.03).'"""
    if t["n_years"] < MIN_YEARS or np.isnan(t["trend_per_decade"]):
        return f"{label}: not enough years to judge a trend."
    v = t["trend_per_decade"]
    if round(v, decimals) == 0:
        return f"{label}: no clear change since {t['first_year']} (p = {t['p_value']:.2f})."
    verdict = ("likely a real change" if t["significant"]
               else "could be chance - not a clear trend")
    if unit == "day of year":            # dates: earlier / later
        return (f"{label} comes about {abs(v):.{decimals}f} days {'later' if v > 0 else 'earlier'} per decade "
                f"since {t['first_year']} - {verdict} (p = {t['p_value']:.2f}).")
    direction = "risen" if v > 0 else "fallen"
    return (f"{label} has {direction} by about {abs(v):.{decimals}f} {unit} per decade since {t['first_year']} "
            f"- {verdict} (p = {t['p_value']:.2f}).")


# --- 2. Trend table ---------------------------------------------------------------------------
def annual_climate(df: pd.DataFrame) -> pd.DataFrame:
    """Annual means of daily temperature and annual rain from POWER (complete years only)."""
    cols = [c for c in ("T2M", "T2M_MAX", "T2M_MIN") if c in df]
    g = df.groupby(df.index.year)
    out = g[cols].mean()
    out["PRECTOTCORR"] = g["PRECTOTCORR"].sum(min_count=360)
    full = g.size() >= 365
    return out[full]


ANNUAL_LABELS = {
    "T2M": ("Average temperature", "C"), "T2M_MAX": ("Average daily maximum temperature", "C"),
    "T2M_MIN": ("Average daily minimum (night) temperature", "C"), "PRECTOTCORR": ("Yearly rain", "mm"),
}


def trend_table(yearly: pd.DataFrame, labels: dict | None = None) -> pd.DataFrame:
    """One row per column of a yearly table: slope per decade, 95 % range, p, significant, sentence.
    labels: {column: (label, unit)}; defaults to indicators.INDICATORS + annual climate labels."""
    if labels is None:
        from fieldshift.model.indicators import INDICATORS
        labels = {**ANNUAL_LABELS, **INDICATORS}
    rows = []
    for col in yearly.columns:
        if col not in labels:
            continue
        label, unit = labels[col]
        t = trend(yearly[col])
        rows.append({"indicator": col, "label": label, "unit": unit,
                     "per_decade": round(t["trend_per_decade"], 3), "low": round(t["low"], 3),
                     "high": round(t["high"], 3), "p_value": round(t["p_value"], 3),
                     "significant": t["significant"], "n_years": t["n_years"],
                     "sentence": describe(label, unit, t, 2 if unit == "C" else 1)})
    return pd.DataFrame(rows).set_index("indicator")


def climate_trends(df: pd.DataFrame) -> pd.DataFrame:
    """Trend table for a POWER daily DataFrame: annual climate + every snapshot indicator."""
    from fieldshift.model.indicators import yearly_indicators
    yearly = annual_climate(df).join(yearly_indicators(df), how="outer")
    return trend_table(yearly)


def result_trend(table: pd.DataFrame, column: str, label: str, unit: str) -> dict:
    """Trend in a model output over the years, e.g. drought deficit of the existing rotation
    (rotation x year table; phases averaged per year)."""
    s = table.groupby("year")[column].mean()
    t = trend(s)
    t["sentence"] = describe(label, unit, t)
    return t


# --- 3. Temperature detrending ---------------------------------------------------------------------
def detrend_temperature(df: pd.DataFrame, end_year: int | None = None, alpha: float = ALPHA,
                        detrend_rain: bool = False, start_year: int | None = None) -> tuple[pd.DataFrame, dict]:
    """Shift past temperatures to the present-day level where the warming trend is significant.

    For each temperature column: Theil-Sen slope of its annual mean (start_year..end_year); if
    Mann-Kendall p < alpha, every day of year y gets + slope x (end_year - y). T2MDEW follows the
    T2M shift. Rain: only if detrend_rain and p < RAIN_ALPHA, scaled by (1 + rel_slope x (end - y)).
    Returns (adjusted copy, report {column: {slope_per_decade, p, applied, shift_first_year}}).
    """
    years_all = df.index.year
    end_year = int(end_year or years_all.max())
    start_year = int(start_year or years_all.min())
    annual = annual_climate(df.loc[str(start_year):str(end_year)])
    out = df.copy()
    report = {}
    years = out.index.year.to_numpy()
    for col in TEMP_COLUMNS:
        if col not in out:
            continue
        t = trend(annual[col])
        slope = t["trend_per_decade"] / 10.0
        apply = bool(t["significant"]) and not np.isnan(slope)
        if apply:
            out[col] = out[col] + slope * (end_year - years)
        report[col] = {"slope_per_decade": round(t["trend_per_decade"], 3), "p_value": round(t["p_value"], 4),
                       "applied": apply, "shift_first_year": round(slope * (end_year - start_year), 2) if apply else 0.0}
    if "T2MDEW" in out and report.get(DEWPOINT_FOLLOWS, {}).get("applied"):
        slope = report[DEWPOINT_FOLLOWS]["slope_per_decade"] / 10.0
        out["T2MDEW"] = out["T2MDEW"] + slope * (end_year - years)
        report["T2MDEW"] = {"follows": DEWPOINT_FOLLOWS, "applied": True}
    t = trend(annual["PRECTOTCORR"])
    rel = (t["trend_per_decade"] / 10.0) / annual["PRECTOTCORR"].mean() if annual["PRECTOTCORR"].mean() else 0.0
    apply_rain = detrend_rain and t["p_value"] < RAIN_ALPHA
    if apply_rain:
        out["PRECTOTCORR"] = out["PRECTOTCORR"] * (1 + rel * (end_year - years))
    report["PRECTOTCORR"] = {"slope_per_decade": round(t["trend_per_decade"], 1), "p_value": round(t["p_value"], 4),
                             "applied": bool(apply_rain)}
    applied = [c for c, r in report.items() if r.get("applied")]
    report["note"] = (f"Past temperatures shifted to {end_year} levels ({', '.join(applied)}); weather patterns "
                      "of each year kept." if applied else
                      "No significant temperature trend - past years used as recorded.")
    return out, report


# --- Self-check ------------------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    import warnings
    warnings.simplefilter("ignore")
    from fieldshift import config

    # synthetic: known slope recovered, white noise mostly not significant
    rng = np.random.default_rng(0)
    yrs = np.arange(1981, 2026)
    s = pd.Series(0.03 * (yrs - 1981) + rng.normal(0, 0.3, len(yrs)), index=yrs)
    t = trend(s)
    assert abs(t["trend_per_decade"] - 0.3) < 0.12 and t["significant"], t
    false_pos = np.mean([trend(pd.Series(rng.normal(0, 1, len(yrs)), index=yrs))["significant"] for _ in range(300)])
    print(f"synthetic: slope {t['trend_per_decade']:.3f}/decade (true 0.30), p {t['p_value']:.4f}; "
          f"false-positive rate on noise {false_pos:.1%} (expect ~5 %)")
    assert false_pos < 0.10
    mk_s = mann_kendall([1, 2, 3, 4, 5])
    assert mk_s["S"] == 10 and mk_s["tau"] == 1.0

    # real POWER data
    cell = "42.000_-93.750"
    df = pd.read_csv(config.SAMPLE_DIR / f"power_{cell}.csv", index_col="date", parse_dates=True)
    df = df.replace(config.POWER_FILL_VALUE, np.nan)
    table = climate_trends(df)
    print(f"\nTrends at POWER cell {cell}, {table['n_years'].max()} years:")
    for _, r in table.iterrows():
        print(f"  {'*' if r.significant else ' '} {r.sentence}")

    adj, rep = detrend_temperature(df.loc["1984":], end_year=2025)
    print("\nDetrending:", json.dumps({k: v for k, v in rep.items() if k != "note"}), "\n ", rep["note"])
    for col in ("T2M_MAX", "T2M_MIN"):
        a0 = annual_climate(df.loc["1984":])[col]
        a1 = annual_climate(adj)[col]
        print(f"  {col}: trend before {trend(a0)['trend_per_decade']:+.2f} C/decade, after {trend(a1)['trend_per_decade']:+.2f}")
        if rep[col]["applied"]:
            assert abs(trend(a1)["trend_per_decade"]) < 0.05
    assert (adj["PRECTOTCORR"].fillna(0) == df.loc["1984":, "PRECTOTCORR"].fillna(0)).all()   # rain untouched
    print("\nOK - checks passed.")

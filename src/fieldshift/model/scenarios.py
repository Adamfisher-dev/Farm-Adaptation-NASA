"""
scenarios.py - "What if it gets warmer or drier?" Delta-change scenarios (playbook 6.9, idea J).

Method (delta change): take the real 1984-2025 daily weather and shift it -
    temperature   + dT to daily mean, max, min and dew point (dew point moves with temperature,
                  so relative humidity stays about the same - as in trends.detrend_temperature)
    summer rain   x (1 + pct/100) on every day in June-August
then recompute reference ET (ET0) and re-run the water model for each rotation. Every year keeps
its own weather pattern (dry spells, storms), only shifted - so the 2012 drought gets hotter too.

These are plausible stress tests, not forecasts (the playbook's decision horizon is 3-10 years;
NEX-GDDP-CMIP6 projections are the lowest-priority add-on).

Simplifications (list as gaps): crop calendars do not shift with warming (no earlier planting or
faster development), no CO2 effect on crop water use, sunshine and wind unchanged, year-to-year
variability unchanged, snow still treated as rain, income unchanged (prices and yields fixed).

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from fieldshift import config
from fieldshift.model import scoring
from fieldshift.model.et0 import et0_from_power
from fieldshift.model.water_balance import simulate_rotation

SUMMER_MONTHS = (6, 7, 8)
TEMP_COLUMNS = ("T2M", "T2M_MAX", "T2M_MIN", "T2MDEW")

# The playbook's what-if set: +1/+2 C and -10/-20 % summer rain, plus the combined stress case.
SCENARIOS = {
    "Today's climate": {"delta_temp_c": 0.0, "summer_rain_pct": 0.0},
    "+1 C": {"delta_temp_c": 1.0, "summer_rain_pct": 0.0},
    "+2 C": {"delta_temp_c": 2.0, "summer_rain_pct": 0.0},
    "-10% summer rain": {"delta_temp_c": 0.0, "summer_rain_pct": -10.0},
    "-20% summer rain": {"delta_temp_c": 0.0, "summer_rain_pct": -20.0},
    "+2 C and -20% summer rain": {"delta_temp_c": 2.0, "summer_rain_pct": -20.0},
}
BASE = "Today's climate"


# --- Weather shift ------------------------------------------------------------------------
def apply_delta(weather: pd.DataFrame, delta_temp_c: float = 0.0, summer_rain_pct: float = 0.0,
                summer_months=SUMMER_MONTHS) -> pd.DataFrame:
    """Copy of daily POWER weather with temperatures shifted by delta_temp_c and summer rain scaled."""
    out = weather.copy()
    if delta_temp_c:
        for col in TEMP_COLUMNS:
            if col in out:
                out[col] = out[col] + delta_temp_c
    if summer_rain_pct:
        summer = out.index.month.isin(summer_months)
        out.loc[summer, "PRECTOTCORR"] = out.loc[summer, "PRECTOTCORR"] * (1 + summer_rain_pct / 100.0)
    return out


def scenario_et0(weather: pd.DataFrame, latitude: float, elevation_m: float | None = None,
                 rs_units: str = "MJ/m^2/day") -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return et0_from_power(weather, latitude, elevation_m, rs_units=rs_units)


# --- Run the rotations under each scenario --------------------------------------------------------
def run_scenarios(weather: pd.DataFrame, rotations: dict, awc_mm_per_m: float, tile_drained: bool,
                  latitude: float, existing: str, slider_weights: dict, ordinal_scores: dict,
                  slope_factor: float | None = None, income: dict | None = None,
                  scenarios: dict | None = None, elevation_m: float | None = None,
                  rs_units: str = "MJ/m^2/day", start_year: int = config.WATER_START_YEAR,
                  end_year: int = config.WATER_END_YEAR, wb_kwargs: dict | None = None) -> dict:
    """Each rotation under each scenario.

    weather: daily POWER (as used for the main analysis). rotations: {name: plan}.
    slider_weights: criteria.yaml slider names (drought, soil_erosion, ...). income: {name: USD/acre}
    (unchanged across scenarios). Returns {
      "scenarios": the settings used,
      "raw": DataFrame (scenario, rotation) x criteria, real units,
      "scores": DataFrame rotation x scenario (existing = 0.5 in each scenario),
      "top": {scenario: best rotation}, "same_top": bool,
      "existing_change": {scenario: {criterion: change vs today}} for the existing rotation,
      "sentences": plain-language lines }
    """
    scenarios = scenarios or SCENARIOS
    w = weather.loc[str(start_year):str(end_year)]
    extra = {n: {"income_usd_per_acre": v} for n, v in (income or {}).items()}
    raws, scores = {}, {}
    for sname, s in scenarios.items():
        ws = apply_delta(w, s["delta_temp_c"], s["summer_rain_pct"])
        e0 = scenario_et0(ws, latitude, elevation_m, rs_units)
        tables = {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for name, plan in rotations.items():
                tables[name] = simulate_rotation(plan, ws["PRECTOTCORR"], e0, awc_mm_per_m, tile_drained,
                                                 start_year, end_year, rotation_id=name, **(wb_kwargs or {}))
        raw = scoring.raw_criteria(tables, ordinal_scores, slope_factor=slope_factor, extra=extra)
        raws[sname] = raw
        res = scoring.score_rotations(raw, existing, slider_weights)
        scores[sname] = res["scores"]["score"]
    raw_long = pd.concat(raws, names=["scenario", "rotation"])
    score_table = pd.DataFrame(scores)
    top = {s: score_table[s].idxmax() for s in score_table.columns}
    same_top = len(set(top.values())) == 1

    base_raw = raws[BASE].loc[existing]
    existing_change = {s: (raws[s].loc[existing] - base_raw).round(1).to_dict() for s in scenarios if s != BASE}
    sentences = []
    for s in scenarios:
        if s == BASE:
            continue
        d_now, d_s = base_raw["drought_risk"], raws[s].loc[existing, "drought_risk"]
        sentences.append(f"{s}: your current rotation's bad-year water shortfall at the sensitive stage goes "
                         f"from {d_now:.0f} to {d_s:.0f} mm ({(d_s - d_now) / d_now:+.0%}); drainage "
                         f"{base_raw['water_leaving']:.0f} -> {raws[s].loc[existing, 'water_leaving']:.0f} mm/yr.")
    if same_top:
        sentences.append(f"The top option ({top[BASE]}) stays the same in every scenario.")
    else:
        changed = {s: t for s, t in top.items() if t != top[BASE]}
        sentences.append("The top option changes in some scenarios: "
                         + "; ".join(f"{s}: {t}" for s, t in changed.items())
                         + " - treat the choice as sensitive to future climate.")
    return {"scenarios": scenarios, "raw": raw_long, "scores": score_table, "top": top,
            "same_top": same_top, "existing_change": existing_change, "sentences": sentences}


# --- Self-check ---------------------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    import time

    warnings.simplefilter("ignore")
    # 1) the weather shift itself
    idx = pd.date_range("2020-01-01", "2020-12-31", freq="D")
    toy = pd.DataFrame({"T2M": 10.0, "T2M_MAX": 15.0, "T2M_MIN": 5.0, "T2MDEW": 3.0, "PRECTOTCORR": 2.0}, index=idx)
    sh = apply_delta(toy, 2.0, -20.0)
    assert (sh["T2M_MAX"] == 17.0).all() and (sh["T2MDEW"] == 5.0).all()
    assert np.isclose(sh.loc["2020-07-15", "PRECTOTCORR"], 1.6) and sh.loc["2020-05-15", "PRECTOTCORR"] == 2.0
    assert toy["T2M_MAX"].iloc[0] == 15.0                                  # input not modified

    # 2) real data: corn-soybean, rye, oats/clover under all scenarios
    cell = "42.000_-93.750"
    weather = pd.read_csv(config.SAMPLE_DIR / f"power_{cell}.csv", index_col="date", parse_dates=True)
    weather = weather.replace(config.POWER_FILL_VALUE, np.nan)
    meta = json.loads((config.SAMPLE_DIR / f"power_{cell}_meta.json").read_text())
    rotations = {"Corn-soybean": [["corn"], ["soybean"]],
                 "C-S + rye": [["corn", "cereal_rye"], ["soybean", "cereal_rye"]],
                 "C-S-oats/clover + rye": [["corn", "cereal_rye"], ["soybean"], ["oats+red_clover"]]}
    ordinal = {"Corn-soybean": {"n_benefit": 1, "pest_break": 1, "som_proxy": 0},
               "C-S + rye": {"n_benefit": 1, "pest_break": 1, "som_proxy": 2},
               "C-S-oats/clover + rye": {"n_benefit": 2, "pest_break": 2, "som_proxy": 3}}
    t0 = time.perf_counter()
    res = run_scenarios(weather, rotations, 183.0, True, meta["requested_point"][0], "Corn-soybean",
                        {"drought": 0.3, "water_quality": 0.3, "soil_erosion": 0.2, "pests_fertiliser": 0.2},
                        ordinal, elevation_m=meta["geometry"]["coordinates"][2])
    print(f"3 rotations x {len(SCENARIOS)} scenarios: {time.perf_counter() - t0:.1f} s")
    print(res["raw"][["drought_risk", "water_leaving", "erosion_exposure"]].round(1).to_string())
    print("\nscores:\n" + res["scores"].round(3).to_string())
    for s in res["sentences"]:
        print(" -", s)
    d = res["raw"]["drought_risk"]
    assert d[("+2 C", "Corn-soybean")] > d[(BASE, "Corn-soybean")]                     # warmer -> more stress
    assert d[("-20% summer rain", "Corn-soybean")] > d[("-10% summer rain", "Corn-soybean")] > d[(BASE, "Corn-soybean")]
    assert res["raw"]["water_leaving"][("-20% summer rain", "Corn-soybean")] < res["raw"]["water_leaving"][(BASE, "Corn-soybean")]
    assert (res["scores"].loc["Corn-soybean"] == 0.5).all()                             # existing = 0.5 in every scenario
    print("\nOK - checks passed.")

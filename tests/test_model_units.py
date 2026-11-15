"""Unit tests for the model files (offline: NASA POWER from sample_data, made-up tables where needed).

One test group per module: scoring, bootstrap, rotations, income, calendar, risks, scenarios,
trends, replay, validation. The playbook sanity checks are in test_sanity.py.
"""

import json
import warnings

import numpy as np
import pandas as pd
import pytest

from fieldshift import config
from fieldshift.model import bootstrap, calendar, income, replay, risks, rotations, scenarios, scoring, trends
from fieldshift.model import validation as val
from fieldshift.model.et0 import et0_from_power
from fieldshift.model.water_balance import simulate_rotation

warnings.filterwarnings("ignore")
CELL = "42.000_-93.750"


@pytest.fixture(scope="module")
def weather():
    w = pd.read_csv(config.SAMPLE_DIR / f"power_{CELL}.csv", index_col="date", parse_dates=True)
    return w.replace(config.POWER_FILL_VALUE, np.nan)


@pytest.fixture(scope="module")
def et0(weather):
    meta = json.loads((config.SAMPLE_DIR / f"power_{CELL}_meta.json").read_text())
    return et0_from_power(weather, meta["requested_point"][0], meta["geometry"]["coordinates"][2])


@pytest.fixture(scope="module")
def cs_run(weather, et0):
    daily = {}
    t = simulate_rotation([["corn"], ["soybean"]], weather["PRECTOTCORR"], et0, 183.0, True, 1984, 2025,
                          daily_out=daily)
    return t, daily


@pytest.fixture(scope="module")
def cs_table(cs_run):
    return cs_run[0]


@pytest.fixture(scope="module")
def cs_daily(cs_run):
    return cs_run[1]


# --- scoring --------------------------------------------------------------------------------------------
TOY_SPEC = {
    "sliders": ["drought", "soil_erosion", "pests_fertiliser"],
    "criteria": {
        "drought_risk": {"type": "simulated", "column": "d", "statistic": "mean", "direction": "cost",
                         "slider": "drought", "unit": "mm", "scale": 1.0, "cap": 0.5},
        "erosion_exposure": {"type": "counted", "column": "e", "statistic": "mean", "direction": "cost",
                             "slider": "soil_erosion", "unit": "days", "scale": 1.0, "cap": 0.5},
        "n_benefit": {"type": "literature", "column": "n", "statistic": "fixed", "direction": "benefit",
                      "slider": "pests_fertiliser", "unit": "ordinal_0_3"},
    },
}


def test_scoring_reproduces_playbook_toy_example():
    raw = pd.DataFrame({"drought_risk": [120, 125, 100], "erosion_exposure": [60, 30, 25], "n_benefit": [1, 1, 3]},
                       index=["C-S", "rye", "alfalfa"])
    res = scoring.score_rotations(raw, "C-S", {"drought": 0.4, "soil_erosion": 0.4, "pests_fertiliser": 0.2}, TOY_SPEC)
    s = res["scores"]["score"]
    assert s["C-S"] == pytest.approx(0.50)
    assert s["rye"] == pytest.approx(0.683, abs=0.005) and s["alfalfa"] == pytest.approx(0.833, abs=0.005)
    assert (res["values"].loc["C-S"] == 0.5).all()                       # existing = 0.5 on every criterion
    assert res["pareto"]["C-S"] and not res["pareto"]["alfalfa"]


def test_income_compared_in_dollars_not_percent():
    c = {"direction": "benefit", "scale": 100.0, "cap": 1.0, "relative": False}
    # same $50 difference whatever the income level -> same value
    assert scoring.criterion_value(250, 300, c) == pytest.approx(scoring.criterion_value(-50, 0, c)) == pytest.approx(0.25)


def test_rank_order_centroid_and_cvar():
    assert [round(x, 2) for x in scoring.rank_order_centroid(5)] == [0.46, 0.26, 0.16, 0.09, 0.04]
    assert scoring.statistic(pd.Series(range(1, 21)), "cvar_0.10") == 19.5     # worst 2 of 20


# --- bootstrap -------------------------------------------------------------------------------------------
def _synthetic_tables():
    yrs = np.arange(1984, 2026)
    base = np.random.default_rng(3).gamma(4, 10, len(yrs))
    def tbl(k):
        return pd.DataFrame({"year": yrs, "phase": 0, "drought_deficit_mm": base * k,
                             "drainage_mm": 300 * k + 0 * base, "bare_wet_days": 5 * k + 0 * base})
    return {"A": tbl(1.0), "B": tbl(0.7), "C": tbl(1.2)}


def test_bootstrap_dominant_option_always_first_and_existing_fixed():
    ords = {k: {"n_benefit": 1, "pest_break": 1, "som_proxy": 0} for k in "ABC"}
    res = bootstrap.run_bootstrap(_synthetic_tables(), "A", {"drought": 1, "water_quality": 1, "soil_erosion": 1},
                                  ords, n_boot=300)
    s = res["summary"]
    assert s.loc["B", "p_top"] == 1.0 and s["p_top"].sum() == pytest.approx(1.0)
    assert s.loc["A", "score_p05"] == pytest.approx(0.5) and s.loc["A", "score_p95"] == pytest.approx(0.5)


def test_bootstrap_uses_income_price_draws():
    ords = {k: {"n_benefit": 1, "pest_break": 1, "som_proxy": 0} for k in "ABC"}
    draws = {k: {"income_usd_per_acre": np.linspace(0, 100, 200) + i} for i, k in enumerate("ABC")}
    res = bootstrap.run_bootstrap(_synthetic_tables(), "A", {"income": 1}, ords, n_boot=200, extra_samples=draws)
    assert "income" not in res["dropped"]
    assert res["criteria"].loc[("B", "income"), "p95"] > res["criteria"].loc[("B", "income"), "p05"]


def test_effective_sample_size_matches_playbook():
    n = bootstrap.effective_sample_size(bootstrap.year_weights(np.arange(1981, 2026), "weighted", 15))
    assert n == pytest.approx(34, abs=1.5)                                # playbook 6.9: ~34 of 45


# --- rotations -------------------------------------------------------------------------------------------
def test_library_has_twelve_rotations_and_scores_follow_rules():
    lib = rotations.library()
    assert len(lib) == 12 and len({r.rotation_id for r in lib}) == 12
    for b in rotations.load_library()["base_sequences"]:
        assert rotations.rule_scores([[e] for e in b["sequence"]]) == b["scores"], b["id"]


def test_constraints_remove_with_reasons_and_keep_three_options():
    farm = {"existing_rotation": ["corn", "soybean"], "livestock_or_hay_buyer": False, "hay_equipment": False,
            "small_grain_buyer": False, "can_seed_cover": True}
    cands, removed = rotations.build_candidates(farm)
    assert cands[0].is_existing and len(cands) >= 3                       # brief: >= 3 compared
    reasons = {r["rotation_id"]: r["reason"] for r in removed}
    assert "Needs livestock or a hay buyer" in reasons["csoaa"]


def test_existing_rotation_matched_whatever_the_start_year():
    assert rotations.rotation_from_history({"2019": "soybean", "2020": "corn", "2021": "soybean",
                                            "2022": "corn"}) == ["corn", "soybean"]
    cands, _ = rotations.build_candidates({"existing_rotation": ["soybean", "corn"], "small_grain_buyer": True})
    assert cands[0].rotation_id == "cs"


# --- income ----------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def toy_income(tmp_path_factory):
    d = tmp_path_factory.mktemp("income")
    pd.DataFrame([
        ("corn", "cash", 200, 4.50, 3.80, 5.20, 800, 281, None), ("soybean", "cash", 60, 11.0, 9.5, 12.5, 570, 281, None),
        ("oats", "cash", 80, 3.5, 3.0, 4.0, 255, 281, None), ("winter_wheat", "cash", 70, 6.0, 5.0, 7.0, 375, 281, None),
        ("alfalfa", "cash", 4.5, 200, 160, 240, 760, 281, None), ("cereal_rye", "cover", None, None, None, None, 35, None, 0),
        ("red_clover", "underseed", None, None, None, None, 20, None, None),
        ("alfalfa_establishment", "underseed", None, None, None, None, 40, None, None),
    ], columns=["crop", "role", "yield", "price", "price_low", "price_high", "cost_per_acre", "land_cost_per_acre",
                "costshare_per_acre"]).to_csv(d / "income.csv", index=False)
    pd.DataFrame({"effect": ["corn_after_corn_yield_pct", "corn_after_corn_extra_cost", "long_rotation_corn_yield_pct",
                             "long_rotation_soybean_yield_pct", "n_credit_after_legume", "rye_before_corn_yield_pct"],
                  "value": [0, 0, 0, 0, 30, 0]}).to_csv(d / "adj.csv", index=False)
    return income.load_tables(d / "income.csv", d / "adj.csv")


def test_income_arithmetic_and_land_basis(toy_income):
    crops, adj = toy_income
    cs = [["corn"], ["soybean"]]
    assert income.rotation_income(cs, crops, adj, basis="all_costs")["usd_per_acre"] == pytest.approx(95.0)
    assert income.rotation_income(cs, crops, adj)["usd_per_acre"] == pytest.approx(95.0 + 281)   # rent added back
    rye = [["corn", "cereal_rye"], ["soybean", "cereal_rye"]]
    assert income.rotation_income(rye, crops, adj, basis="all_costs")["usd_per_acre"] == pytest.approx(60.0)


def test_marsden_bonus_only_with_marsden_crops(toy_income):
    crops, adj = toy_income
    adj2 = dict(adj, long_rotation_soybean_yield_pct=16)
    wheat = income.rotation_income([["corn"], ["soybean"], ["winter_wheat"]], crops, adj2, basis="all_costs")
    oats = income.rotation_income([["corn"], ["soybean"], ["oats+red_clover"]], crops, adj2, basis="all_costs")
    assert wheat["years"][1]["total"] == pytest.approx(60 * 11 - 570)              # no bonus for wheat
    assert oats["years"][1]["total"] == pytest.approx(60 * 1.16 * 11 - 570)        # bonus with oats/clover


def test_missing_income_values_are_listed_not_guessed(toy_income):
    crops, adj = toy_income
    blank = crops.copy()
    blank.loc["corn", "yield"] = np.nan
    res = income.rotation_income([["corn"], ["soybean"]], blank, adj)
    assert np.isnan(res["usd_per_acre"]) and "income.csv: corn.yield" in res["missing"]


# --- calendar --------------------------------------------------------------------------------------------
def test_calendar_states_and_shape(weather, et0, cs_daily):
    cal = calendar.field_calendar([["corn"], ["soybean"]], weather, et0, 183.0, True, dailies=cs_daily)
    by = {(c["year_in_rotation"], c["label"]): c for c in cal["cells"]}
    assert len(cal["cells"]) == 48 and calendar.grid(cal).shape == (2, 24)
    assert by[(1, "Jan 1-15")]["state"] == "bare"
    assert by[(1, "Jul 16-31")]["crop"] == "corn" and "drought" in by[(1, "Jul 16-31")]["risk"]
    rye = calendar.field_calendar([["corn", "cereal_rye"], ["soybean"]], weather, et0, 183.0, True)
    assert {(c["year_in_rotation"], c["label"]): c for c in rye["cells"]}[(2, "Jan 1-15")]["state"] == "cover"
    assert rye["summary"]["bare_days_per_year"] < cal["summary"]["bare_days_per_year"]


# --- risks -----------------------------------------------------------------------------------------------
def test_risk_flags_rye_after_soybean_easier_and_oats_frost_info(weather, cs_daily):
    flags = risks.risk_flags([["corn", "cereal_rye"], ["soybean", "cereal_rye"]], weather, cs_daily)
    by = {f["label"]: f for f in flags}
    assert by["Cereal rye establishment after corn"]["facts"]["median_gdd"] < \
           by["Cereal rye establishment after soybean"]["facts"]["median_gdd"]
    oats = {f["label"]: f for f in risks.risk_flags([["corn"], ["soybean"], ["oats+red_clover"]], weather)}
    assert oats["Frost after planting oats"]["level"] == "info"
    for f in flags:
        assert 0 <= f["n"] <= f["of"] and f["level"] in ("warn", "watch", "info")


# --- scenarios -------------------------------------------------------------------------------------------
def test_scenario_shift_and_direction(weather):
    sh = scenarios.apply_delta(weather.loc["2020"], 2.0, -20.0)
    assert (sh["T2M_MAX"] - weather.loc["2020", "T2M_MAX"]).round(6).eq(2.0).all()
    jul = weather.loc["2020-07-15", "PRECTOTCORR"]
    assert sh.loc["2020-07-15", "PRECTOTCORR"] == pytest.approx(jul * 0.8)
    assert sh.loc["2020-04-15", "PRECTOTCORR"] == weather.loc["2020-04-15", "PRECTOTCORR"]


def test_warmer_and_drier_means_more_drought(weather):
    meta = json.loads((config.SAMPLE_DIR / f"power_{CELL}_meta.json").read_text())
    res = scenarios.run_scenarios(weather, {"cs": [["corn"], ["soybean"]], "rye": [["corn", "cereal_rye"], ["soybean"]]},
                                  183.0, True, meta["requested_point"][0], "cs", {"drought": 1.0},
                                  {"cs": {"n_benefit": 1, "pest_break": 1, "som_proxy": 0},
                                   "rye": {"n_benefit": 1, "pest_break": 1, "som_proxy": 1}},
                                  scenarios={k: scenarios.SCENARIOS[k] for k in
                                             ("Today's climate", "+2 C", "-20% summer rain")})
    d = res["raw"]["drought_risk"]
    assert d[("+2 C", "cs")] > d[("Today's climate", "cs")] < d[("-20% summer rain", "cs")]
    assert (res["scores"].loc["cs"] == 0.5).all()


# --- trends ----------------------------------------------------------------------------------------------
def test_trend_recovers_slope_and_detrending_removes_it(weather):
    yrs = np.arange(1981, 2026)
    s = pd.Series(0.03 * (yrs - 1981) + np.random.default_rng(0).normal(0, 0.3, len(yrs)), index=yrs)
    t = trends.trend(s)
    assert t["trend_per_decade"] == pytest.approx(0.3, abs=0.12) and t["significant"]
    assert trends.mann_kendall([1, 2, 3, 4, 5])["S"] == 10
    adj, rep = trends.detrend_temperature(weather.loc["1984":], end_year=2025)
    if rep["T2M_MAX"]["applied"]:
        assert abs(trends.trend(trends.annual_climate(adj)["T2M_MAX"])["trend_per_decade"]) < 0.05
    assert adj["PRECTOTCORR"].fillna(0).equals(weather.loc["1984":, "PRECTOTCORR"].fillna(0))   # rain untouched


# --- replay ----------------------------------------------------------------------------------------------
def test_2012_is_the_drought_year(cs_table):
    years = replay.suggest_years({"cs": cs_table}, "cs")
    assert 2012 in years["Driest at the sensitive stage"]
    tbl = replay.replay_table({"cs": cs_table}, 2012, "cs")
    assert tbl.loc[("cs", "drought_deficit_mm"), "rank"] <= 3
    with pytest.raises(ValueError):
        replay.replay_table({"cs": cs_table}, 1982, "cs")                    # no solar data -> not simulated


# --- validation ------------------------------------------------------------------------------------------
def test_validation_recovers_known_bias_and_anomalies(weather):
    rng = np.random.default_rng(7)
    station = pd.DataFrame({"tmax_c": weather["T2M_MAX"] - 0.8 + rng.normal(0, 1.5, len(weather)),
                            "tmin_c": weather["T2M_MIN"] + 0.5 + rng.normal(0, 1.5, len(weather)),
                            "precip_mm": weather["PRECTOTCORR"]}, index=weather.index)
    w = val.compare_weather(weather.loc["1984":], station.loc["1984":])
    assert w["tmax"]["bias"] == pytest.approx(0.8, abs=0.1) and w["tmin"]["bias"] == pytest.approx(-0.5, abs=0.1)
    assert abs(val.daily_anomaly(weather["T2M"].loc["1984":]).mean()) < 0.1


def test_ndvi_crossing_is_interpolated():
    d = pd.to_datetime(["2020-05-01", "2020-05-11", "2020-09-20", "2020-09-30"])
    up, down = val._crossings(pd.Series([0.3, 0.7, 0.7, 0.3], index=d), 0.5)
    assert up == pd.Timestamp("2020-05-06") and down == pd.Timestamp("2020-09-25")

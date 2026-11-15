"""Playbook sanity checks (section 10.1), end to end through pipeline.run_analysis.

Offline: the farmer picks a soil class (content/soils.csv) instead of the live USDA soil query;
weather from sample_data, crop history and elevation from the committed data/raw files.
"""

import warnings

import pytest

from fieldshift import config, pipeline

warnings.filterwarnings("ignore")
LAT, LON = config.EXAMPLE_POINTS["flat_tiled"]
OFFLINE = {"soil_class": "silty_clay_loam_poorly_drained", "tile_drained": True,
           "small_grain_buyer": True, "can_seed_cover": True}
NO_HAY = {"livestock_or_hay_buyer": False, "hay_equipment": False}
HAY = {"livestock_or_hay_buyer": True, "hay_equipment": True}
ONLY = {k: 0 for k in ("drought", "soil_health", "water_quality", "income", "pests")}


def run(answers, weights, n_boot=300):
    return pipeline.run_analysis(LAT, LON, {**OFFLINE, **answers}, weights, n_boot=n_boot)


def base_id(res, name):
    return res["candidates"][name]["base_id"]


@pytest.fixture(scope="module")
def income_first():
    return run(NO_HAY, {**ONLY, "income": 10})


@pytest.fixture(scope="module")
def soil_first():
    return run(HAY, {**ONLY, "soil_health": 10})


def test_1_income_first_no_hay_keeps_corn_soybean_on_top(income_first):
    """Income weighted maximally, no hay buyer -> corn-soybean (or its cheap variants) at or near the top."""
    top = income_first["ranking"].index[0]
    assert base_id(income_first, top) == "cs", top
    assert income_first["verdict"]["kind"] == "current_best"        # and the tool says so honestly


def test_2_soil_first_with_hay_puts_marsden_4_year_near_top(soil_first):
    """Soil health weighted maximally, hay possible -> C-S-O/A-A at or near the top (top 3)."""
    top3 = [base_id(soil_first, n) for n in soil_first["ranking"].index[:3]]
    assert "csoaa" in top3, top3


def test_3_no_hay_removes_alfalfa_with_a_reason(income_first, soil_first):
    assert not any(base_id(income_first, n) == "csoaa" for n in income_first["candidates"])
    reasons = {r["rotation_id"]: r["reason"] for r in income_first["removed"]}
    assert "Needs livestock or a hay buyer" in reasons["csoaa"]
    assert any(base_id(soil_first, n) == "csoaa" for n in soil_first["candidates"])     # with hay: kept


def test_5_moving_sliders_changes_ranking(income_first, soil_first):
    drought_first = run(NO_HAY, {**ONLY, "drought": 10})
    assert income_first["ranking"].index[0] != drought_first["ranking"].index[0]
    assert not income_first["ranking"]["p_top"].equals(drought_first["ranking"]["p_top"])


def test_results_are_complete_for_the_app(soil_first):
    res = soil_first
    base = res["existing"]["name"]
    assert res["shown"][0]["name"] == base and res["shown"][0]["tier"] == "current"
    assert len(res["candidates"]) >= 3                                       # brief: >= 3 rotations compared
    assert res["ranking"].loc[base, "score_mean"] == pytest.approx(0.5)
    shown = [s["name"] for s in res["shown"]]
    assert [c["rotation"] for c in res["cards"]] == shown
    for card in res["cards"]:
        for part in ("why", "evidence", "benefits", "gaps", "risks"):
            assert card[part], (card["rotation"], part)
        assert "agronomist" in card["footer"]
    assert set(res["calendar"]) == set(shown) and set(res["risk_flags"]) == set(shown)
    assert not res["dropped_criteria"]                                       # income filled in -> nothing dropped
    assert res["income"]["usd_per_acre"][base] > 0                           # return to land and management
    assert res["validation"]["available"] and res["validation"]["sentences"]
    assert res["replay"]["year"] == 2012 and res["trends"].shape[0] > 5

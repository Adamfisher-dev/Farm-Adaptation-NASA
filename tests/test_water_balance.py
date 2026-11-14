"""Water balance tests: water in = water out + change in storage, and sensible behaviour.

Uses the team's crops.py (rotation format [["corn", "cereal_rye"], ["soybean"]]).
"""

import time
import warnings

import numpy as np
import pandas as pd

from fieldshift.model import water_balance as WB
from fieldshift.model.crops import daily_crop_table

warnings.filterwarnings("ignore", message="No room for")
CROPS = WB.load_crops()


def weather(start="1981-01-01", end="1990-12-31", seed=1, rain_scale=1.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq="D")
    doy = idx.dayofyear.values
    rain = np.where(rng.random(len(idx)) < 0.3, rng.gamma(1.2, 8, len(idx)), 0.0) * rain_scale
    et0 = np.clip(3 + 3 * np.sin((doy - 100) / 365 * 2 * np.pi), 0.2, None)
    return pd.DataFrame({"PRECTOTCORR": rain}, index=idx), pd.Series(et0, index=idx)


def params_for(rotation, index, phase=0):
    ct = daily_crop_table(rotation, index.year.min(), index.year.max(), phase=phase, crops=CROPS)
    return WB.bucket_params(ct, index)


def test_bucket_params_have_no_gaps():
    w, _ = weather()
    p = params_for([["corn"], ["soybean"]], w.index)
    assert not p[["kc", "root_m", "p", "state"]].isna().any().any()
    assert set(p["state"]) <= {"crop", "cover", "bare"}


def test_mass_balance_closes_tiled_and_untiled():
    w, et0 = weather()
    p = params_for([["corn"], ["soybean"], ["oats+red_clover"]], w.index)
    for tiled in (True, False):
        day = WB.run_bucket(w["PRECTOTCORR"], et0, p, 200, tiled=tiled, runoff_fraction=0.05)
        assert abs(WB.mass_balance_error(day)) < 1e-6
        assert (day[["w1", "w2", "wet"]] >= -1e-9).all().all()
        assert (day["eta"] <= day["etc"] + 1e-9).all()


def test_drought_causes_stress_and_no_drainage():
    w, et0 = weather(rain_scale=0.0)
    day = WB.run_bucket(w["PRECTOTCORR"], et0, params_for([["corn"], ["soybean"]], w.index), 200)
    assert day["stressed"].sum() > 100
    assert day["drainage"].sum() == 0


def test_untiled_soil_waterlogs_more():
    w, et0 = weather(rain_scale=3.0)
    p = params_for([["corn"], ["soybean"]], w.index)
    tiled = WB.run_bucket(w["PRECTOTCORR"], et0, p, 200, tiled=True)
    untiled = WB.run_bucket(w["PRECTOTCORR"], et0, p, 200, tiled=False)
    assert untiled["waterlogged"].sum() > tiled["waterlogged"].sum() == 0


def test_rye_cover_reduces_drainage_and_bare_wet_days():
    w, et0 = weather("1981-01-01", "2000-12-31")
    plain = WB.rotation_year_table(w, et0, [["corn"], ["soybean"]], 200, crops=CROPS)
    rye = WB.rotation_year_table(w, et0, [["corn", "cereal_rye"], ["soybean"]], 200, crops=CROPS)
    assert rye["drainage_mm"].mean() < plain["drainage_mm"].mean()
    assert rye["bare_wet_days"].mean() < plain["bare_wet_days"].mean()


def test_rotation_year_table_shape_and_speed():
    w, et0 = weather("1981-01-01", "2025-12-31")
    t0 = time.perf_counter()
    table = WB.rotation_year_table(w, et0, [["corn"], ["soybean"], ["oats+red_clover"]], 200, crops=CROPS)
    elapsed = time.perf_counter() - t0
    assert len(table) == 3 * 45 and set(table["phase"]) == {0, 1, 2}
    assert {"drainage_mm", "deficit_sensitive_mm", "bare_wet_days", "main_crop"} <= set(table.columns)
    print(f"\n3-year rotation, 45 years, 3 phases: {elapsed:.2f} s")

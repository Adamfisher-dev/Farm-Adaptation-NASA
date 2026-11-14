"""Tests for power.py helpers and indicators.py, on synthetic weather (no internet)."""

import json

import numpy as np
import pandas as pd

from fieldshift.data.power import check_units, clean, power_cell
from fieldshift.model import indicators as ind


def fake_weather(seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1981-01-01", "2025-12-31", freq="D")
    doy = idx.dayofyear.values
    mean_t = 9 + 15 * np.sin((doy - 110) / 365 * 2 * np.pi) + (idx.year.values - 1981) * 0.02
    rain = np.where(rng.random(len(idx)) < 0.3, rng.gamma(1.2, 8, len(idx)), 0.0)
    return pd.DataFrame({
        "T2M_MAX": mean_t + 6 + rng.normal(0, 3, len(idx)),
        "T2M_MIN": mean_t - 6 + rng.normal(0, 3, len(idx)),
        "PRECTOTCORR": rain,
        "GWETROOT": np.clip(0.6 + rng.normal(0, 0.05, len(idx)), 0, 1),
    }, index=idx)


def test_gdd_never_negative():
    tmax = pd.Series([-5.0, 5.0, 15.0, 40.0])
    tmin = pd.Series([-10.0, 0.0, 5.0, 25.0])
    gdd = ind.daily_gdd(tmax, tmin)
    assert (gdd >= 0).all()
    assert gdd.tolist() == [0.0, 0.0, 2.5, 17.5]


def test_longest_run():
    assert ind.longest_run([True, True, False, True, True, True, False]) == 3
    assert ind.longest_run([]) == 0


def test_yearly_and_snapshot_are_sensible_and_json_safe():
    yearly = ind.yearly_indicators(fake_weather())
    assert len(yearly) == 45
    assert (yearly["frost_free_days"] ==
            yearly["first_autumn_frost_doy"] - yearly["last_spring_frost_doy"] - 1).all()
    snap = ind.snapshot(yearly)
    assert set(snap) == set(ind.SNAPSHOT_KEYS)
    assert snap["gdd"]["trend_per_decade"] > 0          # fake data has warming built in
    json.dumps(snap)
    json.dumps(ind.series_for_charts(yearly))
    assert all(len(v) == 3 for v in ind.notable_years(yearly).values())


def test_clean_handles_fill_value_and_gaps():
    df = fake_weather().iloc[:-10].copy()               # drop last 10 days
    df.iloc[5, 0] = -999.0
    out = clean(df)
    assert np.isnan(out.iloc[5, 0])
    assert len(out) == len(pd.date_range("1981-01-01", "2025-12-31"))
    assert out["T2M_MAX"].tail(10).isna().all()


def test_power_cell_groups_nearby_points():
    a, b = power_cell(42.03, -93.47), power_cell(42.10, -93.60)
    assert a["id"] == b["id"]
    # Cell edge at about -93.44: Story County spans two cells (if the grid assumption holds)
    assert power_cell(42.03, -93.40)["id"] != a["id"]
    lon_min, lat_min, lon_max, lat_max = a["bounds"]
    assert lon_min <= -93.47 <= lon_max and lat_min <= 42.03 <= lat_max


def test_check_units_flags_mismatch():
    warnings = check_units({"T2M": "C", "ALLSKY_SFC_SW_DWN": "kW-hr/m^2/day"})
    assert any("ALLSKY_SFC_SW_DWN" in w for w in warnings)
    assert not any(w.startswith("T2M:") for w in warnings)

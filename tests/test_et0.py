"""ET0 tests against the FAO-56 worked examples.

Example 18: daily ET0 for Uccle (Brussels), 6 July, lat 50 48' N, 100 m.
Published intermediate values and the result (ET0 = 3.9 mm/day) are checked.
Example 8: Ra at 20 S on 3 September = 32.2 MJ/m^2/day.
Check the numbers against your copy of FAO-56 if a test fails.
"""

import numpy as np
import pandas as pd
import pytest

from fieldshift.model import et0 as E


def test_fao56_example8_extraterrestrial_radiation():
    assert E.extraterrestrial_radiation(-20.0, 246) == pytest.approx(32.2, abs=0.1)


def test_fao56_example18_daily_et0():
    lat, z = 50 + 48 / 60, 100.0
    tmax, tmin, rhmax, rhmin = 21.5, 12.3, 84.0, 63.0
    u2 = 2.078                     # 10 km/h at 10 m, converted to 2 m (Eq. 47)
    rs = 22.07                     # from 9.25 h of sunshine (Eq. 35)
    doy = 187                      # 6 July

    pressure = 101.3 * ((293 - 0.0065 * z) / 293) ** 5.26     # Eq. 7
    assert pressure == pytest.approx(100.1, abs=0.1)
    assert E.psychrometric(pressure) == pytest.approx(0.0666, abs=0.0005)

    ea = E.ea_from_rh_minmax(tmax, tmin, rhmax, rhmin)
    assert ea == pytest.approx(1.409, abs=0.005)
    es = (E.sat_vp(tmax) + E.sat_vp(tmin)) / 2
    assert es == pytest.approx(1.997, abs=0.005)
    assert E.slope_svp((tmax + tmin) / 2) == pytest.approx(0.122, abs=0.001)

    ra = E.extraterrestrial_radiation(lat, doy)
    assert ra == pytest.approx(41.09, abs=0.1)
    rso = E.clear_sky_radiation(ra, z)
    assert rso == pytest.approx(30.90, abs=0.1)
    rn, rns, rnl = E.net_radiation(rs, rso, tmax, tmin, ea)
    assert rns == pytest.approx(17.00, abs=0.05)
    assert rnl == pytest.approx(3.71, abs=0.05)
    assert rn == pytest.approx(13.28, abs=0.1)

    et0 = E.penman_monteith(tmax, tmin, ea, u2, rn, pressure)
    assert et0 == pytest.approx(3.9, abs=0.05)


def test_elevation_round_trip():
    pressure = 101.3 * ((293 - 0.0065 * 300) / 293) ** 5.26
    assert E.elevation_from_pressure(pressure) == pytest.approx(300, abs=0.5)


def test_et0_from_power_shape_and_seasons():
    idx = pd.date_range("2020-01-01", "2020-12-31", freq="D")
    doy = idx.dayofyear.values
    t = 9 + 15 * np.sin((doy - 110) / 365 * 2 * np.pi)
    df = pd.DataFrame({
        "T2M_MAX": t + 6, "T2M_MIN": t - 6, "T2MDEW": t - 6,
        "WS2M": np.full(len(idx), 3.0), "PS": np.full(len(idx), 97.8),
        "ALLSKY_SFC_SW_DWN": 4 + 16 * np.clip(np.sin((doy - 80) / 365 * 2 * np.pi) + 0.3, 0, None),
    }, index=idx)
    et0 = E.et0_from_power(df, lat=42.0)
    assert len(et0) == len(idx) and (et0 >= 0).all()
    july, jan = et0[idx.month == 7].mean(), et0[idx.month == 1].mean()
    assert 3 < july < 8 and jan < 1.5 and july > 4 * jan

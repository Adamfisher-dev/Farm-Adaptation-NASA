"""Tests for data/ground.py parsing on small IEM-style samples (no downloads)."""

import numpy as np
import pytest

from fieldshift.data import ground

CLIMATE = """# Iowa Environmental Mesonet -- NWS Cooperative Data
# Created: 14 Nov 2026 17:48:36 UTC
# Data Period: 2019-07-01 - 2019-07-03
station,station_name,day,doy,high,low,precip
IA0203,AMES 5 SE,2019/07/01,182,212,32,1.0
IA0203,AMES 5 SE,2019/07/02,183,M,50,0.0001
IA0203,AMES 5 SE,2019/07/03,184,86,68,M
"""

ISUSM = """station,valid,high,low,precip,soil12t,soil24t,soil50t,soil12vwc,soil24vwc,soil50vwc
AEEI4,2019-01-15,20.0,5.0,0.10,30.0,33.5,36.0,12.0,20.0,25.0
AEEI4,2019-07-01,90.3,72.9,0.00,80.4,75.7,69.5,24.3,18.5,25.4
AEEI4,2019-07-02,91.7,68.5,M,79.8,M,70.2,M,95.0,25.1
"""


def test_climate_units_trace_and_missing():
    w = ground.parse_climate(CLIMATE)
    assert w.loc["2019-07-01", "tmax_c"] == pytest.approx(100.0)        # 212 F
    assert w.loc["2019-07-01", "tmin_c"] == pytest.approx(0.0)          # 32 F
    assert w.loc["2019-07-01", "precip_mm"] == pytest.approx(25.4)      # 1 inch
    assert w.loc["2019-07-02", "precip_mm"] == 0.0                      # trace -> 0
    assert np.isnan(w.loc["2019-07-02", "tmax_c"]) and np.isnan(w.loc["2019-07-03", "precip_mm"])


def test_isusm_percent_to_fraction_frozen_and_implausible():
    s = ground.parse_isusm(ISUSM)
    assert s.loc["2019-07-01", "vwc_30cm"] == pytest.approx(0.243)
    assert np.isnan(s.loc["2019-01-15", "vwc_30cm"])                    # probe at 30 F: frozen
    assert s.loc["2019-01-15", "vwc_60cm"] == pytest.approx(0.20)       # 33.5 F: not frozen
    assert np.isnan(s.loc["2019-07-02", "vwc_60cm"])                    # 95 % is not plausible
    assert np.isnan(s.loc["2019-07-02", "vwc_30cm"])                    # missing


def test_loaders_read_files_and_check_depth(tmp_path):
    (tmp_path / "c.csv").write_text(CLIMATE, encoding="utf-8")
    (tmp_path / "s.csv").write_text(ISUSM, encoding="utf-8")
    w = ground.load_station_weather(tmp_path / "c.csv")
    assert list(w.columns) == ["tmax_c", "tmin_c", "precip_mm"] and len(w) == 3
    obs = ground.load_soil_moisture("60cm", tmp_path / "s.csv")
    assert obs.index.freq == "D" and obs.name == "isusm_60cm"
    with pytest.raises(ValueError):
        ground.load_soil_moisture("10cm", tmp_path / "s.csv")
    with pytest.raises(FileNotFoundError):
        ground.load_station_weather(tmp_path / "missing.csv")

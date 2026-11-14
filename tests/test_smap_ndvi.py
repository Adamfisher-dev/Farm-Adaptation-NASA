"""Tests for appeears.py, smap.py and ndvi.py on small synthetic AppEEARS-style CSVs (no downloads)."""

import numpy as np
import pandas as pd
import pytest

from fieldshift import config
from fieldshift.data import appeears, ndvi, smap

L3 = "SPL3SMP_E_006_"
L4 = "SPL4SMGP_008_"
AM, AMQ = config.SMAP_L3_LAYERS["am"]
PM, PMQ = config.SMAP_L3_LAYERS["pm"]


def test_task_body_uses_documented_format():
    body = appeears.point_task_body("t", [("SPL3SMP_E.006", AM)], [("centre", "smap", 42.03, -93.47)],
                                    "2015-04-01", "2025-12-31")
    assert body["task_type"] == "point"
    assert body["params"]["dates"] == [{"startDate": "04-01-2015", "endDate": "12-31-2025"}]
    assert body["params"]["coordinates"][0] == {"id": "centre", "category": "smap",
                                                "latitude": 42.03, "longitude": -93.47}


def test_find_column_matches_layer_suffix_only():
    df = pd.DataFrame(columns=["ID", "Date", L3 + AM, L3 + AM + "_dca"])
    assert appeears.find_column(df, AM) == L3 + AM
    assert appeears.find_column(df, "date") == "Date"
    with pytest.raises(KeyError):
        appeears.find_column(df, "missing_layer")


def test_smap_quality_fill_and_daily_mean(tmp_path):
    l3 = pd.DataFrame({
        "ID": ["centre"] * 3, "Category": "smap",
        "Date": ["2016-06-01", "2016-06-02", "2016-06-03"],
        L3 + AM:  [0.30, 0.25, -9999.0],
        L3 + AMQ: [0, 1, 0],            # day 2 AM: not recommended quality -> dropped
        L3 + PM:  [0.20, 0.27, 0.22],
        L3 + PMQ: [0, 0, 65534],        # day 3 PM: flag fill -> dropped
    })
    l4 = pd.DataFrame({
        "ID": ["centre"] * 4, "Date": ["2016-06-01 01:30", "2016-06-01 04:30",
                                       "2016-06-02 01:30", "2016-06-02 04:30"],
        L4 + "Geophysical_Data_sm_rootzone": [0.30, 0.32, -9999.0, 0.28],
        L4 + "Geophysical_Data_sm_surface": [0.25, 0.27, 0.20, 0.22],
    })
    l3.to_csv(tmp_path / "a.csv", index=False)
    l4.to_csv(tmp_path / "b.csv", index=False)
    out = tmp_path / "smap_daily.csv"
    smap.build_compact(tmp_path, out)
    df = smap.load_smap("centre", out)
    d1, d2, d3 = df.loc["2016-06-01"], df.loc["2016-06-02"], df.loc["2016-06-03"]
    assert d1.sm_surface_l3 == pytest.approx(0.25)          # mean of AM 0.30 and PM 0.20
    assert d2.sm_surface_l3 == pytest.approx(0.27)          # AM dropped (quality)
    assert np.isnan(d3.sm_surface_l3)                        # AM fill, PM flag fill
    assert d1.sm_rootzone_l4 == pytest.approx(0.31)          # 3-hourly -> daily mean
    assert d2.sm_rootzone_l4 == pytest.approx(0.28)          # fill ignored
    with pytest.raises(ValueError):
        smap.load_smap("nowhere", out)


def test_seasonal_anomaly_removes_the_annual_cycle():
    idx = pd.date_range("2015-01-01", "2024-12-31", freq="D")
    cycle = 0.25 + 0.08 * np.sin(2 * np.pi * idx.day_of_year / 365)
    s = pd.Series(cycle, index=idx)
    s.loc["2020-07-01":"2020-07-31"] -= 0.10                 # one dry month
    anom = smap.seasonal_anomaly(s)
    assert anom.loc["2018"].abs().mean() < 0.01
    assert anom.loc["2020-07-10":"2020-07-20"].mean() < -0.08


def test_fmask_bits():
    # 0 clear, 2 cloud, 4 adjacent, 8 shadow, 16 snow, 32 water, 64 low aerosol (ok),
    # 192 high aerosol, 255 fill
    f = pd.Series([0, 2, 4, 8, 16, 32, 64, 192, 255])
    assert ndvi.clear_mask(f).tolist() == [True, False, False, False, False, False, True, False, False]


def test_sample_grid_is_centred_and_spaced():
    pts = ndvi.sample_points({"f": (42.0, -93.5)})
    assert len(pts) == 9 and pts[4][2:] == (42.0, -93.5)
    dlat_m = (pts[7][2] - pts[4][2]) * 110_540
    assert dlat_m == pytest.approx(config.HLS_SAMPLE_SPACING_M, abs=0.5)


def test_ndvi_field_median_and_cloudy_dates(tmp_path):
    rows = []
    for k in range(9):
        # 2020-07-01 all clear; 2020-07-05 cloudy except 2 pixels -> dropped (needs 5 of 9)
        rows.append({"ID": f"centre_{k}", "Category": "centre", "Date": "2020-07-01",
                     "HLSL30_020_B04": 400, "HLSL30_020_B05": 3600 + k, "HLSL30_020_Fmask": 64})
        rows.append({"ID": f"centre_{k}", "Category": "centre", "Date": "2020-07-05",
                     "HLSL30_020_B04": 400, "HLSL30_020_B05": 3600,
                     "HLSL30_020_Fmask": 0 if k < 2 else 2})
    pd.DataFrame(rows).to_csv(tmp_path / "l30.csv", index=False)
    s30 = pd.DataFrame({"ID": [f"centre_{k}" for k in range(9)], "Category": "centre",
                        "Date": "2020-07-03", "HLSS30_020_B04": 2000, "HLSS30_020_B05": 2500,
                        "HLSS30_020_B8A": 2000, "HLSS30_020_Fmask": 0})       # bare-ish: NDVI 0
    s30.to_csv(tmp_path / "s30.csv", index=False)
    out = tmp_path / "hls.csv"
    ndvi.build_compact(tmp_path, out)
    obs = ndvi.load_ndvi("centre", out)
    assert list(obs.index.strftime("%Y-%m-%d")) == ["2020-07-01", "2020-07-03"]
    assert obs.loc["2020-07-01", "ndvi"] == pytest.approx((3604 - 400) / (3604 + 400), abs=1e-3)
    assert obs.loc["2020-07-03", "sensor"] == "Sentinel-2"     # B8A used as NIR, not B05
    assert obs.loc["2020-07-03", "ndvi"] == pytest.approx(0.0)
    assert ndvi.dekadal(obs["ndvi"]).iloc[0] == pytest.approx(0.8, abs=0.01)   # max in 1-10 Jul


def test_run_all_submits_everything_first_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(appeears, "TASKS_FILE", tmp_path / "tasks.json")
    calls = []
    monkeypatch.setattr(appeears, "submit", lambda tok, body: calls.append(("submit", body["task_name"])) or body["task_name"] + "_id")
    progress = {"a_id": iter(["pending", "done"]), "b_id": iter(["processing", "processing"])}
    monkeypatch.setattr(appeears, "status", lambda tok, tid: calls.append(("status", tid)) or next(progress[tid]))
    monkeypatch.setattr(appeears, "download", lambda tok, tid, folder: [folder / f"{tid}.csv"])
    jobs = [("a", {"task_name": "a"}, tmp_path), ("b", {"task_name": "b"}, tmp_path)]

    state = appeears.run_all("tok", jobs, wait_minutes=0, poll_s=0)
    assert calls[:2] == [("submit", "a"), ("submit", "b")]          # both submitted before any polling
    assert state == {"a": "pending", "b": "processing"}

    calls.clear()
    state = appeears.run_all("tok", jobs, wait_minutes=0, poll_s=0)  # second run: nothing resubmitted
    assert not [c for c in calls if c[0] == "submit"]
    assert state == {"a": "downloaded", "b": "processing"}
    assert appeears.load_tasks()["a"]["downloaded"] is True

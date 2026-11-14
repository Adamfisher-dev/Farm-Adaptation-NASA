"""Tests for soil.py, terrain.py, cdl.py and field.py on small synthetic files (no downloads)."""

import math

import numpy as np
import pandas as pd
import pytest

gpd = pytest.importorskip("geopandas")
rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402
from shapely.geometry import box  # noqa: E402

from fieldshift.data import cdl, field, soil, terrain  # noqa: E402

LAT, LON = 42.03, -93.47


def test_field_geometry_box_and_geojson():
    g = field.field_geometry(point=(LAT, LON))
    assert g.contains(g.centroid) and 14 < field._area_ha(g) < 18          # ~400 m x 400 m = 16 ha
    drawn = {"type": "Feature", "geometry": g.__geo_interface__}
    assert field.field_geometry(geojson=drawn).equals(g)
    with pytest.raises(ValueError):
        field.field_geometry()


def test_soil_area_weighting():
    fld = field.field_geometry(point=(LAT, LON))
    minx, miny, maxx, maxy = fld.bounds
    mid = (minx + maxx) / 2
    polys = gpd.GeoDataFrame({
        "mukey": ["1", "2"], "muname": ["Webster", "Clarion"],
        "aws0100wta": [20.0, 16.0], "drclassdcd": ["Poorly drained", "Well drained"],
        "hydgrpdcd": ["C/D", "B"],
    }, geometry=[box(minx - 0.01, miny - 0.01, mid, maxy + 0.01), box(mid, miny - 0.01, maxx + 0.01, maxy + 0.01)],
        crs="EPSG:4326").to_crs("EPSG:5070")
    polys["awc_mm_per_m"] = polys["aws0100wta"] * 10
    prof = soil.field_soil_profile(fld, ssurgo=polys)
    assert prof.awc_mm_per_m == pytest.approx(180, abs=3)                  # half 200, half 160
    assert prof.data_coverage == pytest.approx(1.0, abs=0.01)
    assert set(prof.drainage_mix) == {"Poorly drained", "Well drained"}


def test_soil_fallback_from_csv():
    prof = soil.fallback_profile("loam_well_drained")
    assert prof.awc_mm_per_m == 170 and not prof.likely_tiled and "Farmer-provided" in prof.source


def test_slope_of_a_known_ramp():
    res = 1 / 3600                                                          # 1 arc-second
    rows = cols = 120
    transform = from_origin(LON - cols * res / 2, LAT + rows * res / 2, res, res)
    m_per_cell_x = res * 111_320 * math.cos(math.radians(LAT))
    dem = np.tile(np.arange(cols) * m_per_cell_x * 0.04, (rows, 1))        # 4 % rise west -> east
    fld = field.field_geometry(point=(LAT, LON), half_side_m=500)
    s = terrain.field_slope(fld, dem=dem, transform=transform)
    assert s["slope_pct_mean"] == pytest.approx(4.0, abs=0.1)
    assert s["slope_class"].startswith("B") and not s["erosion_prone"]


def test_cdl_history_and_rotation_guess(tmp_path):
    fld = field.field_geometry(point=(LAT, LON))
    albers = gpd.GeoSeries([fld], crs="EPSG:4326").to_crs("EPSG:5070")
    minx, miny, maxx, maxy = albers.total_bounds
    transform = from_origin(minx - 300, maxy + 300, 30, 30)
    shape = (int((maxy - miny + 600) / 30) + 1, int((maxx - minx + 600) / 30) + 1)
    for year, code in [(2019, 1), (2020, 5), (2021, 1), (2022, 5), (2023, 1), (2024, 5)]:
        arr = np.full(shape, code, dtype="uint8")
        with rasterio.open(tmp_path / f"cdl_{year}_19169.tif", "w", driver="GTiff", height=shape[0],
                           width=shape[1], count=1, dtype="uint8", crs="EPSG:5070", transform=transform) as dst:
            dst.write(arr, 1)
    hist, details = cdl.crop_history(fld, folder=tmp_path, fips="19169")
    assert hist == {"2019": "corn", "2020": "soybean", "2021": "corn", "2022": "soybean",
                    "2023": "corn", "2024": "soybean"}
    rotation, text = cdl.guess_rotation(hist)
    assert rotation == [["corn"], ["soybean"]] and "2019-2024" in text


def test_field_profile_falls_back_without_data(monkeypatch, tmp_path):
    monkeypatch.setattr(soil, "SSURGO_DIR", tmp_path)
    soil._cached_ssurgo.cache_clear()
    monkeypatch.setattr(soil, "find_ssurgo_files", lambda folder=tmp_path: (_ for _ in ()).throw(FileNotFoundError("none")))
    monkeypatch.setattr(terrain, "load_dem", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("none")))
    monkeypatch.setattr(cdl, "CDL_DIR", tmp_path)
    monkeypatch.setattr(cdl, "available_years", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("none")))
    prof = field.build_field_profile(field.field_geometry(point=(LAT, LON)),
                                     overrides={"tile_drained": False, "existing_rotation": [["corn"], ["soybean"]]})
    d = prof.to_dict()
    assert d["awc_mm_per_m"] == 200 and d["tile_drained"] is False
    assert d["existing_rotation_guess"] == [["corn"], ["soybean"]]
    assert {"tile_drained", "existing_rotation"} <= set(d["overridden"])
    assert len(d["warnings"]) >= 3 and d["power_cell"]["id"] == "42.000_-93.750"

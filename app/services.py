"""Data and analysis calls for the app, cached so each field and each set of answers is computed once.

UI-free helpers live here so every view uses the same cached results.
"""

import json

import streamlit as st

from fieldshift import config, pipeline

N_BOOT = 1000         # resamples per analysis (the pipeline's full setting; up to about a minute)
CALENDAR_START_YEAR = 2021   # any run of years works; the calendar shows one rotation cycle


@st.cache_resource(show_spinner=False)
def county_shape():
    """Story County outline (shapely polygon, WGS84)."""
    from shapely.geometry import shape
    data = json.loads(config.COUNTY_GEOJSON.read_text(encoding="utf-8"))
    return shape(data["features"][0]["geometry"])


def county_geojson() -> dict:
    return json.loads(config.COUNTY_GEOJSON.read_text(encoding="utf-8"))


def in_county(lat: float, lon: float) -> bool:
    from shapely.geometry import Point
    return county_shape().contains(Point(lon, lat))


@st.cache_data(show_spinner=False)
def field_lookup(lat: float, lon: float) -> dict:
    """Soil, slope and crop history for the ~400 m field around the point."""
    return pipeline.field_profile(lat, lon).to_dict()


def freeze(d: dict) -> tuple:
    """Hashable form of a dict of answers (lists become tuples) for the cache key."""
    return tuple(sorted((k, tuple(v) if isinstance(v, list) else v) for k, v in d.items()))


@st.cache_data(show_spinner=False, max_entries=20)
def analyse(lat: float, lon: float, answers_frozen: tuple, weights_frozen: tuple) -> dict:
    answers = {k: list(v) if isinstance(v, tuple) else v for k, v in answers_frozen}
    return pipeline.run_analysis(lat, lon, answers=answers, weights=dict(weights_frozen), n_boot=N_BOOT)


@st.cache_data(show_spinner=False, max_entries=64)
def crop_days(plan_frozen: tuple):
    """Day-by-day crop table for one rotation cycle (for the calendar)."""
    from fieldshift.model import crops as crops_mod
    plan = [list(year) for year in plan_frozen]
    return crops_mod.daily_crop_table(plan, CALENDAR_START_YEAR, CALENDAR_START_YEAR + len(plan) - 1, phase=0)



# --- where the field is ------------------------------------------------------------------------------
PLACES_FILE = config.ROOT / "sample_data" / "story_places.json"   # US Census incorporated places


@st.cache_resource(show_spinner=False)
def _places() -> list:
    return json.loads(PLACES_FILE.read_text(encoding="utf-8"))["places"]


def location_text(lat: float, lon: float) -> str:
    """'In Ames' / '3.4 km NE of Nevada' from the nearest Story County town (US Census places)."""
    import math
    best = None
    for p in _places():
        dy = (p["lat"] - lat) * 110.57
        dx = (p["lon"] - lon) * 111.32 * math.cos(math.radians(lat))
        d = math.hypot(dx, dy)
        if best is None or d < best[0]:
            best = (d, p["name"], -dx, -dy)            # vector from the town to the field
    d, name, dx, dy = best
    if d < 1.5:
        return f"In {name}"
    points = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    bearing = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    return f"{d:.1f} km {points[int((bearing + 22.5) // 45) % 8]} of {name}"


def field_area_ha(lat: float, lon: float) -> float:
    from fieldshift.data.field import _area_ha, field_geometry
    return _area_ha(field_geometry(point=(lat, lon)))

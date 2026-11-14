"""field.py - everything we know about one field, in one FieldProfile.

Combines soil (soil.py, SSURGO), slope (terrain.py, SRTM), crop history (cdl.py, CDL)
and the weather cell (power.py, NASA POWER), then applies the farmer's corrections.
Every source is optional: if its files are missing (e.g. on Streamlit Cloud) the
profile falls back to farmer answers and says so in `warnings`, so the app never crashes.

    from fieldshift.data.field import field_geometry, build_field_profile
    geom = field_geometry(point=(42.03, -93.47))            # or geojson=<drawn polygon>
    prof = build_field_profile(geom, overrides={"soil_class": "loam_well_drained"})
    prof.to_dict()                                            # -> results["field"] (CLAUDE.md 10.3)

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from fieldshift.data import cdl, soil, terrain
from fieldshift.data.power import power_cell

BOX_HALF_SIDE_M = 200.0          # clicked point -> ~400 m x 400 m box (CLAUDE.md 4)
DEFAULT_SOIL_CLASS = "silty_clay_loam_poorly_drained"


def field_geometry(geojson=None, point=None, half_side_m=BOX_HALF_SIDE_M):
    """Shapely polygon (WGS84) from a drawn GeoJSON polygon/feature, or a box around (lat, lon)."""
    from shapely.geometry import box, shape
    if geojson is not None:
        g = geojson.get("geometry", geojson) if isinstance(geojson, dict) else geojson
        geom = shape(g)
        if geom.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"Field must be a polygon, got {geom.geom_type}")
        return geom
    if point is None:
        raise ValueError("Give either geojson or point=(lat, lon)")
    lat, lon = point
    dlat = half_side_m / 110_540.0
    dlon = half_side_m / (111_320.0 * math.cos(math.radians(lat)))
    return box(lon - dlon, lat - dlat, lon + dlon, lat + dlat)


@dataclass
class FieldProfile:
    centroid: list                        # [lat, lon]
    area_ha: float
    soil: dict
    slope: dict
    crop_history: dict
    existing_rotation_guess: list | None
    rotation_question: str
    power_cell: dict
    awc_mm_per_m: float
    tile_drained: bool
    erosion_prone: bool
    hydrologic_group: str | None
    overridden: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _area_ha(geom):
    import geopandas as gpd
    return float(gpd.GeoSeries([geom], crs="EPSG:4326").to_crs("EPSG:5070").area.iloc[0] / 10_000)


def build_field_profile(geom, overrides=None):
    """FieldProfile for a polygon. overrides (farmer answers, all optional):
    soil_class, tile_drained, erosion_prone, existing_rotation.
    """
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    warnings, sources, overridden = [], {}, []
    c = geom.centroid

    # soil
    if "soil_class" in overrides:
        s = soil.fallback_profile(overrides["soil_class"])
        overridden.append("soil_class")
    else:
        try:
            s = soil.field_soil_profile(geom)
        except (FileNotFoundError, ValueError) as err:
            s = soil.fallback_profile(DEFAULT_SOIL_CLASS)
            warnings.append(f"Soil survey not available ({err}). Using a typical central-Iowa soil; "
                            "please pick your soil type.")
    sources["soil"] = s.source
    warnings += s.warnings

    # slope
    try:
        sl = terrain.field_slope(geom)
        sources["slope"] = sl["source"]
    except (FileNotFoundError, ValueError) as err:
        sl = {"slope_pct_mean": None, "slope_pct_p90": None, "slope_class": "unknown",
              "erosion_prone": False, "rusle_s": None, "source": "not available"}
        warnings.append(f"Elevation data not available ({err}). Please say whether the field is sloping.")

    # crop history
    try:
        hist, _ = cdl.crop_history(geom)
        guess, question = cdl.guess_rotation(hist)
        sources["crop_history"] = "USDA NASS Cropland Data Layer"
    except (FileNotFoundError, ValueError) as err:
        hist, guess, question = {}, None, "What do you grow on this field now?"
        warnings.append(f"Crop history not available ({err}).")

    # farmer corrections win over data
    tile = overrides.get("tile_drained", s.likely_tiled)
    erosion = overrides.get("erosion_prone", sl["erosion_prone"])
    for key in ("tile_drained", "erosion_prone", "existing_rotation"):
        if key in overrides:
            overridden.append(key)
    if "existing_rotation" in overrides:
        guess = overrides["existing_rotation"]

    hsg = s.hydrologic_group if s.hydrologic_group not in ("Unknown", "nan", "") else None
    return FieldProfile(
        centroid=[round(c.y, 5), round(c.x, 5)],
        area_ha=round(_area_ha(geom), 1),
        soil=s.to_dict(), slope=sl, crop_history=hist,
        existing_rotation_guess=guess, rotation_question=question,
        power_cell=power_cell(c.y, c.x),
        awc_mm_per_m=s.awc_mm_per_m, tile_drained=bool(tile), erosion_prone=bool(erosion),
        hydrologic_group=hsg, overridden=overridden, sources=sources, warnings=warnings,
    )

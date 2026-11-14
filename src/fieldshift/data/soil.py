"""soil.py - soil properties for one field from USDA NRCS SSURGO (CLAUDE.md 10.4, Appendix B).

Inputs : SSURGO map-unit polygons (shapefile from Web Soil Survey, key MUKEY)
         + attributes CSV from Soil Data Access (scripts/prefetch_field_data.py)
Method : area-weighted overlay of map units with the field boundary
Output : SoilProfile  (or a farmer-chosen fallback from content/soils.csv)

    from fieldshift.data.soil import field_soil_profile, fallback_profile
    soil = field_soil_profile(field_polygon_wgs84)      # needs data/raw/ssurgo
    soil = fallback_profile("loam_well_drained")         # no data needed

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic) from the team's Appendix B; reviewed by the team.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from fieldshift import config

ROOT = Path(__file__).resolve().parents[3]
RAW = getattr(config, "DATA_RAW", ROOT / "data" / "raw")
SSURGO_DIR = RAW / "ssurgo"
SOILS_CSV = getattr(config, "CONTENT_DIR", ROOT / "content") / "soils.csv"

EQUAL_AREA_CRS = "EPSG:5070"   # CONUS Albers equal-area: .area in m²
WGS84 = "EPSG:4326"
WET_CLASSES = {"Poorly drained", "Very poorly drained"}


@dataclass
class SoilProfile:
    awc_mm_per_m: float                    # plant-available water per metre of soil (area-weighted)
    drainage_class: str                    # dominant by area
    drainage_mix: dict                     # class -> fraction of field area
    hydrologic_group: str                  # dominant hydrologic soil group (A-D)
    dominant_mapunit: str
    mapunit_mix: dict
    data_coverage: float                   # fraction of field with valid AWC
    likely_tiled: bool                     # hint only - farmer confirms
    source: str = "USDA NRCS SSURGO, survey area IA169 (muaggatt table)"
    warnings: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


# --- Files -------------------------------------------------------------------
def find_ssurgo_files(folder: Path = SSURGO_DIR):
    """(polygons shapefile, attributes CSV) under data/raw/ssurgo, or raise FileNotFoundError."""
    shapes = sorted(folder.rglob("soilmu_a_*.shp"))
    attrs = sorted(folder.rglob("*muaggatt*.csv"))
    if not shapes or not attrs:
        raise FileNotFoundError(
            f"SSURGO files not found under {folder}. Download polygons from Web Soil Survey "
            "and run scripts/prefetch_field_data.py for the attributes.")
    return shapes[0], attrs[0]


def load_ssurgo(polygons_path: Path, attributes_csv: Path):
    """Join SSURGO polygons to attributes; project to equal-area. Call once, then cache."""
    import geopandas as gpd
    polys = gpd.read_file(polygons_path)
    attrs = pd.read_csv(attributes_csv, dtype={"mukey": str}, encoding="utf-8")
    key = "MUKEY" if "MUKEY" in polys.columns else "mukey"
    polys[key] = polys[key].astype(str)
    merged = polys.merge(attrs, left_on=key, right_on="mukey", how="left")
    # aws0100wta = cm of available water in top 100 cm -> x10 = mm per metre of soil
    merged["awc_mm_per_m"] = pd.to_numeric(merged["aws0100wta"], errors="coerce") * 10.0
    return merged.to_crs(EQUAL_AREA_CRS)


@lru_cache(maxsize=1)
def _cached_ssurgo():
    return load_ssurgo(*find_ssurgo_files())


# --- Field summary -------------------------------------------------------------
def _area_mix(pieces, column: str) -> dict:
    shares = pieces.groupby(column)["frac"].sum()
    if shares.empty:
        return {}
    shares = shares / shares.sum()
    return shares.sort_values(ascending=False).round(3).to_dict()


def field_soil_profile(field_geom, ssurgo=None) -> SoilProfile:
    """Area-weighted soil summary for one field (shapely polygon in WGS84)."""
    import geopandas as gpd
    ssurgo = _cached_ssurgo() if ssurgo is None else ssurgo
    fld = gpd.GeoDataFrame(geometry=[field_geom], crs=WGS84).to_crs(EQUAL_AREA_CRS)
    field_area = fld.area.iloc[0]

    idx = ssurgo.sindex.query(fld.geometry.iloc[0], predicate="intersects")
    if len(idx) == 0:
        raise ValueError("Field is outside the downloaded SSURGO survey area.")
    pieces = gpd.overlay(ssurgo.iloc[idx], fld, how="intersection")
    pieces["frac"] = pieces.area / field_area

    warnings = []
    mapped = pieces["frac"].sum()
    if mapped < 0.98:
        warnings.append(f"Only {mapped:.0%} of the field lies inside the soil survey area.")

    valid = pieces.dropna(subset=["awc_mm_per_m"])
    coverage = valid["frac"].sum()
    if coverage == 0:
        raise ValueError("No water-capacity data for any part of this field.")
    if coverage < 0.9:
        warnings.append(f"Soil water data covers only {coverage:.0%} of the field.")
    awc = (valid["awc_mm_per_m"] * valid["frac"]).sum() / coverage

    var = ((valid["awc_mm_per_m"] - awc) ** 2 * valid["frac"]).sum() / coverage
    if awc > 0 and var ** 0.5 / awc > 0.25:
        warnings.append("Soil water capacity varies a lot within this field; consider treating parts separately.")

    drainage_mix = _area_mix(pieces, "drclassdcd")
    hydgroup_mix = _area_mix(pieces, "hydgrpdcd")
    mapunit_mix = _area_mix(pieces, "muname")
    wet_share = sum(f for c, f in drainage_mix.items() if c in WET_CLASSES)

    return SoilProfile(
        awc_mm_per_m=round(float(awc), 1),
        drainage_class=next(iter(drainage_mix), "Unknown"),
        drainage_mix=drainage_mix,
        hydrologic_group=next(iter(hydgroup_mix), "Unknown"),
        dominant_mapunit=next(iter(mapunit_mix), "Unknown"),
        mapunit_mix=mapunit_mix,
        data_coverage=round(float(coverage), 3),
        likely_tiled=wet_share > 0.3,     # heuristic, confirmed by farmer
        warnings=warnings,
    )


# --- Farmer fallback (no SSURGO needed) ----------------------------------------
def soil_classes(path: Path = SOILS_CSV) -> pd.DataFrame:
    """content/soils.csv: the soil choices offered to the farmer."""
    return pd.read_csv(path, encoding="utf-8").set_index("soil_class", drop=False)


def fallback_profile(soil_class: str, path: Path = SOILS_CSV) -> SoilProfile:
    """SoilProfile from a farmer-selected class in content/soils.csv (marked farmer-provided)."""
    row = soil_classes(path).loc[soil_class]
    tiled = str(row["tile_drained_default"]).strip().lower() == "true"
    return SoilProfile(
        awc_mm_per_m=float(row["awc_mm_per_m"]),
        drainage_class="Poorly drained" if tiled else "Well drained",
        drainage_mix={},
        hydrologic_group=str(row["hydrologic_group"]),
        dominant_mapunit=str(row["label"]),
        mapunit_mix={},
        data_coverage=0.0,
        likely_tiled=tiled,
        source=f"Farmer-provided soil class '{soil_class}' (content/soils.csv: {row['source']})",
        warnings=["Soil values are typical for the chosen class, not measured for this field."],
    )

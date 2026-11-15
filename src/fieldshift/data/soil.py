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
    slope_pct: float | None = None         # area-weighted representative slope of the map units
    # hydraulics for the water model on UNTILED fields (SSURGO chorizon + muaggatt; None if unavailable)
    ksat_mm_day: float | None = None       # saturated conductivity of the most restrictive layer in 0-150 cm
    drainable_mm: float | None = None      # water held between field capacity and saturation, top 1 m
    spring_wt_shallow_share: float | None = None   # share of the field with an Apr-Jun water table < 100 cm
    hydraulics_source: str | None = None
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
    """Area-weighted soil summary for one field (shapely polygon in WGS84).
    Uses local SSURGO files when present (or `ssurgo` passed in), otherwise asks
    USDA Soil Data Access live (works anywhere in the US, needs internet)."""
    if ssurgo is None:
        try:
            ssurgo = _cached_ssurgo()
        except FileNotFoundError:
            return field_soil_profile_sda(field_geom)
    import geopandas as gpd
    fld = gpd.GeoDataFrame(geometry=[field_geom], crs=WGS84).to_crs(EQUAL_AREA_CRS)
    field_area = fld.area.iloc[0]

    idx = ssurgo.sindex.query(fld.geometry.iloc[0], predicate="intersects")
    if len(idx) == 0:
        raise ValueError("Field is outside the downloaded SSURGO survey area.")
    pieces = gpd.overlay(ssurgo.iloc[idx], fld, how="intersection")
    pieces["frac"] = pieces.area / field_area
    prof = summarise_pieces(pd.DataFrame(pieces.drop(columns="geometry")))
    key = "MUKEY" if "MUKEY" in pieces.columns else "mukey"
    _add_hydraulics(prof, pieces.groupby(key)["frac"].sum())
    return prof


# --- Live: USDA Soil Data Access ------------------------------------------------
SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"

# SDA macros clip SSURGO map-unit polygons to the field and return their true areas
# (geography, m2). Joined to muaggatt for the same attributes as the local files.
SDA_FIELD_QUERY = """~DeclareGeometry(@aoi)~
select @aoi = geometry::STPolyFromText('{wkt}', 4326)
~DeclareIdGeomTable(@intersectedPolygonGeometries)~
~GetClippedMapunits(@aoi,polygon,geo,@intersectedPolygonGeometries)~
~DeclareIdGeogTable(@intersectedPolygonGeographies)~
~GetGeogFromGeomWgs84(@intersectedPolygonGeometries,@intersectedPolygonGeographies)~
select g.id as mukey, sum(g.geog.STArea()) as area_m2, mu.muname,
       ma.aws0100wta, ma.drclassdcd, ma.hydgrpdcd, ma.slopegradwta
from @intersectedPolygonGeographies g
inner join mapunit mu on mu.mukey = g.id
inner join muaggatt ma on ma.mukey = g.id
group by g.id, mu.muname, ma.aws0100wta, ma.drclassdcd, ma.hydgrpdcd, ma.slopegradwta"""


def sda_field_mapunits(field_geom, timeout=60) -> pd.DataFrame:
    """SSURGO map units inside the field from Soil Data Access, one row per map unit."""
    import requests
    geom = field_geom if field_geom.geom_type == "Polygon" else field_geom.convex_hull
    q = SDA_FIELD_QUERY.format(wkt=geom.wkt)
    try:
        r = requests.post(SDA_URL, json={"query": q, "format": "JSON+COLUMNNAME"}, timeout=timeout)
    except requests.RequestException as err:      # offline / service down -> caller falls back
        raise ValueError(f"USDA Soil Data Access not reachable ({type(err).__name__})") from err
    if r.status_code != 200:
        raise ValueError(f"Soil Data Access error {r.status_code}: {r.text[:200]}")
    table = (r.json() or {}).get("Table") or []
    if len(table) < 2:
        raise ValueError("No SSURGO soil map units found for this field.")
    df = pd.DataFrame(table[1:], columns=table[0])
    for c in ("area_m2", "aws0100wta", "slopegradwta"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def field_soil_profile_sda(field_geom, mapunits: pd.DataFrame | None = None) -> SoilProfile:
    """Area-weighted soil summary from live SSURGO (Soil Data Access)."""
    from fieldshift.data.field import _area_ha
    df = sda_field_mapunits(field_geom) if mapunits is None else mapunits.copy()
    df["frac"] = df["area_m2"] / (_area_ha(field_geom) * 10_000)
    prof = summarise_pieces(df)
    prof.source = "USDA NRCS SSURGO via Soil Data Access (live query, muaggatt table)"
    if mapunits is None:                # live query: also fetch drainage properties (skipped for given rows/tests)
        _add_hydraulics(prof, df.groupby("mukey")["frac"].sum())
    return prof


# --- Hydraulic properties (for untiled fields in the water model) -------------------------
SHALLOW_WATER_TABLE_CM = 100      # the water model's profile is the top 1 m
KSAT_DEPTH_CM = 150               # restrictive layer searched in the top 1.5 m
UM_S_TO_MM_DAY = 86.4             # 1 micrometre per second = 86.4 mm per day

SDA_HYDRAULICS_QUERY = """SELECT ma.mukey, ma.wtdepaprjunmin, c.cokey, c.comppct_r,
       h.hzdept_r, h.hzdepb_r, h.ksat_r, h.wsatiated_r, h.wthirdbar_r
FROM muaggatt ma JOIN component c ON c.mukey = ma.mukey JOIN chorizon h ON h.cokey = c.cokey
WHERE ma.mukey IN ({keys}) AND c.majcompflag = 'Yes'"""


def sda_hydraulics(mukey_fracs: pd.Series, timeout=60) -> dict:
    """Field hydraulics from SSURGO, weighted by map-unit area and major-component percentage:
        ksat_mm_day   most restrictive (lowest) Ksat in 0-150 cm, geometric mean across the field
        drainable_mm  sum over 0-100 cm of (saturated - 1/3-bar water content) x thickness
        spring_wt_shallow_share  share of the field whose April-June water table is < 100 cm deep
    """
    import numpy as np
    import requests
    fr = mukey_fracs[mukey_fracs > 0]
    keys = ",".join(f"'{k}'" for k in fr.index.astype(str))
    r = requests.post(SDA_URL, json={"query": SDA_HYDRAULICS_QUERY.format(keys=keys),
                                     "format": "JSON+COLUMNNAME"}, timeout=timeout)
    if r.status_code != 200:
        raise ValueError(f"Soil Data Access error {r.status_code}")
    table = (r.json() or {}).get("Table") or []
    if len(table) < 2:
        raise ValueError("No horizon data for these map units")
    h = pd.DataFrame(table[1:], columns=table[0])
    for c in ("wtdepaprjunmin", "comppct_r", "hzdept_r", "hzdepb_r", "ksat_r", "wsatiated_r", "wthirdbar_r"):
        h[c] = pd.to_numeric(h[c], errors="coerce")
    comps = []
    for (mukey, cokey), g in h.groupby(["mukey", "cokey"]):
        top, bot = g["hzdept_r"], g["hzdepb_r"]
        ks = g.loc[top < KSAT_DEPTH_CM, "ksat_r"].dropna()
        thick = (np.minimum(bot, SHALLOW_WATER_TABLE_CM) - top).clip(lower=0)
        drain = ((g["wsatiated_r"] - g["wthirdbar_r"]).clip(lower=0) / 100.0 * thick * 10.0)   # cm -> mm
        wt = g["wtdepaprjunmin"].iloc[0]
        comps.append({"mukey": str(mukey), "w": g["comppct_r"].iloc[0],
                      "ksat": ks.min() * UM_S_TO_MM_DAY if len(ks) else np.nan,
                      "drainable": drain.sum() if drain.notna().any() else np.nan,
                      "shallow": float(pd.notna(wt) and wt < SHALLOW_WATER_TABLE_CM)})
    c = pd.DataFrame(comps)
    c["w"] = c["w"] * c["mukey"].map(lambda k: float(fr.get(k, fr.get(int(k), 0)) if k.isdigit() else fr.get(k, 0)))
    c = c[c["w"] > 0]
    if c.empty:
        raise ValueError("No weighted components")
    def wmean(col, geo=False):
        d = c.dropna(subset=[col])
        if d.empty:
            return None
        v = np.log(d[col].clip(lower=1e-6)) if geo else d[col]
        m = float((v * d["w"]).sum() / d["w"].sum())
        return float(np.exp(m)) if geo else m
    return {"ksat_mm_day": round(wmean("ksat", geo=True), 1) if wmean("ksat", geo=True) else None,
            "drainable_mm": round(wmean("drainable"), 1) if wmean("drainable") is not None else None,
            "spring_wt_shallow_share": round(wmean("shallow"), 3) if wmean("shallow") is not None else None}


def _add_hydraulics(prof: SoilProfile, mukey_fracs: pd.Series) -> None:
    """Attach SSURGO hydraulics to a profile; leaves them None (placeholders used) if the query fails."""
    try:
        hyd = sda_hydraulics(mukey_fracs)
    except Exception as err:                       # offline / service down / missing data
        prof.warnings.append(f"Soil drainage properties not available ({type(err).__name__}); "
                             "the water model uses default drainage for untiled fields.")
        return
    prof.ksat_mm_day = hyd["ksat_mm_day"]
    prof.drainable_mm = hyd["drainable_mm"]
    prof.spring_wt_shallow_share = hyd["spring_wt_shallow_share"]
    prof.hydraulics_source = ("USDA NRCS SSURGO via Soil Data Access: chorizon ksat_r, wsatiated_r, "
                              "wthirdbar_r; muaggatt wtdepaprjunmin")


# --- Area-weighted summary (shared) -----------------------------------------------
def summarise_pieces(pieces: pd.DataFrame) -> SoilProfile:
    """pieces: one row per map-unit piece inside the field with frac (share of field area),
    aws0100wta [cm in top 100 cm], drclassdcd, hydgrpdcd, muname, optional slopegradwta [%]."""
    pieces = pieces.copy()
    # aws0100wta = cm of available water in top 100 cm -> x10 = mm per metre of soil
    if "awc_mm_per_m" not in pieces:
        pieces["awc_mm_per_m"] = pd.to_numeric(pieces["aws0100wta"], errors="coerce") * 10.0
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

    slope = None
    if "slopegradwta" in pieces:
        sl = pieces.dropna(subset=["slopegradwta"])
        if sl["frac"].sum() > 0:
            slope = round(float((sl["slopegradwta"] * sl["frac"]).sum() / sl["frac"].sum()), 2)

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
        slope_pct=slope,
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

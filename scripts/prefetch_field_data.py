"""Download the field-scale data for Story County into data/raw/ (CLAUDE.md Appendix A).

Run from the repo root:   python scripts/prefetch_field_data.py [ssurgo] [srtm] [cdl] [smap] [hls] [nasa]
(no arguments = ssurgo srtm cdl; smap and hls are run on request because they queue)

    python scripts/prefetch_field_data.py nasa              # all SMAP + HLS requests at once
    python scripts/prefetch_field_data.py nasa --wait 60    # keep checking for up to 60 minutes

  ssurgo : map-unit attributes from USDA Soil Data Access -> data/raw/ssurgo/ia169_muaggatt.csv
           The POLYGONS are a manual download: websoilsurvey.nrcs.usda.gov -> Download Soils
           Data -> Soil Survey Area (SSURGO) -> Iowa -> Story County (IA169); unzip into
           data/raw/ssurgo/ (any subfolder is fine; soil.py finds soilmu_a_*.shp).
  srtm   : NASA SRTM GL1 tiles via earthaccess (needs an Earthdata login) -> data/raw/srtm/
  cdl    : USDA CropScape county GeoTIFFs 2008-2025 -> data/raw/cdl/cdl_<year>_19169.tif
  smap   : NASA SMAP soil moisture at the example points via NASA AppEEARS (Earthdata login)
           -> data/raw/appeears/smap/ + compact sample_data/smap_daily.csv
  hls    : NASA HLS NDVI at the example fields (3 x 3 pixels each) via AppEEARS (Earthdata login)
           -> data/raw/appeears/hls/ + compact sample_data/hls_ndvi.csv
           AppEEARS queues requests (minutes to hours). All requests are submitted together,
           then checked together for up to 10 minutes (--wait N to change). Rerun the same
           command later to download the rest; nothing is submitted twice.
  ground : ground measurements for validation from the Iowa Environmental Mesonet (no login):
           ISU Soil Moisture Network AEEI4 (soil moisture 30/60/127 cm, daily since 2013) and
           NWS climate station IA0203 Ames 5 SE (temperature, rain) -> data/raw/ground/

Service URLs and product names are from CLAUDE.md and marked (verify) there.
"""

import re
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fieldshift import config  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
FIPS, AREA = "19169", "IA169"
BBOX = (-93.70, 41.86, -93.23, 42.21)          # approx. Story County (lon_min, lat_min, lon_max, lat_max)


def ssurgo_attributes():
    out = RAW / "ssurgo"
    out.mkdir(parents=True, exist_ok=True)
    query = f"""
    SELECT mu.mukey, mu.muname, ma.aws0100wta, ma.drclassdcd, ma.hydgrpdcd, ma.slopegradwta
    FROM legend l
    INNER JOIN mapunit mu ON mu.lkey = l.lkey
    INNER JOIN muaggatt ma ON ma.mukey = mu.mukey
    WHERE l.areasymbol = '{AREA}'
    """
    url = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
    r = requests.post(url, data={"query": query, "format": "JSON+COLUMNNAME"}, timeout=180)
    if r.status_code != 200 or "Table" not in r.text:
        r = requests.post(url, json={"query": query, "format": "JSON+COLUMNNAME"}, timeout=180)
    r.raise_for_status()
    rows = r.json()["Table"]
    df = pd.DataFrame(rows[1:], columns=rows[0])
    path = out / f"{AREA.lower()}_muaggatt.csv"
    df.to_csv(path, index=False, encoding="utf-8")
    awc = pd.to_numeric(df["aws0100wta"], errors="coerce") * 10
    print(f"SSURGO: {len(df)} map units -> {path}")
    print(f"  AWC mm/m: median {awc.median():.0f} (expect roughly 150-250 for Midwest loams)")
    shapes = list((RAW / "ssurgo").rglob("soilmu_a_*.shp"))
    print("  polygons:", shapes[0] if shapes else "NOT FOUND - download from Web Soil Survey (see top of file)")


def srtm_tiles():
    import earthaccess
    out = RAW / "srtm"
    out.mkdir(parents=True, exist_ok=True)
    earthaccess.login(strategy="interactive", persist=True)
    res = earthaccess.search_data(short_name="SRTMGL1", version="003", bounding_box=BBOX)
    print(f"SRTM: {len(res)} granules, {sum(g.size() for g in res):.1f} MB")
    earthaccess.download(res, str(out))
    print("  saved to", out)


def cdl_years(first=2008, last=2025):
    out = RAW / "cdl"
    out.mkdir(parents=True, exist_ok=True)
    svc = "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile"
    for year in range(first, last + 1):
        path = out / f"cdl_{year}_{FIPS}.tif"
        if path.exists():
            continue
        try:
            r = requests.get(svc, params={"year": year, "fips": FIPS}, timeout=180)
            m = re.search(r"<returnURL>(.*?)</returnURL>", r.text)
            if not m:
                print(f"  CDL {year}: no file ({r.text[:120]!r})")
                continue
            path.write_bytes(requests.get(m.group(1), timeout=600).content)
            print(f"  CDL {year}: {path.stat().st_size / 1e6:.1f} MB")
        except requests.RequestException as err:
            print(f"  CDL {year}: CropScape failed ({type(err).__name__}); trying Planetary Computer")
            try:
                cdl_from_planetary_computer(year, path)
                print(f"  CDL {year}: {path.stat().st_size / 1e6:.1f} MB (Planetary Computer copy)")
            except Exception as err2:  # noqa: BLE001 - report and carry on with other years
                print(f"  CDL {year} failed there too: {err2}")


PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PC_TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/usda-cdl"


def cdl_from_planetary_computer(year, path, bbox=BBOX):
    """Same USDA NASS CDL (30 m, EPSG:5070) from Microsoft Planetary Computer's public copy:
    reads only the county window from the cloud-optimised tiles. No login needed.
    Writes a GeoTIFF clipped to the bbox (CropScape files are clipped to the county outline;
    cdl.py reads by field polygon, so the result is the same for fields in the county)."""
    import geopandas as gpd
    import rasterio
    from rasterio.merge import merge
    from shapely.geometry import box
    r = requests.post(PC_STAC, json={"collections": ["usda-cdl"], "bbox": list(bbox),
                                     "datetime": f"{year}-01-01/{year}-12-31", "limit": 50}, timeout=60)
    r.raise_for_status()
    hrefs = [f["assets"]["cropland"]["href"] for f in r.json()["features"]
             if f["properties"].get("usda_cdl:type") == "cropland" and "cropland" in f["assets"]]
    if not hrefs:
        raise FileNotFoundError(f"no {year} cropland tiles on Planetary Computer")
    token = requests.get(PC_TOKEN, timeout=60).json()["token"]
    bounds = gpd.GeoSeries([box(*bbox)], crs="EPSG:4326").to_crs("EPSG:5070").total_bounds
    sources = [rasterio.open(f"{h}?{token}") for h in hrefs]
    try:
        data, transform = merge(sources, bounds=tuple(bounds))
        profile = sources[0].profile
    finally:
        for src in sources:
            src.close()
    profile.update(driver="GTiff", height=data.shape[1], width=data.shape[2], transform=transform,
                   compress="deflate", tiled=False)
    profile.pop("blockxsize", None); profile.pop("blockysize", None)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data)


def ground_stations():
    from fieldshift.data import ground
    for label, fetch, load in (("ISU soil moisture", ground.fetch_isusm, ground.parse_isusm),
                               ("climate station", ground.fetch_climate, ground.parse_climate)):
        try:
            path = fetch()
        except Exception as err:  # noqa: BLE001 - report and carry on
            print(f"  {label} failed: {err}")
            continue
        table = load(path.read_text(encoding="utf-8"))
        print(f"  {label}: {len(table)} days {table.index.min():%Y-%m-%d} to {table.index.max():%Y-%m-%d} -> {path}")
        print("   ", table.describe().loc[["count", "mean"]].round(3).to_string().replace(chr(10), chr(10) + "    "))


def _appeears_dates(product_id, start):
    """Request window: later of `start` and the product's first date, to the last full year."""
    from fieldshift.data import appeears
    first = appeears.product_info(product_id)["TemporalExtentStart"][:10]
    return max(start, first), f"{config.END_YEAR}-12-31"


def smap_jobs():
    from fieldshift.data import appeears
    points = [(name, "smap", lat, lon) for name, (lat, lon) in config.EXAMPLE_POINTS.items()]
    l3_layers = [lyr for pair in config.SMAP_L3_LAYERS.values() for lyr in pair]
    l4_layers = list(config.SMAP_L4_LAYERS.values())
    jobs = []
    for name, product, layers in [("fieldshift_smap_l3", config.SMAP_L3, l3_layers),
                                  ("fieldshift_smap_l4", config.SMAP_L4, l4_layers)]:
        appeears.check_layers(product, layers)
        start, end = _appeears_dates(product, config.SMAP_START)
        body = appeears.point_task_body(name, [(product, lyr) for lyr in layers], points, start, end)
        jobs.append((name, body, config.APPEEARS_DIR / "smap"))
    return jobs


def hls_jobs():
    from fieldshift.data import appeears, ndvi
    pts = ndvi.sample_points()
    jobs = []
    for product, layers in config.HLS_PRODUCTS.items():
        appeears.check_layers(product, layers)
        start, end = _appeears_dates(product, "2013-01-01")
        name = f"fieldshift_{product.split('.')[0].lower()}"
        body = appeears.point_task_body(name, [(product, lyr) for lyr in layers], pts, start, end)
        jobs.append((name, body, config.APPEEARS_DIR / "hls"))
    return jobs


def build_smap():
    from fieldshift.data import smap
    daily = smap.build_compact(points=config.EXAMPLE_POINTS)
    print(f"SMAP: {len(daily)} point-days -> {config.SMAP_DAILY_CSV}")
    print(daily.groupby("point_id")[smap.SERIES].median().round(3).to_string())
    print("  (expect roughly 0.15-0.40 m3/m3 for Iowa soils)")


def build_hls():
    from fieldshift.data import ndvi
    obs = ndvi.build_compact(fields=config.EXAMPLE_POINTS)
    print(f"HLS: {len(obs)} clear field-dates -> {config.HLS_NDVI_CSV}")
    print(obs.groupby(["field", "sensor"])["ndvi"].describe()[["count", "50%", "max"]].round(2).to_string())
    print("  (expect summer peaks around 0.8-0.9 and winter values around 0.1-0.3)")


def appeears_requests(want_smap, want_hls, wait_minutes):
    """Submit all SMAP/HLS requests at once, wait for them together, then build the
    compact files for every dataset whose requests have all been downloaded."""
    from fieldshift.data import appeears
    groups = {}
    if want_smap:
        groups["smap"] = smap_jobs()
    if want_hls:
        groups["hls"] = hls_jobs()
    token = appeears.login()                 # one login; token reused for ~47 h
    state = appeears.run_all(token, [j for jobs in groups.values() for j in jobs], wait_minutes)
    for key, build in (("smap", build_smap), ("hls", build_hls)):
        if key in groups:
            names = [name for name, _, _ in groups[key]]
            if all(state.get(n) == "downloaded" for n in names):
                build()
            else:
                print(f"{key.upper()}: not built yet (waiting for {', '.join(n for n in names if state.get(n) != 'downloaded')})")


if __name__ == "__main__":
    args = sys.argv[1:]
    wait = 10
    if "--wait" in args:                     # --wait N: minutes to keep polling AppEEARS
        k = args.index("--wait")
        wait = float(args[k + 1])
        del args[k:k + 2]
    steps = set(args or ["ssurgo", "srtm", "cdl"])
    if "nasa" in steps:                      # all AppEEARS requests at once
        steps |= {"smap", "hls"}
    if "ssurgo" in steps:
        ssurgo_attributes()
    if "srtm" in steps:
        srtm_tiles()
    if "cdl" in steps:
        cdl_years()
    if "ground" in steps:
        ground_stations()
    if "smap" in steps or "hls" in steps:
        appeears_requests("smap" in steps, "hls" in steps, wait)

"""Download the field-scale data for Story County into data/raw/ (CLAUDE.md Appendix A).

Run from the repo root:   python scripts/prefetch_field_data.py [ssurgo] [srtm] [cdl]
(no arguments = all three)

  ssurgo : map-unit attributes from USDA Soil Data Access -> data/raw/ssurgo/ia169_muaggatt.csv
           The POLYGONS are a manual download: websoilsurvey.nrcs.usda.gov -> Download Soils
           Data -> Soil Survey Area (SSURGO) -> Iowa -> Story County (IA169); unzip into
           data/raw/ssurgo/ (any subfolder is fine; soil.py finds soilmu_a_*.shp).
  srtm   : NASA SRTM GL1 tiles via earthaccess (needs an Earthdata login) -> data/raw/srtm/
  cdl    : USDA CropScape county GeoTIFFs 2008-2025 -> data/raw/cdl/cdl_<year>_19169.tif

Service URLs and product names are from CLAUDE.md and marked (verify) there.
"""

import re
import sys
from pathlib import Path

import pandas as pd
import requests

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
            print(f"  CDL {year} failed: {err} (fallback: CropScape website, AOI = Story County)")


if __name__ == "__main__":
    steps = sys.argv[1:] or ["ssurgo", "srtm", "cdl"]
    if "ssurgo" in steps:
        ssurgo_attributes()
    if "srtm" in steps:
        srtm_tiles()
    if "cdl" in steps:
        cdl_years()

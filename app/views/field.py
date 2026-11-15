"""Step 1 (Home): choose a field in Story County on the map, see what we know about it, start.

The map is drawn once and keeps its view: the selected field is a separate layer
(feature_group_to_add), so clicking a field does not reset the map. Panning is limited to the
county; the farmer controls the zoom.
"""

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import services
import ui
from fieldshift import config
from fieldshift.data.field import field_geometry

MAP_ZOOM = 14
SLOPE_BANDS = [(0, 2, "Nearly level"), (2, 5, "Gentle"), (5, 9, "Moderate"), (9, 15, "Steep")]
DRAINAGE_COLOURS = {"Very poorly drained": "#3f5f6b", "Poorly drained": "#5b7d8a",
                    "Somewhat poorly drained": "#8fa89c", "Moderately well drained": "#c9b48a",
                    "Well drained": ui.SOIL, "Somewhat excessively drained": "#c49a55",
                    "Excessively drained": ui.WHEAT}


def _map():
    lat, lon = st.session_state.lat, st.session_state.lon
    center = st.session_state.setdefault("map_center", [lat, lon])
    x0, y0, x1, y1 = config.COUNTY_BBOX
    m = folium.Map(location=center, zoom_start=MAP_ZOOM, min_zoom=10, max_zoom=18, max_bounds=True,
                   min_lat=y0 - 0.03, max_lat=y1 + 0.03, min_lon=x0 - 0.04, max_lon=x1 + 0.04,
                   tiles="Esri.WorldImagery", attr="Esri World Imagery", control_scale=True)
    folium.GeoJson(services.county_geojson(), name="Story County",
                   style_function=lambda _: {"color": "#ffffff", "weight": 2, "fill": False}).add_to(m)
    fg = folium.FeatureGroup(name="Your field")
    minx, miny, maxx, maxy = field_geometry(point=(lat, lon)).bounds
    folium.Rectangle(bounds=[[miny, minx], [maxy, maxx]], color="#f2c94c", weight=3, fill=True,
                     fill_opacity=0.12, tooltip="The field analysed (about 400 m x 400 m)").add_to(fg)
    data = st_folium(m, height=430, use_container_width=True, returned_objects=["last_clicked"],
                     feature_group_to_add=fg, key="field_map")
    # no center/zoom arguments: st_folium re-applies those on every rerun (resetting the farmer's zoom).
    # map_center is only the first view; after that the farmer's own pan and zoom are kept.
    return (data or {}).get("last_clicked")


def _soil_tab(fld: dict):
    soil = fld["soil"]
    st.html(f'<div class="fs-stats">'
            f'<div class="fs-stat"><div class="l">Water the soil holds</div><div class="v">{fld["awc_mm_per_m"]:.0f} mm</div>'
            f'<div class="n">per metre of soil</div></div>'
            f'<div class="fs-stat"><div class="l">Drainage</div><div class="v" style="font-size:1.15rem">'
            f'{soil["drainage_class"]}</div><div class="n">most of the field</div></div>'
            f'<div class="fs-stat"><div class="l">Tile drainage</div><div class="v" style="font-size:1.15rem">'
            f'{"Likely" if fld["tile_drained"] else "Unlikely"}</div><div class="n">from the drainage class</div></div>'
            f'</div>')
    mix = pd.DataFrame([{"Soil": n.split(",")[0], "Full name": n, "Share": s}
                        for n, s in soil.get("mapunit_mix", {}).items() if s >= 0.01])
    drain = pd.DataFrame([{"Drainage": d, "Share": s} for d, s in soil.get("drainage_mix", {}).items() if s >= 0.01])
    c1, c2 = st.columns([3, 2], gap="medium")
    if len(mix):
        with c1:
            st.markdown("**Soil types in the field**")
            st.html(ui.hbar_html([(r.Soil, r.Share * 100, ui.SOIL) for r in mix.itertuples()], vmax=100,
                                 fmt=lambda v: f"{v:.0f}%"))
    if len(drain):
        with c2:
            st.markdown("**Drainage**")
            st.html(ui.donut_html([(r.Drainage, r.Share, DRAINAGE_COLOURS.get(r.Drainage, ui.OTHER_COLOUR))
                                   for r in drain.itertuples()], size=140))
    st.html('<p class="fs-source">USDA NRCS soil survey (SSURGO), looked up for this field.</p>')


def _slope_tab(fld: dict):
    slope = fld["slope"]
    top = SLOPE_BANDS[-1][1]
    zone_colours = ["#dfe8cf", "#cddcb4", "#e7d3a6", "#dcb581"]
    zones = "".join(f'<div style="width:{(b - a) / top * 100:.2f}%;background:{c}"></div>'
                    for (a, b, _), c in zip(SLOPE_BANDS, zone_colours))
    names = "".join(f'<div style="width:{(b - a) / top * 100:.2f}%">{n}<br>{a}-{b}%</div>'
                    for a, b, n in SLOPE_BANDS)
    marks = [("top", ui.GREEN, "USDA soil survey", slope["slope_pct_mean"])]
    if slope.get("srtm_slope_pct_mean") is not None:
        marks.append(("bot", ui.SOIL, "NASA SRTM", slope["srtm_slope_pct_mean"]))
    pins = "".join(f'<div class="mk" style="left:{min(v, top) / top * 100:.2f}%;border-color:{c}"></div>'
                   for _, c, _, v in marks)
    key = "".join(f'<span><i style="background:{c}"></i>{who}: <b>{v:.1f}%</b></span>' for _, c, who, v in marks)
    agree = slope.get("srtm_agrees")
    st.markdown(f"**{slope['slope_class'].split(': ')[-1].split(' (')[0].capitalize()}** - "
                + ("erosion-prone when bare in heavy rain" if fld["erosion_prone"] else "low erosion risk")
                + ("" if agree is None else (" · NASA elevation data agrees" if agree else
                                             " · NASA elevation data reads a little differently")))
    st.html(f'<div class="fs-gauge"><div class="zones">{zones}</div><div class="zl">{names}</div>{pins}</div>'
            f'<div class="fs-legend">{key}</div>')
    st.html('<p class="fs-source">Average slope from the USDA soil survey, checked against NASA SRTM 30 m elevation.</p>')


def _crops_tab(fld: dict):
    hist = fld.get("crop_history") or {}
    if not hist:
        st.info("No crop-map history for this spot.")
        return
    years = sorted(hist, key=int)
    def name(c):
        return ui.crop_label(c) if c in ui.CROP else c.replace("_", " ").capitalize()
    cols = f"grid-template-columns: repeat({len(years)}, minmax(0, 1fr))"
    cells = "".join(f'<div title="{y}: {name(hist[y])}" style="background:{ui.crop_colour(hist[y])}"></div>'
                    for y in years)
    labels = "".join(f"<div>{y if (int(y) % 2 == 0 or len(years) <= 10) else ''}</div>" for y in years)
    seen = list(dict.fromkeys(hist[y] for y in years))
    legend = "".join(f'<span><i style="background:{ui.crop_colour(c)}"></i>{name(c)}</span>' for c in seen)
    recent = [name(hist[y]).lower() for y in years[-6:]]
    st.markdown(f"**Recent years: {', '.join(recent)}**")
    st.html(f'<div class="fs-strip" style="{cols}">{cells}</div>'
            f'<div class="fs-strip-years" style="{cols}">{labels}</div>'
            f'<div class="fs-legend" style="margin-top:.6rem">{legend}</div>')
    st.html('<p class="fs-source">USDA NASS Cropland Data Layer, 2008-2025 (mapped from Landsat and Sentinel-2 images).</p>')


def _location_card(lat: float, lon: float):
    ha = services.field_area_ha(lat, lon)
    ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
    with ui.section("location"):
        st.html(f'<div class="fs-loc"><p class="fs-kicker">Selected field</p>'
                f'<p class="place">{services.location_text(lat, lon)}</p>'
                f'<p class="county">Story County, Iowa</p>'
                f'<div class="row"><span>Latitude</span><span>{abs(lat):.4f}&deg; {ns}</span></div>'
                f'<div class="row"><span>Longitude</span><span>{abs(lon):.4f}&deg; {ew}</span></div>'
                f'<div class="row"><span>Area analysed</span><span>{ha:.0f} ha ({ha * 2.471:.0f} acres)</span></div>'
                f'<p class="hint">Click another spot on the map to move the field. Nearest town: US Census Bureau.</p>'
                f'</div>')


def render():
    ui.hero("Find the best crop rotation for your farm", [
        ("pin", "Pick your field", "Click it on the map"),
        ("list", "Tell us about your farm", "A few quick questions"),
        ("chart", "Get your best rotation", "40 years of NASA weather"),
    ])

    ui.section_heading("Pick your field", sub="Click it on the map - anywhere in Story County, Iowa.")
    map_col, info_col = st.columns([1, 1], gap="medium")
    with map_col:
        with ui.section("map", sand=False):
            click = _map()
            st.html('<p class="fs-source">Satellite imagery: Esri World Imagery · County outline: US Census '
                    'Bureau. The yellow square is the area analysed.</p>')
    if click:
        new = (round(click["lat"], 5), round(click["lng"], 5))
        if new != st.session_state.get("handled_click"):         # act on each click once
            st.session_state.handled_click = new
            if not services.in_county(*new):
                st.session_state.click_warning = True
            elif new != (st.session_state.lat, st.session_state.lon):
                st.session_state.lat, st.session_state.lon = new
                st.session_state.result = None
                st.session_state.click_warning = False
                st.rerun()

    lat, lon = st.session_state.lat, st.session_state.lon
    with info_col:
        _location_card(lat, lon)
        if st.session_state.get("click_warning"):
            st.warning("That spot is outside Story County. Please pick a field inside the white outline.")

    ui.section_heading("What we know about this field",
                       sub="From the USDA soil survey, NASA elevation data and USDA crop maps.")
    with ui.section("field"):
        try:
            with st.spinner("Looking up the soil survey, slope and crop maps..."):
                fld = services.field_lookup(lat, lon)
        except Exception as e:                                    # network trouble: the farmer can still go on
            st.warning(f"Field details could not be loaded ({e}). You can still continue.")
        else:
            soil_tab, slope_tab, crops_tab = st.tabs(["Soil", "Slope", "Past crops"])
            with soil_tab:
                _soil_tab(fld)
            with slope_tab:
                _slope_tab(fld)
            with crops_tab:
                _crops_tab(fld)
            for w in fld.get("warnings", []):
                st.info(w)

    st.button("Start questionnaire", icon=":material/arrow_forward:", type="primary", width="stretch",
              on_click=ui.go("questions"))

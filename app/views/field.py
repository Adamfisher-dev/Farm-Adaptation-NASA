"""Step 1 (Home): choose a field in Story County on the map, then start the questionnaire."""

import folium
import streamlit as st
from streamlit_folium import st_folium

import services
import ui
from fieldshift import config
from fieldshift.data.field import field_geometry
from fieldshift.data.power import power_cell

EXAMPLES = {"flat_tiled": "Flat, tile-drained", "sloping": "Sloping", "light_soil": "Lighter soil"}


def _pick_example():
    name = st.session_state.get("example_pick")
    if name:
        st.session_state.lat, st.session_state.lon = config.EXAMPLE_POINTS[name]
        st.session_state.result = None
        st.session_state.click_warning = False


def render():
    lat, lon = st.session_state.lat, st.session_state.lon
    st.header("Choose your field")
    st.html('<p class="fs-lead">Click your field on the map. Orbital Acre covers Story County, Iowa '
            '(outlined in white); the yellow square is the area analysed.</p>')

    m = folium.Map(location=[lat, lon], zoom_start=13, min_zoom=10, max_bounds=True,
                   min_lat=41.7, max_lat=42.4, min_lon=-93.95, max_lon=-93.0,
                   tiles="Esri.WorldImagery", attr="Esri World Imagery", control_scale=True)
    folium.GeoJson(services.county_geojson(), name="Story County",
                   style_function=lambda _: {"color": "#ffffff", "weight": 2, "fill": False},
                   tooltip="Story County").add_to(m)
    minx, miny, maxx, maxy = field_geometry(point=(lat, lon)).bounds
    folium.Rectangle(bounds=[[miny, minx], [maxy, maxx]], color="#ffd400", weight=3,
                     tooltip="The field analysed (about 400 m x 400 m)").add_to(m)
    folium.CircleMarker([lat, lon], radius=5, color="#ffd400", fill=True, fill_opacity=1,
                        tooltip="Selected point").add_to(m)
    map_data = st_folium(m, height=440, use_container_width=True, returned_objects=["last_clicked"],
                         key="field_map")

    click = (map_data or {}).get("last_clicked")
    if click:
        new = (round(click["lat"], 5), round(click["lng"], 5))
        if new != st.session_state.get("handled_click"):        # act on each click once
            st.session_state.handled_click = new
            if not services.in_county(*new):
                st.session_state.click_warning = True
            elif new != (lat, lon):
                st.session_state.lat, st.session_state.lon = new
                st.session_state.result = None
                st.session_state.click_warning = False
                st.session_state.reset_example = True
                st.rerun()
    if st.session_state.get("click_warning"):
        st.warning("That spot is outside Story County. Please pick a field inside the white outline.")

    if st.session_state.pop("reset_example", False):          # before the widget is drawn
        st.session_state.example_pick = None
    st.pills("Or try an example field", list(EXAMPLES), format_func=EXAMPLES.get,
             key="example_pick", on_change=_pick_example)

    with st.container(border=True):
        st.subheader("This field")
        try:
            with st.spinner("Looking up the soil survey, slope and crop maps for this field..."):
                fld = services.field_lookup(lat, lon)
        except Exception as e:                                   # network trouble: the farmer can still go on
            st.warning(f"Field details could not be loaded ({e}). You can still continue.")
        else:
            soil, slope = fld["soil"], fld["slope"]
            mix = ", ".join(f"{n.split(',')[0]} {s:.0%}" for n, s in list(soil.get("mapunit_mix", {}).items())[:3])
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f"**Soil**  \n{mix or soil.get('dominant_mapunit', 'unknown')}  \n"
                            f"<span class='fs-muted'>Holds {fld['awc_mm_per_m']:.0f} mm of water per metre; "
                            f"mostly {soil['drainage_class'].lower()}</span>", unsafe_allow_html=True)
            with c2:
                srtm = slope.get("srtm_slope_pct_mean")
                check = ""
                if srtm is not None:
                    check = f"NASA SRTM elevation: {srtm}%" + (" (agrees)" if slope.get("srtm_agrees") else "")
                st.markdown(f"**Slope**  \n{slope['slope_pct_mean']}% - {slope['slope_class'].split(': ')[-1]}  \n"
                            f"<span class='fs-muted'>{check}</span>", unsafe_allow_html=True)
            with c3:
                st.markdown(f"**Past crops**  \n{fld['rotation_question']}", unsafe_allow_html=True)
            st.caption(f"{lat:.4f}, {lon:.4f} - NASA POWER weather cell {power_cell(lat, lon)['id']} (about 50 km)")
            for w in fld.get("warnings", []):
                st.info(w)

    st.button("Start questionnaire", icon=":material/arrow_forward:", type="primary", width="stretch",
              on_click=ui.go("questions"))

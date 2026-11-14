import sys
from pathlib import Path

import folium
import streamlit as st
from streamlit_folium import st_folium

# Make src/ importable when run as:  streamlit run app/app.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fieldshift import pipeline                      # noqa: E402
from fieldshift.data.power import power_cell         # noqa: E402

IOWA_BOUNDS = {"min_lat": 40.38, "max_lat": 43.50, "min_lon": -96.64, "max_lon": -90.14}
IOWA_CENTRE = (42.03, -93.62)

SLIDER_LABELS = {
    "water_quality": "Water quality",
    "soil_health": "Soil health",
    "drought": "Drought resilience",
    "income": "Income",
    "pests": "Pest resilience",
}


def in_iowa(lat, lon):
    b = IOWA_BOUNDS
    return b["min_lat"] <= lat <= b["max_lat"] and b["min_lon"] <= lon <= b["max_lon"]


@st.cache_data(show_spinner=False)
def run_for_cell(cell_id, lat, lon, rotation_names):
    """Cached per POWER cell + rotation set: every field in a cell has the same weather."""
    rotations = {n: pipeline.ROTATIONS[n] for n in rotation_names}
    return pipeline.run_basic(lat, lon, rotations=rotations)


st.set_page_config(page_title="Field Shift", layout="wide")
st.title("Field Shift")

# Sidebar: priorities
st.sidebar.header("What matters most to you?")
st.sidebar.caption("0 = not important, 10 = very important")
priorities = {
    "water_quality": st.sidebar.slider("Water quality", 0, 10, 5),
    "soil_health": st.sidebar.slider("Soil health and erosion", 0, 10, 5),
    "drought": st.sidebar.slider("Drought resilience", 0, 10, 5),
    "income": st.sidebar.slider("Income", 0, 10, 5),
    "pests": st.sidebar.slider("Pest resilience", 0, 10, 5),
}

total = sum(priorities.values())
if total == 0:
    st.sidebar.warning("Set at least one priority above 0.")
    weights = {k: 1 / len(priorities) for k in priorities}
else:
    weights = {k: v / total for k, v in priorities.items()}

# Sidebar: farm questions
st.sidebar.header("About your farm")
want_cover = st.sidebar.radio("Do you want cover crops?", ["Yes", "No"], horizontal=True)
hay_buyer = st.sidebar.radio("Is there a buyer for hay near you?", ["Yes", "No"], horizontal=True)
hay_equipment = st.sidebar.radio("Do you have hay equipment?", ["Yes", "No"], horizontal=True)
open_to_new = st.sidebar.radio("Are you open to growing new crops?", ["Yes", "No"], horizontal=True)

current_crops = []
if open_to_new == "No":
    current_crops = st.sidebar.multiselect(
        "Which crops do you grow now?",
        ["Corn", "Soybean", "Oats", "Winter wheat", "Alfalfa"],
        default=["Corn", "Soybean"],
    )

# Map
if "lat" not in st.session_state:
    st.session_state.lat, st.session_state.lon = IOWA_CENTRE

st.write("Click the map to pick a field in Iowa")
m = folium.Map(
    location=[st.session_state.lat, st.session_state.lon],
    zoom_start=7,
    min_zoom=6,
    max_bounds=True,
    min_lat=IOWA_BOUNDS["min_lat"] - 1,
    max_lat=IOWA_BOUNDS["max_lat"] + 1,
    min_lon=IOWA_BOUNDS["min_lon"] - 1,
    max_lon=IOWA_BOUNDS["max_lon"] + 1,
)
folium.Rectangle(
    bounds=[[IOWA_BOUNDS["min_lat"], IOWA_BOUNDS["min_lon"]],
            [IOWA_BOUNDS["max_lat"], IOWA_BOUNDS["max_lon"]]],
    color="green", fill=False, weight=2,
).add_to(m)

cell = power_cell(st.session_state.lat, st.session_state.lon)
lon_min, lat_min, lon_max, lat_max = cell["bounds"]
folium.Rectangle(
    bounds=[[lat_min, lon_min], [lat_max, lon_max]],
    color="orange", fill=True, fill_opacity=0.1, weight=1,
    tooltip="NASA POWER weather cell (same weather everywhere inside)",
).add_to(m)
folium.Marker([st.session_state.lat, st.session_state.lon]).add_to(m)
map_data = st_folium(m, height=400, width=700)

if map_data and map_data.get("last_clicked"):
    new_lat = round(map_data["last_clicked"]["lat"], 2)
    new_lon = round(map_data["last_clicked"]["lng"], 2)
    if not in_iowa(new_lat, new_lon):
        st.warning("That's outside Iowa. Pick a location inside the green box.")
    elif (new_lat, new_lon) != (st.session_state.lat, st.session_state.lon):
        st.session_state.lat, st.session_state.lon = new_lat, new_lon
        st.rerun()

lat, lon = st.session_state.lat, st.session_state.lon
st.write(f"Selected: {lat}, {lon}  (weather cell {cell['id']})")

# Run the model
allowed = pipeline.filter_rotations(
    want_cover=want_cover == "Yes",
    hay_buyer=hay_buyer == "Yes",
    hay_equipment=hay_equipment == "Yes",
    open_to_new=open_to_new == "Yes",
    current_crops=current_crops if open_to_new == "No" else None,
)

try:
    with st.spinner("Loading NASA POWER weather and running the water model "
                    "(first time for a new area downloads ~45 years of data)..."):
        out = run_for_cell(cell["id"], lat, lon, tuple(allowed))
except Exception as e:  # network / API errors: show them instead of crashing
    st.error(f"Could not load data for this location: {e}")
    st.stop()

st.caption(
    f"Weather: NASA POWER, {out['loaded_from']}, {out['years']['weather'][0]}-{out['years']['weather'][1]}. "
    f"Water model {out['years']['water_model'][0]}-{out['years']['water_model'][1]}. "
    f"Soil: AWC {out['soil']['awc_mm_per_m']:.0f} mm/m, "
    f"{'tile-drained' if out['soil']['tile_drained'] else 'not tiled'} ({out['soil']['source']})."
)
for w in out["field"]["warnings"]:
    st.info(w)
for w in out["unit_warnings"]:
    st.warning(w)

tab_rank, tab_climate = st.tabs(["Rotations", "Climate snapshot"])

with tab_rank:
    scores = pipeline.basic_scores(out, weights)
    st.subheader("Basic ranking")
    st.caption(
        f"0.5 = same as {pipeline.BASELINE}; higher is better. Drought, water quality, soil health "
        "and pests are scored; income is not scored yet."
    )
    show = scores.rename(columns={**SLIDER_LABELS, "score": "Score"})
    st.dataframe(show.style.format("{:.2f}"), width="stretch")
    st.bar_chart(scores.drop(columns="score"))

    st.subheader("Water model results (mean per year)")
    labels = {c: f"{lab} [{unit}]" for c, (lab, unit, _) in pipeline.WATER_COLUMNS.items()}
    st.dataframe(out["water"].rename(columns=labels).style.format("{:.1f}"), width="stretch")

with tab_climate:
    st.subheader("Recent climate and trend")
    rows = []
    for key, s in out["snapshot"].items():
        rows.append({
            "Indicator": s["label"],
            "Unit": s["unit"],
            f"Mean {s['recent_years'][0]}-{s['recent_years'][1]}": s["recent_mean"],
            "Range": f"{s['recent_min']} to {s['recent_max']}",
            "Trend per decade": s.get("trend_per_decade"),
            "p-value": s.get("p_value"),
        })
    st.dataframe(rows, width="stretch")
    st.line_chart(out["yearly"][["growing_season_rain_mm"]])
    st.write("Hard years:", out["notable_years"])

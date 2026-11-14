import requests
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

IOWA_BOUNDS = {"min_lat": 40.38, "max_lat": 43.50, "min_lon": -96.64, "max_lon": -90.14}
IOWA_CENTRE = (42.03, -93.62)

def in_iowa(lat, lon):
    b = IOWA_BOUNDS
    return b["min_lat"] <= lat <= b["max_lat"] and b["min_lon"] <= lon <= b["max_lon"]

@st.cache_data
def get_power(lat, lon, start=1981, end=2024):
    url = "https://power.larc.nasa.gov/api/temporal/daily/point"
    params = {
        "parameters": "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,GWETTOP,GWETROOT",
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "start": f"{start}0101",
        "end": f"{end}1231",
        "format": "JSON",
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["properties"]["parameter"])
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    return df.where(df != -999)

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
        ["Corn", "Soybean", "Oats", "Wheat", "Alfalfa"],
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
st.write(f"Selected: {lat}, {lon}")

# Everything the engine will need
farmer = {
    "lat": lat,
    "lon": lon,
    "want_cover": want_cover == "Yes",
    "hay_buyer": hay_buyer == "Yes",
    "hay_equipment": hay_equipment == "Yes",
    "open_to_new": open_to_new == "Yes",
    "current_crops": current_crops,
    "weights": weights,
}
st.write(farmer)  # debug: remove once the engine is wired in
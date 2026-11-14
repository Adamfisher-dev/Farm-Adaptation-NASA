"""Field Shift - Streamlit app. Run from the repo root:  python -m streamlit run app/app.py

UI only: every number comes from fieldshift.pipeline.run_analysis() (playbook 6.1 order:
field -> existing rotation -> candidates -> water model -> scores -> uncertainty -> what to show).
"""

import sys
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

# Make src/ importable when run as:  streamlit run app/app.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fieldshift import config, pipeline              # noqa: E402
from fieldshift.data.power import power_cell         # noqa: E402

IOWA_BOUNDS = {"min_lat": 40.38, "max_lat": 43.50, "min_lon": -96.64, "max_lon": -90.14}
N_BOOT = 300                                          # resamples per run (~10 s); the pipeline default is 1000

SLIDERS = {                                           # app key -> label
    "drought": "Drought resilience",
    "water_quality": "Water quality",
    "soil_health": "Soil health and erosion",
    "income": "Income",
    "pests": "Pests and fertiliser",
}
SLIDER_COLS = {"drought": "Drought", "soil_erosion": "Soil & erosion", "water_quality": "Water quality",
               "income": "Income", "pests_fertiliser": "Pests & fertiliser"}
CRITERIA = {                                          # criterion -> (label, unit)
    "drought_risk": ("Water missed at the crop's sensitive stage (worst years)", "mm"),
    "water_leaving": ("Water draining below the roots (nitrate-loss proxy)", "mm/yr"),
    "erosion_exposure": ("Bare soil in heavy rain, slope-weighted", "days/yr"),
    "som_proxy": ("Soil organic matter (literature score)", "0-3"),
    "n_benefit": ("Nitrogen from legumes (literature score)", "0-3"),
    "pest_break": ("Pest and disease break (literature score)", "0-3"),
    "income": ("Income after all costs incl. land", "$/acre/yr"),
}
EXISTING_CHOICES = {
    "As the crop maps show": None,
    "Corn - soybean": ["corn", "soybean"],
    "Corn - corn - soybean": ["corn", "corn", "soybean"],
    "Continuous corn": ["corn"],
}
TIER = {"current": "Your current rotation", "small_step": "Small step", "bigger_shift": "Bigger shift"}


def in_iowa(lat, lon):
    b = IOWA_BOUNDS
    return b["min_lat"] <= lat <= b["max_lat"] and b["min_lon"] <= lon <= b["max_lon"]


def _freeze(d):
    return tuple(sorted((k, tuple(v) if isinstance(v, list) else v) for k, v in d.items()))


@st.cache_data(show_spinner=False)
def field_lookup(lat, lon):
    """Soil, slope and crop history for the ~400 m field around the point (pre-fills the questions)."""
    return pipeline.field_profile(lat, lon).to_dict()


@st.cache_data(show_spinner=False, max_entries=20)
def analyse(lat, lon, answers_frozen, weights_frozen):
    answers = {k: list(v) if isinstance(v, tuple) else v for k, v in answers_frozen}
    return pipeline.run_analysis(lat, lon, answers=answers, weights=dict(weights_frozen), n_boot=N_BOOT)


def money(x):
    return "n/a" if x is None or pd.isna(x) else f"{'-' if x < 0 else ''}${abs(x):,.0f}"


# --- Page ------------------------------------------------------------------------------------------------
st.set_page_config(page_title="Field Shift", layout="wide")
st.title("Field Shift")
st.caption("Compare crop rotations for one Iowa field, using NASA weather and elevation data, the USDA soil "
           "survey and crop maps. A starting point for a conversation with your agronomist - not a prescription.")

if "lat" not in st.session_state:
    st.session_state.lat, st.session_state.lon = config.EXAMPLE_POINTS[config.DEFAULT_POINT]
    st.session_state.result = None

# Sidebar: pick a field ------------------------------------------------------------------------------------
st.sidebar.header("1. Pick a field")
def _jump_to_example():
    # Runs only when the dropdown CHANGES. (Checking it on every rerun fought with map clicks: the
    # dropdown moved the field back, the map reported the click again -> endless reruns, dimmed page.)
    name = st.session_state.example
    if name != "-":
        st.session_state.lat, st.session_state.lon = config.EXAMPLE_POINTS[name]
        st.session_state.result = None


if st.session_state.pop("reset_example", False):     # must happen before the widget is drawn
    st.session_state.example = "-"
st.sidebar.selectbox("Jump to an example field (Story County)", ["-"] + list(config.EXAMPLE_POINTS),
                     key="example", on_change=_jump_to_example)
st.sidebar.caption("...or click the map.")
lat, lon = st.session_state.lat, st.session_state.lon

with st.spinner("Looking up this field (soil survey, slope, crop maps)..."):
    try:
        fld = field_lookup(lat, lon)
    except Exception as e:                                      # network problems: still let the farmer answer
        fld, field_error = None, str(e)
    else:
        field_error = None

# Sidebar: questions and priorities (a form, so the ~10 s analysis runs only on request) -------------------
with st.sidebar.form("questions"):
    st.header("2. Your farm")
    guess = (fld or {}).get("existing_rotation_guess")
    seen = "-".join(y[0] if isinstance(y, (list, tuple)) else y for y in guess) if guess else None
    existing_label = st.selectbox(
        "What do you grow on this field now?", list(EXISTING_CHOICES),
        help=f"The crop maps suggest: {seen}." if seen else "No crop-map history for this spot.")
    tiled_guess = (fld or {}).get("tile_drained")
    tile = st.radio(f"Tile-drained? (soil survey suggests: {'yes' if tiled_guess else 'no'})",
                    ["As suggested", "Yes", "No"], horizontal=True)
    eros_guess = (fld or {}).get("erosion_prone")
    eros = st.radio(f"Sloping / erosion-prone? (data suggest: {'yes' if eros_guess else 'no'})",
                    ["As suggested", "Yes", "No"], horizontal=True)
    hay_buyer = st.checkbox("Livestock or a hay buyer nearby", value=False)
    hay_equipment = st.checkbox("Hay equipment (own or hired)", value=False)
    grain_buyer = st.checkbox("A buyer for oats or wheat within reach", value=True)
    cover = st.checkbox("Someone can seed a cover crop after harvest", value=True)
    openness = st.radio("Open to new crops?", ["yes", "maybe", "no"], index=1, horizontal=True)
    current_crops = st.multiselect("If not: which crops do you grow now?",
                                   ["Corn", "Soybean", "Oats", "Winter wheat", "Alfalfa"],
                                   default=["Corn", "Soybean"])

    st.header("3. What matters most?")
    st.caption("0 = not important, 10 = very important")
    weights = {k: st.slider(label, 0, 10, 5) for k, label in SLIDERS.items()}
    submitted = st.form_submit_button("Run analysis", type="primary", width="stretch")

answers = {
    "livestock_or_hay_buyer": hay_buyer, "hay_equipment": hay_equipment,
    "small_grain_buyer": grain_buyer, "can_seed_cover": cover, "openness": openness,
}
if EXISTING_CHOICES[existing_label]:
    answers["existing_rotation"] = EXISTING_CHOICES[existing_label]
if tile != "As suggested":
    answers["tile_drained"] = tile == "Yes"
if eros != "As suggested":
    answers["erosion_prone"] = eros == "Yes"
if openness == "no":
    answers["current_crops"] = current_crops
if sum(weights.values()) == 0:
    st.sidebar.warning("All priorities are 0 - treating them as equal.")
    weights = {k: 1 for k in weights}

# Map --------------------------------------------------------------------------------------------------------
left, right = st.columns([3, 2])
with left:
    m = folium.Map(location=[lat, lon], zoom_start=13, min_zoom=6, max_bounds=True,
                   min_lat=IOWA_BOUNDS["min_lat"] - 1, max_lat=IOWA_BOUNDS["max_lat"] + 1,
                   min_lon=IOWA_BOUNDS["min_lon"] - 1, max_lon=IOWA_BOUNDS["max_lon"] + 1,
                   tiles="Esri.WorldImagery", attr="Esri World Imagery")
    cell = power_cell(lat, lon)
    lon_min, lat_min, lon_max, lat_max = cell["bounds"]
    folium.Rectangle(bounds=[[lat_min, lon_min], [lat_max, lon_max]], color="orange", fill=False, weight=2,
                     tooltip="NASA POWER weather cell (~50 km): the same weather everywhere inside").add_to(m)
    from fieldshift.data.field import field_geometry
    g = field_geometry(point=(lat, lon))
    minx, miny, maxx, maxy = g.bounds
    folium.Rectangle(bounds=[[miny, minx], [maxy, maxx]], color="yellow", weight=2,
                     tooltip="The field analysed (~400 m x 400 m)").add_to(m)
    map_data = st_folium(m, height=420, use_container_width=True, returned_objects=["last_clicked"])
    click = (map_data or {}).get("last_clicked")
    if click:
        new = (round(click["lat"], 5), round(click["lng"], 5))
        # act on each click once: the map keeps reporting its last click on every rerun, which would
        # otherwise undo a later dropdown choice (and could loop)
        if new != st.session_state.get("handled_click"):
            st.session_state.handled_click = new
            if not in_iowa(*new):
                st.warning("That's outside Iowa. Pick a field inside Iowa.")
            elif new != (lat, lon):
                st.session_state.lat, st.session_state.lon = new
                st.session_state.result = None
                st.session_state.reset_example = True  # dropdown no longer describes the field (reset next run)
                st.rerun()

with right:
    st.subheader("This field")
    st.write(f"{lat:.4f}, {lon:.4f}")
    if fld:
        soil, slope = fld["soil"], fld["slope"]
        mix = ", ".join(f"{n.split(',')[0]} {s:.0%}" for n, s in list(soil.get("mapunit_mix", {}).items())[:3])
        st.markdown(f"**Soil** (USDA soil survey): {mix or soil.get('dominant_mapunit')}  \n"
                    f"Water-holding {fld['awc_mm_per_m']:.0f} mm per metre, mostly {soil['drainage_class'].lower()}.")
        srtm = slope.get("srtm_slope_pct_mean")
        st.markdown(f"**Slope**: {slope['slope_pct_mean']}% ({slope['slope_class']})"
                    + (f"; NASA SRTM elevation: {srtm}%"
                       + (" - agrees" if slope.get("srtm_agrees") else " - differs") if srtm is not None else ""))
        st.markdown(f"**Past crops** (USDA crop maps): {fld['rotation_question']}")
        for w in fld["warnings"]:
            st.info(w)
    else:
        st.warning(f"Field data could not be loaded ({field_error}). You can still answer the questions.")

# Run ----------------------------------------------------------------------------------------------------------
if submitted:
    with st.spinner("Running 40+ years of NASA weather through each rotation and testing the ranking "
                    f"{N_BOOT} times..."):
        try:
            st.session_state.result = analyse(lat, lon, _freeze(answers), _freeze(weights))
        except Exception as e:
            st.session_state.result = None
            st.error(f"The analysis could not run: {e}")
r = st.session_state.result
if r is None:
    st.info("Answer the questions on the left and press **Run analysis**.")
    st.stop()

base = r["existing"]["name"]
inc = r["income"]
rk = r["ranking"].copy()

tabs = st.tabs(["Recommendation", "Why", "Hard year", "Climate", "Evidence"])

# Recommendation -----------------------------------------------------------------------------------------------
with tabs[0]:
    v = r.get("verdict") or {}
    (st.success if v.get("kind") == "options_better" else st.info)(v.get("message", ""))
    shown = [s["name"] for s in r["shown"]]
    cols = st.columns(len(shown))
    for col, name in zip(cols, shown):
        c = r["candidates"][name]
        row = rk.loc[name]
        rng = inc["ranges"].get(name, {})
        with col:
            st.markdown(f"**{name}**  \n_{TIER.get(c.get('tier'), '')}_")
            st.metric("Score (0.5 = same as now)", f"{row['score_mean']:.2f}",
                      help=f"Range {row['score_p05']:.2f}-{row['score_p95']:.2f} across past years and weightings")
            st.caption(f"Chance of being the best option: {row['p_top']:.0%}")
            if rng:
                st.caption(f"Income: {money(rng.get('mid'))}/acre/yr ({money(rng.get('low'))} to {money(rng.get('high'))} "
                           "with low/high prices)")
            for f in r["flags"].get(name, []):
                st.caption(f"- {f}")
    st.subheader("All rotations compared")
    table = pd.DataFrame({
        "Type": [TIER.get(r["candidates"][n].get("tier"), "") for n in rk.index],
        "Score": rk["score_mean"], "Low": rk["score_p05"], "High": rk["score_p95"],
        "Chance best": rk["p_top"],
        "Income $/acre/yr": [inc["usd_per_acre"].get(n) for n in rk.index],
    }, index=rk.index)
    st.dataframe(table.style.format({"Score": "{:.2f}", "Low": "{:.2f}", "High": "{:.2f}",
                                     "Chance best": "{:.0%}", "Income $/acre/yr": "{:,.0f}"}, na_rep="n/a"),
                 width="stretch")
    if inc.get("note"):
        st.caption(inc["note"])
    if r["removed"]:
        with st.expander(f"{len(r['removed'])} rotations not shown, and why"):
            for x in r["removed"]:
                st.write(f"- **{x['name']}**: {x['reason']}")
    rob = r.get("robustness") or {}
    if rob.get("note"):
        st.caption(rob["note"])

# Why -------------------------------------------------------------------------------------------------------------
with tabs[1]:
    sv = r["point_scores"]["slider_values"].rename(columns=SLIDER_COLS)
    st.subheader("How each rotation does on your priorities")
    st.caption("0.5 = same as your current rotation; above 0.5 = better.")
    st.bar_chart(sv.loc[[n for n in shown if n in sv.index]].T, stack=False)
    st.dataframe(sv.style.format("{:.2f}"), width="stretch")
    st.subheader("The numbers behind it (real units)")
    raw = r["criteria_raw"].rename(columns={k: f"{lab} [{u}]" for k, (lab, u) in CRITERIA.items()})
    st.dataframe(raw.style.format("{:,.1f}", na_rep="n/a"), width="stretch")
    if r.get("dropped_criteria"):
        st.caption(f"Not scored (no data): {', '.join(r['dropped_criteria'])}")
    st.caption("Drought uses the average of the worst 10% of years; drainage, erosion and income are yearly "
               "averages; the 0-3 scores come from published research (content/rotations.yaml).")

# Hard year -----------------------------------------------------------------------------------------------------
with tabs[2]:
    years = sorted({y for ys in r["replay"]["suggested_years"].values() for y in ys})
    year = st.selectbox("Replay a past year", years, index=years.index(2012) if 2012 in years else 0,
                        help="Hard years picked from the NASA weather record and the model results.")
    rp = r["replay"] if year == r["replay"]["year"] else pipeline.replay(r["run"], year)
    st.write(rp["sentence"])
    t = rp["table"].reset_index()
    first = t.columns[0]
    pick = st.selectbox("Rotation", list(dict.fromkeys(t[first])))
    st.dataframe(t[t[first] == pick].drop(columns=[first]), width="stretch", hide_index=True)

# Climate ---------------------------------------------------------------------------------------------------------
with tabs[3]:
    st.subheader("Recent climate at this field (NASA POWER)")
    rows = [{"Indicator": s["label"], "Unit": s["unit"],
             f"Mean {s['recent_years'][0]}-{s['recent_years'][1]}": round(s["recent_mean"], 1),
             "Range": f"{s['recent_min']:.0f} to {s['recent_max']:.0f}",
             "Trend per decade": round(s.get("trend_per_decade") or 0, 2), "p-value": s.get("p_value")}
            for s in r["snapshot"].values()]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    tr = r.get("trends")
    if tr is not None and len(tr):
        st.subheader("Long-term trends")
        for s in tr["sentence"]:
            st.write(f"- {s}")
    st.write("Hard years in the record:", r["notable_years"])

# Evidence ----------------------------------------------------------------------------------------------------------
with tabs[4]:
    val = r.get("validation") or {}
    st.subheader("Checking the model against measurements")
    for s in val.get("sentences", []):
        st.write(f"- {s}")
    if not val.get("sentences"):
        st.write("No independent measurements are available for this field yet.")
    st.subheader("Data used for this field")
    for k, s in r["field"].get("sources", {}).items():
        st.write(f"- **{k.replace('_', ' ').capitalize()}**: {s}")
    st.write("- **Weather**: NASA POWER daily data, 1981-2025, for the ~50 km cell outlined on the map")
    with st.expander("Technical notes"):
        for n in val.get("notes", []):
            st.write(f"- {n}")

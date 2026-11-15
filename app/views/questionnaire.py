"""Step 2: the questionnaire. Part 1 about the farm, Part 2 the farmer's priorities, then run.

Answers keep their values when the farmer moves between steps (persist_state="session").
"""

import streamlit as st

import services
import ui

EXISTING = {
    "As the crop maps show": None,
    "Corn - soybean": ["corn", "soybean"],
    "Corn - corn - soybean": ["corn", "corn", "soybean"],
    "Continuous corn": ["corn"],
}
PRIORITY_SLIDERS = {   # app weight key -> (label, help)
    "drought": ("Drought resilience", "Keeping the crop supplied with water at its most sensitive stage in dry years"),
    "water_quality": ("Water quality", "Less water - and the nitrate it carries - draining below the roots"),
    "soil_health": ("Soil health and erosion", "Living cover in heavy rain, especially on slopes; building organic matter"),
    "income": ("Income", "Typical income after all costs, including land"),
    "pests": ("Pests and fertiliser", "Breaking pest and disease cycles; nitrogen from legumes"),
}
KEEP = {"persist_state": "session"}


def _answers(fld: dict | None) -> tuple[dict, dict]:
    ss = st.session_state
    answers = {
        "livestock_or_hay_buyer": ss.q_hay_buyer, "hay_equipment": ss.q_hay_equipment,
        "small_grain_buyer": ss.q_grain_buyer, "can_seed_cover": ss.q_cover, "openness": ss.q_open,
    }
    if EXISTING.get(ss.q_existing):
        answers["existing_rotation"] = EXISTING[ss.q_existing]
    if ss.q_tile in ("Yes", "No"):
        answers["tile_drained"] = ss.q_tile == "Yes"
    if ss.q_slope in ("Yes", "No"):
        answers["erosion_prone"] = ss.q_slope == "Yes"
    if ss.q_open == "no":
        answers["current_crops"] = list(ss.get("q_current_crops", ["Corn", "Soybean"]))
    weights = {k: ss[f"w_{k}"] for k in PRIORITY_SLIDERS}
    if sum(weights.values()) == 0:
        weights = {k: 1 for k in weights}
    return answers, weights


def render():
    lat, lon = st.session_state.lat, st.session_state.lon
    st.button("Change field", icon=":material/arrow_back:", type="tertiary", on_click=ui.go("field"))
    st.header("About your farm")
    try:
        fld = services.field_lookup(lat, lon)
    except Exception:
        fld = None
    guess = (fld or {}).get("existing_rotation_guess")
    seen = " - ".join(ui.crop_label(y[0] if isinstance(y, (list, tuple)) else y).lower() for y in guess) if guess else None
    st.html(f'<p class="fs-lead">Field at {lat:.4f}, {lon:.4f}'
            + (f" - the crop maps show {seen}." if seen else ".") + "</p>")

    with st.container(border=True):
        st.subheader("Part 1 - Your farm")
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.selectbox("What do you grow on this field now?", list(EXISTING), key="q_existing",
                         help=f"The crop maps suggest {seen}." if seen else "No crop-map history here.", **KEEP)
            st.radio("Is the field tile-drained?", ["As suggested", "Yes", "No"],
                     key="q_tile", horizontal=True, **KEEP)
            if fld:
                st.caption(f"The soil survey suggests: {'yes' if fld.get('tile_drained') else 'no'} "
                           f"({fld['soil']['drainage_class'].lower()} soils).")
            st.radio("Is it sloping or prone to erosion?", ["As suggested", "Yes", "No"],
                     key="q_slope", horizontal=True, **KEEP)
            if fld:
                st.caption(f"The slope data suggest: {'yes' if fld.get('erosion_prone') else 'no'} "
                           f"(about {fld['slope']['slope_pct_mean']}% slope).")
        with c2:
            st.markdown("**What can you do on this farm?**")
            st.checkbox("I have livestock or a hay buyer nearby", key="q_hay_buyer", **KEEP)
            st.checkbox("I have hay equipment (own or hired)", key="q_hay_equipment", **KEEP)
            st.checkbox("There is a buyer for oats or wheat within reach", value=True, key="q_grain_buyer", **KEEP)
            st.checkbox("Someone can seed a cover crop after harvest", value=True, key="q_cover", **KEEP)
            st.segmented_control("Are you open to growing new crops?", ["yes", "maybe", "no"], default="maybe",
                                 format_func=str.capitalize, key="q_open", required=True, **KEEP)
            if st.session_state.get("q_open") == "no":
                st.multiselect("Which crops do you grow now?", ["Corn", "Soybean", "Oats", "Winter wheat", "Alfalfa"],
                               default=["Corn", "Soybean"], key="q_current_crops", **KEEP)

    with st.container(border=True):
        st.subheader("Part 2 - What matters most to you?")
        st.caption("0 = not important, 10 = very important")
        cols = st.columns(2, gap="large")
        for i, (key, (label, why)) in enumerate(PRIORITY_SLIDERS.items()):
            with cols[i % 2]:
                st.slider(label, 0, 10, 5, key=f"w_{key}", help=why, **KEEP)

    if st.button("Run analysis", icon=":material/play_arrow:", type="primary", width="stretch"):
        answers, weights = _answers(fld)
        with st.spinner("Running 40+ years of NASA weather through each rotation and testing the "
                        f"ranking {services.N_BOOT} times - about 15 seconds..."):
            try:
                result = services.analyse(lat, lon, services.freeze(answers), services.freeze(weights))
            except Exception as e:
                st.error(f"The analysis could not run: {e}")
                return
        order = ui.risk_order(result)
        best = result["ranking"].index[0]
        st.session_state.result = result
        st.session_state.risk_order = order
        st.session_state.pick_featured = st.session_state.pick_calendar = best
        st.session_state.step = "results"
        st.rerun()

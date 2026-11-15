"""Step 2: the questionnaire. Part 1 about the farm, Part 2 the farmer's priorities, then run.

The current rotation is built with a crop picker (Year 1, Year 2, ... up to 4 years), pre-filled
from the crop maps, so any rotation can be entered - not only corn-soybean.
Answers keep their values when the farmer moves between steps (persist_state="session").
"""

import streamlit as st

import services
import ui

CROP_CHOICES = {   # value passed to the model (crops.py format) -> label
    "corn": "Corn",
    "soybean": "Soybean",
    "winter_wheat": "Winter wheat",
    "oats": "Oats",
    "oats+red_clover": "Oats + red clover",
    "oats+alfalfa": "Oats + alfalfa seeding",
    "alfalfa": "Alfalfa hay",
}
MAX_YEARS = 4
PRIORITY_SLIDERS = {   # app weight key -> (label, help)
    "drought": ("Drought resilience", "Keeping the crop supplied with water at its most sensitive stage in dry years"),
    "water_quality": ("Water quality", "Less water - and the nitrate it carries - draining below the roots"),
    "soil_health": ("Soil health and erosion", "Living cover in heavy rain, especially on slopes; building organic matter"),
    "income": ("Income", "Typical return over costs (before land rent)"),
    "pests": ("Pests and fertiliser", "Breaking pest and disease cycles; nitrogen from legumes"),
}
KEEP = {"persist_state": "session"}


# --- current rotation picker --------------------------------------------------------------------------
def _from_maps(fld: dict | None) -> list:
    guess = (fld or {}).get("existing_rotation_guess") or []
    crops = [y[0] if isinstance(y, (list, tuple)) else y for y in guess]
    return [c for c in crops if c in CROP_CHOICES][:MAX_YEARS]


def _add(crop: str):
    if len(st.session_state.rot_pick) < MAX_YEARS:
        st.session_state.rot_pick = st.session_state.rot_pick + [crop]


def _undo():
    st.session_state.rot_pick = st.session_state.rot_pick[:-1]


def _clear():
    st.session_state.rot_pick = []


def _use_maps(crops: list):
    st.session_state.rot_pick = list(crops)


def _rotation_picker(fld: dict | None):
    field_id = (st.session_state.lat, st.session_state.lon)
    if st.session_state.get("rot_field") != field_id:            # new field: start from its crop maps
        st.session_state.rot_field = field_id
        st.session_state.rot_pick = _from_maps(fld)
    pick = st.session_state.rot_pick
    maps = _from_maps(fld)

    st.markdown("**Your current rotation**")
    st.caption("Tap the crops in the order you grow them." + (" Filled in from the crop maps - change it if needed."
                                                              if maps else ""))
    chips = "".join(
        f'<span class="fs-chip"><b>Year {i + 1}</b>{CROP_CHOICES[pick[i]]}</span>' if i < len(pick)
        else f'<span class="fs-chip empty"><b>Year {i + 1}</b>{"tap a crop" if i == len(pick) else "-"}</span>'
        for i in range(max(3, min(MAX_YEARS, len(pick) + 1))))
    st.html(f'<div class="fs-chips">{chips}</div>')
    full = len(pick) >= MAX_YEARS
    with st.container(horizontal=True, gap="small", wrap=True):
        for value, label in CROP_CHOICES.items():
            st.button(label, key=f"add_{value}", on_click=_add, args=(value,), disabled=full)
    with st.container(horizontal=True, gap="small", wrap=True):
        st.button("Undo", icon=":material/undo:", type="tertiary", on_click=_undo, disabled=not pick)
        st.button("Clear", icon=":material/close:", type="tertiary", on_click=_clear, disabled=not pick)
        if maps and maps != pick:
            st.button("Use the crop maps", icon=":material/satellite_alt:", type="tertiary",
                      on_click=_use_maps, args=(maps,))


# --- answers -------------------------------------------------------------------------------------------
def _answers() -> tuple[dict, dict]:
    ss = st.session_state
    answers = {
        "livestock_or_hay_buyer": ss.q_hay_buyer, "hay_equipment": ss.q_hay_equipment,
        "small_grain_buyer": ss.q_grain_buyer, "can_seed_cover": ss.q_cover, "openness": ss.q_open,
    }
    if ss.get("rot_pick"):
        answers["existing_rotation"] = list(ss.rot_pick)
    if ss.q_tile in ("Yes", "No"):
        answers["tile_drained"] = ss.q_tile == "Yes"
    if ss.q_slope in ("Yes", "No"):
        answers["erosion_prone"] = ss.q_slope == "Yes"
    if ss.q_open == "no":
        grown = {part for c in ss.get("rot_pick", []) for part in c.split("+")}   # e.g. oats, red_clover
        answers["current_crops"] = sorted(grown or {"corn", "soybean"})
    weights = {k: ss[f"w_{k}"] for k in PRIORITY_SLIDERS}
    if sum(weights.values()) == 0:
        weights = {k: 1 for k in weights}
    return answers, weights


def render():
    lat, lon = st.session_state.lat, st.session_state.lon
    st.button("Change field", icon=":material/arrow_back:", type="tertiary", on_click=ui.go("field"))
    ui.page_header("Step 2 of 3", "About your farm",
                   f"Two short parts, then we compare rotations for your field "
                   f"({services.location_text(lat, lon)}).")
    try:
        fld = services.field_lookup(lat, lon)
    except Exception:
        fld = None

    ui.section_heading("Your farm", number=1, sub="What you grow now and what you can do.")
    with ui.section("part1"):
        _rotation_picker(fld)
        st.divider()
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.radio("Is the field tile-drained?", ["As suggested", "Yes", "No"], key="q_tile", horizontal=True, **KEEP)
            if fld:
                st.caption(f"Soil survey suggests: {'yes' if fld.get('tile_drained') else 'no'}")
            st.radio("Is it sloping or prone to erosion?", ["As suggested", "Yes", "No"], key="q_slope",
                     horizontal=True, **KEEP)
            if fld:
                st.caption(f"Slope data suggest: {'yes' if fld.get('erosion_prone') else 'no'} "
                           f"(about {fld['slope']['slope_pct_mean']:.0f}% slope)")
            st.segmented_control("Open to growing new crops?", ["yes", "maybe", "no"], default="maybe",
                                 format_func=str.capitalize, key="q_open", required=True, **KEEP)
        with c2:
            st.markdown("**What can you do on this farm?**")
            st.checkbox("Livestock or a hay buyer nearby", key="q_hay_buyer", **KEEP)
            st.checkbox("Hay equipment (own or hired)", key="q_hay_equipment", **KEEP)
            st.checkbox("A buyer for oats or wheat within reach", value=True, key="q_grain_buyer", **KEEP)
            st.checkbox("Someone can seed a cover crop after harvest", value=True, key="q_cover", **KEEP)

    ui.section_heading("What matters most to you?", number=2, sub="0 = not important, 10 = very important.")
    with ui.section("part2"):
        cols = st.columns(2, gap="large")
        for i, (key, (label, why)) in enumerate(PRIORITY_SLIDERS.items()):
            with cols[i % 2]:
                st.slider(label, 0, 10, 5, key=f"w_{key}", help=why, **KEEP)

    st.html('<div style="height:.6rem"></div>')
    clicked = st.button("Run analysis", icon=":material/play_arrow:", type="primary", width="stretch")
    st.html('<p class="fs-source" style="text-align:center;margin-top:.1rem">This can take up to a minute.</p>')
    if clicked:
        answers, weights = _answers()
        with st.spinner("Running 40+ years of NASA weather through each rotation - this can take up to a minute..."):
            try:
                result = services.analyse(lat, lon, services.freeze(answers), services.freeze(weights))
            except Exception as e:
                st.error(f"The analysis could not run: {e}")
                return
        opts = ui.four_options(result)
        first = "Best fit" if "Best fit" in opts else "Current"
        st.session_state.result = result
        st.session_state.options = opts
        for key in ("pick_featured", "pick_calendar", "pick_replay"):
            st.session_state[key] = first
        st.session_state.step = "results"
        st.rerun()

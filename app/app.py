"""Orbital Acre - Streamlit app. Run from the repo root:  python -m streamlit run app/app.py

One page, three steps plus About, chosen by st.session_state.step:
    field       Home: choose a field in Story County on the map      (app/views/field.py)
    questions   Questionnaire: Part 1 your farm, Part 2 priorities    (app/views/questionnaire.py)
    results     Best-fit rotation, rotation calendar, more detail     (app/views/results.py)
    about       Data, method, limits, team                            (app/views/about.py)
The banner (app/banner.py) is on every screen; its Home button returns to the field map.
"""

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR.parent / "src"))     # fieldshift package
sys.path.insert(0, str(APP_DIR))                    # banner, ui, services, calendar_view, views

import banner  # noqa: E402
import ui  # noqa: E402
from fieldshift import config  # noqa: E402
from views import about, field, questionnaire, results  # noqa: E402

st.set_page_config(page_title=banner.NAME, page_icon=str(banner.logo_path()), layout="wide",
                   initial_sidebar_state="collapsed")

ss = st.session_state
if "step" not in ss:
    ss.step = "field"
    ss.lat, ss.lon = config.EXAMPLE_POINTS[config.DEFAULT_POINT]
    ss.result = None

ui.inject_css()
banner.render()
{"field": field.render, "questions": questionnaire.render,
 "results": results.render, "about": about.render}.get(ss.step, field.render)()

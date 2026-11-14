"""Field Shift - Streamlit app entry point. Run from the repo root:  python -m streamlit run app/app.py

Sets up the page, draws the banner (app/banner.py: logo, name, menu) and opens the chosen page:
    app/views/home.py      Home
    app/views/analyse.py   Analyse a field (the tool)
    app/views/about.py     About (data, method, limits, team)
"""

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR.parent / "src"))     # fieldshift package
sys.path.insert(0, str(APP_DIR))                    # banner.py

import banner  # noqa: E402

st.set_page_config(page_title=banner.NAME, page_icon=str(banner.logo_path()), layout="wide")

PAGES = [
    st.Page("views/home.py", title="Home", icon=":material/home:", default=True),
    st.Page("views/analyse.py", title="Analyse a field", icon=":material/agriculture:", url_path="analyse"),
    st.Page("views/about.py", title="About", icon=":material/info:", url_path="about"),
]
page = st.navigation(PAGES, position="hidden")      # the banner is the menu
banner.render(PAGES)
page.run()

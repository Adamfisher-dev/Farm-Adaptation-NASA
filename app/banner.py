"""Full-width banner fixed to the top of every screen: logo, name, tagline, Home and About.

It slides away when the page is scrolled down and comes back when scrolling up.

To change the branding, edit the settings below:
  - LOGO:    put your logo in app/assets/ (PNG, JPG or SVG) and name it here.
             Until then the placeholder app/assets/logo_placeholder.svg is shown.
  - NAME:    the project name shown next to the logo.
  - TAGLINE: one short line under the name (hidden on phones), or "" for none.
"""

from pathlib import Path

import streamlit as st

import ui

ASSETS = Path(__file__).resolve().parent / "assets"
LOGO = "logo.png"                                   # your logo file in app/assets/
LOGO_PLACEHOLDER = "logo_placeholder.svg"
NAME = "Field Shift"
TAGLINE = "Adapting Iowa crop rotations with NASA data"

BANNER_CSS = f"""
<style>
.st-key-banner {{
    position: fixed; top: 0; left: 0; right: 0; width: 100% !important; z-index: 999990;
    background: linear-gradient(90deg, {ui.GREEN_DARK} 0%, {ui.GREEN} 65%, #3d7d45 100%);
    box-shadow: 0 2px 10px rgba(0,0,0,0.18);
    padding: 0.55rem max(1.25rem, calc((100vw - 1100px) / 2 + 1.25rem));
    transition: transform 0.28s ease;
}}
body.fs-banner-hidden .st-key-banner {{ transform: translateY(-110%); }}
.st-key-banner p, .st-key-banner span {{ color: #ffffff !important; }}
.st-key-banner img {{ display: block; }}
.fs-name {{ font-size: 1.45rem; font-weight: 700; line-height: 1.1; margin: 0; color: #fff; white-space: nowrap; }}
.fs-tagline {{ font-size: 0.85rem; opacity: 0.85; margin: 0; color: #fff; white-space: nowrap; }}
.st-key-banner button {{
    background: transparent !important; border: 1px solid rgba(255,255,255,0.0) !important;
    color: #ffffff !important; font-weight: 600; padding: 0.3rem 0.8rem !important; border-radius: 8px !important;
}}
.st-key-banner button:hover {{ background: rgba(255,255,255,0.14) !important; }}
.st-key-banner button p {{ color: #ffffff !important; }}
.st-key-nav_home_on button, .st-key-nav_about_on button {{ border-color: rgba(255,255,255,0.65) !important; }}
@media (max-width: 640px) {{
    .st-key-banner {{ padding: 0.45rem 0.8rem; }}
    .fs-name {{ font-size: 1.15rem; }}
    .fs-tagline {{ display: none; }}
    .st-key-banner button {{ padding: 0.25rem 0.55rem !important; }}
}}
</style>
"""

# Hide on scroll down, show on scroll up. Listens to scroll events from any element (Streamlit
# scrolls an inner container, not the window) and toggles a class on <body>, which survives reruns.
SCROLL_JS = """
<script>
(function () {
  if (window.__fsBannerScroll) return;
  window.__fsBannerScroll = true;
  var last = new WeakMap();
  document.addEventListener("scroll", function (e) {
    var el = (e.target === document) ? (document.scrollingElement || document.documentElement) : e.target;
    if (!el || typeof el.scrollTop !== "number") return;
    var y = el.scrollTop, prev = last.has(el) ? last.get(el) : 0;
    if (Math.abs(y - prev) < 6) return;
    if (y > prev && y > 80) document.body.classList.add("fs-banner-hidden");
    else document.body.classList.remove("fs-banner-hidden");
    last.set(el, y);
  }, true);
})();
</script>
"""


def logo_path() -> Path:
    custom = ASSETS / LOGO
    return custom if custom.exists() else ASSETS / LOGO_PLACEHOLDER


def render() -> None:
    st.html(BANNER_CSS)
    step = st.session_state.get("step", "field")
    with st.container(key="banner", horizontal=True, vertical_alignment="center",
                      horizontal_alignment="distribute"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small", width="content"):
            st.image(str(logo_path()), width=44)
            st.html(f'<div><p class="fs-name">{NAME}</p>'
                    + (f'<p class="fs-tagline">{TAGLINE}</p>' if TAGLINE else "") + "</div>")
        with st.container(horizontal=True, vertical_alignment="center", gap="small", width="content"):
            st.button("Home", icon=":material/home:", on_click=ui.go("field"),
                      key="nav_home_on" if step in ("field", "questions", "results") else "nav_home")
            st.button("About", icon=":material/info:", on_click=ui.go("about"),
                      key="nav_about_on" if step == "about" else "nav_about")
    st.html(SCROLL_JS, unsafe_allow_javascript=True)

"""Full-width banner fixed to the top of every screen: logo, name, tagline, Home and About.

It slides away when the page is scrolled down and comes back when scrolling up.

To change the branding, edit the settings below:
  - LOGO:    the banner logo in app/assets/ - a cream line logo on a transparent background, drawn
             straight on the green (logo_colour.png is the earlier colour logo, kept for reference).
  - ICON:    the browser-tab icon (dark version, so it shows on light tabs).
  - NAME:    the project name shown next to the logo.
  - TAGLINE: one short line under the name (hidden on phones), or "" for none.
"""

from pathlib import Path

import streamlit as st

import ui

ASSETS = Path(__file__).resolve().parent / "assets"
LOGO = "logo.png"                                   # your logo file in app/assets/
LOGO_PLACEHOLDER = "logo_placeholder.svg"
ICON = "logo_icon.png"                              # browser-tab icon
NAME = "Orbital Acre"
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
/* logo: cream line logo straight on the green (wider than tall), with a soft shadow for depth */
.st-key-banner [data-testid="stImage"] img {{
    display: block; width: 96px !important; height: 66px !important; object-fit: contain;
    filter: drop-shadow(0 1px 2px rgba(0,0,0,0.35));
}}
/* the image's wrappers keep the width given to st.image; let them shrink with the logo on phones */
.st-key-banner [data-testid="stFullScreenFrame"],
.st-key-banner [data-testid="stElementContainer"]:has([data-testid="stImage"]) {{
    width: fit-content !important; flex: 0 0 auto !important; }}
.fs-name {{ font-size: 1.8rem; font-weight: 800; letter-spacing: 0.01em; line-height: 1.05; margin: 0;
           color: #fff; white-space: nowrap; text-shadow: 0 1px 2px rgba(0,0,0,0.25); }}
.fs-tagline {{ font-size: 0.88rem; opacity: 0.9; margin: 0.15rem 0 0; color: #fff; white-space: nowrap; }}
.st-key-banner button {{
    background: transparent !important; border: none !important; box-shadow: none !important;
    color: #ffffff !important; padding: 0.35rem 0.75rem !important; border-radius: 0 !important;
    min-height: 0 !important; opacity: 0.82; transition: opacity 0.15s ease;
}}
.st-key-banner button:hover, .st-key-banner button:focus-visible {{ opacity: 1; background: transparent !important; }}
.st-key-banner button p {{ color: #ffffff !important; font-size: 1.08rem !important; font-weight: 650; }}
.st-key-banner button [data-testid="stIconMaterial"] {{ font-size: 1.25rem !important; }}
/* current page: full brightness and a thin white underline instead of a box */
.st-key-nav_home_on button, .st-key-nav_about_on button {{ opacity: 1; }}
.st-key-nav_home_on button p, .st-key-nav_about_on button p {{
    text-decoration: underline; text-decoration-thickness: 2px; text-underline-offset: 0.45rem; }}
@media (max-width: 640px) {{
    .st-key-banner {{ padding: 0.45rem 0.8rem; }}
    .st-key-banner [data-testid="stImage"] img {{ width: 64px !important; height: 44px !important; }}
    .fs-name {{ font-size: 1.3rem; }}
    .fs-tagline {{ display: none; }}
    .st-key-banner button {{ padding: 0.25rem 0.55rem !important; }}
}}
@media (max-width: 480px) {{        /* phones: icon-only menu so the banner stays on one line */
    .st-key-nav_home_on button, .st-key-nav_about_on button {{ border-bottom: 2px solid #ffffff !important; }}
    .st-key-banner button p {{ position: absolute !important; width: 1px; height: 1px; overflow: hidden;
                              clip: rect(0 0 0 0); white-space: nowrap; }}   /* still read by screen readers */
    .st-key-banner button {{ padding: 0.35rem 0.5rem !important; min-width: 2.4rem; }}
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


def icon_path() -> Path:
    icon = ASSETS / ICON
    return icon if icon.exists() else logo_path()


def render() -> None:
    st.html(BANNER_CSS)
    step = st.session_state.get("step", "field")
    with st.container(key="banner", horizontal=True, vertical_alignment="center",
                      horizontal_alignment="distribute", wrap=False):
        with st.container(horizontal=True, vertical_alignment="center", gap="small", width="content"):
            st.image(str(logo_path()), width=96)
            st.html(f'<div><p class="fs-name">{NAME}</p>'
                    + (f'<p class="fs-tagline">{TAGLINE}</p>' if TAGLINE else "") + "</div>")
        with st.container(horizontal=True, vertical_alignment="center", gap="small", width="content"):
            st.button("Home", icon=":material/home:", on_click=ui.go("field"), help="Home: choose your field",
                      key="nav_home_on" if step in ("field", "questions", "results") else "nav_home")
            st.button("About", icon=":material/info:", on_click=ui.go("about"), help="About Orbital Acre",
                      key="nav_about_on" if step == "about" else "nav_about")
    st.html(SCROLL_JS, unsafe_allow_javascript=True)

"""Top banner shown on every page: logo, name, tagline and the main menu.

To change the branding, edit the three settings below:
  - LOGO:    put your logo in app/assets/ (PNG, JPG or SVG) and name it here.
             Until then the placeholder app/assets/logo_placeholder.svg is shown.
  - NAME:    the project name shown next to the logo.
  - TAGLINE: one short line under the name (or "" for none).
"""

from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parent / "assets"
LOGO = "logo.png"                                   # your logo file in app/assets/
LOGO_PLACEHOLDER = "logo_placeholder.svg"
NAME = "Field Shift"
TAGLINE = "Adapting Iowa crop rotations with NASA data"

BANNER_CSS = """
<style>
.st-key-banner {
    background: linear-gradient(90deg, #1f4d2b 0%, #2f6b3a 60%, #3d7d45 100%);
    border-radius: 12px;
    padding: 0.6rem 1.1rem;
    margin-bottom: 0.8rem;
}
.st-key-banner p, .st-key-banner span, .st-key-banner a { color: #ffffff !important; }
.st-key-banner .banner-name { font-size: 1.6rem; font-weight: 700; line-height: 1.1; margin: 0; }
.st-key-banner .banner-tagline { font-size: 0.9rem; opacity: 0.85; margin: 0; }
.st-key-banner [data-testid="stPageLink"] a {
    border-radius: 8px; padding: 0.25rem 0.6rem; justify-content: center;
}
.st-key-banner [data-testid="stPageLink"] a:hover { background: rgba(255, 255, 255, 0.15); }
.st-key-banner [data-testid="stPageLink-NavLink"][aria-current="page"],
.st-key-banner [data-testid="stPageLink"] a[aria-current="page"] { background: rgba(255, 255, 255, 0.22); }
</style>
"""


def logo_path() -> Path:
    custom = ASSETS / LOGO
    return custom if custom.exists() else ASSETS / LOGO_PLACEHOLDER


def render(pages: list) -> None:
    """Draw the banner. `pages` are the st.Page objects for the menu, in order."""
    st.markdown(BANNER_CSS, unsafe_allow_html=True)
    with st.container(key="banner"):
        logo_col, name_col, menu_col = st.columns([1, 6, 6], vertical_alignment="center")
        with logo_col:
            st.image(str(logo_path()), width=64)
        with name_col:
            st.markdown(f'<p class="banner-name">{NAME}</p>'
                        + (f'<p class="banner-tagline">{TAGLINE}</p>' if TAGLINE else ""),
                        unsafe_allow_html=True)
        with menu_col:
            for col, page in zip(st.columns(len(pages)), pages):
                with col:
                    st.page_link(page, label=page.title, icon=page.icon or None, width="stretch")

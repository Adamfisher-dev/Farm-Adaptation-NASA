"""Shared look and small helpers: page CSS, names, colours, number formats."""

import pandas as pd
import streamlit as st

GREEN = "#2f6b3a"
GREEN_DARK = "#1f4d2b"

# Crop names and calendar colours (cover crops are drawn striped).
CROP = {   # crop: (label, colour, text colour)
    "corn": ("Corn", "#F2C14E", "#2b2300"),
    "soybean": ("Soybean", "#5B8C3A", "#ffffff"),
    "winter_wheat": ("Winter wheat", "#C9A66B", "#2b1d00"),
    "oats": ("Oats", "#A7B85A", "#1f2600"),
    "alfalfa": ("Alfalfa", "#7B5EA7", "#ffffff"),
    "red_clover": ("Red clover", "#C2504A", "#ffffff"),
    "cereal_rye": ("Cereal rye", "#2F7F8F", "#ffffff"),
}
SHORT = {"corn": "Corn", "soybean": "Soy", "winter_wheat": "Wheat", "oats": "Oats", "alfalfa": "Alfalfa",
         "red_clover": "clover", "cereal_rye": "rye"}
COVER_SHORT = {"none": "", "rye_before_soy": " + rye before soy", "rye": " + rye"}
TIER = {"current": "Your current rotation", "small_step": "Small step", "bigger_shift": "Bigger change"}
PRIORITIES = {   # slider column in the results -> label
    "drought": "Drought resilience",
    "soil_erosion": "Soil health and erosion",
    "water_quality": "Water quality",
    "income": "Income",
    "pests_fertiliser": "Pests and fertiliser",
}


def crop_label(crop: str) -> str:
    return CROP.get(crop, (crop.replace("_", " ").capitalize(),))[0]


def short_name(cand: dict) -> str:
    """Compact rotation name for buttons, e.g. 'Corn–Soy–Oats/clover + rye'."""
    parts = []
    for year in cand.get("plan", []):           # the plan keeps under-sown crops ("oats+red_clover")
        cash, _, under = year[0].partition("+")
        parts.append(SHORT.get(cash, cash.capitalize()) + (f"/{SHORT.get(under, under)}" if under else ""))
    return "–".join(parts) + COVER_SHORT.get(cand.get("cover_option", "none"), "")


def money(x) -> str:
    if x is None or pd.isna(x):
        return "n/a"
    return f"{'-' if x < 0 else ''}${abs(x):,.0f}"


def risk_order(result: dict) -> list:
    """The current rotation first (the yardstick: it scores 0.5 in every run by definition), then the
    alternatives from lowest to highest risk for this farmer: by the score in a bad case (the 5th
    percentile over past weather years, prices and priority weights), then by the average score."""
    rk = result["ranking"]
    current = [n for n in rk.index if result["candidates"][n].get("tier") == "current"]
    others = sorted((n for n in rk.index if n not in current),
                    key=lambda n: (-rk.loc[n, "score_p05"], -rk.loc[n, "score_mean"]))
    return current + others


def go(step: str):
    """on_click callback: switch the screen."""
    def _go():
        st.session_state.step = step
    return _go


PAGE_CSS = f"""
<style>
/* page frame: no Streamlit header or sidebar, centred readable column, room for the fixed banner */
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"], [data-testid="stDecoration"] {{ display: none !important; }}
[data-testid="stMainBlockContainer"], .block-container {{
    max-width: 1100px; padding-top: 6.8rem !important; padding-bottom: 4rem;
    padding-left: 1.25rem; padding-right: 1.25rem;
}}
@media (max-width: 640px) {{
    [data-testid="stMainBlockContainer"], .block-container {{
        padding-top: 5.2rem !important; padding-left: 0.8rem; padding-right: 0.8rem;
    }}
}}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
.fs-lead {{ font-size: 1.05rem; opacity: 0.85; margin-top: -0.4rem; }}
.fs-badge {{ display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.8rem;
            font-weight: 600; background: {GREEN}; color: #fff; margin-bottom: 0.4rem; }}
.fs-badge.current {{ background: #6b7280; }}
.fs-badge.alt {{ background: #8a6d1f; }}
.fs-muted {{ opacity: 0.75; font-size: 0.9rem; }}

/* key numbers on the featured card: 4 across, 2 x 2 on phones */
.fs-stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.7rem; margin: 0.3rem 0 0.9rem; }}
@media (max-width: 640px) {{ .fs-stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
.fs-stat {{ border: 1px solid rgba(128,128,128,0.28); border-radius: 10px; padding: 0.6rem 0.8rem; }}
.fs-stat .l {{ font-size: 0.8rem; opacity: 0.75; }}
.fs-stat .v {{ font-size: 1.55rem; font-weight: 700; line-height: 1.25; }}
.fs-stat .n {{ font-size: 0.75rem; opacity: 0.8; }}
.fs-stat .n.up {{ color: {GREEN}; opacity: 1; font-weight: 600; }}
.fs-stat .n.down {{ color: #b36b00; opacity: 1; font-weight: 600; }}

/* priority comparison bars */
.fs-bars {{ display: grid; grid-template-columns: minmax(8rem, 13rem) 1fr 4.5rem; gap: 0.45rem 0.8rem;
           align-items: center; margin: 0.4rem 0 0.2rem; }}
.fs-bar {{ position: relative; height: 0.7rem; border-radius: 999px; background: rgba(128,128,128,0.18); }}
.fs-bar .mid {{ position: absolute; left: 50%; top: -0.2rem; bottom: -0.2rem; width: 2px;
               background: rgba(128,128,128,0.7); }}
.fs-bar .fill {{ position: absolute; top: 0; bottom: 0; border-radius: 999px; }}
.fs-bar .fill.up {{ background: {GREEN}; }}
.fs-bar .fill.down {{ background: #c27c0e; }}
.fs-bars .verdict {{ font-size: 0.85rem; font-weight: 600; text-align: right; }}
@media (max-width: 640px) {{ .fs-bars {{ grid-template-columns: 1fr 4rem; }}
                             .fs-bars .lab {{ grid-column: 1 / -1; margin-bottom: -0.3rem; }} }}

/* rotation calendar */
.fs-cal {{ width: 100%; }}
.fs-cal-months {{ position: relative; height: 1.3rem; margin-left: 0; font-size: 0.78rem; opacity: 0.75; }}
.fs-cal-months span {{ position: absolute; transform: translateX(2px); }}
.fs-cal-months .s {{ display: none; }}
@media (max-width: 640px) {{ .fs-cal-months .l {{ display: none; }} .fs-cal-months .s {{ display: inline; }} }}
.fs-cal-row {{ margin-bottom: 0.9rem; }}
.fs-cal-label {{ font-size: 0.9rem; margin-bottom: 0.25rem; }}
.fs-cal-track {{ position: relative; height: 2rem; border-radius: 6px; overflow: hidden;
                background: repeating-linear-gradient(135deg, rgba(128,128,128,0.10) 0 6px, rgba(128,128,128,0.20) 6px 12px); }}
.fs-cal-track .grid {{ position: absolute; top: 0; bottom: 0; width: 1px; background: rgba(128,128,128,0.35); }}
.fs-seg {{ position: absolute; top: 0; bottom: 0; display: flex; align-items: center; justify-content: center;
          font-size: 0.78rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          border-right: 1px solid rgba(255,255,255,0.6); }}
.fs-sens {{ position: relative; height: 0.35rem; margin-top: 0.2rem; }}
.fs-sens div {{ position: absolute; top: 0; bottom: 0; border-radius: 999px; background: #d0442f; }}
.fs-legend {{ display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; font-size: 0.82rem; margin-top: 0.3rem; }}
.fs-legend i {{ display: inline-block; width: 0.9rem; height: 0.9rem; border-radius: 3px; margin-right: 0.35rem;
               vertical-align: -0.15rem; }}
</style>
"""


def inject_css():
    st.html(PAGE_CSS)

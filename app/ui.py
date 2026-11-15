"""Shared look and small helpers: colour palette, page CSS, names, number formats, rotation options."""

import pandas as pd
import streamlit as st

# Palette: field green, sand panels, soil brown, wheat gold (theme colours in .streamlit/config.toml).
GREEN = "#2f6b3a"
GREEN_DARK = "#1f4d2b"
SAND = "#f3ecdd"
SAND_LINE = "#e2d6bd"
SOIL = "#8a6a44"
WHEAT = "#d9b44a"
INK = "#23301f"
AMBER = "#b0761a"

# Crop names and colours (calendar, charts). Cover crops are drawn striped in the calendar.
CROP = {   # crop: (label, colour, text colour)
    "corn": ("Corn", "#e0b54a", "#2b2300"),
    "soybean": ("Soybean", "#6e8b3d", "#ffffff"),
    "winter_wheat": ("Winter wheat", "#c9a66b", "#2b1d00"),
    "oats": ("Oats", "#b9b27a", "#232000"),
    "alfalfa": ("Alfalfa", "#7a6a99", "#ffffff"),
    "red_clover": ("Red clover", "#b5584e", "#ffffff"),
    "cereal_rye": ("Cereal rye", "#3f7f7a", "#ffffff"),
}
OTHER_COLOUR = "#b9b2a3"
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


def crop_colour(crop: str) -> str:
    return CROP.get(crop, (None, OTHER_COLOUR))[1]


def short_name(cand: dict) -> str:
    """Compact rotation name, e.g. 'Corn–Soy–Oats/clover + rye'."""
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
    """Alternatives (not the current rotation) from lowest to highest risk for this farmer: by the score
    in a bad case (5th percentile over past weather, prices and priority weights), then the average."""
    rk = result["ranking"]
    alts = [n for n in rk.index if result["candidates"][n].get("tier") != "current"]
    return sorted(alts, key=lambda n: (-rk.loc[n, "score_p05"], -rk.loc[n, "score_mean"]))


def four_options(result: dict) -> dict:
    """The four rotations the results screen switches between: {label: rotation name}.
    Current, Best fit, then the lowest-risk alternatives not already shown (Risk 1, Risk 2, ...)."""
    rk = result["ranking"]
    current = next((n for n in rk.index if result["candidates"][n].get("tier") == "current"), rk.index[0])
    best = rk.index[0]
    opts = {"Current": current}
    if best != current:
        opts["Best fit"] = best
    i = 1
    for name in risk_order(result):
        if len(opts) == 4:
            break
        if name not in opts.values():
            opts[f"Risk {i}"] = name
            i += 1
    return opts


def go(step: str):
    """on_click callback: switch the screen."""
    def _go():
        st.session_state.step = step
    return _go


def section(key: str, sand: bool = True):
    """A rounded panel; sand-coloured by default (styled through its key)."""
    return st.container(key=f"sec_{'sand' if sand else 'plain'}_{key}")


PAGE_CSS = f"""
<style>
/* page frame: no Streamlit header or sidebar, centred readable column, room for the fixed banner */
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"], [data-testid="stDecoration"] {{ display: none !important; }}
[data-testid="stMainBlockContainer"], .block-container {{
    max-width: 1040px; padding-top: 6.5rem !important; padding-bottom: 4rem;
    padding-left: 1.25rem; padding-right: 1.25rem;
}}
@media (max-width: 640px) {{
    [data-testid="stMainBlockContainer"], .block-container {{
        padding-top: 4.7rem !important; padding-left: 0.75rem; padding-right: 0.75rem;
    }}
}}
h1, h2, h3 {{ letter-spacing: -0.01em; color: {INK}; }}
h2 {{ font-size: 1.75rem !important; }}
.fs-lead {{ font-size: 1rem; opacity: 0.8; margin: -0.5rem 0 0.2rem; }}

/* panels: sand sections and plain bordered frames */
[class*="st-key-sec_sand_"] {{
    background: {SAND}; border: 1px solid {SAND_LINE}; border-radius: 14px; padding: 1.1rem 1.25rem 1.2rem;
}}
[class*="st-key-sec_plain_"] {{
    background: #ffffff; border: 1px solid {SAND_LINE}; border-radius: 14px; padding: 1rem 1.15rem 1.1rem;
}}
@media (max-width: 640px) {{
    [class*="st-key-sec_sand_"], [class*="st-key-sec_plain_"] {{ padding: 0.85rem 0.8rem 0.95rem; border-radius: 12px; }}
}}
.fs-kicker {{ font-size: 0.78rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
             color: {SOIL}; margin: 0 0 0.15rem; }}
.fs-title {{ font-size: 1.45rem; font-weight: 750; line-height: 1.2; margin: 0 0 0.25rem; color: {INK}; }}
.fs-sub {{ font-size: 0.92rem; opacity: 0.78; margin: 0; }}
.fs-source {{ font-size: 0.78rem; opacity: 0.7; margin: 0.35rem 0 0; }}
.fs-badge {{ display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.78rem;
            font-weight: 650; background: {GREEN}; color: #fff; margin-right: 0.4rem; vertical-align: 0.1rem; }}
.fs-badge.current {{ background: #6b6f63; }}
.fs-badge.alt {{ background: {SOIL}; }}

/* key numbers */
.fs-stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.7rem; margin: 0.6rem 0 0.4rem; }}
@media (max-width: 640px) {{ .fs-stats {{ grid-template-columns: 1fr; }} }}
.fs-stat {{ background: #ffffff; border: 1px solid {SAND_LINE}; border-radius: 12px; padding: 0.65rem 0.85rem; }}
.fs-stat .l {{ font-size: 0.8rem; opacity: 0.75; }}
.fs-stat .v {{ font-size: 1.6rem; font-weight: 750; line-height: 1.2; color: {INK}; }}
.fs-stat .n {{ font-size: 0.78rem; opacity: 0.8; }}
.fs-stat .n.up {{ color: {GREEN}; opacity: 1; font-weight: 650; }}
.fs-stat .n.down {{ color: {AMBER}; opacity: 1; font-weight: 650; }}

/* priority comparison bars */
.fs-bars {{ display: grid; grid-template-columns: minmax(8rem, 12rem) 1fr 4.2rem; gap: 0.5rem 0.8rem;
           align-items: center; margin: 0.3rem 0 0.2rem; }}
.fs-bars .lab {{ font-size: 0.92rem; }}
.fs-bar {{ position: relative; height: 0.65rem; border-radius: 999px; background: #e9e0cd; }}
.fs-bar .mid {{ position: absolute; left: 50%; top: -0.2rem; bottom: -0.2rem; width: 2px; background: #9c8f74; }}
.fs-bar .fill {{ position: absolute; top: 0; bottom: 0; border-radius: 999px; }}
.fs-bar .fill.up {{ background: {GREEN}; }}
.fs-bar .fill.down {{ background: {AMBER}; }}
.fs-bars .verdict {{ font-size: 0.82rem; font-weight: 650; text-align: right; }}
@media (max-width: 640px) {{ .fs-bars {{ grid-template-columns: 1fr 3.8rem; }}
                             .fs-bars .lab {{ grid-column: 1 / -1; margin-bottom: -0.3rem; }} }}
.fs-list {{ margin: 0.2rem 0 0; padding-left: 1.1rem; font-size: 0.92rem; }}
.fs-list li {{ margin: 0.15rem 0; }}

/* rotation calendar */
.fs-cal {{ width: 100%; }}
.fs-cal-months {{ position: relative; height: 1.3rem; font-size: 0.78rem; opacity: 0.75; }}
.fs-cal-months span {{ position: absolute; transform: translateX(2px); }}
.fs-cal-months .s {{ display: none; }}
@media (max-width: 640px) {{ .fs-cal-months .l {{ display: none; }} .fs-cal-months .s {{ display: inline; }} }}
.fs-cal-row {{ margin-bottom: 0.85rem; }}
.fs-cal-label {{ font-size: 0.9rem; margin-bottom: 0.25rem; }}
.fs-cal-track {{ position: relative; height: 2rem; border-radius: 6px; overflow: hidden;
                background: repeating-linear-gradient(135deg, #e7dcc4 0 6px, #ddd0b3 6px 12px); }}
.fs-cal-track .grid {{ position: absolute; top: 0; bottom: 0; width: 1px; background: rgba(120,100,70,0.25); }}
.fs-seg {{ position: absolute; top: 0; bottom: 0; display: flex; align-items: center; justify-content: center;
          font-size: 0.78rem; font-weight: 650; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          border-right: 1px solid rgba(255,255,255,0.6); }}
.fs-sens {{ position: relative; height: 0.32rem; margin-top: 0.2rem; }}
.fs-sens div {{ position: absolute; top: 0; bottom: 0; border-radius: 999px; background: #b4442f; }}
.fs-legend {{ display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; font-size: 0.82rem; margin-top: 0.3rem; }}
.fs-legend i {{ display: inline-block; width: 0.9rem; height: 0.9rem; border-radius: 3px; margin-right: 0.35rem;
               vertical-align: -0.15rem; }}

/* data sources */
.fs-data {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.7rem; }}
@media (max-width: 640px) {{ .fs-data {{ grid-template-columns: 1fr; }} }}
.fs-data div {{ background: #ffffff; border: 1px solid {SAND_LINE}; border-radius: 12px; padding: 0.65rem 0.85rem; }}
.fs-data b {{ display: block; font-size: 0.95rem; }}
.fs-data span {{ font-size: 0.84rem; opacity: 0.8; }}
.fs-data .nasa {{ border-left: 4px solid {GREEN}; }}

/* simple horizontal bar rows (soil types, hard-year replay) */
.fs-hb {{ display: grid; grid-template-columns: minmax(6rem, 11rem) 1fr 3.6rem; gap: 0.35rem 0.7rem;
         align-items: center; font-size: 0.88rem; }}
.fs-hb .t {{ position: relative; height: 0.9rem; border-radius: 999px; background: #e9e0cd; overflow: hidden; }}
.fs-hb .t i {{ position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px; }}
.fs-hb .v {{ text-align: right; font-weight: 650; }}
.fs-hb .lab {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.fs-mini {{ background: #ffffff; border: 1px solid {SAND_LINE}; border-radius: 12px; padding: 0.6rem 0.8rem 0.7rem; }}
.fs-mini h4 {{ font-size: 0.92rem; font-weight: 650; margin: 0 0 0.45rem; padding: 0; }}
.fs-mini .fs-hb {{ grid-template-columns: 5.5rem 1fr 4.2rem; }}
.fs-minis {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.7rem; }}
@media (max-width: 640px) {{ .fs-minis {{ grid-template-columns: 1fr; }} }}

/* slope gauge */
.fs-gauge {{ position: relative; margin: 0.9rem 0 0.6rem; }}
.fs-gauge .zones {{ display: flex; height: 0.9rem; border-radius: 999px; overflow: hidden; }}
.fs-gauge .zones div {{ height: 100%; }}
.fs-gauge .zl {{ display: flex; font-size: 0.75rem; opacity: 0.8; margin-top: 0.25rem; }}
.fs-gauge .zl div {{ text-align: center; }}
.fs-gauge .mk {{ position: absolute; top: -0.3rem; width: 0; height: 1.5rem; border-left: 4px solid;
                 border-radius: 2px; transform: translateX(-2px); }}
.fs-gauge .mk span {{ position: absolute; white-space: nowrap; font-size: 0.8rem; font-weight: 650;
                     transform: translateX(-50%); }}
.fs-gauge .mk.top span {{ bottom: 1.65rem; }}
.fs-gauge .mk.bot span {{ top: 2.6rem; }}

/* past-crops strip */
.fs-strip {{ display: grid; gap: 3px; }}
.fs-strip div {{ height: 1.6rem; border-radius: 4px; }}
.fs-strip-years {{ display: grid; gap: 3px; font-size: 0.72rem; opacity: 0.75; text-align: center; margin-top: 0.2rem; }}

/* rotation picker chips */
.fs-chips {{ display: flex; flex-wrap: wrap; gap: 0.45rem; margin: 0.2rem 0 0.4rem; }}
.fs-chip {{ background: #ffffff; border: 1px solid {SAND_LINE}; border-radius: 10px; padding: 0.35rem 0.7rem;
           font-size: 0.9rem; }}
.fs-chip b {{ color: {SOIL}; font-weight: 700; margin-right: 0.3rem; }}
.fs-chip.empty {{ opacity: 0.55; border-style: dashed; }}
</style>
"""


def inject_css():
    st.html(PAGE_CSS)


def chart_config(chart):
    """Calm, professional defaults for Altair charts."""
    return (chart.configure(background="transparent", font="sans-serif")
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor=INK, titleColor=INK, gridColor="#e6dcc7", domainColor="#c9bb9d",
                            tickColor="#c9bb9d", labelFontSize=12, titleFontSize=12, titleFontWeight="normal")
            .configure_legend(labelColor=INK, titleColor=INK, labelFontSize=12, titleFontSize=12, orient="bottom"))


def hbar_html(rows: list, vmax: float | None = None, fmt=lambda v: f"{v:.0f}") -> str:
    """Horizontal bars: rows = [(label, value, colour)]. Scaled to vmax (default: the largest value)."""
    top = vmax if vmax else max([r[1] for r in rows] + [0]) or 1.0
    cells = "".join(
        f'<div class="lab" title="{label}">{label}</div>'
        f'<div class="t"><i style="width:{max(0.0, min(1.0, value / top)) * 100:.1f}%;background:{colour}"></i></div>'
        f'<div class="v">{fmt(value)}</div>' for label, value, colour in rows)
    return f'<div class="fs-hb">{cells}</div>'

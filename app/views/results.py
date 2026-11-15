"""Step 3: results.

Four sections, each with the same rotation switcher at the top (Current, Best fit, Rotation 2, Rotation 3;
the switchers stay in sync):
    1. Featured rotation   key numbers, comparison with what the farmer grows now, things to check
    2. Rotation calendar   what is in the field through the year
    3. Replay a hard year  that year vs a typical year
    4. Where the data comes from
Then one collapsed "More detail" area (all rotations, rotations left out, climate).
"""

import html

import pandas as pd
import streamlit as st

import calendar_view
import services
import ui
from fieldshift import pipeline

PICK_KEYS = ("pick_featured", "pick_calendar", "pick_replay")
REPLAY_MEASURES = {   # replay measure -> (label, unit)
    "drought_deficit_mm": ("Water the crop missed", "mm"),
    "drainage_mm": ("Water draining away", "mm"),
    "bare_wet_days": ("Bare days in heavy rain", "days"),
    "waterlogged_days": ("Waterlogged days", "days"),
}


def _sync(src: str):
    for key in PICK_KEYS:
        st.session_state[key] = st.session_state[src]


def _switcher(key: str, labels: list):
    st.segmented_control("Rotation", labels, key=key, required=True, on_change=_sync, args=(key,),
                         label_visibility="collapsed", width="stretch")


def _priority_bars(sv_row: pd.Series) -> str:
    rows = []
    for col, label in ui.PRIORITIES.items():
        if col not in sv_row.index or pd.isna(sv_row[col]):
            continue
        v = float(min(max(sv_row[col], 0.0), 1.0))
        d = v - 0.5
        word, cls = ("Similar", "up") if abs(d) < 0.02 else (("Better", "up") if d > 0 else ("Worse", "down"))
        rows.append(f'<div class="lab">{html.escape(label)}</div>'
                    f'<div class="fs-bar"><div class="fill {cls}" style="left:{min(v, 0.5) * 100:.1f}%;'
                    f'width:{abs(d) * 100:.1f}%"></div><div class="mid"></div></div>'
                    f'<div class="verdict">{word}</div>')
    return f'<div class="fs-bars">{"".join(rows)}</div>'


def _header(label: str, name: str, cand: dict) -> None:
    cls = {"Current": "current", "Best fit": ""}.get(label, "alt")
    years = " → ".join(calendar_view.year_text(y) for y in cand["plan"])
    st.html(f'<span class="fs-badge {cls}">{html.escape(label)}</span>'
            f'<p class="fs-title" style="margin-top:.4rem">{html.escape(name)}</p>'
            f'<p class="fs-sub">{html.escape(years)}</p>')


# --- 1. featured ----------------------------------------------------------------------------------------
def _featured(r: dict, label: str, name: str, labels: list):
    cand = r["candidates"][name]
    row = r["ranking"].loc[name]
    is_current = cand.get("tier") == "current"
    ui.section_heading("Your recommended rotation", number=1,
                       sub="Switch between your current rotation, the best fit and the next two.")
    with ui.section("featured"):
        _switcher("pick_featured", labels)
        _header(label, name, cand)

        verdict = r.get("verdict") or {}
        if label == "Best fit" and verdict.get("message"):
            st.success(verdict["message"])

        rng = r["income"]["ranges"].get(name, {})
        diff = row["score_mean"] - 0.5
        fit_note = ('<div class="n">what the others are compared with</div>' if is_current else
                    f'<div class="n {"up" if diff >= 0 else "down"}">{diff * 100:+.0f} vs what you grow now</div>')
        st.html(
            '<div class="fs-stats">'
            f'<div class="fs-stat" title="50/100 = the same as now; higher is better for your priorities">'
            f'<div class="l">Overall fit for your priorities</div><div class="v">{ui.score100(row["score_mean"])}</div>'
            f'{fit_note}</div>'
            f'<div class="fs-stat"><div class="l">Return over costs</div><div class="v">{ui.money(rng.get("mid"))}'
            f'<span style="font-size:.9rem;font-weight:500">/acre/yr</span></div>'
            f'<div class="n">{ui.money(rng.get("low"))} to {ui.money(rng.get("high"))} with low/high prices; '
            f'before land rent</div></div>'
            f'<div class="fs-stat"><div class="l">Came out best</div><div class="v">{row["p_top"]:.0%}</div>'
            f'<div class="n">of runs over 40+ years of weather and prices</div></div>'
            '</div>')

        if not is_current:
            st.markdown("**Compared with what you grow now**")
            st.html(_priority_bars(r["point_scores"]["slider_values"].loc[name]))

        checks = list(r["flags"].get(name, []))
        checks += [f["sentence"] for f in r.get("risk_flags", {}).get(name, []) if f.get("level") in ("warn", "watch")]
        if checks:
            st.markdown("**Things to check**")
            st.html('<ul class="fs-list">' + "".join(f"<li>{html.escape(c)}</li>" for c in checks[:4]) + "</ul>")


# --- 2. calendar ---------------------------------------------------------------------------------------
def _calendar(r: dict, label: str, name: str, labels: list):
    ui.section_heading("Through the year", number=2, sub="What is in the field each month, cover crops included.")
    with ui.section("calendar", sand=False):
        _switcher("pick_calendar", labels)
        _header(label, name, r["candidates"][name])
        st.html(calendar_view.calendar_html(r["candidates"][name]["plan"]))


# --- 3. hard year ---------------------------------------------------------------------------------------
def _mini(title: str, unit: str, year: int, that: float, typical: float) -> str:
    """One measure: a typical year vs the chosen year (amber = worse than typical, green = better)."""
    if max(that, typical) < 0.5:
        body = f'<div class="fs-sub">None in {year} or in a typical year.</div>'
    else:
        worse = that > typical
        fmt = (lambda v: f"{v:.1f} {unit}" if unit == "days" and v < 10 else f"{v:.0f} {unit}")
        body = ui.hbar_html([("Typical year", typical, "#cbbd9c"),
                             (str(year), that, ui.AMBER if worse else ui.GREEN)], fmt=fmt)
    return f'<div class="fs-mini"><h4>{html.escape(title)}</h4>{body}</div>'


def _replay(r: dict, label: str, name: str, labels: list):
    ui.section_heading("In a hard year", number=3, sub="Replay a past drought or wet year on your field.")
    with ui.section("replay"):
        _switcher("pick_replay", labels)
        _header(label, name, r["candidates"][name])
        reasons = {}
        for why, ys in r["replay"]["suggested_years"].items():
            for y in ys:
                reasons.setdefault(int(y), why.replace(" (weather)", "").lower())
        years = sorted(reasons)
        default = 2012 if 2012 in years else years[0]
        year = st.selectbox("Year", years, index=years.index(default), key="replay_year",
                            format_func=lambda y: f"{y} - {reasons[y]}")
        rp = r["replay"] if year == r["replay"]["year"] else pipeline.replay(r["run"], year)
        t = rp["table"]
        if name not in t.index.get_level_values(0):
            st.info("No replay for this rotation.")
            return
        rows = t.loc[name]
        cards = [_mini(title, unit, year, float(rows.loc[m, "that_year"]), float(rows.loc[m, "typical"]))
                 for m, (title, unit) in REPLAY_MEASURES.items() if m in rows.index]
        st.html(f'<div class="fs-minis">{"".join(cards)}</div>')
        st.html('<p class="fs-source">Your field\'s soil and this rotation, run with that year\'s NASA POWER '
                'weather. Amber = worse than a typical year.</p>')


# --- 4. data sources --------------------------------------------------------------------------------------
def _data_sources(r: dict):
    notes = " ".join((r.get("validation") or {}).get("notes", []))
    smap = "Coming soon" if "SMAP not available" in notes else "Checks the water model"
    hls = "Coming soon" if "HLS NDVI not available" in notes else "Checks the crop calendar"
    cards = [
        ("nasa", "NASA POWER - daily weather", "Rain, temperature and sunshine for your area since 1981. "
                                                "Drives every water and climate result."),
        ("nasa", "NASA SRTM - elevation", "30 m elevation map. Checks your field's slope."),
        ("nasa", "NASA SMAP - soil moisture from space", f"Satellite soil moisture since 2015. {smap}."),
        ("nasa", "NASA HLS - Landsat and Sentinel-2", f"How green your field is through the year. {hls}."),
        ("", "USDA soil survey and crop maps", "Your field's soils, drainage, slope and past crops."),
        ("", "Iowa State University and USDA", "Crop budgets, yields, prices and rotation research."),
    ]
    ui.section_heading("Where the data comes from", number=4, sub="NASA Earth observations, with USDA and Iowa State.")
    with ui.section("data", sand=False):
        st.html('<div class="fs-data">' + "".join(
                    f'<div class="{cls}"><b>{html.escape(t)}</b><span>{html.escape(d)}</span></div>'
                    for cls, t, d in cards) + "</div>"
                '<p class="fs-source">Checked against a weather station and soil-moisture probes near Ames '
                '(Iowa Environmental Mesonet).</p>')


# --- more detail ----------------------------------------------------------------------------------------
def _details(r: dict, options: dict):
    rk, inc = r["ranking"], r["income"]["ranges"]
    tag = {name: label for label, name in options.items()}
    order = [options["Current"]] + ui.risk_order(r)
    with st.expander("More detail: all rotations, rotations left out, climate"):
        st.markdown("**All rotations compared** (lowest risk first)")
        table = pd.DataFrame({
            "Rotation": order,
            "Shown as": [tag.get(n, "") for n in order],
            "Overall fit": [ui.score100(rk.loc[n, "score_mean"]) for n in order],
            "Return $/acre/yr": [inc.get(n, {}).get("mid") for n in order],
        })
        st.dataframe(table.style.format({"Return $/acre/yr": "{:,.0f}"}, na_rep="n/a"),
                     width="stretch", hide_index=True)
        if r["removed"]:
            st.markdown("**Left out for your farm**")
            st.markdown("\n".join(f"- {x['name']}: {x['reason']}" for x in r["removed"]))
        st.markdown("**Climate at your field** (NASA POWER, recent years)")
        rows = [{"Indicator": s["label"], "Recent average": f"{s['recent_mean']:.0f} {s['unit']}",
                 "Range": f"{s['recent_min']:.0f} to {s['recent_max']:.0f}"} for s in r["snapshot"].values()]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render():
    r = st.session_state.get("result")
    if r is None:
        st.session_state.step = "questions"
        st.rerun()
    options = st.session_state.get("options") or ui.four_options(r)
    labels = list(options)
    for key in PICK_KEYS:                                       # e.g. after a new analysis
        if st.session_state.get(key) not in labels:
            st.session_state[key] = "Best fit" if "Best fit" in labels else labels[0]
    label = st.session_state.pick_featured
    name = options[label]

    with st.container(horizontal=True, gap="small"):
        st.button("Edit answers", icon=":material/arrow_back:", type="tertiary", on_click=ui.go("questions"))
        st.button("Change field", icon=":material/map:", type="tertiary", on_click=ui.go("field"))
    lat, lon = st.session_state.lat, st.session_state.lon
    ui.page_header("Step 3 of 3", "Your results",
                   f"Rotations for your field ({services.location_text(lat, lon)}), compared with what you "
                   "grow now. Work through the four sections in order.")

    _featured(r, label, name, labels)
    _calendar(r, label, name, labels)
    _replay(r, label, name, labels)
    _data_sources(r)
    _details(r, options)

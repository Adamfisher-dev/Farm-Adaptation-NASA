"""Step 3: results.

Five numbered sections; the first three have the same rotation switcher at the top (Current, Best fit,
Rotation 2, Rotation 3; the switchers stay in sync):
    1. Featured rotation   key numbers, why this rotation, benefits and risks (content/rotations.yaml),
                           comparison with what the farmer grows now, a one-line climate check
    2. Rotation calendar   what is in the field through the year
    3. Replay a hard year  that year vs a typical year
    4. Trust               the water model checked against NASA SMAP, NASA POWER and ground sensors
    5. Where the data comes from
A downloadable one-page PDF report (report.py) sits at the top.
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


def _climate_line(r: dict, name: str) -> str:
    """One line from the what-if scenarios (warmer / drier): does this rotation stay the top choice?"""
    scores = (r.get("what_if") or {}).get("scores")
    if scores is None or name not in scores.index:
        return ""
    wins, n = int(sum(scores[c].idxmax() == name for c in scores.columns)), len(scores.columns)
    where = f"all {n}" if wins == n else f"{wins} of {n}"
    return (f"Climate check: still the top choice in {where} climates we tested, from today's to 2 °C warmer "
            "with 20% less summer rain.")


def _about_rotation(r: dict, name: str) -> str:
    """Why this rotation, its benefits and its risks: the hand-written text in content/rotations.yaml
    (base rotation + cover crop), plus the field-specific checks from the analysis."""
    from fieldshift.model import cards
    try:
        t = cards._texts(r, name)
    except Exception:                                          # noqa: BLE001 - the numbers still show
        return ""
    checks = list(r["flags"].get(name, []))
    checks += [f["sentence"] for f in r.get("risk_flags", {}).get(name, []) if f.get("level") in ("warn", "watch")]
    risks = t["risks"] + [c for c in checks if c not in t["risks"]]

    def items(xs, limit):
        return "".join(f"<li>{html.escape(x)}</li>" for x in xs[:limit])

    why = " ".join(t["why"])
    out = f'<p class="fs-why">{html.escape(why)}</p>' if why else ""
    out += ('<div class="fs-procon">'
            f'<div class="pro"><h4>Benefits</h4><ul>{items(t["benefits"], 4)}</ul></div>'
            f'<div class="con"><h4>Risks and things to check</h4><ul>{items(risks, 4)}</ul></div></div>')
    if t["gaps"]:
        out += ('<details class="fs-gaps"><summary>Good to know</summary><ul>'
                f'{items(t["gaps"], 4)}</ul></details>')
    return out


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

        if label == "Best fit":
            line = _climate_line(r, name)
            if line:
                st.html(f'<p class="fs-climate">{html.escape(line)}</p>')

        st.html(_about_rotation(r, name))

        if not is_current:
            st.markdown("**Compared with what you grow now**")
            st.html(_priority_bars(r["point_scores"]["slider_values"].loc[name]))


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


# --- 4. can you trust it -----------------------------------------------------------------------------------
def _strength(r: float) -> str:
    return "Strong" if r >= 0.7 else "Good" if r >= 0.5 else "Fair" if r >= 0.3 else "Weak"


def _trust_chart(series: pd.DataFrame, obs_label: str):
    import altair as alt
    df = series.rename(columns={"m": "Our water model", "o": obs_label}).reset_index()
    df = df.rename(columns={df.columns[0]: "month"})
    df["year"] = df["month"].dt.year
    long = df.melt(["month", "year"], var_name="Series", value_name="Departure")
    domain = ["Our water model", obs_label]
    legend = alt.Legend(title=None, orient="bottom", symbolType="stroke", symbolStrokeWidth=2.5, symbolSize=300)
    base = alt.Chart(long).encode(
        x=alt.X("month:T", title=None, axis=alt.Axis(format="%Y", tickCount="year", grid=False)),
        y=alt.Y("Departure:Q", title="Wetter than normal  ↑    ↓  drier",
                axis=alt.Axis(tickCount=5, labels=False, ticks=False)),
        color=alt.Color("Series:N", scale=alt.Scale(domain=domain, range=["#2e7d3c", "#2b6cb0"]), legend=legend),
        strokeDash=alt.StrokeDash("Series:N", scale=alt.Scale(domain=domain, range=[[1, 0], [5, 3]]), legend=legend),
        detail="year:N",
        tooltip=[alt.Tooltip("month:T", title="Month", format="%B %Y"), alt.Tooltip("Series:N"),
                 alt.Tooltip("Departure:Q", title="Departure from normal", format="+.2f")])
    lines = base.mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=18, filled=True))
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#c9bb9d").encode(y="y:Q")
    st.altair_chart(ui.chart_config((zero + lines).properties(height=260)), width="stretch")


def _trust(r: dict):
    ui.section_heading("Can you trust these results?", number=4,
                       sub="We checked our model against NASA satellites and ground sensors.")
    v = r.get("validation") or {}
    with ui.section("trust", sand=False):
        comps = v.get("comparisons") or {}
        if not v.get("available") or not comps:
            st.info("The checks against satellite and ground data could not run for this field.")
            return
        cards = []
        smap = comps.get("sm_surface_l3") or comps.get("sm_rootzone_l4")
        power = comps.get("power_gwetroot")
        probe = comps.get("isusm_60cm") or comps.get("isusm_30cm")

        def card(title, comp, note):
            rr = comp["monthly_anomaly"]["r"]
            if rr is None or pd.isna(rr):
                return
            cards.append(f'<div class="fs-stat"><div class="l">{html.escape(title)}</div>'
                         f'<div class="v">{rr:.2f} <span style="font-size:.95rem;font-weight:600">'
                         f'{_strength(rr)}</span></div><div class="n">{html.escape(note)}</div></div>')
        if smap:
            sp = v.get("smap_point") or {}
            where = (f"9 km satellite cell, {sp['distance_km']:.0f} km away" if sp.get("distance_km")
                     else "9 km satellite cell over this area")
            card("Soil moisture vs NASA SMAP satellite", smap, f"{where}, 2015-2025")
        if power:
            card("Soil wetness vs NASA POWER", power, "NASA's own root-zone model, 2013-2025")
        if probe:
            card("Soil moisture vs Iowa State probe", probe, "Buried sensor near Ames, 2014-2025")
        w = v.get("weather") or {}
        weather_card = bool(w.get("tmax")) and len(cards) < 3
        if weather_card:
            cards.append(f'<div class="fs-stat"><div class="l">NASA weather vs Ames station</div>'
                         f'<div class="v">{w["tmax"]["r"]:.2f} <span style="font-size:.95rem;font-weight:600">'
                         f'{_strength(w["tmax"]["r"])}</span></div><div class="n">Daily highs; monthly rain '
                         f'{w["rain_monthly"]["r"]:.2f}</div></div>')
        st.html(f'<div class="fs-stats">{"".join(cards[:3])}</div>'
                '<p class="fs-source" style="margin-top:.4rem">Match = how closely the ups and downs agree, month '
                'by month in April-October (1.00 = perfect, 0 = none).</p>')
        chart = smap or power
        if chart is not None and isinstance(chart.get("monthly_series"), pd.DataFrame) and len(chart["monthly_series"]):
            label = "NASA SMAP satellite" if chart is smap else "NASA POWER"
            st.markdown(f"**Wetter or drier than normal: our model vs {label}**")
            _trust_chart(chart["monthly_series"], label)
        if w.get("tmax") and not weather_card:
            st.html(f'<p class="fs-source">NASA POWER weather against the Ames ground station: daily highs '
                    f'match {w["tmax"]["r"]:.2f}, monthly rain {w["rain_monthly"]["r"]:.2f}.</p>')


# --- 5. data sources --------------------------------------------------------------------------------------
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
    ui.section_heading("Where the data comes from", number=5, sub="NASA Earth observations, with USDA and Iowa State.")
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


def _report_button(r: dict, options: dict):
    """One-page PDF for the farmer to keep or take to an agronomist (built once per analysis)."""
    import report
    ss = st.session_state
    lat, lon = ss.lat, ss.lon
    if ss.get("_report_for") != id(r):
        try:
            ss._report_pdf = report.build_pdf(r, options, lat, lon)
        except Exception as err:                                   # noqa: BLE001 - the page still works
            ss._report_pdf = None
            ss._report_error = str(err)
        ss._report_for = id(r)
    if ss.get("_report_pdf"):
        st.download_button("Download report (PDF)", ss._report_pdf, file_name="orbital-acre-field-report.pdf",
                           mime="application/pdf", icon=":material/download:", type="tertiary",
                           on_click="ignore")


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
        _report_button(r, options)
    lat, lon = st.session_state.lat, st.session_state.lon
    ui.page_header("Step 3 of 3", "Your results",
                   f"Rotations for your field ({services.location_text(lat, lon)}), compared with what you "
                   "grow now. Work through the sections in order.")

    _featured(r, label, name, labels)
    _calendar(r, label, name, labels)
    _replay(r, label, name, labels)
    _trust(r)
    _data_sources(r)
    _details(r, options)

"""Step 3: results. Featured rotation (best fit first), its calendar, then more detail.

The featured card and the calendar each have a rotation switcher ordered from lowest to highest
risk for this farmer; the two switchers stay in sync.
"""

import html

import pandas as pd
import streamlit as st

import calendar_view
import services
import ui
from fieldshift import pipeline


def _sync(src: str, dst: str):
    st.session_state[dst] = st.session_state[src]


def _risk_rank(r: dict, order: list) -> dict:
    """Risk rank of each alternative (1 = lowest risk); the current rotation has none."""
    alts = [n for n in order if r["candidates"][n].get("tier") != "current"]
    return {name: i + 1 for i, name in enumerate(alts)}


def _label(r: dict, order: list, best: str):
    rank = _risk_rank(r, order)

    def fmt(name: str) -> str:
        short = ui.short_name(r["candidates"][name])
        text = f"{rank[name]}. {short}" if name in rank else f"Now: {short}"
        return text + ("  ★" if name == best else "")
    return fmt


def _priority_bars(sv_row: pd.Series) -> str:
    rows = []
    for col, label in ui.PRIORITIES.items():
        if col not in sv_row.index or pd.isna(sv_row[col]):
            continue
        v = float(min(max(sv_row[col], 0.0), 1.0))
        d = v - 0.5
        if abs(d) < 0.02:
            word, cls = "Similar", "up"
        elif d > 0:
            word, cls = "Better", "up"
        else:
            word, cls = "Worse", "down"
        rows.append(f'<div class="lab">{html.escape(label)}</div>'
                    f'<div class="fs-bar"><div class="fill {cls}" style="left:{min(v, 0.5) * 100:.1f}%;'
                    f'width:{abs(d) * 100:.1f}%"></div><div class="mid"></div></div>'
                    f'<div class="verdict">{word}</div>')
    return f'<div class="fs-bars">{"".join(rows)}</div>'


def _featured(r: dict, sel: str, best: str, order: list, fmt):
    cand = r["candidates"][sel]
    row = r["ranking"].loc[sel]
    is_current = cand.get("tier") == "current"
    with st.container(border=True, key="featured"):
        if sel == best:
            badge = '<span class="fs-badge">Best fit for you</span>'
        elif is_current:
            badge = '<span class="fs-badge current">Your current rotation</span>'
        else:
            rank = _risk_rank(r, order)
            badge = f'<span class="fs-badge alt">Option {rank[sel]} of {len(rank)}, ordered by risk</span>'
        st.html(badge)
        st.subheader(sel)
        st.caption(" → ".join(f"Year {i + 1}: {calendar_view.year_text(y)}" for i, y in enumerate(cand["plan"])))

        verdict = r.get("verdict") or {}
        if sel == best and verdict.get("message"):
            (st.success if verdict.get("kind") == "options_better" else st.info)(verdict["message"])

        rng = r["income"]["ranges"].get(sel, {})
        diff = row["score_mean"] - 0.5
        fit_note = ('<div class="n">what the others are compared with</div>' if is_current else
                    f'<div class="n {"up" if diff >= 0 else "down"}">{diff:+.2f} vs what you grow now</div>')
        stats = [
            ("Overall fit", f"{row['score_mean']:.2f}", fit_note,
             "0.5 = same as now; higher is better for your priorities"),
            ("In a bad case", f"{row['score_p05']:.2f}", "score in the worst 5% of runs", ""),
            ("Chance it is best", f"{row['p_top']:.0%}", "of the runs over past weather and prices", ""),
            ("Return to land & management", f"{ui.money(rng.get('mid'))}/acre",
             f"{ui.money(rng.get('low'))} to {ui.money(rng.get('high'))} by price; "
             f"after land rent: {ui.money(r['income'].get('all_costs_usd_per_acre', {}).get(sel))}",
             r["income"].get("land_rent_note", "")),
        ]
        cells = "".join(
            f'<div class="fs-stat" title="{html.escape(tip)}"><div class="l">{label}</div><div class="v">{value}</div>'
            + (note if note.startswith("<div") else f'<div class="n">{note}</div>') + "</div>"
            for label, value, note, tip in stats)
        st.html(f'<div class="fs-stats">{cells}</div>')
        st.caption("Scores: 0.5 = the same as what you grow now, higher = better for your priorities. "
                   f"Each rotation was run {services.N_BOOT} times over past weather years, prices and small changes "
                   "in your priorities.")

        if is_current:
            st.markdown("This is what you grow now: every other rotation is compared with it.")
        else:
            st.markdown("**Compared with what you grow now**")
            st.html(_priority_bars(r["point_scores"]["slider_values"].loc[sel]))

        risks = r.get("risk_flags", {}).get(sel, [])
        if risks:                                   # field-specific weather risks (model/risks.py)
            st.markdown("**Weather risks on this field**")
            icon = {"warn": "⚠️", "watch": "👁️", "info": "ℹ️"}
            st.markdown("\n".join(f"- {icon.get(f['level'], '')} {f['sentence']}" for f in risks))
            if r.get("risk_note"):
                st.caption(r["risk_note"])

        flags = r["flags"].get(sel, [])
        if flags:
            st.markdown("**Before you switch**")
            st.markdown("\n".join(f"- {f}" for f in flags))

        st.divider()
        st.pills("See another rotation (lowest risk first)", order, format_func=fmt, key="pick_featured",
                 required=True, on_change=_sync, args=("pick_featured", "pick_calendar"))


def _calendar(r: dict, sel: str, order: list, fmt):
    with st.container(border=True, key="calendar"):
        st.subheader("Rotation calendar")
        st.caption("What is in the field through the year, for each year of the rotation.")
        st.pills("Rotations, lowest risk first", order, format_func=fmt, key="pick_calendar",
                 required=True, on_change=_sync, args=("pick_calendar", "pick_featured"))
        st.html(calendar_view.calendar_html(r["candidates"][sel]["plan"]))
        st.caption("Planting and harvest dates are typical for central Iowa. Bare soil is when erosion and "
                   "nitrate loss are most likely. Hover over a bar for its dates. "
                   "★ = best fit. \"Now\" is what you grow today; the others are numbered from lowest to highest "
                   "risk, by each rotation's score in a bad case (the worst 5% of runs over past weather, "
                   "prices and your priorities).")


def _details(r: dict, sel: str, order: list):
    st.subheader("More detail")
    rk, inc = r["ranking"], r["income"]["usd_per_acre"]
    with st.expander("All rotations compared"):
        table = pd.DataFrame({
            "Rotation": order,
            "Type": [ui.TIER.get(r["candidates"][n].get("tier"), "") for n in order],
            "Overall fit": [rk.loc[n, "score_mean"] for n in order],
            "Bad case": [rk.loc[n, "score_p05"] for n in order],
            "Chance best": [rk.loc[n, "p_top"] for n in order],
            "Return $/acre/yr (before rent)": [inc.get(n) for n in order],
            "After rent": [r["income"].get("all_costs_usd_per_acre", {}).get(n) for n in order],
        }, index=pd.Index([str(_risk_rank(r, order).get(n, "now")) for n in order], name="Risk rank"))
        st.dataframe(table.style.format({"Overall fit": "{:.2f}", "Bad case": "{:.2f}", "Chance best": "{:.0%}",
                                         "Return $/acre/yr (before rent)": "{:,.0f}", "After rent": "{:,.0f}"},
                                        na_rep="n/a"), width="stretch")
        if r["income"].get("basis"):
            st.caption(f"Return: {r['income']['basis']}. {r['income'].get('land_rent_note', '')}")
        rob = (r.get("robustness") or {}).get("note")
        if rob:
            st.caption(rob)
    if r["removed"]:
        with st.expander(f"Rotations left out for your farm ({len(r['removed'])})"):
            for x in r["removed"]:
                st.markdown(f"- **{x['name']}**: {x['reason']}")
    with st.expander("Replay a hard year"):
        rp0 = r["replay"]
        years = sorted({y for ys in rp0["suggested_years"].values() for y in ys})
        year = st.selectbox("Year", years, index=years.index(rp0["year"]) if rp0["year"] in years else 0,
                            key="replay_year")
        rp = rp0 if year == rp0["year"] else pipeline.replay(r["run"], year)
        st.write(rp["sentence"])
        t = rp["table"].reset_index()
        first = t.columns[0]
        show = t[t[first] == sel].drop(columns=[first])
        st.caption(f"For: {sel}")
        st.dataframe(show, width="stretch", hide_index=True)
    with st.expander("Climate at your field (NASA POWER)"):
        rows = [{"Indicator": s["label"], "Unit": s["unit"],
                 f"Mean {s['recent_years'][0]}-{s['recent_years'][1]}": round(s["recent_mean"], 1),
                 "Range": f"{s['recent_min']:.0f} to {s['recent_max']:.0f}",
                 "Trend per decade": round(s.get("trend_per_decade") or 0, 2)}
                for s in r["snapshot"].values()]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        tr = r.get("trends")
        if tr is not None and len(tr):
            st.markdown("\n".join(f"- {s}" for s in tr["sentence"]))
    with st.expander("Evidence and data sources"):
        val = r.get("validation") or {}
        st.markdown("**Checking the model against measurements**")
        st.markdown("\n".join(f"- {s}" for s in val.get("sentences", [])) or "No measurements for this field yet.")
        st.markdown("**Data used for this field**")
        src = [f"- **{k.replace('_', ' ').capitalize()}**: {v}" for k, v in r["field"].get("sources", {}).items()]
        src.append("- **Weather**: NASA POWER daily data, 1981-2025, for the ~50 km cell containing the field")
        st.markdown("\n".join(src))
        notes = val.get("notes", [])
        if notes:
            st.caption("Notes: " + " ".join(notes))


def render():
    r = st.session_state.get("result")
    if r is None:
        st.session_state.step = "questions"
        st.rerun()
    order = st.session_state.risk_order
    best = r["ranking"].index[0]
    fmt = _label(r, order, best)
    for key in ("pick_featured", "pick_calendar"):             # e.g. after a new analysis
        if st.session_state.get(key) not in order:
            st.session_state[key] = best
    sel = st.session_state.pick_featured

    with st.container(horizontal=True, gap="small"):
        st.button("Edit answers", icon=":material/arrow_back:", type="tertiary", on_click=ui.go("questions"))
        st.button("Change field", icon=":material/map:", type="tertiary", on_click=ui.go("field"))
    st.header("Your results")
    lat, lon = st.session_state.lat, st.session_state.lon
    st.html(f'<p class="fs-lead">Field at {lat:.4f}, {lon:.4f} - {len(order)} rotations compared with what '
            "you grow now, over 40+ years of NASA weather.</p>")

    _featured(r, sel, best, order, fmt)
    _calendar(r, sel, order, fmt)
    _details(r, sel, order)

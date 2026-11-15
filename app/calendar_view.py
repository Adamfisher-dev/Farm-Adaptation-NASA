"""Rotation calendar: one row per rotation year, months across, what is in the field each day.

Built from the same day-by-day crop table the water model uses (fieldshift.model.crops), so the
calendar shows exactly what was simulated: cash crops, cover and under-sown crops (striped), bare
soil (grey) and the crop's drought-sensitive stage (red line under the bar).
"""

import html

import pandas as pd

import services
import ui

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _runs(day: pd.DataFrame):
    """Consecutive blocks of the same crop and role: [(start, end, crop, role)]."""
    key = day["crop"] + "|" + day["role"]
    block = (key != key.shift()).cumsum()
    out = []
    for _, d in day.groupby(block):
        out.append((d.index[0], d.index[-1], d["crop"].iloc[0], d["role"].iloc[0]))
    return out


def _seg_label(crop: str, role: str) -> str:
    if role == "bare":
        return "Bare soil"
    name = ui.crop_label(crop)
    if role == "cover":
        return {"cereal_rye": "Rye cover", "alfalfa": "Alfalfa (new)"}.get(crop, name)
    return name


def year_text(year_plan: list) -> str:
    cash, _, under = year_plan[0].partition("+")
    text = ui.crop_label(cash)
    if under:
        text += f", {ui.crop_label(under).lower()} sown with it"
    if len(year_plan) > 1:
        text += f", then {ui.crop_label(year_plan[1]).lower()} cover over winter"
    return text


def calendar_html(plan: list) -> str:
    """HTML calendar for one rotation (crops.py plan format)."""
    days = services.crop_days(tuple(tuple(y) for y in plan))
    rows = []
    for i, year_plan in enumerate(plan):
        year = services.CALENDAR_START_YEAR + i
        day = days[days.index.year == year]
        n = len(day)
        start_doy = lambda ts: (ts.dayofyear - 1) / n * 100                     # noqa: E731
        segs = []
        for s, e, crop, role in _runs(day):
            left, width = start_doy(s), (e - s).days / n * 100 + 100 / n
            label = _seg_label(crop, role)
            tip = html.escape(f"{label}: {s:%d %b} - {e:%d %b}")
            if role == "bare":
                segs.append(f'<div class="fs-seg" title="{tip}" style="left:{left:.2f}%;width:{width:.2f}%;'
                            f'border-right:none"></div>')
                continue
            _, colour, text = ui.CROP.get(crop, (label, "#888888", "#ffffff"))
            fill = (f"repeating-linear-gradient(135deg,{colour} 0 7px,{colour}cc 7px 14px)"
                    if role == "cover" else colour)
            shown = html.escape(label) if width >= 11 else ""
            segs.append(f'<div class="fs-seg" title="{tip}" style="left:{left:.2f}%;width:{width:.2f}%;'
                        f'background:{fill};color:{text}">{shown}</div>')
        grid = "".join(f'<div class="grid" style="left:{(pd.Timestamp(year, m, 1).dayofyear - 1) / n * 100:.2f}%"></div>'
                       for m in range(2, 13))
        sens = day["sensitive"].astype(bool)
        marks = []
        if sens.any():
            for s, e, flag, _ in _runs(pd.DataFrame({"crop": sens.astype(str), "role": ""}, index=day.index)):
                if flag == "True":
                    marks.append(f'<div title="{html.escape(f"Drought-sensitive stage: {s:%d %b} - {e:%d %b}")}" '
                                 f'style="left:{start_doy(s):.2f}%;width:{(e - s).days / n * 100 + 100 / n:.2f}%"></div>')
        rows.append(
            f'<div class="fs-cal-row"><div class="fs-cal-label"><b>Year {i + 1}</b> &middot; '
            f'{html.escape(year_text(year_plan))}</div>'
            f'<div class="fs-cal-track">{grid}{"".join(segs)}</div>'
            f'<div class="fs-sens">{"".join(marks)}</div></div>')

    first = days[days.index.year == services.CALENDAR_START_YEAR]
    n0 = len(first)
    months = "".join(f'<span style="left:{(pd.Timestamp(services.CALENDAR_START_YEAR, m + 1, 1).dayofyear - 1) / n0 * 100:.2f}%">'
                     f'<span class="l">{name}</span><span class="s">{name[0]}</span></span>'
                     for m, name in enumerate(MONTHS))
    in_plan = {c for y in plan for e in y for c in e.split("+")}
    legend = []
    for crop, (label, colour, _) in ui.CROP.items():
        if crop in in_plan:
            striped = crop in ("cereal_rye", "red_clover")
            fill = f"repeating-linear-gradient(135deg,{colour} 0 4px,{colour}cc 4px 8px)" if striped else colour
            legend.append(f'<span><i style="background:{fill}"></i>{html.escape(label)}'
                          f'{" (cover / under-sown)" if striped else ""}</span>')
    legend.append('<span><i style="background:repeating-linear-gradient(135deg,rgba(128,128,128,.25) 0 4px,'
                  'rgba(128,128,128,.45) 4px 8px)"></i>Bare soil</span>')
    legend.append('<span><i style="background:#d0442f;height:.35rem;vertical-align:.15rem"></i>'
                  'Drought-sensitive stage</span>')
    return (f'<div class="fs-cal"><div class="fs-cal-months">{months}</div>{"".join(rows)}'
            f'<div class="fs-legend">{"".join(legend)}</div></div>')

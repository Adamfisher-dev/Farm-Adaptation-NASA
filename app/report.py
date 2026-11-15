"""One-page PDF field report: the field, the recommendation, the four options, the climate stress test
and the checks against NASA data - for the farmer to keep or take to an agronomist or lender.

Drawn with matplotlib (already a dependency), A4 portrait. No Streamlit calls except the cached
field lookup in services.
"""

from __future__ import annotations

import io
import textwrap
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

import banner  # noqa: E402
import calendar_view  # noqa: E402
import services  # noqa: E402
import ui  # noqa: E402

TEAM = "A&L Orbital"
EVENT = "NASA Space Apps Challenge 2026 - Field Shift: Adapting Farms with NASA Data"
W_IN, H_IN = 8.27, 11.69                 # A4
M = 0.55 / W_IN                          # side margin (figure fraction)
INK, MUTED, LINE = ui.INK, "#5d6657", "#e2d6bd"


class _Page:
    """Writes top-down on one figure; y is the figure-fraction cursor."""

    def __init__(self):
        self.fig = plt.figure(figsize=(W_IN, H_IN))
        self.y = 1.0

    def text(self, s, size=9.5, weight="normal", color=INK, x=M, wrap=None, gap=0.0045, **kw):
        if wrap is None:                 # characters per line from the space left and the font size
            wrap = int((1 - M - x) * W_IN * 72 / (size * 0.56))
        lines = textwrap.wrap(s, wrap) or [""]
        step = size / 72 / H_IN * 1.38
        for ln in lines:
            self.fig.text(x, self.y, ln, fontsize=size, fontweight=weight, color=color, va="top", **kw)
            self.y -= step
        self.y -= gap

    def heading(self, s):
        self.y -= 0.009
        self.fig.text(M, self.y, s, fontsize=12.5, fontweight="bold", color=ui.GREEN, va="top")
        self.y -= 0.024

    def rule(self):
        self.fig.add_artist(plt.Line2D([M, 1 - M], [self.y, self.y], color=LINE, lw=0.8))
        self.y -= 0.008


def _strength(r: float) -> str:
    return "strong" if r >= 0.7 else "good" if r >= 0.5 else "fair" if r >= 0.3 else "weak"


def build_pdf(r: dict, options: dict, lat: float, lon: float, fmt: str = "pdf") -> bytes:
    """The report as PDF bytes (fmt="png" gives a preview image)."""
    p = _Page()
    fig = p.fig

    # --- header band -------------------------------------------------------------------------------
    band = 1.15 / H_IN
    fig.add_artist(Rectangle((0, 1 - band), 1, band, transform=fig.transFigure, color=ui.GREEN, zorder=0))
    try:
        logo = mpimg.imread(str(banner.logo_path()))
        h = 0.78 / H_IN
        w = h * logo.shape[1] / logo.shape[0] * H_IN / W_IN
        ax = fig.add_axes([M, 1 - band + (band - h) / 2, w, h])
        ax.imshow(logo)
        ax.axis("off")
        tx = M + w + 0.02
    except Exception:                                          # noqa: BLE001 - report works without a logo
        tx = M
    fig.text(tx, 1 - band * 0.36, f"{banner.NAME} - field report", fontsize=19, fontweight="bold", color="white",
             va="center")
    fig.text(tx, 1 - band * 0.64, f"{services.location_text(lat, lon)}, Story County, Iowa  ·  "
             f"{abs(lat):.4f}° N, {abs(lon):.4f}° W", fontsize=9.5, color="white", va="center")
    fig.text(tx, 1 - band * 0.83, f"Made {date.today():%d %B %Y}", fontsize=8, color="white", va="center",
             alpha=0.85)
    p.y = 1 - band - 0.022

    # --- the field ---------------------------------------------------------------------------------
    p.heading("Your field")
    try:
        fld = services.field_lookup(lat, lon)
        soil = fld["soil"]
        hist = fld.get("crop_history") or {}
        recent = ", ".join(ui.crop_label(hist[y]).lower() if hist[y] in ui.CROP else hist[y].replace("_", " ")
                           for y in sorted(hist, key=int)[-4:])
        ha = services.field_area_ha(lat, lon)
        p.text(f"About {ha:.0f} ha ({ha * 2.471:.0f} acres).  Soil: {soil['drainage_class'].lower()}, holds "
               f"{fld['awc_mm_per_m']:.0f} mm of water per metre; tile drainage "
               f"{'likely' if fld['tile_drained'] else 'unlikely'}.  Average slope about "
               f"{fld['slope']['slope_pct_mean']:.1f}%." + (f"  Recent crops: {recent}." if recent else ""))
    except Exception:                                          # noqa: BLE001
        p.text("Field details could not be loaded for this report.", color=MUTED)

    # --- recommendation ----------------------------------------------------------------------------
    rk, inc = r["ranking"], r["income"]["ranges"]
    current = options["Current"]
    top_label = "Best fit" if "Best fit" in options else "Current"
    best = options[top_label]
    cand = r["candidates"][best]
    p.heading("Recommended rotation" if top_label == "Best fit" else "Your current rotation comes out on top")
    box_top = p.y + 0.004
    p.y -= 0.008
    p.text(best, size=12.5, weight="bold", x=M + 0.02)
    p.text(" → ".join(calendar_view.year_text(y) for y in cand["plan"]), size=9, color=MUTED, x=M + 0.02)
    row = rk.loc[best]
    rng = inc.get(best, {})
    diff = (row["score_mean"] - rk.loc[current, "score_mean"]) * 100
    stats = [("Overall fit for your priorities", ui.score100(row["score_mean"]),
              "" if best == current else f"{diff:+.0f} vs what you grow now"),
             ("Return over costs", f"{ui.money(rng.get('mid'))}/acre/yr",
              f"{ui.money(rng.get('low'))} to {ui.money(rng.get('high'))}; before land rent"),
             ("Came out best", f"{row['p_top']:.0%}", "of runs over 40+ years of weather")]
    p.y -= 0.006
    col_w = (1 - 2 * M - 0.04) / 3
    for i, (lab, val, note) in enumerate(stats):
        x = M + 0.02 + i * col_w
        fig.text(x, p.y, lab, fontsize=8.5, color=MUTED, va="top")
        fig.text(x, p.y - 0.018, val, fontsize=15, fontweight="bold", color=INK, va="top")
        fig.text(x, p.y - 0.043, note, fontsize=7.8, color=MUTED, va="top")
    p.y -= 0.064
    if r.get("verdict", {}).get("message") and top_label == "Best fit":
        p.text(r["verdict"]["message"], size=8.8, color=ui.GREEN_DARK, x=M + 0.02)
    fig.add_artist(FancyBboxPatch((M, p.y), 1 - 2 * M, box_top - p.y, boxstyle="round,pad=0,rounding_size=0.008",
                                  transform=fig.transFigure, facecolor=ui.SAND, edgecolor=LINE, lw=0.8, zorder=-1))
    p.y -= 0.012

    checks = list(r["flags"].get(best, []))
    checks += [f["sentence"] for f in r.get("risk_flags", {}).get(best, []) if f.get("level") in ("warn", "watch")]
    if checks:
        p.text("Things to check", size=10, weight="bold")
        for c in checks[:3]:
            p.text("•  " + c, size=8.8, gap=0.001)
        p.y -= 0.004

    # --- the four options --------------------------------------------------------------------------
    p.heading("Your four options")
    cols = [(M, "Option"), (M + 0.12, "Rotation"), (0.57, "Fit"), (0.67, "Return/acre/yr"), (0.81, "Came out best")]
    for x, h in cols:
        fig.text(x, p.y, h, fontsize=8.3, fontweight="bold", color=ui.SOIL, va="top")
    p.y -= 0.02
    p.rule()
    for label, name in options.items():
        rr = rk.loc[name]
        cells = [label, ui.short_name(r["candidates"][name]), ui.score100(rr["score_mean"]),
                 ui.money(inc.get(name, {}).get("mid")), f"{rr['p_top']:.0%}"]
        for (x, _), c in zip(cols, cells):
            fig.text(x, p.y, c, fontsize=9, color=INK, va="top",
                     fontweight="bold" if label == top_label and x == M else "normal")
        p.y -= 0.022
        p.rule()

    # --- climate stress test -----------------------------------------------------------------------
    wi = r.get("what_if") or {}
    if "scores" in wi:
        p.heading("In a changing climate")
        tag = {n: lbl for lbl, n in options.items()}
        other_label = next(lbl for lbl in options if lbl != "Current")
        tops = [tag.get(wi["scores"][c].idxmax(), "another rotation") for c in wi["scores"].columns]
        wins, n = sum(t == other_label for t in tops), len(tops)
        raw = wi["raw"]
        base, worst = list(wi["scores"].columns)[0], list(wi["scores"].columns)[-1]
        d0, d1 = raw.loc[(base, current), "drought_risk"], raw.loc[(worst, current), "drought_risk"]
        p.text(f"{other_label} is the top choice in {wins} of {n} climates tested (today's, 1-2 °C warmer, "
               f"10-20% less summer rain, and both together). If summers get 2 °C warmer and 20% drier, the water "
               f"your current rotation misses in a dry year grows from {d0:.0f} to {d1:.0f} mm "
               f"({(d1 - d0) / d0:+.0%}). A stress test on 1984-2025 NASA POWER weather, not a forecast.")

    # --- checks against NASA data ------------------------------------------------------------------
    v = r.get("validation") or {}
    comps = v.get("comparisons") or {}
    lines = []
    for key, what in (("sm_surface_l3", "NASA SMAP satellite soil moisture"),
                      ("power_gwetroot", "NASA POWER root-zone wetness"),
                      ("isusm_60cm", "the Iowa State soil-moisture probe (60 cm)")):
        c = comps.get(key)
        rr = c and c["monthly_anomaly"]["r"]
        if rr is not None and not pd.isna(rr):
            lines.append(f"Our water model vs {what}: {rr:.2f} ({_strength(rr)} month-to-month match).")
    w = v.get("weather") or {}
    if w.get("tmax"):
        lines.append(f"NASA POWER weather vs the Ames ground station: daily highs {w['tmax']['r']:.2f}, "
                     f"monthly rain {w['rain_monthly']['r']:.2f}.")
    if lines:
        p.heading("Checked against NASA satellites and ground sensors")
        for ln in lines:
            p.text("•  " + ln, size=9, gap=0.001)
        p.text("1.00 = the ups and downs match perfectly, 0 = no relation (April-October, by month).",
               size=8, color=MUTED)

    # --- footer ------------------------------------------------------------------------------------
    fy = 0.085
    fig.add_artist(plt.Line2D([M, 1 - M], [fy + 0.012, fy + 0.012], color=LINE, lw=0.8))
    foot = ("Data: NASA POWER daily weather (1981-2025), NASA SRTM elevation, NASA SMAP soil moisture, USDA NRCS "
            "soil survey (SSURGO), USDA NASS Cropland Data Layer, Iowa State University crop budgets and "
            "USDA prices. Income compares rotations with typical yields, prices and costs; it is not a profit "
            "forecast. Talk to your agronomist before changing your rotation.")
    yy = fy
    for ln in textwrap.wrap(foot, int((1 - 2 * M) * W_IN * 72 / (7.4 * 0.56))):
        fig.text(M, yy, ln, fontsize=7.4, color=MUTED, va="top")
        yy -= 0.013
    fig.text(M, yy - 0.004, f"Made by {TEAM} (Adam and Leo) for the {EVENT}.", fontsize=7.4, color=ui.GREEN,
             fontweight="bold", va="top")

    for t in fig.texts:                  # "$" is money here, not maths markup
        t.set_parse_math(False)
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, dpi=110 if fmt == "png" else None)
    plt.close(fig)
    return buf.getvalue()

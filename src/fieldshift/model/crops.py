"""
crops.py - Daily crop state for a rotation: which crop is in the ground, its crop
coefficient (Kc), root depth and depletion fraction (p), day by day.

This is the "what is growing today?" layer between et0.py and water_balance.py:
    ETc = Kc * ET0                                  (crop water use)
    TAW = AWC * root_depth                          (bucket size, in water_balance.py)
    RAW = p * TAW                                   (easily available water)

Weather and soil are identical across rotations; this file is the ONLY thing that
differs between rotations in the water model.

Method (FAO-56, Allen et al. 1998, Chapter 6):
  - Kc follows the FAO-56 piecewise-linear curve: Kc_ini -> Kc_mid -> Kc_end over
    four stages (initial, development, mid-season, late season)  (FAO-56 Fig. 25, eq. 66).
  - Cash crops: the four stage lengths are stretched/shrunk to fit the actual
    planting -> harvest window for Iowa.
  - Cover crops / underseeded crops: nominal stage lengths from seeding, cut off at
    termination (they are killed before they finish their cycle).
  - Perennials (alfalfa): Kc_mid in the growing season, a low dormant Kc in winter.
  - Root depth grows linearly from ROOT_DEPTH_START_M at planting to the crop's
    maximum at the end of the development stage, then stays there (simplification).
  - Days with no crop are "bare" with a low evaporation-only Kc (simplification).

Rotation format (rotations.py will produce these):
    A rotation is a list of years; each year is a list of strings:
        [cash_crop]                      e.g. ["corn"]
        [cash_crop, cover_crop]          e.g. ["corn", "cereal_rye"]   rye seeded after corn harvest
        ["cash+underseeded"]             e.g. ["oats+red_clover"]      clover takes over after oat harvest
    Winter annuals (winter_wheat) listed in year N are planted in autumn of year N-1.
    Examples:
        C-S                    [["corn"], ["soybean"]]
        C-S + rye before soy   [["corn", "cereal_rye"], ["soybean"]]
        C-S + rye every gap    [["corn", "cereal_rye"], ["soybean", "cereal_rye"]]
        C-S-W                  [["corn"], ["soybean"], ["winter_wheat"]]
        C-S-O/RC               [["corn"], ["soybean"], ["oats+red_clover"]]
        C-S-O/A-A (Marsden)    [["corn"], ["soybean"], ["oats+alfalfa"], ["alfalfa"]]

IMPORTANT - parameter values:
  The crop table is read from content/crops.csv (edit that file to change the model).
  DEFAULT_CROPS below is only a fallback copy used if that file is missing.
  Values are STARTING VALUES recalled from FAO-56 Tables 11, 12 and 22 and typical
  Iowa dates; every row has verified=False until checked against FAO-56 and USDA
  "Usual Planting and Harvesting Dates" (2010) / NASS Crop Progress.
  Agronomist should review.

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from fieldshift import config

CROPS_PATH = config.CONTENT_DIR / "crops.csv"

# --- Global settings (simplifications; list in README "gaps") ----------------
BARE_SOIL_KC = 0.30          # evaporation-only Kc for bare soil. SIMPLIFICATION - verify vs FAO-56 Ch. 6/11
BARE_ROOT_DEPTH_M = 0.15     # depth of soil that dries by evaporation when bare (FAO-56 Ze ~0.10-0.15 m)
ROOT_DEPTH_START_M = 0.15    # root depth at sowing (FAO-56 suggests ~0.15-0.20 m)
MAX_ROOT_DEPTH_M = 1.0       # cap: SSURGO aws0100wta only describes the top 100 cm (playbook 6.2)
COVER_SEED_DELAY_DAYS = 3    # days between cash harvest and cover seeding. PLACEHOLDER
TERMINATE_DAYS_BEFORE = 14   # cover/perennial killed this many days before next planting
                             # (playbook: ~10-14 days before corn - verify with Iowa State Extension)

KINDS = {"summer_annual", "winter_annual", "perennial", "cover"}

REQUIRED_COLUMNS = [
    "crop", "kind", "kc_ini", "kc_mid", "kc_end",
    "l_ini", "l_dev", "l_mid", "l_late",
    "root_max_m", "p", "plant_md", "harvest_md",
    "sensitive_start_md", "sensitive_end_md",
    "greenup_md", "dormancy_md", "kc_dormant",
    "source", "verified",
]

# --- Fallback crop table (same values as content/crops.csv; used only if that file is missing) ----
# kc_*: FAO-56 Table 12. l_*: stage lengths in days, FAO-56 Table 11.
# root_max_m: lower end of FAO-56 Table 22 range (capped at 1 m anyway). p: FAO-56 Table 22.
# *_md: month-day "MM-DD". Sensitive window = days when water stress hurts yield most.
_N = np.nan
DEFAULT_CROPS = pd.DataFrame(
    [
        # crop,          kind,           kc_ini kc_mid kc_end  l_ini l_dev l_mid l_late root  p     plant    harvest  sens_start sens_end greenup  dormancy kc_dorm source, verified
        ("corn",         "summer_annual", 0.30, 1.20, 0.35,    30,   40,   50,   30,   1.0, 0.55, "05-01", "10-15", "07-10", "07-31", None,    None,    _N,
         "FAO-56 T11/T12/T22 (maize, grain; Kc_end 0.35 = dry harvest); Iowa dates approx.; pollination window approx.", False),
        ("soybean",      "summer_annual", 0.40, 1.15, 0.50,    20,   35,   60,   25,   0.6, 0.50, "05-15", "10-05", "08-01", "08-31", None,    None,    _N,
         "FAO-56 T11 (Central USA, May)/T12/T22; Iowa dates approx.; pod-fill window approx.", False),
        ("oats",         "summer_annual", 0.30, 1.15, 0.25,    20,   25,   60,   30,   1.0, 0.55, "04-01", "07-15", "06-10", "07-05", None,    None,    _N,
         "FAO-56 T11 (spring small grains)/T12/T22; Iowa dates approx.", False),
        ("winter_wheat", "winter_annual", 0.40, 1.15, 0.25,   160,   75,   75,   25,   1.0, 0.55, "10-01", "07-10", "05-20", "06-15", None,    None,    _N,
         "FAO-56 T11 (winter wheat, Idaho Oct)/T12/T22; Iowa dates approx.", False),
        ("cereal_rye",   "cover",         0.40, 1.15, 0.25,   160,   75,   75,   25,   1.0, 0.55, None,    None,    None,    None,    None,    None,    _N,
         "NOT IN FAO-56: winter small-grain (wheat) values used as proxy - information gap", False),
        ("red_clover",   "cover",         0.40, 0.90, 0.85,    10,   30,   30,   10,   0.6, 0.50, None,    None,    None,    None,    "04-01", "10-31", 0.40,
         "Red clover not in FAO-56: clover hay (berseem, averaged) Kc used as proxy; stage lengths, green-up/dormancy and dormant Kc PLACEHOLDER", False),
        ("alfalfa",      "perennial",     0.40, 0.95, 0.90,    10,   30,   25,   10,   1.0, 0.55, None,    None,    "07-01", "07-31", "04-01", "10-31", 0.40,
         "FAO-56 T12 (alfalfa hay, averaged for cuttings)/T11 (1st cutting cycle)/T22; green-up/dormancy dates and dormant Kc PLACEHOLDER", False),
    ],
    columns=REQUIRED_COLUMNS,
).set_index("crop", drop=False)


# --- Loading -----------------------------------------------------------------
def load_crop_table(path: str | Path | None = None) -> pd.DataFrame:
    """Return the crop parameter table, indexed by crop name.

    path=None -> content/crops.csv if it exists, else the built-in DEFAULT_CROPS (with a warning).
    path=...  -> any CSV with REQUIRED_COLUMNS.
    """
    if path is None:
        if CROPS_PATH.exists():
            path = CROPS_PATH
        else:
            warnings.warn(f"{CROPS_PATH} not found - using built-in DEFAULT_CROPS "
                          "(unverified starting values).", stacklevel=2)
            return DEFAULT_CROPS.copy()

    table = pd.read_csv(path, dtype={"plant_md": str, "harvest_md": str, "sensitive_start_md": str,
                                     "sensitive_end_md": str, "greenup_md": str, "dormancy_md": str})
    missing = [c for c in REQUIRED_COLUMNS if c not in table.columns]
    if missing:
        raise KeyError(f"{path}: missing columns {missing}")
    bad_kind = set(table["kind"]) - KINDS
    if bad_kind:
        raise ValueError(f"{path}: unknown kind(s) {bad_kind}; allowed {KINDS}")
    return table.set_index("crop", drop=False)


@lru_cache(maxsize=4)
def _cached_table(path: str, mtime: float) -> pd.DataFrame:
    return load_crop_table(path)


def default_crop_table() -> pd.DataFrame:
    """The crop table every function uses when none is passed: content/crops.csv
    (re-read automatically when the file changes), else DEFAULT_CROPS."""
    if CROPS_PATH.exists():
        return _cached_table(str(CROPS_PATH), CROPS_PATH.stat().st_mtime)
    return load_crop_table(None)


# --- FAO-56 curves -----------------------------------------------------------
def kc_curve(day, l_ini, l_dev, l_mid, l_late, kc_ini, kc_mid, kc_end):
    """FAO-56 piecewise-linear Kc at `day` days after planting (day 0 = planting).
    Flat Kc_ini, linear rise to Kc_mid, flat Kc_mid, linear fall to Kc_end, then held."""
    b1 = l_ini
    b2 = b1 + l_dev
    b3 = b2 + l_mid
    b4 = b3 + l_late
    return np.interp(np.asarray(day, dtype=float), [0, b1, b2, b3, b4],
                     [kc_ini, kc_ini, kc_mid, kc_mid, kc_end])


def root_depth_curve(day, days_to_max, root_max_m, root_start_m=ROOT_DEPTH_START_M):
    """Root depth [m] growing linearly from root_start_m at planting to root_max_m
    after `days_to_max` days (end of development stage), then constant."""
    return np.interp(np.asarray(day, dtype=float), [0, max(days_to_max, 1)],
                     [root_start_m, max(root_max_m, root_start_m)])


# --- Building the season timeline ---------------------------------------------
@dataclass
class Segment:
    """One crop occupying the field from `start` to `end` (inclusive)."""
    crop: str
    role: str                 # "cash" | "cover"
    start: pd.Timestamp
    end: pd.Timestamp
    kind: str
    rotation_year: int        # position in the rotation (1-based), for the field calendar


def _md(year: int, md: str) -> pd.Timestamp:
    return pd.Timestamp(f"{year}-{md}")


def _mdi(md) -> int:
    """'MM-DD' -> MMDD as an integer (e.g. '07-10' -> 710), for fast date-window comparisons."""
    return int(md[:2]) * 100 + int(md[3:5])


def _parse_year_plan(plan, crops: pd.DataFrame):
    """["corn"] / ["corn", "cereal_rye"] / ["oats+red_clover"] -> (cash, follow_crop, underseeded)."""
    if isinstance(plan, str):
        plan = [plan]
    if not 1 <= len(plan) <= 2:
        raise ValueError(f"Year plan must be [cash] or [cash, cover], got {plan!r}")
    cash, _, under = plan[0].partition("+")
    cover = plan[1] if len(plan) == 2 else None
    if under and cover:
        raise ValueError(f"{plan!r}: use either an underseeded crop or a cover crop, not both")
    follow = under or cover
    for c in filter(None, [cash, follow]):
        if c not in crops.index:
            raise KeyError(f"Unknown crop {c!r}; known: {list(crops.index)}")
    if crops.loc[cash, "kind"] == "cover":
        raise ValueError(f"{cash!r} is a cover crop and cannot be the cash crop of a year")
    return cash, follow, bool(under)


def build_segments(rotation, start_year: int, end_year: int, phase: int = 0,
                   crops: pd.DataFrame | None = None,
                   terminate_days_before: int = TERMINATE_DAYS_BEFORE,
                   cover_seed_delay_days: int = COVER_SEED_DELAY_DAYS) -> list[Segment]:
    """Lay out every crop of `rotation` on the calendar from start_year to end_year.

    phase: which rotation year is grown in start_year (0 = first entry). Running every
           phase lets every weather year meet every crop (playbook 6.2).
    One extra year either side is built so crops crossing 1 January are complete.
    """
    crops = default_crop_table() if crops is None else crops
    n = len(rotation)
    if n == 0:
        raise ValueError("Rotation is empty")
    plans = [_parse_year_plan(p, crops) for p in rotation]
    one_day = pd.Timedelta(days=1)

    # 1) Cash crops (incl. perennial years), in order
    cash_segs, follows = [], []
    for y in range(start_year - 1, end_year + 2):
        k = (y - start_year + phase) % n
        cash, follow, under = plans[k]
        row = crops.loc[cash]
        if row["kind"] == "summer_annual":
            s, e = _md(y, row["plant_md"]), _md(y, row["harvest_md"])
        elif row["kind"] == "winter_annual":
            s, e = _md(y - 1, row["plant_md"]), _md(y, row["harvest_md"])
        else:  # perennial: the whole calendar year
            s, e = pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31")
        if cash_segs and s <= cash_segs[-1].end:          # e.g. wheat planted right after soybean harvest
            s = cash_segs[-1].end + one_day
        cash_segs.append(Segment(cash, "cash", s, e, row["kind"], k + 1))
        follows.append((follow, under))

    # 2) Perennials before an annual: keep growing until terminated before the next planting
    for i in range(len(cash_segs) - 1):
        cur, nxt = cash_segs[i], cash_segs[i + 1]
        if cur.kind == "perennial" and nxt.kind != "perennial":
            cur.end = max(cur.end, nxt.start - pd.Timedelta(days=terminate_days_before))

    # 3) Cover / underseeded crops fill the gap after each cash crop
    segments = []
    for i, cur in enumerate(cash_segs):
        segments.append(cur)
        follow, under = follows[i]
        if follow is None or i + 1 >= len(cash_segs):
            continue
        nxt = cash_segs[i + 1]
        delay = 0 if under else cover_seed_delay_days
        s = cur.end + pd.Timedelta(days=delay + 1)
        if nxt.crop == follow and nxt.kind == "perennial":
            e = nxt.start - one_day                        # establishment year runs into the perennial
        else:
            e = nxt.start - pd.Timedelta(days=terminate_days_before)
        if e < s:
            if start_year <= cur.end.year <= end_year:
                warnings.warn(f"No room for {follow} between {cur.crop} (harvest {cur.end.date()}) "
                              f"and {nxt.crop} (planting {nxt.start.date()}); skipped.", stacklevel=2)
            continue
        segments.append(Segment(follow, "cover", s, e, crops.loc[follow, "kind"], cur.rotation_year))
    return segments


# --- Daily table -------------------------------------------------------------
def daily_crop_table(rotation, start_year: int, end_year: int, phase: int = 0,
                     crops: pd.DataFrame | None = None,
                     max_root_depth_m: float = MAX_ROOT_DEPTH_M,
                     bare_soil_kc: float = BARE_SOIL_KC,
                     terminate_days_before: int = TERMINATE_DAYS_BEFORE,
                     cover_seed_delay_days: int = COVER_SEED_DELAY_DAYS) -> pd.DataFrame:
    """Day-by-day crop state for one rotation and phase, 1 Jan start_year .. 31 Dec end_year.

    Returns a DataFrame indexed by date with columns:
        crop            crop name, or "bare"
        role            "cash" | "cover" | "bare"
        kc              crop coefficient [-]           -> ETc = kc * ET0
        root_depth_m    root-zone depth [m] (capped)   -> TAW = AWC * root_depth_m
        p               FAO-56 depletion fraction [-]  -> RAW = p * TAW  (NaN when bare: no crop to stress)
        sensitive       True inside the cash crop's yield-sensitive window
        days_since_start days since this crop was planted / took over (-1 when bare)
        rotation_year   which year of the rotation (1..n) this date belongs to
    """
    crops = default_crop_table() if crops is None else crops
    dates = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31", freq="D")
    nd = len(dates)

    crop = np.full(nd, "bare", dtype=object)
    role = np.full(nd, "bare", dtype=object)
    kc = np.full(nd, bare_soil_kc, dtype=float)
    zr = np.full(nd, BARE_ROOT_DEPTH_M, dtype=float)
    p = np.full(nd, np.nan, dtype=float)
    sensitive = np.zeros(nd, dtype=bool)
    dss = np.full(nd, -1, dtype=int)
    rot_year = np.zeros(nd, dtype=int)
    md = (dates.month * 100 + dates.day).to_numpy()          # MMDD integers (fast; same order as 'MM-DD')
    n = len(rotation)
    rot_year[:] = ((dates.year - start_year + phase) % n + 1).to_numpy()  # default: calendar year

    segs = build_segments(rotation, start_year, end_year, phase, crops,
                          terminate_days_before, cover_seed_delay_days)

    for seg in segs:
        mask = (dates >= seg.start) & (dates <= seg.end)
        if not mask.any():
            continue
        r = crops.loc[seg.crop]
        d = (dates[mask] - seg.start).days.to_numpy()
        stages = np.array([r["l_ini"], r["l_dev"], r["l_mid"], r["l_late"]], dtype=float)

        if seg.kind == "perennial" and seg.role == "cash":
            growing = (md[mask] >= _mdi(r["greenup_md"])) & (md[mask] <= _mdi(r["dormancy_md"]))
            kc[mask] = np.where(growing, r["kc_mid"], r["kc_dormant"])
            zr[mask] = r["root_max_m"]
        else:
            if seg.role == "cash":
                # stretch FAO-56 stage lengths to the actual planting -> harvest window
                season = (seg.end - seg.start).days + 1
                stages = stages * season / stages.sum()
            k = kc_curve(d, *stages, r["kc_ini"], r["kc_mid"], r["kc_end"])
            if isinstance(r["greenup_md"], str) and isinstance(r["dormancy_md"], str):
                # crops with a dormant season (clover, establishing alfalfa): cap Kc in winter
                dormant = ~((md[mask] >= _mdi(r["greenup_md"])) & (md[mask] <= _mdi(r["dormancy_md"])))
                k = np.where(dormant, np.minimum(k, r["kc_dormant"]), k)
            kc[mask] = k
            zr[mask] = root_depth_curve(d, stages[0] + stages[1], r["root_max_m"])

        crop[mask] = seg.crop
        role[mask] = seg.role
        p[mask] = r["p"]
        dss[mask] = d
        if seg.role == "cash":
            rot_year[mask] = seg.rotation_year
        s_start, s_end = r["sensitive_start_md"], r["sensitive_end_md"]
        if seg.role == "cash" and isinstance(s_start, str) and isinstance(s_end, str):
            sensitive[mask] = (md[mask] >= _mdi(s_start)) & (md[mask] <= _mdi(s_end))

    return pd.DataFrame({
        "crop": crop, "role": role, "kc": kc,
        "root_depth_m": np.minimum(zr, max_root_depth_m),
        "p": p, "sensitive": sensitive, "days_since_start": dss, "rotation_year": rot_year,
    }, index=dates)


def all_phases(rotation, start_year: int, end_year: int, **kwargs) -> dict[int, pd.DataFrame]:
    """daily_crop_table for every starting phase of the rotation: {phase: DataFrame}.
    C-S gives 2 runs (start corn / start soy), a 4-year rotation gives 4."""
    return {ph: daily_crop_table(rotation, start_year, end_year, phase=ph, **kwargs)
            for ph in range(len(rotation))}


def crop_et(et0: pd.Series, crop_table: pd.DataFrame) -> pd.Series:
    """Potential crop water use ETc = Kc * ET0 [mm/day], aligned on dates.
    (Unstressed; water_balance.py applies the stress coefficient Ks.)"""
    kc = crop_table["kc"].reindex(et0.index)
    if kc.isna().any():
        raise ValueError("crop_table does not cover all ET0 dates")
    return (kc * et0).rename("ETc_mm_day")


# --- Self-check ----------------------------------------------------------------
if __name__ == "__main__":
    warnings.simplefilter("always")
    examples = {
        "C-S":           [["corn"], ["soybean"]],
        "C-S + rye->soy": [["corn", "cereal_rye"], ["soybean"]],
        "C-S-W":         [["corn"], ["soybean"], ["winter_wheat"]],
        "C-S-O/RC":      [["corn"], ["soybean"], ["oats+red_clover"]],
        "C-S-O/A-A":     [["corn"], ["soybean"], ["oats+alfalfa"], ["alfalfa"]],
    }
    for name, rot in examples.items():
        df = daily_crop_table(rot, 2010, 2013, phase=0)
        # monthly snapshot (15th of each month) of the crop in the ground and its Kc
        snap = df[df.index.day == 15]
        print(f"\n{name}  (bare days/yr: {(df['role'] == 'bare').sum() / 4:.0f})")
        for yr, g in snap.groupby(snap.index.year):
            cells = " ".join(f"{c[:4]:>4}{k:4.2f}" for c, k in zip(g["crop"], g["kc"]))
            print(f"  {yr}: {cells}")

        # basic checks
        assert df["kc"].between(0, 1.4).all()
        assert (df["root_depth_m"] <= MAX_ROOT_DEPTH_M + 1e-9).all()
        assert df.index.is_unique and len(df) == 1461

    # Corn Kc should peak at Kc_mid in July and the sensitive window should be marked
    cs = daily_crop_table([["corn"], ["soybean"]], 2012, 2012)
    assert abs(cs.loc["2012-07-20", "kc"] - 1.20) < 1e-9 and cs.loc["2012-07-20", "sensitive"]
    assert cs.loc["2012-01-15", "crop"] == "bare"
    print("\nOK - checks passed.")

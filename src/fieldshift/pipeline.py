"""pipeline.py - Orchestration only: field -> data -> model -> scores. No agronomy or maths here.

Who does what (playbook 10.1):
    data/field.py          FieldProfile: soil (SSURGO), slope (SRTM), crop history (CDL), POWER cell
    data/power.py          daily weather;  model/et0.py  reference ET
    model/rotations.py     library, existing rotation, constraint filters, ordinal scores (content/rotations.yaml)
    model/water_balance.py rotation x year table per rotation
    model/scoring.py       normalise vs existing rotation, weights, score, Pareto (content/criteria.yaml)
    model/indicators.py    climate snapshot + notable years

The functions below keep the names app/app.py already calls (ROTATIONS, BASELINE,
filter_rotations, run_basic, basic_scores, WATER_COLUMNS), now backed by those modules.

    from fieldshift import pipeline
    out = pipeline.run_basic(42.03, -93.47)
    table = pipeline.basic_scores(out, {"drought": 0.4, "water_quality": 0.3, "soil_health": 0.3})

No Streamlit calls in this file (project rule).
"""

from __future__ import annotations

import warnings

import pandas as pd

from fieldshift import config
from fieldshift.data import field as field_mod
from fieldshift.data.power import load_power
from fieldshift.model import rotations as rot_mod
from fieldshift.model import scoring
from fieldshift.model.et0 import et0_from_power
from fieldshift.model.indicators import notable_years, snapshot, yearly_indicators
from fieldshift.model.water_balance import simulate_rotation

# --- Rotation library (from content/rotations.yaml via rotations.py) -----------------------
_LIBRARY = {r.name: r for r in rot_mod.library()}
ROTATIONS = {name: r.plan for name, r in _LIBRARY.items()}          # name -> crops.py plan
BASELINE = next(name for name, r in _LIBRARY.items() if r.rotation_id == "cs")
DEFAULT_EXISTING = ["corn", "soybean"]   # until the app asks for / confirms the existing rotation

# App slider keys -> criteria.yaml sliders
APP_SLIDERS = {"drought": "drought", "water_quality": "water_quality", "soil_health": "soil_erosion",
               "income": "income", "pests": "pests_fertiliser"}

# Water-model outputs shown in the app: column -> (label, unit, lower_is_better)
WATER_COLUMNS = {
    "drought_deficit_mm": ("Water deficit in sensitive window", "mm/yr", True),
    "drought_stress_days": ("Drought-stress days in sensitive window", "days/yr", True),
    "drainage_mm": ("Drainage (nitrate-loss proxy)", "mm/yr", True),
    "bare_wet_days": ("Bare days with erosive rain", "days/yr", True),
    "waterlogged_days": ("Waterlogged days", "days/yr", True),
    "bare_days": ("Days with no living cover", "days/yr", True),
    "runoff_mm": ("Runoff", "mm/yr", True),
}


# --- Candidates ------------------------------------------------------------------------------
def farm_inputs(want_cover=True, hay_buyer=True, hay_equipment=True, open_to_new=True,
                small_grain_buyer=True, existing_rotation=None) -> dict:
    """App answers -> the FarmInputs fields rotations.build_candidates reads.
    The app does not ask about a grain buyer yet, so small_grain_buyer defaults to True
    (oat/wheat options stay, each with a 'confirm a buyer' flag)."""
    return {
        "existing_rotation": existing_rotation or DEFAULT_EXISTING,
        "livestock_or_hay_buyer": hay_buyer,
        "hay_equipment": hay_equipment,
        "small_grain_buyer": small_grain_buyer,
        "can_seed_cover": want_cover,
        "openness": "yes" if open_to_new else "no",
    }


def candidates(want_cover=True, hay_buyer=True, hay_equipment=True, open_to_new=True,
               current_crops=None, small_grain_buyer=True, existing_rotation=None):
    """(candidate Rotation objects, removed [{rotation_id, name, reason}]).

    If the farmer is not open to new crops and lists current crops, rotations with
    other cash crops are removed too (cover crops still allowed, since they are asked separately).
    """
    inputs = farm_inputs(want_cover, hay_buyer, hay_equipment, open_to_new, small_grain_buyer,
                         existing_rotation)
    cands, removed = rot_mod.build_candidates(inputs)
    if not open_to_new and current_crops:
        current = {c.lower().replace(" ", "_") for c in current_crops} | {"cereal_rye"}
        keep = []
        for r in cands:
            crops = {c for y in r.plan for e in y for c in e.split("+")}
            if r.is_existing or crops <= current:
                keep.append(r)
            else:
                removed.append({"rotation_id": r.rotation_id, "name": r.name,
                                "reason": "Uses crops you do not grow now"})
        cands = keep
    for r in cands:                            # farmer variants become available by name too
        ROTATIONS.setdefault(r.name, r.plan)
        _LIBRARY.setdefault(r.name, r)
    return cands, removed


def filter_rotations(want_cover=True, hay_buyer=True, hay_equipment=True, open_to_new=True,
                     current_crops=None, small_grain_buyer=True) -> dict:
    """{name: plan} of the rotations this farm can run (existing rotation first)."""
    cands, _ = candidates(want_cover, hay_buyer, hay_equipment, open_to_new, current_crops,
                          small_grain_buyer)
    return {r.name: r.plan for r in cands}


# --- Data ---------------------------------------------------------------------------------------
def load_weather(lat, lon, allow_download=True):
    """POWER data + daily ET0 for the cell containing (lat, lon)."""
    df, meta = load_power(lat, lon, allow_download=allow_download)
    geom = meta.get("geometry") or {}
    coords = geom.get("coordinates") or []
    elevation = coords[2] if len(coords) > 2 else None   # None -> estimated from PS
    rs_units = meta.get("units", {}).get("ALLSKY_SFC_SW_DWN", "MJ/m^2/day")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        et0 = et0_from_power(df, meta["cell"]["centre"][0], elevation, rs_units=rs_units)
    return df, meta, et0


def field_profile(lat, lon, geojson=None, overrides=None):
    """FieldProfile from a drawn polygon (geojson) or a ~400 m box around (lat, lon).
    Falls back to farmer answers / typical values when local data files are missing."""
    geom = field_mod.field_geometry(geojson=geojson) if geojson else field_mod.field_geometry(point=(lat, lon))
    return field_mod.build_field_profile(geom, overrides=overrides)


# --- Run -------------------------------------------------------------------------------------------
def run_basic(lat, lon, rotations=None, awc_mm_per_m=None, tile_drained=None, allow_download=True,
              geojson=None, overrides=None, use_runoff=False):
    """Everything the app shows, as plain Python / pandas objects.

    Soil water capacity, tile drainage and slope come from the field profile (SSURGO/SRTM)
    unless given here. use_runoff=True turns on curve-number runoff from the field's
    hydrologic soil group (off by default: playbook MVP).
    """
    unique, seen = {}, set()
    for name, plan in (rotations or ROTATIONS).items():  # same crops under two names -> run once
        key = rot_mod.canonical(plan)
        if key not in seen:
            seen.add(key)
            unique[name] = plan
    rotations = unique
    # the baseline (0.5 on every criterion) is the existing rotation; find it by its crops, not
    # its name ("Corn–soybean" and "Corn–soybean (your current rotation)" are the same rotation)
    base_key = rot_mod.canonical(ROTATIONS[BASELINE])
    baseline = next((n for n, p in rotations.items() if rot_mod.canonical(p) == base_key), None)
    if baseline is None:                                 # always compare against the baseline
        baseline = BASELINE
        rotations = {BASELINE: ROTATIONS[BASELINE], **rotations}
    df, meta, et0 = load_weather(lat, lon, allow_download)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        prof = field_profile(lat, lon, geojson, overrides)
    awc = float(awc_mm_per_m if awc_mm_per_m is not None else prof.awc_mm_per_m)
    tiled = bool(tile_drained if tile_drained is not None else prof.tile_drained)
    hsg = prof.hydrologic_group if use_runoff else None

    yearly = yearly_indicators(df)
    start, end = config.WATER_START_YEAR, config.WATER_END_YEAR

    tables, rows, ordinal = {}, [], {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, plan in rotations.items():
            t = simulate_rotation(plan, df["PRECTOTCORR"], et0, awc, tiled, start, end,
                                  hydrologic_group=hsg, rotation_id=name)
            tables[name] = t
            rows.append({"rotation": name, **t[list(WATER_COLUMNS)].mean().to_dict()})
            lib = _LIBRARY.get(name)
            ordinal[name] = lib.scores if lib else rot_mod.rule_scores(plan)
    water = pd.DataFrame(rows).set_index("rotation")
    criteria_raw = scoring.raw_criteria(tables, ordinal, slope_factor=prof.slope.get("rusle_s"))

    return {
        "cell": meta["cell"],
        "loaded_from": meta["loaded_from"],
        "unit_warnings": meta["unit_warnings"],
        "years": {"weather": [int(yearly.index.min()), int(yearly.index.max())],
                  "water_model": [start, end]},
        "soil": {"awc_mm_per_m": awc, "tile_drained": tiled, "hydrologic_group": prof.hydrologic_group,
                 "source": prof.sources.get("soil", "typical value")},
        "field": prof.to_dict(),
        "snapshot": snapshot(yearly),
        "notable_years": notable_years(yearly),
        "yearly": yearly,
        "water": water,
        "tables": tables,                 # rotation x year table per rotation (bootstrap, replay)
        "criteria_raw": criteria_raw,     # raw criterion values in real units
        "ordinal_scores": ordinal,        # 0-3 literature scores per rotation (rotations.py)
        "baseline": baseline,
    }


# --- Scores --------------------------------------------------------------------------------------
def score_details(out: dict, weights: dict, baseline: str | None = None) -> dict:
    """Full scoring.score_rotations result for the app's slider weights."""
    sliders = {APP_SLIDERS.get(k, k): v for k, v in weights.items()}
    return scoring.score_rotations(out["criteria_raw"], baseline or out["baseline"], sliders)


def basic_scores(out: dict, weights: dict, baseline: str | None = None) -> pd.DataFrame:
    """One row per rotation: a 0-1 value per app slider (0.5 = same as the baseline) + score,
    best first. Sliders without data yet (income) are left out and the rest renormalised."""
    if isinstance(out, pd.DataFrame):
        raise TypeError("basic_scores now takes the dict returned by run_basic(), not out['water']")
    res = score_details(out, weights, baseline)
    back = {v: k for k, v in APP_SLIDERS.items()}
    table = res["slider_values"].rename(columns=back)
    table["score"] = res["scores"]["score"]
    return table.sort_values("score", ascending=False)


def robust_scores(out: dict, weights: dict, n_boot: int = 1000, window: str = "all",
                  baseline: str | None = None, with_robustness: bool = True) -> dict:
    """Year bootstrap + weight sampling (model/bootstrap.py): score mean / 5-95 % range /
    P(rank first) per rotation, criterion ranges, 'stressed in N of M years', and whether the
    top option changes with how past climate is weighted."""
    from fieldshift.model import bootstrap
    sliders = {APP_SLIDERS.get(k, k): v for k, v in weights.items()}
    baseline = baseline or out["baseline"]
    ordinal = out["ordinal_scores"]
    slope = out["field"]["slope"].get("rusle_s")
    res = bootstrap.run_bootstrap(out["tables"], baseline, sliders, ordinal, slope,
                                  n_boot=n_boot, window=window)
    res["stressed_years"] = {n: bootstrap.stressed_years(t) for n, t in out["tables"].items()}
    if with_robustness:
        res["robustness"] = bootstrap.robustness(out["tables"], baseline, sliders, ordinal, slope)
    return res


def replay(out: dict, year: int) -> dict:
    """Hard-year replay (model/replay.py) for the rotations in a run_basic() result."""
    from fieldshift.model import replay as rp
    tables = out["tables"]
    return {
        "year": int(year),
        "suggested_years": rp.suggest_years(tables, out["baseline"], weather_notable=out["notable_years"]),
        "table": rp.replay_table(tables, year, out["baseline"]),
        "contract": rp.contract_block(tables, year),
        "sentence": rp.sentence(tables, year, out["baseline"]),
    }

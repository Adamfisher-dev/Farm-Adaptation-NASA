"""pipeline.py - Basic end-to-end run: field location -> weather -> climate snapshot
-> water model for each candidate rotation.

This is the BASIC version so the app has something real to call. It does not yet
produce the full results contract (playbook 10.3): no scoring, bootstrap or soil
data. Those come with scoring.py / soil.py.

    from fieldshift.pipeline import run_basic
    out = run_basic(42.03, -93.47)

No Streamlit calls in this file (project rule).
"""

from __future__ import annotations

import warnings

import pandas as pd

from fieldshift import config
from fieldshift.data.power import load_power
from fieldshift.model.et0 import et0_from_power
from fieldshift.model.indicators import notable_years, snapshot, yearly_indicators
from fieldshift.model.water_balance import simulate_rotation

# Candidate rotations (format: see crops.py docstring). The first is the baseline.
ROTATIONS = {
    "Corn-Soybean": [["corn"], ["soybean"]],
    "Corn-Soybean + rye before soy": [["corn", "cereal_rye"], ["soybean"]],
    "Corn-Soybean + rye every winter": [["corn", "cereal_rye"], ["soybean", "cereal_rye"]],
    "Corn-Soybean-Wheat": [["corn"], ["soybean"], ["winter_wheat"]],
    "Corn-Soybean-Oats/red clover": [["corn"], ["soybean"], ["oats+red_clover"]],
    "Corn-Soybean-Oats/alfalfa-Alfalfa": [["corn"], ["soybean"], ["oats+alfalfa"], ["alfalfa"]],
}
BASELINE = "Corn-Soybean"

# Soil placeholders until soil.py reads SSURGO for the field.
DEFAULT_AWC_MM_PER_M = 200.0   # typical central-Iowa silt loam
DEFAULT_TILE_DRAINED = True

# Water-model outputs shown in the app: column -> (label, unit, lower_is_better)
WATER_COLUMNS = {
    "drought_stress_days": ("Drought-stress days in sensitive window", "days/yr", True),
    "drainage_mm": ("Drainage (nitrate-loss proxy)", "mm/yr", True),
    "waterlogged_days": ("Waterlogged days", "days/yr", True),
    "bare_days": ("Days with no living cover", "days/yr", True),
    "runoff_mm": ("Runoff", "mm/yr", True),
}


# BASIC scoring: slider -> water-model column it uses for now (playbook 6.4 simplified).
# Income and pests have no data yet, so they are left out of the score.
SLIDER_TO_COLUMN = {
    "drought": "drought_stress_days",   # playbook wants CVaR of worst 10 % years; mean for now
    "water_quality": "drainage_mm",
    "soil_health": "bare_days",         # stand-in for erosion_exposure / som_proxy
}
SCALE = {"drought_stress_days": 1.0, "drainage_mm": 10.0, "bare_days": 1.0}   # s_k
SATURATION = 0.5                                                              # c_k


def basic_scores(water: pd.DataFrame, weights: dict, baseline=BASELINE) -> pd.DataFrame:
    """Playbook 6.5 normalisation on the modelled criteria only.
    Baseline scores 0.5 on every criterion; > 0.5 = better than now.
    Weights for sliders with no criterion yet (income, pests) are dropped and
    the rest renormalised. Returns one row per rotation: v per criterion + score."""
    used = {s: w for s, w in weights.items() if s in SLIDER_TO_COLUMN and w > 0}
    if not used:
        used = {s: 1.0 for s in SLIDER_TO_COLUMN}
    total = sum(used.values())
    base = water.loc[baseline]
    out = pd.DataFrame(index=water.index)
    score = 0.0
    for slider, w in used.items():
        col = SLIDER_TO_COLUMN[slider]
        r = (base[col] - water[col]) / max(abs(base[col]), SCALE[col])   # all are costs
        v = 0.5 + 0.5 * (r / SATURATION).clip(-1, 1)
        out[slider] = v
        score = score + (w / total) * v
    out["score"] = score
    return out.sort_values("score", ascending=False)


def rotation_crops(rotation) -> set[str]:
    """All crop names in a rotation, e.g. {'corn', 'soybean', 'cereal_rye'}."""
    names = set()
    for year in rotation:
        for item in year:
            names.update(item.split("+"))
    return names


def filter_rotations(want_cover=True, hay_buyer=True, hay_equipment=True,
                     open_to_new=True, current_crops=None):
    """Constraint filter from the farm questions. Returns {name: rotation}.
    The baseline is always kept so there is something to compare against."""
    hay = {"alfalfa", "red_clover"}
    covers = {"cereal_rye"}
    allowed = {}
    for name, rot in ROTATIONS.items():
        crops = rotation_crops(rot)
        if name != BASELINE:
            if not want_cover and crops & covers:
                continue
            if not (hay_buyer and hay_equipment) and crops & hay:
                continue
            if not open_to_new and current_crops is not None:
                current = {c.lower().replace(" ", "_") for c in current_crops} | covers
                if not crops <= current:
                    continue
        allowed[name] = rot
    return allowed


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


def run_basic(lat, lon, rotations=None, awc_mm_per_m=DEFAULT_AWC_MM_PER_M,
              tile_drained=DEFAULT_TILE_DRAINED, allow_download=True):
    """Everything the basic app shows, as plain Python / pandas objects."""
    rotations = ROTATIONS if rotations is None else rotations
    df, meta, et0 = load_weather(lat, lon, allow_download)

    yearly = yearly_indicators(df)
    start, end = config.WATER_START_YEAR, config.WATER_END_YEAR

    rows = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # default (unverified) crop table warning
        for name, rot in rotations.items():
            t = simulate_rotation(rot, df["PRECTOTCORR"], et0, awc_mm_per_m, tile_drained, start, end)
            means = t[list(WATER_COLUMNS)].mean()
            rows.append({"rotation": name, **means.to_dict()})
    water = pd.DataFrame(rows).set_index("rotation")

    return {
        "cell": meta["cell"],
        "loaded_from": meta["loaded_from"],
        "unit_warnings": meta["unit_warnings"],
        "years": {"weather": [int(yearly.index.min()), int(yearly.index.max())],
                  "water_model": [start, end]},
        "soil": {"awc_mm_per_m": awc_mm_per_m, "tile_drained": tile_drained, "source": "placeholder"},
        "snapshot": snapshot(yearly),
        "notable_years": notable_years(yearly),
        "yearly": yearly,
        "water": water,
    }

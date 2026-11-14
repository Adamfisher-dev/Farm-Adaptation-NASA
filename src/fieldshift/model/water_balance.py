"""Daily soil-water bucket (FAO-56 Chapter 8, simplified) and the rotation x year table.

The soil to 1 m is split in two layers that move as roots grow:
    layer 1 = root zone (depth Zr from crops.py)       capacity TAW_r = AWC * Zr
    layer 2 = below the roots, down to 1 m             capacity TAW_b = AWC * (1 - Zr)
Water is stored as plant-available water (mm above wilting point).

Each day:
    1. Roots grow or shrink -> water moves between layers in proportion (mass kept).
    2. Rain (minus runoff) fills layer 1, overflow goes to layer 2, overflow from
       layer 2 drains below 1 m (tile-drained: same day; not tiled: up to a daily
       limit, the rest sits as waterlogging).
    3. Crop water use ETa = Ks * Kc * ET0, taken from layer 1.
       Ks < 1 when root-zone depletion passes RAW = p * TAW_r (FAO-56 Eq. 84).

Simplifications (list them as information gaps): snow treated as rain, no frozen
soil, runoff 0 by default, single crop coefficient, uniform soil to 1 m.

    from fieldshift.model.water_balance import run_bucket, rotation_year_table
"""

import numpy as np
import pandas as pd

from fieldshift import config
from fieldshift.model.crops import DEFAULT_CROPS, all_phases, load_crop_table

PROFILE_M = 1.0                 # SSURGO aws0100 covers the top 100 cm
UNTILED_DRAIN_MM_DAY = 10.0     # drainage limit without tiles (assumption, verify)
ERODING_RAIN_MM = 12.7          # 0.5 inch: RUSLE ignores smaller storms
EPS = 1e-9                      # ignore floating-point dust when checking for overflow
BARE_P = 0.5                    # crops.py gives p = NaN on bare days (no crop to stress)
STATE_FROM_ROLE = {"cash": "crop", "cover": "cover", "bare": "bare"}


def load_crops():
    """content/crops.csv if present, else crops.py's built-in DEFAULT_CROPS."""
    path = config.CONTENT_DIR / "crops.csv"
    return load_crop_table(path) if path.exists() else DEFAULT_CROPS.copy()


def bucket_params(crop_table, index=None):
    """Turn crops.daily_crop_table() output into the columns run_bucket() reads."""
    params = pd.DataFrame({
        "kc": crop_table["kc"],
        "root_m": crop_table["root_depth_m"],
        "p": crop_table["p"].fillna(BARE_P),
        "state": crop_table["role"].map(STATE_FROM_ROLE),
        "sensitive": crop_table["sensitive"].astype(bool),
        "crop": crop_table["crop"],
    }, index=crop_table.index)
    return params if index is None else params.reindex(index)


def run_bucket(rain, et0, params, awc_mm_per_m, tiled=True, runoff_fraction=0.0,
               start_full=True):
    """Run the bucket day by day. Inputs are aligned daily Series / DataFrame.

    rain   : precipitation [mm/day] (NASA POWER PRECTOTCORR)
    et0    : reference ET [mm/day] (et0.py)
    params : bucket_params() output: kc, root_m, p, state, sensitive, crop
    Returns one row per day with every flux and store (mm).
    """
    n = len(rain)
    P = np.nan_to_num(rain.to_numpy(dtype=float))
    E0 = np.nan_to_num(et0.to_numpy(dtype=float))
    kc = params["kc"].to_numpy(dtype=float)
    zr = np.clip(params["root_m"].to_numpy(dtype=float), 0.05, PROFILE_M)
    pp = params["p"].to_numpy(dtype=float)
    awc = float(awc_mm_per_m)

    out = {k: np.zeros(n) for k in
           ("runoff", "infiltration", "etc", "eta", "ks", "drainage", "w1", "w2", "wet", "taw_r")}

    z_prev = zr[0]
    w1 = awc * z_prev if start_full else 0.0
    w2 = awc * (PROFILE_M - z_prev) if start_full else 0.0
    wet = 0.0                                        # water above field capacity (waterlogging)

    for i in range(n):
        z = zr[i]
        # 1. move water between layers as roots change depth (keeps water content per metre)
        if z > z_prev:
            moved = w2 * (z - z_prev) / max(PROFILE_M - z_prev, 1e-9)
            w1, w2 = w1 + moved, w2 - moved
        elif z < z_prev:
            moved = w1 * (z_prev - z) / z_prev
            w1, w2 = w1 - moved, w2 + moved
        z_prev = z
        taw_r, taw_b = awc * z, awc * (PROFILE_M - z)

        # 2. rain in, overflow down, drainage out
        ro = runoff_fraction * P[i]
        inf = P[i] - ro
        w1 += inf + wet                              # standing surplus re-enters first
        wet = 0.0
        if w1 > taw_r + EPS:
            w2 += w1 - taw_r
            w1 = taw_r
        drain = 0.0
        if w2 > taw_b + EPS:
            excess = w2 - taw_b
            w2 = taw_b
            if tiled:
                drain = excess
            else:
                drain = min(excess, UNTILED_DRAIN_MM_DAY)
                wet = excess - drain

        # 3. crop water use from the root zone
        etc = kc[i] * E0[i]
        dr = taw_r - w1
        raw = pp[i] * taw_r
        ks = 1.0 if dr <= raw else max(0.0, (taw_r - dr) / ((1 - pp[i]) * taw_r))
        eta = min(ks * etc, w1)
        w1 -= eta

        out["runoff"][i], out["infiltration"][i], out["etc"][i] = ro, inf, etc
        out["eta"][i], out["ks"][i], out["drainage"][i] = eta, ks, drain
        out["w1"][i], out["w2"][i], out["wet"][i], out["taw_r"][i] = w1, w2, wet, taw_r

    df = pd.DataFrame(out, index=rain.index)
    df["rain"] = P
    df["et0"] = E0
    df["storage"] = df["w1"] + df["w2"] + df["wet"]
    df["initial_storage"] = (awc * PROFILE_M) if start_full else 0.0
    for col in ("crop", "state", "sensitive"):
        df[col] = params[col].to_numpy()
    df["stressed"] = df["ks"] < 1.0
    df["waterlogged"] = df["wet"] > 0
    return df


def mass_balance_error(day):
    """Rain - ET - drainage - runoff - change in storage. Should be ~0 (mm)."""
    change = day["storage"].iloc[-1] - day["initial_storage"].iloc[0]
    return float(day["rain"].sum() - day["eta"].sum() - day["drainage"].sum()
                 - day["runoff"].sum() - change)


def yearly_summary(day):
    """Per calendar year: the simulated measures behind the scoring criteria."""
    m = day.index.month
    bare = day["state"] == "bare"
    eroding = day["rain"] > ERODING_RAIN_MM
    sens = day["sensitive"].astype(bool)
    g = day.assign(
        deficit_sensitive=np.where(sens, day["etc"] - day["eta"], 0.0),
        stressed_sensitive=sens & day["stressed"],
        bare_day=bare,
        bare_wet_day=bare & eroding,
        bare_wet_spring=bare & eroding & (m >= 3) & (m <= 6),
    ).groupby(day.index.year)
    return pd.DataFrame({
        "rain_mm": g["rain"].sum(),
        "eta_mm": g["eta"].sum(),
        "drainage_mm": g["drainage"].sum(),
        "deficit_sensitive_mm": g["deficit_sensitive"].sum(),
        "stressed_sensitive_days": g["stressed_sensitive"].sum(),
        "bare_days": g["bare_day"].sum(),
        "bare_wet_days": g["bare_wet_day"].sum(),
        "bare_wet_spring_days": g["bare_wet_spring"].sum(),
        "waterlogged_days": g["waterlogged"].sum(),
        "main_crop": g["crop"].agg(lambda s: s[s != "bare"].mode().iloc[0] if (s != "bare").any() else "bare"),
    })


def rotation_year_table(weather, et0, rotation, awc_mm_per_m, tiled=True,
                        crops=None, rotation_id=None):
    """Run every phase of a rotation through the full weather record (CLAUDE.md 6.2).

    rotation : crops.py format, e.g. [["corn", "cereal_rye"], ["soybean"]]
    Returns one row per (phase, year): the rotation x year table that the
    bootstrap, scoring and hard-year replay all read.
    """
    crops = load_crops() if crops is None else crops
    years = weather.index.year
    phases = all_phases(rotation, int(years.min()), int(years.max()), crops=crops)
    frames = []
    for phase, crop_table in phases.items():
        params = bucket_params(crop_table, weather.index)
        day = run_bucket(weather["PRECTOTCORR"], et0, params, awc_mm_per_m, tiled=tiled)
        err = mass_balance_error(day)
        if abs(err) > 1e-6:
            raise RuntimeError(f"Water balance does not close: {err:.6f} mm")
        yearly = yearly_summary(day)
        yearly.insert(0, "phase", phase)
        frames.append(yearly)
    table = pd.concat(frames).rename_axis("year").reset_index()
    label = rotation_id or " / ".join("+".join(year) if isinstance(year, list) else year for year in rotation)
    table.insert(0, "rotation_id", label)
    return table

"""
water_balance.py - Daily soil-water "bucket" for one field and one rotation (FAO-56 Chapter 8).

    tomorrow's water = today's + rain - runoff - crop water use - drainage

Weather and soil are the same for every rotation; only the crop table (crops.py)
changes. So differences between rotations in drought stress, drainage (nitrate-loss
proxy) and waterlogging come out of this arithmetic, not hand-written rules.

Structure: a fixed 1 m soil profile (SSURGO aws0100wta describes the top 100 cm)
split into two layers that move as roots grow or shrink:

    surface -> [ root zone : 0 .. Zr ]       crop takes water only from here
               [ lower zone: Zr .. 1 m ]     stores water roots can reach later
               ---------------------------- -> drainage (tile or deep percolation)

  - Water is counted as plant-available water (mm above wilting point).
    Each layer holds at most AWC [mm/m] x its depth = its "field capacity".
  - When roots deepen, the lower zone hands over its water for the new depth;
    when the crop is harvested and the root zone shrinks to the bare-soil layer,
    the water goes back to the lower zone. Nothing is created or lost (mass conserved).
  - Rain enters the root zone. Water above field capacity moves down; water above
    field capacity of the whole profile is "surplus":
        tile-drained -> surplus leaves the same day (drainage)
        not tiled    -> at most `untiled_drain_mm_day` leaves per day; the rest stays
                        (waterlogged day) and beyond `max_surplus_mm` it runs off.
  - Crop water use: ETc = Kc x ET0. Under water shortage FAO-56's Ks reduces it:
        TAW = AWC x Zr, RAW = p x TAW, Dr = depletion of the root zone
        Ks = (TAW - Dr) / ((1 - p) TAW)  when Dr > RAW, else 1        (FAO-56 eq. 84)
        p is adjusted for the day's ETc: p = p_table + 0.04 (5 - ETc)  (FAO-56 Table 22 note)
    Bare soil: evaporation falls in proportion to how full the thin top layer is
    (Ks = water / TAW, i.e. p = 0) - a simplification of FAO-56's Kr (Ch. 7).
  - Runoff: none by default (playbook MVP). If a hydrologic soil group (A-D) is given,
    the SCS curve-number method (USDA TR-55) is used with cover-dependent CNs.

Simplifications (list as gaps in README): snow is treated as rain (snowmelt timing);
no capillary rise from below 1 m; CN ignores antecedent moisture; single crop
coefficient (soil evaporation after rain not separated); fixed calendar dates.

Reference: Allen, Pereira, Raes & Smith (1998), FAO-56, Chapters 7-8; USDA NRCS
(1986) TR-55 "Urban Hydrology for Small Watersheds", Table 2-2 (curve numbers).

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fieldshift.model import crops as crops_mod

# --- Settings (starting values; list in README "gaps") -----------------------
PROFILE_DEPTH_M = crops_mod.MAX_ROOT_DEPTH_M  # 1 m, matches SSURGO aws0100wta
UNTILED_DRAIN_MM_DAY = 10.0   # max drainage/day without tiles. PLACEHOLDER - should come
                              # from SSURGO Ksat / drainage class
MAX_SURPLUS_MM = 50.0         # water above field capacity the soil can hold before it runs
                              # off (roughly saturation - FC). PLACEHOLDER
WATERLOGGED_MM = 5.0          # surplus above this at the end of a day = waterlogged day
INITIAL_FRACTION = 1.0        # start at field capacity (Iowa soils usually recharge over winter)

# SCS curve numbers (antecedent condition II), USDA TR-55 Table 2-2, cultivated
# agricultural land, straight row, good hydrologic condition. VERIFY before use.
CURVE_NUMBERS = {
    #               A   B   C   D
    "bare":        (77, 86, 91, 94),   # fallow, bare soil
    "row_crop":    (67, 78, 85, 89),   # corn, soybean
    "small_grain": (63, 75, 83, 87),   # oats, wheat, cereal rye
    "legume":      (58, 72, 81, 85),   # close-seeded legumes / rotation meadow (alfalfa, clover)
}
CN_CLASS = {
    "corn": "row_crop", "soybean": "row_crop",
    "oats": "small_grain", "winter_wheat": "small_grain", "cereal_rye": "small_grain",
    "alfalfa": "legume", "red_clover": "legume",
}


# --- Helpers ------------------------------------------------------------------
def curve_number_runoff(p_mm: float, cn: float) -> float:
    """SCS curve-number runoff [mm] from daily rain p_mm [mm]. TR-55 eqs. 2-1 to 2-4 (SI)."""
    if p_mm <= 0 or cn <= 0:
        return 0.0
    s = 25400.0 / cn - 254.0           # potential retention [mm]
    ia = 0.2 * s                        # initial abstraction [mm]
    return (p_mm - ia) ** 2 / (p_mm - ia + s) if p_mm > ia else 0.0


def _cn_for(crop: str, hsg: str | None) -> float:
    if hsg is None:
        return 0.0
    g = hsg.strip().upper()[:1]         # "C/D" (dual group, drained/undrained) -> "C"
    if not g or g not in "ABCD":
        raise ValueError(f"Hydrologic soil group must be A-D, got {hsg!r}")
    cls = "bare" if crop == "bare" else CN_CLASS.get(crop, "row_crop")
    return float(CURVE_NUMBERS[cls]["ABCD".index(g)])


# --- Core simulation ----------------------------------------------------------
def run_water_balance(
    precip_mm: pd.Series,
    et0_mm: pd.Series,
    crop_table: pd.DataFrame,
    awc_mm_per_m: float,
    tile_drained: bool,
    hydrologic_group: str | None = None,
    untiled_drain_mm_day: float = UNTILED_DRAIN_MM_DAY,
    max_surplus_mm: float = MAX_SURPLUS_MM,
    initial_fraction: float = INITIAL_FRACTION,
) -> pd.DataFrame:
    """Simulate the daily soil-water balance.

    Parameters
    ----------
    precip_mm     daily rain [mm/day] (POWER PRECTOTCORR), DatetimeIndex
    et0_mm        daily reference ET [mm/day] (et0.et0_from_power), same dates
    crop_table    output of crops.daily_crop_table for the same dates
    awc_mm_per_m  plant-available water capacity [mm per m of soil] (SSURGO aws0100wta x 10)
    tile_drained  True if the field has tile drainage
    hydrologic_group  "A".."D" from SSURGO hydgrpdcd, or None for no runoff (MVP)

    Returns a daily DataFrame (see column list at the end of this function).
    Raises ValueError if any input day is missing (ET0 is NaN before 1984 because
    POWER solar radiation starts then - begin the simulation in 1984).
    """
    idx = crop_table.index
    p_all = precip_mm.reindex(idx)
    e_all = et0_mm.reindex(idx)
    if p_all.isna().any() or e_all.isna().any():
        bad = idx[p_all.isna() | e_all.isna()]
        raise ValueError(f"Missing rain/ET0 on {len(bad)} days ({bad.min().date()} .. {bad.max().date()}). "
                         "Simulate only over dates with complete weather (ET0 starts 1984).")
    if not 20 <= awc_mm_per_m <= 400:
        raise ValueError(f"awc_mm_per_m={awc_mm_per_m}: outside 20-400 mm/m - units bug? "
                         "(SSURGO aws0100wta is cm in top 100 cm -> multiply by 10)")

    P = p_all.to_numpy(float)
    ET0 = e_all.to_numpy(float)
    kc = crop_table["kc"].to_numpy(float)
    zr = np.minimum(crop_table["root_depth_m"].to_numpy(float), PROFILE_DEPTH_M)
    p_tab = crop_table["p"].to_numpy(float)
    crop = crop_table["crop"].to_numpy(object)
    n = len(idx)
    a = float(awc_mm_per_m)

    out = {k: np.zeros(n) for k in
           ["runoff", "infiltration", "etc", "ks", "eta", "drainage", "depletion",
            "taw", "raw", "sw_root", "sw_lower", "surplus"]}

    # initial state
    zr_prev = zr[0]
    sw_root = initial_fraction * a * zr_prev
    sw_lower = initial_fraction * a * (PROFILE_DEPTH_M - zr_prev)
    surplus = 0.0

    for i in range(n):
        # 1) move the root/lower boundary to today's root depth (mass-conserving)
        z = zr[i]
        if z > zr_prev:
            lower_depth = PROFILE_DEPTH_M - zr_prev
            moved = sw_lower * (z - zr_prev) / lower_depth if lower_depth > 1e-9 else 0.0
            sw_lower -= moved
            sw_root += moved
        elif z < zr_prev:
            moved = sw_root * (zr_prev - z) / zr_prev
            sw_root -= moved
            sw_lower += moved
        zr_prev = z
        taw = a * z
        taw_lower = a * (PROFILE_DEPTH_M - z)

        # yesterday's surplus is back in the root zone (available to the crop, drains again)
        sw_root += surplus
        surplus = 0.0

        # 2) stress coefficient from start-of-day depletion (FAO-56 eq. 84)
        etc = kc[i] * ET0[i]
        dr = max(taw - sw_root, 0.0)
        if np.isnan(p_tab[i]):                                   # bare soil
            p_day = 0.0
        else:
            p_day = float(np.clip(p_tab[i] + 0.04 * (5.0 - etc), 0.1, 0.8))
        raw = p_day * taw
        ks = 1.0 if dr <= raw else max((taw - dr) / ((1.0 - p_day) * taw), 0.0)

        # 3) rain -> runoff / infiltration
        ro = curve_number_runoff(P[i], _cn_for(crop[i], hydrologic_group)) if hydrologic_group else 0.0
        inf = P[i] - ro
        sw_root += inf

        # 4) crop water use (cannot take more than is there)
        eta = min(ks * etc, sw_root)
        sw_root -= eta

        # 5) excess above field capacity: root zone -> lower zone -> surplus -> drainage
        excess = max(sw_root - taw, 0.0)
        sw_root -= excess
        sw_lower += excess
        excess = max(sw_lower - taw_lower, 0.0)
        sw_lower -= excess
        surplus += excess
        dp = surplus if tile_drained else min(surplus, untiled_drain_mm_day)
        surplus -= dp
        sat_ro = max(surplus - max_surplus_mm, 0.0)              # soil saturated -> runs off
        surplus -= sat_ro
        ro += sat_ro

        o = out
        o["runoff"][i] = ro
        o["infiltration"][i] = P[i] - ro
        o["etc"][i] = etc
        o["ks"][i] = ks
        o["eta"][i] = eta
        o["drainage"][i] = dp
        o["depletion"][i] = max(taw - sw_root, 0.0)
        o["taw"][i] = taw
        o["raw"][i] = raw
        o["sw_root"][i] = sw_root
        o["sw_lower"][i] = sw_lower
        o["surplus"][i] = surplus

    df = pd.DataFrame(out, index=idx)
    df.insert(0, "precip", P)
    df.insert(1, "et0", ET0)
    df["kc"] = kc
    df["root_depth_m"] = zr
    df["deficit"] = df["etc"] - df["eta"]                  # water the crop wanted but did not get
    df["storage"] = df["sw_root"] + df["sw_lower"] + df["surplus"]
    df["crop"] = crop
    df["role"] = crop_table["role"].to_numpy(object)
    df["sensitive"] = crop_table["sensitive"].to_numpy(bool)
    df["rotation_year"] = crop_table["rotation_year"].to_numpy(int)
    has_crop = df["role"] != "bare"
    df["stressed"] = has_crop & (df["ks"] < 1.0)
    df["waterlogged"] = df["surplus"] > WATERLOGGED_MM
    df.attrs["initial_storage"] = initial_fraction * a * PROFILE_DEPTH_M
    # columns: precip, et0, runoff, infiltration, etc, ks, eta, drainage, depletion, taw, raw,
    #          sw_root, sw_lower, surplus, kc, root_depth_m, deficit, storage, crop, role,
    #          sensitive, rotation_year, stressed, waterlogged   (all water in mm or mm/day)
    return df


def mass_balance_error(daily: pd.DataFrame) -> float:
    """sum(P) - sum(RO) - sum(ETa) - sum(DP) - (S_end - S_start); should be ~0 mm."""
    ds = daily["storage"].iloc[-1] - daily.attrs["initial_storage"]
    return float(daily["precip"].sum() - daily["runoff"].sum() - daily["eta"].sum()
                 - daily["drainage"].sum() - ds)


# --- Yearly summary: the rotation x year table -----------------------------------
def yearly_summary(daily: pd.DataFrame) -> pd.DataFrame:
    """One row per calendar year with the simulated criteria inputs (playbook 6.3):
        drought_stress_days   days with Ks < 1 inside the cash crop's sensitive window
        drought_deficit_mm    ETc - ETa summed over the sensitive window
        drainage_mm           water leaving the bottom / tiles (nitrate-loss proxy)
        runoff_mm, eta_mm, precip_mm, et0_mm
        waterlogged_days      surplus > WATERLOGGED_MM
        stressed_days_season  days with Ks < 1 while any crop is in the ground
        bare_days             days with no living crop
        cash_crop             main crop that year (for labels / phase pooling)
    """
    g = daily.groupby(daily.index.year)
    sens = daily["sensitive"]
    out = pd.DataFrame({
        "drought_stress_days": (daily["stressed"] & sens).groupby(daily.index.year).sum(),
        "drought_deficit_mm": daily["deficit"].where(sens, 0.0).groupby(daily.index.year).sum(),
        "drainage_mm": g["drainage"].sum(),
        "runoff_mm": g["runoff"].sum(),
        "eta_mm": g["eta"].sum(),
        "precip_mm": g["precip"].sum(),
        "et0_mm": g["et0"].sum(),
        "waterlogged_days": g["waterlogged"].sum(),
        "stressed_days_season": g["stressed"].sum(),
        "bare_days": (daily["role"] == "bare").groupby(daily.index.year).sum(),
        "cash_crop": daily[daily["role"] == "cash"].groupby(daily[daily["role"] == "cash"].index.year)["crop"]
                     .agg(lambda s: s.value_counts().idxmax()),
    })
    out.index.name = "year"
    return out


def simulate_rotation(
    rotation,
    precip_mm: pd.Series,
    et0_mm: pd.Series,
    awc_mm_per_m: float,
    tile_drained: bool,
    start_year: int,
    end_year: int,
    hydrologic_group: str | None = None,
    crops: pd.DataFrame | None = None,
    **wb_kwargs,
) -> pd.DataFrame:
    """Run every phase of a rotation and stack the yearly summaries.

    Returns the rotation x year table for this rotation: one row per (phase, year),
    columns from yearly_summary plus 'phase'. Phases are pooled downstream
    (bootstrap.py), so every weather year meets every crop (playbook 6.2).
    """
    tables = []
    for phase, ct in crops_mod.all_phases(rotation, start_year, end_year, crops=crops).items():
        daily = run_water_balance(precip_mm, et0_mm, ct, awc_mm_per_m, tile_drained,
                                  hydrologic_group, **wb_kwargs)
        y = yearly_summary(daily)
        y.insert(0, "phase", phase)
        tables.append(y.reset_index())
    return pd.concat(tables, ignore_index=True)


# --- Self-check on the real sample POWER data ----------------------------------------
if __name__ == "__main__":
    import json
    import warnings

    from fieldshift import config
    from fieldshift.model.et0 import et0_from_power

    warnings.simplefilter("ignore")  # default-crop-table warning
    cell = "42.000_-93.750"
    weather = pd.read_csv(config.SAMPLE_DIR / f"power_{cell}.csv", index_col="date", parse_dates=True)
    weather = weather.replace(config.POWER_FILL_VALUE, np.nan)
    meta = json.loads((config.SAMPLE_DIR / f"power_{cell}_meta.json").read_text())
    lat, elev = meta["requested_point"][0], meta["geometry"]["coordinates"][2]
    et0 = et0_from_power(weather, lat, elev, rs_units=meta["units"]["ALLSKY_SFC_SW_DWN"])

    START, END = config.WATER_START_YEAR, config.WATER_END_YEAR   # ET0 needs solar radiation (from 1984)
    AWC, TILED = 200.0, True       # typical central-Iowa silt loam (placeholder until soil.py)

    # mass conservation on one run, with and without runoff/tiles
    ct = crops_mod.daily_crop_table([["corn"], ["soybean"]], START, END)
    for tiled, hsg in [(True, None), (False, "C")]:
        d = run_water_balance(weather["PRECTOTCORR"], et0, ct, AWC, tiled, hsg)
        err = mass_balance_error(d)
        print(f"mass balance error (tiled={tiled}, HSG={hsg}): {err:.2e} mm over {END - START + 1} years")
        assert abs(err) < 1e-6
        assert (d["sw_root"] >= -1e-9).all() and (d["sw_root"] <= d["taw"] + 1e-9).all()

    rotations = {
        "C-S":           [["corn"], ["soybean"]],
        "C-S + rye":     [["corn", "cereal_rye"], ["soybean"]],
        "C-S-O/A-A":     [["corn"], ["soybean"], ["oats+alfalfa"], ["alfalfa"]],
    }
    print(f"\nCell {cell}, AWC {AWC} mm/m, tiled={TILED}, {START}-{END}; means per rotation-year:")
    print(f"{'rotation':<12} {'drainage':>9} {'ETa':>6} {'stress days':>12} {'deficit':>8} {'bare':>6}")
    for name, rot in rotations.items():
        t = simulate_rotation(rot, weather["PRECTOTCORR"], et0, AWC, TILED, START, END)
        print(f"{name:<12} {t.drainage_mm.mean():9.0f} {t.eta_mm.mean():6.0f} "
              f"{t.drought_stress_days.mean():12.1f} {t.drought_deficit_mm.mean():8.1f} {t.bare_days.mean():6.0f}")

    # does 2012 stand out for corn?
    t = simulate_rotation([["corn"], ["soybean"]], weather["PRECTOTCORR"], et0, AWC, TILED, START, END)
    corn = t[t.cash_crop == "corn"].set_index("year")
    print("\nCorn years, worst 5 by stress days in pollination window:")
    print(corn.nlargest(5, "drought_stress_days")[["drought_stress_days", "drought_deficit_mm", "precip_mm"]]
          .round(0).to_string())
    print("\nOK - checks passed.")

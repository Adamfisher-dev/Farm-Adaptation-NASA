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

from fieldshift import config
from fieldshift.model import crops as crops_mod

# --- Settings (starting values; list in README "gaps") -----------------------
PROFILE_DEPTH_M = crops_mod.MAX_ROOT_DEPTH_M  # 1 m, matches SSURGO aws0100wta
UNTILED_DRAIN_MM_DAY = 10.0   # FALLBACK only: untiled fields normally get SSURGO values from
MAX_SURPLUS_MM = 50.0         # pipeline.drainage_params() (restrictive-layer Ksat, spring water table,
                              # saturation - field capacity). Used when SSURGO hydraulics are unavailable.
WATERLOGGED_MM = 5.0          # surplus above this at the end of a day = waterlogged day
INITIAL_FRACTION = 1.0        # start at field capacity (Iowa soils usually recharge over winter)
ERODING_RAIN_MM = 12.7        # 0.5 inch: RUSLE ignores smaller storms (Renard et al. 1997, AH-703)
EPS = 1e-9                    # mm; ignore floating-point dust when checking for overflow
BARE_P = 0.5                  # p shown for bare days in bucket_params() (not used for stress)
STATE_FROM_ROLE = {"cash": "crop", "cover": "cover", "bare": "bare"}

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
    runoff_fraction: float = 0.0,
    untiled_drain_mm_day: float = UNTILED_DRAIN_MM_DAY,
    max_surplus_mm: float = MAX_SURPLUS_MM,
    untiled_drain_by_month: dict | None = None,
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
    hydrologic_group  "A".."D" from SSURGO hydgrpdcd -> curve-number runoff; None -> runoff_fraction
    runoff_fraction   share of each day's rain that runs off when no hydrologic group (default 0)
    untiled_drain_mm_day / untiled_drain_by_month / max_surplus_mm
                      untiled fields only: drainage capacity (mm/day; a {month: rate} dict overrides it
                      in those months, e.g. a high spring water table) and the water the soil holds above
                      field capacity before it runs off. From SSURGO via pipeline.drainage_params().

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
           ["runoff", "infiltration", "ks", "eta", "drainage", "depletion",
            "taw", "raw", "sw_root", "sw_lower", "surplus"]}

    # Terms that do not depend on the soil-water state: computed once for all days (speed).
    etc_all = kc * ET0                                                      # crop water use
    p_all_days = np.where(np.isnan(p_tab), 0.0,                             # bare soil: p = 0
                          np.clip(p_tab + 0.04 * (5.0 - etc_all), 0.1, 0.8))  # FAO-56 Table 22 note
    if hydrologic_group:
        cn = np.array([_cn_for(c, hydrologic_group) for c in crop])
        ro_all = np.array([curve_number_runoff(pp, c) for pp, c in zip(P, cn)])
    else:
        ro_all = runoff_fraction * P
    # plain Python lists: indexing them in the loop is much faster than numpy scalars
    zr_l, etc_l, p_l, ro_l, P_l = zr.tolist(), etc_all.tolist(), p_all_days.tolist(), ro_all.tolist(), P.tolist()
    if untiled_drain_by_month:
        months = idx.month.to_numpy()
        drain_l = [float(untiled_drain_by_month.get(int(m), untiled_drain_mm_day)) for m in months]
    else:
        drain_l = [float(untiled_drain_mm_day)] * n
    o_ro, o_inf, o_ks, o_eta, o_dp = out["runoff"], out["infiltration"], out["ks"], out["eta"], out["drainage"]
    o_dep, o_taw, o_raw, o_sr, o_sl, o_sp = (out["depletion"], out["taw"], out["raw"], out["sw_root"],
                                            out["sw_lower"], out["surplus"])

    # initial state
    zr_prev = zr[0]
    sw_root = initial_fraction * a * zr_prev
    sw_lower = initial_fraction * a * (PROFILE_DEPTH_M - zr_prev)
    surplus = 0.0

    for i in range(n):
        # 1) move the root/lower boundary to today's root depth (mass-conserving)
        z = zr_l[i]
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
        etc = etc_l[i]
        dr = taw - sw_root if taw > sw_root else 0.0
        p_day = p_l[i]
        raw = p_day * taw
        if dr <= raw:
            ks = 1.0
        else:
            ks = (taw - dr) / ((1.0 - p_day) * taw)
            ks = ks if ks > 0.0 else 0.0

        # 3) rain -> runoff / infiltration
        ro = ro_l[i]
        inf = P_l[i] - ro
        sw_root += inf

        # 4) crop water use (cannot take more than is there)
        eta = ks * etc
        eta = eta if eta < sw_root else sw_root
        sw_root -= eta

        # 5) excess above field capacity: root zone -> lower zone -> surplus -> drainage
        # (overflows below EPS are rounding noise from the layer moves: leave them in place)
        excess = sw_root - taw if sw_root - taw > EPS else 0.0
        sw_root -= excess
        sw_lower += excess
        excess = sw_lower - taw_lower if sw_lower - taw_lower > EPS else 0.0
        sw_lower -= excess
        surplus += excess
        cap = drain_l[i]
        dp = surplus if (tile_drained or surplus < cap) else cap
        surplus -= dp
        sat_ro = surplus - max_surplus_mm if surplus > max_surplus_mm else 0.0   # soil saturated -> runs off
        surplus -= sat_ro
        ro += sat_ro

        o_ro[i] = ro
        o_inf[i] = P_l[i] - ro
        o_ks[i] = ks
        o_eta[i] = eta
        o_dp[i] = dp
        o_dep[i] = taw - sw_root if taw > sw_root else 0.0
        o_taw[i] = taw
        o_raw[i] = raw
        o_sr[i] = sw_root
        o_sl[i] = sw_lower
        o_sp[i] = surplus

    out["etc"] = etc_all
    df = pd.DataFrame(out, index=idx)
    df = df[["runoff", "infiltration", "etc", "ks", "eta", "drainage", "depletion", "taw", "raw",
             "sw_root", "sw_lower", "surplus"]]
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
    df["state"] = df["role"].map(STATE_FROM_ROLE)
    df["initial_storage"] = initial_fraction * a * PROFILE_DEPTH_M
    df.attrs["initial_storage"] = initial_fraction * a * PROFILE_DEPTH_M
    # aliases used by tests/test_water_balance.py and scripts/check_water_balance.py
    df["rain"], df["w1"], df["w2"], df["wet"] = df["precip"], df["sw_root"], df["sw_lower"], df["surplus"]
    # columns: precip (= rain), et0, runoff, infiltration, etc, ks, eta, drainage, depletion, taw, raw,
    #          sw_root (= w1), sw_lower (= w2), surplus (= wet), kc, root_depth_m, deficit, storage,
    #          crop, role, state, sensitive, rotation_year, stressed, waterlogged, initial_storage
    #          (all water in mm or mm/day)
    return df


def mass_balance_error(daily: pd.DataFrame) -> float:
    """sum(P) - sum(RO) - sum(ETa) - sum(DP) - (S_end - S_start); should be ~0 mm."""
    start = daily["initial_storage"].iloc[0] if "initial_storage" in daily else daily.attrs["initial_storage"]
    ds = daily["storage"].iloc[-1] - start
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
        bare_wet_days         bare days with erosive rain (> ERODING_RAIN_MM = 12.7 mm, RUSLE) - erosion exposure
        bare_wet_spring_days  the same, March-June only (before canopy closure)
        cash_crop / main_crop main crop that year (for labels / phase pooling)
    Also, under the names used in tests/test_water_balance.py: rain_mm (= precip_mm),
    deficit_sensitive_mm (= drought_deficit_mm), stressed_sensitive_days (= drought_stress_days).
    """
    g = daily.groupby(daily.index.year)
    sens = daily["sensitive"]
    m = daily.index.month
    bare_wet = (daily["role"] == "bare") & (daily["precip"] > ERODING_RAIN_MM)
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
        "bare_wet_days": bare_wet.groupby(daily.index.year).sum(),
        "bare_wet_spring_days": (bare_wet & (m >= 3) & (m <= 6)).groupby(daily.index.year).sum(),
        "cash_crop": daily[daily["role"] == "cash"].groupby(daily[daily["role"] == "cash"].index.year)["crop"]
                     .agg(lambda s: s.value_counts().idxmax()),
    })
    out.index.name = "year"
    out["cash_crop"] = out["cash_crop"].fillna("bare")
    out["main_crop"] = out["cash_crop"]
    out["rain_mm"] = out["precip_mm"]
    out["deficit_sensitive_mm"] = out["drought_deficit_mm"]
    out["stressed_sensitive_days"] = out["drought_stress_days"]
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
    rotation_id: str | None = None,
    keep_daily: bool = False,
    **wb_kwargs,
) -> pd.DataFrame:
    """Run every phase of a rotation and stack the yearly summaries.

    Returns the rotation x year table for this rotation: one row per (phase, year),
    columns from yearly_summary plus 'phase'. Phases are pooled downstream
    (bootstrap.py), so every weather year meets every crop (playbook 6.2).
    """
    tables, dailies = [], {}
    for phase, ct in crops_mod.all_phases(rotation, start_year, end_year, crops=crops).items():
        daily = run_water_balance(precip_mm, et0_mm, ct, awc_mm_per_m, tile_drained,
                                  hydrologic_group, **wb_kwargs)
        if keep_daily:      # small copy for the field calendar (stress and waterlogging by half-month)
            dailies[phase] = daily[["stressed", "sensitive", "waterlogged"]].copy()
        y = yearly_summary(daily)
        y.insert(0, "phase", phase)
        tables.append(y.reset_index())
    table = pd.concat(tables, ignore_index=True)
    label = rotation_id or " / ".join("+".join(y) if isinstance(y, (list, tuple)) else y for y in rotation)
    table.insert(0, "rotation_id", label)
    if keep_daily:
        table.attrs["daily"] = dailies
    return table


# --- Second interface (names from the partner's version; same model underneath) -----------
# Kept so tests/test_water_balance.py, scripts/check_water_balance.py and older callers work.
def load_crops() -> pd.DataFrame:
    """content/crops.csv if present, else crops.py's built-in table."""
    return crops_mod.default_crop_table()


def bucket_params(crop_table: pd.DataFrame, index=None) -> pd.DataFrame:
    """crops.daily_crop_table() output -> columns kc, root_m, p, state, sensitive, crop
    (p filled with BARE_P on bare days so there are no gaps)."""
    params = pd.DataFrame({
        "kc": crop_table["kc"],
        "root_m": crop_table["root_depth_m"],
        "p": crop_table["p"].fillna(BARE_P),
        "state": crop_table["role"].map(STATE_FROM_ROLE),
        "sensitive": crop_table["sensitive"].astype(bool),
        "crop": crop_table["crop"],
        "rotation_year": crop_table["rotation_year"],
    }, index=crop_table.index)
    return params if index is None else params.reindex(index)


def run_bucket(rain, et0, params, awc_mm_per_m, tiled=True, runoff_fraction=0.0, start_full=True,
               hydrologic_group=None):
    """run_water_balance() taking bucket_params() output. start_full=False starts at wilting point."""
    role_from_state = {v: k for k, v in STATE_FROM_ROLE.items()}
    crop_table = pd.DataFrame({
        "kc": params["kc"],
        "root_depth_m": params["root_m"],
        "p": params["p"].where(params["state"] != "bare"),     # bare: evaporation rule, not crop p
        "crop": params["crop"],
        "role": params["state"].map(role_from_state),
        "sensitive": params["sensitive"].astype(bool),
        "rotation_year": params["rotation_year"] if "rotation_year" in params else 0,
    }, index=params.index)
    return run_water_balance(rain, et0, crop_table, awc_mm_per_m, tiled, hydrologic_group,
                             runoff_fraction=runoff_fraction, initial_fraction=1.0 if start_full else 0.0)


def rotation_year_table(weather, et0, rotation, awc_mm_per_m, tiled=True, crops=None,
                        rotation_id=None, hydrologic_group=None):
    """simulate_rotation() over every full year in `weather` (needs PRECTOTCORR) -
    the rotation x year table read by bootstrap, scoring and the hard-year replay."""
    years = weather.index.year
    return simulate_rotation(rotation, weather["PRECTOTCORR"], et0, awc_mm_per_m, tiled,
                             int(years.min()), int(years.max()), hydrologic_group, crops, rotation_id)


# --- Self-check on the real sample POWER data ----------------------------------------
if __name__ == "__main__":
    import json
    import warnings

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
    print(f"{'rotation':<12} {'drainage':>9} {'ETa':>6} {'stress days':>12} {'deficit':>8} {'bare':>6} {'bare+wet':>9}")
    for name, rot in rotations.items():
        t = simulate_rotation(rot, weather["PRECTOTCORR"], et0, AWC, TILED, START, END)
        print(f"{name:<12} {t.drainage_mm.mean():9.0f} {t.eta_mm.mean():6.0f} "
              f"{t.drought_stress_days.mean():12.1f} {t.drought_deficit_mm.mean():8.1f} {t.bare_days.mean():6.0f}"
              f" {t.bare_wet_days.mean():9.2f}")

    # does 2012 stand out for corn?
    t = simulate_rotation([["corn"], ["soybean"]], weather["PRECTOTCORR"], et0, AWC, TILED, START, END)
    corn = t[t.cash_crop == "corn"].set_index("year")
    print("\nCorn years, worst 5 by stress days in pollination window:")
    print(corn.nlargest(5, "drought_stress_days")[["drought_stress_days", "drought_deficit_mm", "precip_mm"]]
          .round(0).to_string())
    print("\nOK - checks passed.")

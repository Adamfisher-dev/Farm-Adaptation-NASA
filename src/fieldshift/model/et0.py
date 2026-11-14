"""
et0.py - Reference evapotranspiration (ET0) with the FAO-56 Penman-Monteith equation.

ET0 is "how thirsty the weather is": the water (mm/day) a standard, well-watered
grass surface would use under that day's sun, temperature, humidity and wind.
Crop water use is then ETc = Kc * ET0 (Kc comes from crops.py, not here).

Reference: Allen, Pereira, Raes & Smith (1998), FAO Irrigation and Drainage
Paper 56, "Crop evapotranspiration", Chapters 3-4 (equation numbers below refer to it).

Units used throughout (all SI, as FAO-56):
    temperature  degC
    pressure     kPa
    radiation    MJ m-2 day-1
    wind         m s-1 at 2 m height
    vapour press kPa
    ET0          mm day-1

No Streamlit calls in this file (project rule). Pure numpy/pandas.

AI use: drafted with Claude (Anthropic) from the FAO-56 equations; reviewed by the team.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

# --- Constants (FAO-56) ------------------------------------------------------
SOLAR_CONSTANT = 0.0820      # Gsc, MJ m-2 min-1                    (eq. 21)
STEFAN_BOLTZMANN = 4.903e-9  # sigma, MJ K-4 m-2 day-1               (eq. 39)
GRASS_ALBEDO = 0.23          # albedo of the hypothetical grass reference (eq. 38)
KWH_TO_MJ = 3.6              # 1 kWh m-2 = 3.6 MJ m-2


# --- Atmospheric parameters --------------------------------------------------
def pressure_from_elevation(elevation_m):
    """Atmospheric pressure P [kPa] from elevation z [m]. FAO-56 eq. 7."""
    z = np.asarray(elevation_m, dtype=float)
    return 101.3 * ((293.0 - 0.0065 * z) / 293.0) ** 5.26


def elevation_from_pressure(pressure_kpa):
    """Elevation z [m] from atmospheric pressure [kPa]: FAO-56 eq. 7 solved for z.
    Used when no elevation is given (POWER's PS is available every day)."""
    p = np.asarray(pressure_kpa, dtype=float)
    return (293.0 - 293.0 * (p / 101.3) ** (1.0 / 5.26)) / 0.0065


def psychrometric_constant(pressure_kpa):
    """Psychrometric constant gamma [kPa degC-1] from pressure [kPa]. FAO-56 eq. 8."""
    return 0.665e-3 * np.asarray(pressure_kpa, dtype=float)


# --- Humidity ----------------------------------------------------------------
def saturation_vapour_pressure(t_c):
    """Saturation vapour pressure e0(T) [kPa] at air temperature T [degC]. FAO-56 eq. 11."""
    t = np.asarray(t_c, dtype=float)
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def slope_vapour_pressure_curve(t_c):
    """Slope of the saturation vapour pressure curve Delta [kPa degC-1]. FAO-56 eq. 13."""
    t = np.asarray(t_c, dtype=float)
    return 4098.0 * saturation_vapour_pressure(t) / (t + 237.3) ** 2


def mean_saturation_vapour_pressure(tmax_c, tmin_c):
    """Mean saturation vapour pressure es [kPa] = mean of e0(Tmax) and e0(Tmin). FAO-56 eq. 12.
    (Using e0 of the mean temperature instead would underestimate es.)"""
    return (saturation_vapour_pressure(tmax_c) + saturation_vapour_pressure(tmin_c)) / 2.0


def actual_vapour_pressure_from_dewpoint(tdew_c):
    """Actual vapour pressure ea [kPa] from dewpoint [degC]. FAO-56 eq. 14 (preferred method)."""
    return saturation_vapour_pressure(tdew_c)


def actual_vapour_pressure_from_rh_minmax(tmax_c, tmin_c, rhmax_pct, rhmin_pct):
    """Actual vapour pressure ea [kPa] from daily max/min relative humidity [%]. FAO-56 eq. 17."""
    return (saturation_vapour_pressure(tmin_c) * np.asarray(rhmax_pct, dtype=float) / 100.0
            + saturation_vapour_pressure(tmax_c) * np.asarray(rhmin_pct, dtype=float) / 100.0) / 2.0


def actual_vapour_pressure_from_rhmean(rh_mean_pct, tmax_c, tmin_c):
    """Actual vapour pressure ea [kPa] from mean relative humidity [%]. FAO-56 eq. 19.
    Less accurate than dewpoint; used only as a fallback."""
    rh = np.asarray(rh_mean_pct, dtype=float)
    return rh / 100.0 * mean_saturation_vapour_pressure(tmax_c, tmin_c)


# --- Radiation ---------------------------------------------------------------
def extraterrestrial_radiation(latitude_deg, day_of_year):
    """Daily extraterrestrial radiation Ra [MJ m-2 day-1] (top of atmosphere).
    FAO-56 eqs. 21-25. Depends only on latitude and date."""
    phi = np.deg2rad(np.asarray(latitude_deg, dtype=float))
    j = np.asarray(day_of_year, dtype=float)

    dr = 1.0 + 0.033 * np.cos(2.0 * np.pi * j / 365.0)            # inverse relative Earth-Sun distance (eq. 23)
    delta = 0.409 * np.sin(2.0 * np.pi * j / 365.0 - 1.39)         # solar declination [rad] (eq. 24)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1.0, 1.0))  # sunset hour angle [rad] (eq. 25)

    return (24.0 * 60.0 / np.pi) * SOLAR_CONSTANT * dr * (
        ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws)
    )


def clear_sky_radiation(ra, elevation_m):
    """Clear-sky solar radiation Rso [MJ m-2 day-1]. FAO-56 eq. 37."""
    return (0.75 + 2e-5 * np.asarray(elevation_m, dtype=float)) * np.asarray(ra, dtype=float)


def net_shortwave_radiation(rs, albedo=GRASS_ALBEDO):
    """Net shortwave radiation Rns [MJ m-2 day-1] = (1 - albedo) * Rs. FAO-56 eq. 38."""
    return (1.0 - albedo) * np.asarray(rs, dtype=float)


def net_longwave_radiation(tmax_c, tmin_c, ea_kpa, rs, rso):
    """Net outgoing longwave radiation Rnl [MJ m-2 day-1]. FAO-56 eq. 39.
    Rs/Rso is the relative cloudiness term, limited to <= 1.0 as FAO-56 requires."""
    tmax_k = np.asarray(tmax_c, dtype=float) + 273.16
    tmin_k = np.asarray(tmin_c, dtype=float) + 273.16
    ea = np.asarray(ea_kpa, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs_rso = np.clip(np.asarray(rs, dtype=float) / np.asarray(rso, dtype=float), 0.0, 1.0)
    return (
        STEFAN_BOLTZMANN * (tmax_k**4 + tmin_k**4) / 2.0
        * (0.34 - 0.14 * np.sqrt(ea))
        * (1.35 * rs_rso - 0.35)
    )


def net_radiation(rs, rso, tmax_c, tmin_c, ea_kpa, albedo=GRASS_ALBEDO):
    """Net radiation Rn = Rns - Rnl [MJ m-2 day-1]. FAO-56 eq. 40. Returns (rn, rns, rnl)."""
    rns = net_shortwave_radiation(rs, albedo)
    rnl = net_longwave_radiation(tmax_c, tmin_c, ea_kpa, rs, rso)
    return rns - rnl, rns, rnl


def wind_speed_at_2m(u_z, height_m):
    """Convert wind speed measured at height z [m] to 2 m [m s-1]. FAO-56 eq. 47.
    (POWER's WS2M is already at 2 m, so this is only needed for other sources, e.g. WS10M.)"""
    return np.asarray(u_z, dtype=float) * 4.87 / np.log(67.8 * height_m - 5.42)


# --- Core equation -----------------------------------------------------------
def penman_monteith(tmax_c, tmin_c, ea_kpa, u2, rn, pressure_kpa, g=0.0):
    """FAO-56 eq. 6 given net radiation already computed. Returns ET0 [mm/day] (not clipped).
    Tmean = (Tmax + Tmin) / 2 (eq. 9); es from Tmax and Tmin (eq. 12)."""
    tmax = np.asarray(tmax_c, dtype=float)
    tmin = np.asarray(tmin_c, dtype=float)
    u2 = np.asarray(u2, dtype=float)
    tmean = (tmax + tmin) / 2.0
    gamma = psychrometric_constant(pressure_kpa)
    delta = slope_vapour_pressure_curve(tmean)
    vpd = np.maximum(mean_saturation_vapour_pressure(tmax, tmin) - np.asarray(ea_kpa, dtype=float), 0.0)
    numerator = 0.408 * delta * (np.asarray(rn, dtype=float) - g) + gamma * (900.0 / (tmean + 273.0)) * u2 * vpd
    return numerator / (delta + gamma * (1.0 + 0.34 * u2))


def et0_penman_monteith(
    tmax_c,
    tmin_c,
    rs,
    u2,
    ea_kpa,
    latitude_deg,
    day_of_year,
    elevation_m,
    pressure_kpa=None,
    soil_heat_flux=0.0,
    clip_negative=True,
):
    """FAO-56 Penman-Monteith reference evapotranspiration, daily step. FAO-56 eq. 6.

    Parameters (scalars or equal-length arrays)
    ----------
    tmax_c, tmin_c : daily max / min air temperature at 2 m [degC]
    rs             : incoming solar (shortwave) radiation [MJ m-2 day-1]
    u2             : wind speed at 2 m [m s-1]
    ea_kpa         : actual vapour pressure [kPa]
    latitude_deg   : latitude [decimal degrees, north positive]
    day_of_year    : 1..366
    elevation_m    : site elevation [m] (used for Rso, and for P if pressure not given)
    pressure_kpa   : surface pressure [kPa]; if None, estimated from elevation (eq. 7)
    soil_heat_flux : G [MJ m-2 day-1]; FAO-56 says G ~ 0 for daily steps
    clip_negative  : set negative ET0 (can happen on cold, dark winter days when Rn < 0)
                     to 0, so the water balance never gains water from ET

    Returns
    -------
    ET0 [mm day-1], numpy array (or float for scalar input)
    """
    p = pressure_from_elevation(elevation_m) if pressure_kpa is None else np.asarray(pressure_kpa, dtype=float)
    ra = extraterrestrial_radiation(latitude_deg, day_of_year)
    rso = clear_sky_radiation(ra, elevation_m)
    rn, _, _ = net_radiation(rs, rso, tmax_c, tmin_c, ea_kpa)
    # vapour pressure deficit is floored at 0 inside penman_monteith (ea > es = data error)
    et0 = penman_monteith(tmax_c, tmin_c, ea_kpa, u2, rn, p, soil_heat_flux)

    if clip_negative:
        et0 = np.where(np.isnan(et0), np.nan, np.maximum(et0, 0.0))
    return et0


# --- NASA POWER wrapper ------------------------------------------------------
def et0_from_power(
    df: pd.DataFrame,
    latitude_deg: float | None = None,
    elevation_m: float | None = None,
    rs_units: str = "MJ/m^2/day",
    use_power_pressure: bool = True,
    clip_negative: bool = True,
    lat: float | None = None,
) -> pd.Series:
    """Daily ET0 [mm/day] from a NASA POWER daily DataFrame (as made by data/power.py).

    Required columns: T2M_MAX, T2M_MIN [degC], WS2M [m/s], ALLSKY_SFC_SW_DWN,
    and either T2MDEW [degC] (preferred) or RH2M [%].
    Optional: PS [kPa] surface pressure (else estimated from elevation).
    Index must be a DatetimeIndex (one row per day). -999 fill values must already be NaN.

    rs_units: units of ALLSKY_SFC_SW_DWN as stated in the POWER response metadata.
              "MJ/m^2/day" (AG community) or "kWh/m^2/day" (RE/SB communities). Never assume;
              read js["parameters"]["ALLSKY_SFC_SW_DWN"]["units"].

    latitude_deg (or lat=, same thing): field / POWER-cell latitude.
    elevation_m: site elevation [m] (POWER meta geometry.coordinates[2]). If None, it is
              estimated from the mean of POWER's PS column (FAO-56 eq. 7 inverted).

    Days with any missing input return NaN (no silent gap filling here).
    """
    if latitude_deg is None:
        latitude_deg = lat
    if latitude_deg is None:
        raise TypeError("et0_from_power needs latitude_deg (or lat=).")
    if elevation_m is None:
        if "PS" not in df.columns or df["PS"].isna().all():
            raise ValueError("Give elevation_m, or include POWER's PS column to estimate it.")
        elevation_m = float(elevation_from_pressure(df["PS"].mean()))
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("df must have a DatetimeIndex (one row per day).")

    required = ["T2M_MAX", "T2M_MIN", "WS2M", "ALLSKY_SFC_SW_DWN"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"Missing POWER columns for ET0: {missing}")

    # Solar radiation -> MJ m-2 day-1
    units = rs_units.replace(" ", "").lower()
    if units in ("mj/m^2/day", "mj/m2/day", "mjm-2day-1"):
        rs = df["ALLSKY_SFC_SW_DWN"].to_numpy(dtype=float)
    elif units in ("kw-hr/m^2/day", "kwh/m^2/day", "kwh/m2/day"):
        rs = df["ALLSKY_SFC_SW_DWN"].to_numpy(dtype=float) * KWH_TO_MJ
    else:
        raise ValueError(f"Unrecognised rs_units {rs_units!r}; expected MJ/m^2/day or kWh/m^2/day.")

    # Actual vapour pressure: dewpoint preferred (FAO-56 eq. 14), RH fallback (eq. 19)
    tmax = df["T2M_MAX"].to_numpy(dtype=float)
    tmin = df["T2M_MIN"].to_numpy(dtype=float)
    if "T2MDEW" in df.columns:
        ea = actual_vapour_pressure_from_dewpoint(df["T2MDEW"].to_numpy(dtype=float))
    elif "RH2M" in df.columns:
        ea = actual_vapour_pressure_from_rhmean(df["RH2M"].to_numpy(dtype=float), tmax, tmin)
    else:
        raise KeyError("Need T2MDEW or RH2M to compute vapour pressure.")

    pressure = df["PS"].to_numpy(dtype=float) if (use_power_pressure and "PS" in df.columns) else None

    _check_units(tmax, tmin, rs, df["WS2M"].to_numpy(dtype=float), pressure)

    et0 = et0_penman_monteith(
        tmax_c=tmax,
        tmin_c=tmin,
        rs=rs,
        u2=df["WS2M"].to_numpy(dtype=float),
        ea_kpa=ea,
        latitude_deg=latitude_deg,
        day_of_year=df.index.dayofyear.to_numpy(),
        elevation_m=elevation_m,
        pressure_kpa=pressure,
        clip_negative=clip_negative,
    )
    return pd.Series(et0, index=df.index, name="ET0_mm_day")


def _check_units(tmax, tmin, rs, u2, pressure):
    """Warn when inputs fall outside physically plausible ranges (usually a units bug)."""
    def frac_outside(x, lo, hi):
        x = x[~np.isnan(x)]
        return 0.0 if x.size == 0 else float(np.mean((x < lo) | (x > hi)))

    checks = [
        ("T2M_MAX/T2M_MIN [degC]", np.concatenate([tmax, tmin]), -50, 55, "Kelvin or degF?"),
        ("Solar radiation [MJ m-2 day-1]", rs, 0, 40, "kWh vs MJ mix-up?"),
        ("WS2M [m s-1]", u2, 0, 30, "km/h or wrong height?"),
    ]
    if pressure is not None:
        checks.append(("PS [kPa]", pressure, 50, 110, "hPa/Pa instead of kPa?"))

    for name, x, lo, hi, hint in checks:
        f = frac_outside(np.asarray(x, dtype=float), lo, hi)
        if f > 0.01:
            warnings.warn(f"{name}: {f:.1%} of values outside [{lo}, {hi}] - {hint}", stacklevel=3)

    n_bad = int(np.sum(np.asarray(tmax) < np.asarray(tmin)))
    if n_bad:
        warnings.warn(f"{n_bad} day(s) with Tmax < Tmin - check input data.", stacklevel=3)


# --- Short aliases (names used by tests/test_et0.py and scripts/check_et0.py) --------
sat_vp = saturation_vapour_pressure
slope_svp = slope_vapour_pressure_curve
psychrometric = psychrometric_constant
ea_from_dewpoint = actual_vapour_pressure_from_dewpoint
ea_from_rh_minmax = actual_vapour_pressure_from_rh_minmax


# --- Self-check: FAO-56 Example 18 (Brussels, 6 July) -----------------------
if __name__ == "__main__":
    # Inputs from FAO-56 Chapter 4, Example 18. Published answer: ET0 = 3.9 mm/day
    # (intermediates: Ra = 41.09, Rso = 30.90, Rns = 16.99, Rnl = 3.71, Rn = 13.28).
    lat = 50.0 + 48.0 / 60.0          # 50 deg 48' N
    doy = 187                         # 6 July
    z = 100.0                         # m
    tmax, tmin = 21.5, 12.3           # degC
    ea = 1.409                        # kPa (from RHmax 84 %, RHmin 63 %)
    u2 = 2.078                        # m/s (10 km/h at 10 m, converted to 2 m)
    rs = 22.07                        # MJ m-2 day-1 (from 9.25 h of sunshine)

    ra = extraterrestrial_radiation(lat, doy)
    rso = clear_sky_radiation(ra, z)
    rnl = net_longwave_radiation(tmax, tmin, ea, rs, rso)
    et0 = et0_penman_monteith(tmax, tmin, rs, u2, ea, lat, doy, z)

    print(f"Ra  = {float(ra):.2f}   (FAO: 41.09)")
    print(f"Rso = {float(rso):.2f}   (FAO: 30.90)")
    print(f"Rnl = {float(rnl):.2f}    (FAO: 3.71)")
    print(f"ET0 = {float(et0):.2f}    (FAO: 3.9 mm/day)")
    assert abs(float(et0) - 3.9) < 0.1, "ET0 does not reproduce FAO-56 Example 18"
    print("OK - reproduces FAO-56 Example 18.")

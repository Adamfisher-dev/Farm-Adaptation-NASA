"""Reference evapotranspiration (ET0) by FAO-56 Penman-Monteith, daily.

ET0 = how much water a standard, well-watered grass would use today:
"how thirsty the weather is". Crop water use is later ET0 x Kc (crops.py).

Reference: Allen, Pereira, Raes and Smith (1998), FAO Irrigation and
Drainage Paper 56, Chapters 3-4. Equation numbers below refer to it.

    from fieldshift.data.power import load_power
    from fieldshift.model.et0 import et0_from_power

    df, meta = load_power(42.03, -93.47)
    et0 = et0_from_power(df, lat=meta["cell"]["centre"][0])   # mm/day, one value per day

Inputs from NASA POWER (AG community; units checked in power.py):
    T2M_MAX, T2M_MIN  [C]            daily max / min air temperature at 2 m
    T2MDEW            [C]            dew point at 2 m -> actual vapour pressure
    WS2M              [m/s]          wind speed at 2 m
    PS                [kPa]          surface pressure -> psychrometric constant
    ALLSKY_SFC_SW_DWN [MJ/m^2/day]   incoming solar radiation Rs
"""

import numpy as np
import pandas as pd

SIGMA = 4.903e-9      # Stefan-Boltzmann constant, MJ K^-4 m^-2 day^-1
GSC = 0.0820          # solar constant, MJ m^-2 min^-1
ALBEDO = 0.23         # grass reference crop


# ---------------------------------------------------------------------------
# Vapour pressure and temperature terms
# ---------------------------------------------------------------------------

def sat_vp(t):
    """Saturation vapour pressure e°(T) [kPa] at air temperature t [C]. Eq. 11."""
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def slope_svp(t):
    """Slope of the saturation vapour pressure curve, Delta [kPa/C]. Eq. 13."""
    return 4098 * sat_vp(t) / (t + 237.3) ** 2


def psychrometric(pressure_kpa):
    """Psychrometric constant gamma [kPa/C]. Eq. 8."""
    return 0.665e-3 * pressure_kpa


def ea_from_dewpoint(tdew):
    """Actual vapour pressure from dew point [kPa]. Eq. 14 (FAO's preferred route)."""
    return sat_vp(tdew)


def ea_from_rh_minmax(tmax, tmin, rhmax, rhmin):
    """Actual vapour pressure from daily max/min RH [kPa]. Eq. 17 (used in the FAO test)."""
    return (sat_vp(tmin) * rhmax / 100 + sat_vp(tmax) * rhmin / 100) / 2


def elevation_from_pressure(pressure_kpa):
    """Invert Eq. 7 to estimate elevation [m] from surface pressure."""
    return (293 - 293 * (pressure_kpa / 101.3) ** (1 / 5.26)) / 0.0065


# ---------------------------------------------------------------------------
# Radiation terms
# ---------------------------------------------------------------------------

def extraterrestrial_radiation(lat_deg, doy):
    """Ra [MJ/m^2/day], radiation at the top of the atmosphere. Eqs. 21-25."""
    phi = np.radians(lat_deg)
    doy = np.asarray(doy, dtype=float)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)                 # Eq. 23
    delta = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)           # Eq. 24
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1, 1))   # Eq. 25
    return (24 * 60 / np.pi) * GSC * dr * (
        ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))


def clear_sky_radiation(ra, elevation_m):
    """Rso [MJ/m^2/day]. Eq. 37."""
    return (0.75 + 2e-5 * elevation_m) * ra


def net_radiation(rs, rso, tmax, tmin, ea):
    """Rn = Rns - Rnl [MJ/m^2/day]. Eqs. 38-40. Returns (rn, rns, rnl)."""
    rns = (1 - ALBEDO) * rs                                            # Eq. 38
    # FAO-56 limits Rs/Rso to <= 1.0. The 0.3 floor is our choice: it keeps
    # Rnl positive on very overcast days.
    ratio = np.clip(np.where(rso > 0, rs / rso, 1.0), 0.3, 1.0)
    rnl = SIGMA * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 \
        * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * ratio - 0.35)          # Eq. 39
    return rns - rnl, rns, rnl


# ---------------------------------------------------------------------------
# Penman-Monteith
# ---------------------------------------------------------------------------

def penman_monteith(tmax, tmin, ea, u2, rn, pressure_kpa, g=0.0):
    """Daily reference ET0 [mm/day]. Eq. 6, with T = mean of Tmax and Tmin (Eq. 9)."""
    t = (tmax + tmin) / 2
    es = (sat_vp(tmax) + sat_vp(tmin)) / 2                            # Eq. 12
    delta = slope_svp(t)
    gamma = psychrometric(pressure_kpa)
    num = 0.408 * delta * (rn - g) + gamma * 900 / (t + 273) * u2 * (es - ea)
    den = delta + gamma * (1 + 0.34 * u2)
    return num / den


def et0_from_power(df, lat):
    """Daily ET0 [mm/day] for a POWER DataFrame (DatetimeIndex). Negative values clipped to 0.

    Days with any missing input give NaN; fill or drop them before the water balance.
    """
    tmax, tmin = df["T2M_MAX"], df["T2M_MIN"]
    ea = ea_from_dewpoint(df["T2MDEW"])
    pressure = df["PS"]
    ra = extraterrestrial_radiation(lat, df.index.dayofyear)
    rso = clear_sky_radiation(ra, elevation_from_pressure(pressure))
    rn, _, _ = net_radiation(df["ALLSKY_SFC_SW_DWN"], rso, tmax, tmin, ea)
    et0 = penman_monteith(tmax, tmin, ea, df["WS2M"], rn, pressure)
    return pd.Series(np.clip(et0, 0, None), index=df.index, name="ET0")

"""Run the water balance for the main rotations on real NASA POWER data.

Run from the repo root:   python scripts/check_water_balance.py
Optional:                 python scripts/check_water_balance.py 41.89 -93.26 170 untiled
                          (lat, lon, AWC in mm per m, tiled|untiled)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fieldshift.data.power import load_power                     # noqa: E402
from fieldshift.model.et0 import et0_from_power                    # noqa: E402
from fieldshift.model.water_balance import load_crops, rotation_year_table   # noqa: E402
import warnings                                                    # noqa: E402
warnings.filterwarnings("ignore", message="No room for")

args = sys.argv[1:]
lat, lon = (float(args[0]), float(args[1])) if len(args) >= 2 else (42.03, -93.47)
awc = float(args[2]) if len(args) >= 3 else 200.0
tiled = not (len(args) >= 4 and args[3] == "untiled")

ROTATIONS = {                       # crops.py rotation format
    "Corn-soybean": [["corn"], ["soybean"]],
    "C-S + rye before soy": [["corn", "cereal_rye"], ["soybean"]],
    "C-S-oats/red clover": [["corn"], ["soybean"], ["oats+red_clover"]],
    "C-S-wheat": [["corn"], ["soybean"], ["winter_wheat"]],
    "C-S-oats/alfalfa-alfalfa": [["corn"], ["soybean"], ["oats+alfalfa"], ["alfalfa"]],
}

weather, meta = load_power(lat, lon, allow_download=False)
weather = weather.dropna(subset=["PRECTOTCORR", "T2M_MAX", "T2M_MIN"])
et0 = et0_from_power(weather, lat=meta["cell"]["centre"][0]).fillna(0)
crops = load_crops()

print(f"Cell {meta['cell']['id']}, AWC {awc:.0f} mm/m, {'tiled' if tiled else 'not tiled'}")
print(f"Mean rain {weather['PRECTOTCORR'].groupby(weather.index.year).sum().mean():.0f} mm/yr, "
      f"ET0 {et0.groupby(et0.index.year).sum().mean():.0f} mm/yr\n")
print(f"{'Rotation':<27}{'drain mm':>9}{'deficit mm':>11}{'worst 10%':>10}{'stress d':>9}"
      f"{'bare d':>8}{'bare+wet':>9}{'wet d':>7}")
for name, rotation in ROTATIONS.items():
    t = rotation_year_table(weather, et0, rotation, awc, tiled=tiled, crops=crops)
    worst = t["deficit_sensitive_mm"].quantile(0.9)
    cvar = t.loc[t["deficit_sensitive_mm"] >= worst, "deficit_sensitive_mm"].mean()
    print(f"{name:<27}{t['drainage_mm'].mean():9.0f}{t['deficit_sensitive_mm'].mean():11.1f}"
          f"{cvar:10.1f}{t['stressed_sensitive_days'].mean():9.1f}{t['bare_days'].mean():8.0f}"
          f"{t['bare_wet_days'].mean():9.1f}{t['waterlogged_days'].mean():7.1f}")

t = rotation_year_table(weather, et0, [["corn"], ["soybean"]], awc, tiled=tiled, crops=crops)
corn = t[t["main_crop"] == "corn"].set_index("year")["deficit_sensitive_mm"]
print("\nCorn years with the biggest water deficit at pollination:",
      ", ".join(str(y) for y in corn.nlargest(5).index))

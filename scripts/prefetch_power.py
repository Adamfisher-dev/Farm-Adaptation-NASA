"""Download NASA POWER data for the example points, then copy it to sample_data/.

Run from the repo root:   python scripts/prefetch_power.py

Each point is saved by POWER grid cell, so points in the same cell share a
file. The printout shows whether your example points fall in different cells.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fieldshift import config                                          # noqa: E402
from fieldshift.data.power import fetch_power, power_cell, save        # noqa: E402
from fieldshift.model.indicators import yearly_indicators, snapshot    # noqa: E402
from fieldshift.data.power import clean, check_units                   # noqa: E402

done = set()
for name, (lat, lon) in config.EXAMPLE_POINTS.items():
    cell = power_cell(lat, lon)
    print(f"\n{name}: ({lat}, {lon}) -> POWER cell {cell['id']}")
    if cell["id"] in done:
        print("  same cell as an earlier point, skipping download")
        continue

    df, meta = fetch_power(*cell["centre"])
    meta["cell"] = cell
    csv_path = save(df, meta)
    config.SAMPLE_DIR.mkdir(exist_ok=True)
    shutil.copy(csv_path, config.SAMPLE_DIR / csv_path.name)
    shutil.copy(csv_path.with_name(csv_path.stem + "_meta.json"), config.SAMPLE_DIR)
    done.add(cell["id"])

    for w in check_units(meta["units"]):
        print("  UNIT WARNING:", w)
    print("  units:", meta["units"])

    df = clean(df)
    annual_rain = df["PRECTOTCORR"].groupby(df.index.year).sum().mean()
    print(f"  mean annual rain: {annual_rain:.0f} mm  (rough expectation for central Iowa: 800-1000)")
    snap = snapshot(yearly_indicators(df))
    for key, s in snap.items():
        print(f"  {s['label']:<42} {s['recent_mean']:>8} {s['unit']:<14} trend {s['trend_per_decade']:+} / decade (p={s['p_value']})")

print("\nSaved to", config.POWER_DIR, "and copied to", config.SAMPLE_DIR)

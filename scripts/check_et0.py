"""Print ET0 by month for each POWER cell saved in sample_data/.

Run from the repo root:   python scripts/check_et0.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fieldshift import config                              # noqa: E402
from fieldshift.data.power import load_power                # noqa: E402
from fieldshift.model.et0 import et0_from_power             # noqa: E402

seen = set()
for name, (lat, lon) in config.EXAMPLE_POINTS.items():
    df, meta = load_power(lat, lon, allow_download=False)
    if meta["cell"]["id"] in seen:
        continue
    seen.add(meta["cell"]["id"])

    et0 = et0_from_power(df, lat=meta["cell"]["centre"][0])
    print(f"\nCell {meta['cell']['id']}  (loaded from {meta['loaded_from']})")
    print(f"  missing ET0 days: {int(et0.isna().sum())}")
    monthly = et0.groupby(et0.index.month).mean()
    print("  mean ET0 by month, mm/day:")
    print("   " + "  ".join(f"{m:>4}" for m in range(1, 13)))
    print("   " + "  ".join(f"{v:4.1f}" for v in monthly))
    annual = et0.groupby(et0.index.year).sum().mean()
    rain = df["PRECTOTCORR"].groupby(df.index.year).sum().mean()
    print(f"  mean annual ET0: {annual:.0f} mm   mean annual rain: {rain:.0f} mm")

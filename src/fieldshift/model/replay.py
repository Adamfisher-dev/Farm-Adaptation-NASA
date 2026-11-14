"""
replay.py - "Replay a hard year": how each rotation would have coped in one real past year
(playbook 6.14, idea K). Display output only; it does not change the scores.

Nothing is re-simulated: the rotation x year tables from water_balance already hold every
rotation in every weather year and every phase. For a chosen year this module reads that
year's row(s) and compares them with
  - the same rotation's typical year (median over all simulated years), and
  - the existing rotation in that same year.

Because a rotation could have had any of its crops in the field that year, values are shown
both averaged over the rotation's phases and per crop ("if corn was in the field: ...").

    from fieldshift.model import replay
    years = replay.suggest_years(tables, existing_id)            # {"Driest at pollination": [2012, 1988, ...], ...}
    table = replay.replay_table(tables, 2012, existing_id)       # one row per rotation x measure
    block = replay.contract_block(tables, 2012)                  # results[i]["replay"] (contract 10.3)

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fieldshift.model import scoring

# Measures shown in the replay: column of the rotation x year table -> (label, unit, lower_is_better)
MEASURES = {
    "drought_deficit_mm": ("Water the crop missed in its sensitive window", "mm", True),
    "drought_stress_days": ("Water-stressed days in the sensitive window", "days", True),
    "drainage_mm": ("Water draining from the field (nitrate-loss proxy)", "mm", True),
    "bare_wet_days": ("Bare days with erosive rain", "days", True),
    "bare_wet_spring_days": ("Bare days with erosive rain, March-June", "days", True),
    "waterlogged_days": ("Waterlogged days", "days", True),
}

# Automatic shortlist: label -> (column, take the highest values?) on the EXISTING rotation
SUGGESTIONS = {
    "Driest at the sensitive stage": ("drought_deficit_mm", True),
    "Most water (and nitrate) draining": ("drainage_mm", True),
    "Most erosion risk in spring": ("bare_wet_spring_days", True),
    "Wettest (waterlogging)": ("waterlogged_days", True),
}


# --- Per-year values -------------------------------------------------------------------
def per_year(table: pd.DataFrame, column: str) -> pd.Series:
    """One value per weather year: mean over the rotation's phases."""
    return table.groupby("year")[column].mean()


def by_crop(table: pd.DataFrame, year: int, column: str) -> dict:
    """{crop in the field that year: value} for one year (one entry per phase)."""
    rows = table[table["year"] == year]
    crop_col = "cash_crop" if "cash_crop" in rows else "main_crop"
    return {str(c): round(float(v), 1) for c, v in zip(rows[crop_col], rows[column])}


def year_rank(series: pd.Series, year: int, worst_is_high: bool = True) -> int:
    """1 = the worst year on record for this measure."""
    order = series.sort_values(ascending=not worst_is_high)
    return int(list(order.index).index(year) + 1)


# --- Suggested years ---------------------------------------------------------------------
def suggest_years(tables: dict, existing_id: str, n: int = 3, weather_notable: dict | None = None) -> dict:
    """Hard years to offer in the picker, found in the model results for the existing rotation
    (plus, if given, indicators.notable_years from the weather). Confirm a year stands out
    here before demoing it (e.g. 2012)."""
    t = tables[existing_id]
    out = {}
    for label, (col, high) in SUGGESTIONS.items():
        if col not in t:
            continue
        s = per_year(t, col)
        if s.max() <= 0:                       # e.g. no waterlogging at all on a tiled field
            continue
        picks = s.nlargest(n) if high else s.nsmallest(n)
        out[label] = [int(y) for y in picks.index]
    if weather_notable:
        simulated = set(t["year"])
        for label, years in weather_notable.items():
            pretty = label.replace("_", " ").capitalize() + " (weather)"
            out[pretty] = [int(y) for y in years if y in simulated]
    return out


# --- The replay ------------------------------------------------------------------------------
def replay_table(tables: dict, year: int, existing_id: str | None = None,
                 measures: dict | None = None) -> pd.DataFrame:
    """One row per (rotation, measure) for the chosen year:
        that_year      value in that year (mean over the rotation's phases)
        typical        the rotation's median year
        vs_typical     that_year - typical
        rank           1 = worst year on record for this rotation and measure
        of             number of simulated years
        vs_existing    that_year - existing rotation's that_year (negative = better when lower is better)
        by_crop        {crop: value} - what it would have been with each crop in the field
    """
    measures = measures or MEASURES
    first = next(iter(tables.values()))
    if year not in set(first["year"]):
        lo, hi = int(first["year"].min()), int(first["year"].max())
        raise ValueError(f"{year} is not in the simulated years ({lo}-{hi}).")
    rows = []
    existing_vals = {}
    if existing_id is not None:
        te = tables[existing_id]
        existing_vals = {c: float(per_year(te, c).loc[year]) for c in measures if c in te}
    for rid, t in tables.items():
        for col, (label, unit, lower_better) in measures.items():
            if col not in t:
                continue
            s = per_year(t, col)
            val, typ = float(s.loc[year]), float(s.median())
            rows.append({
                "rotation": rid, "measure": col, "label": label, "unit": unit,
                "that_year": round(val, 1), "typical": round(typ, 1), "vs_typical": round(val - typ, 1),
                "rank": year_rank(s, year, worst_is_high=lower_better), "of": int(len(s)),
                "vs_existing": round(val - existing_vals[col], 1) if col in existing_vals else np.nan,
                "by_crop": by_crop(t, year, col),
            })
    return pd.DataFrame(rows).set_index(["rotation", "measure"])


def contract_block(tables: dict, year: int, spec: dict | None = None) -> dict:
    """{rotation: {"year", "criteria": {criterion: {"that_year", "typical"}}}} for the simulated
    criteria in content/criteria.yaml (contract 10.3 results[i]["replay"]). Values are that year's
    mean over phases vs the median year (single-year values, so no CVaR)."""
    spec = spec or scoring.load_criteria()
    out = {}
    for rid, t in tables.items():
        crit = {}
        for name, c in spec["criteria"].items():
            if c["type"] in ("simulated", "counted") and c["column"] in t:
                s = per_year(t, c["column"])
                crit[name] = {"that_year": round(float(s.loc[year]), 1), "typical": round(float(s.median()), 1),
                              "unit": c.get("unit", "")}
        out[rid] = {"year": int(year), "criteria": crit}
    return out


def sentence(tables: dict, year: int, rotation: str, column: str = "drought_deficit_mm") -> str:
    """Plain-language line for a card, e.g.
    'In 2012 the crop would have missed 99 mm of water at its sensitive stage (typical year: 31 mm)
     - the worst of 42 years.'"""
    t = tables[rotation]
    s = per_year(t, column)
    label, unit, lower_better = MEASURES[column]
    r = year_rank(s, year, worst_is_high=lower_better)
    where = "the worst" if r == 1 else f"the {_ordinal(r)} worst"
    crops = by_crop(t, year, column)
    crop_bit = ""
    if len(crops) > 1:
        one = "day" if unit == "days" else unit
        crop_bit = " (" + ", ".join(f"{c.replace('_', ' ')} {v:.0f} {one if v == 1 else unit}"
                                    for c, v in crops.items()) + ")"
    label = label[0].lower() + label[1:]
    return (f"In {year}: {label} {s.loc[year]:.0f} {unit}{crop_bit}; typical year {s.median():.0f} {unit}"
            f" - {where} of {len(s)} years.")


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# --- Self-check -----------------------------------------------------------------------------------
if __name__ == "__main__":
    import warnings
    warnings.simplefilter("ignore")
    from fieldshift import pipeline

    allowed = pipeline.filter_rotations(hay_buyer=True, hay_equipment=True)
    out = pipeline.run_basic(42.18, -93.66, rotations=allowed, allow_download=False)
    tables, e = out["tables"], out["baseline"]

    years = suggest_years(tables, e, weather_notable=out["notable_years"])
    print("Suggested hard years:")
    for k, v in years.items():
        print(f"  {k:<40} {v}")
    assert 2012 in years["Driest at the sensitive stage"], "2012 should stand out as a drought year"

    tbl = replay_table(tables, 2012, e)
    show = tbl.xs("drought_deficit_mm", level="measure")[["that_year", "typical", "rank", "of", "vs_existing", "by_crop"]]
    print("\n2012 - water missed in the sensitive window (mm):")
    print(show.to_string())
    print("\n" + sentence(tables, 2012, e))
    print(sentence(tables, 2019, e, "bare_wet_spring_days"))

    block = contract_block(tables, 2012)
    print("\ncontract block (existing):", block[e])
    assert tbl.loc[(e, "drought_deficit_mm"), "vs_existing"] == 0
    assert set(block[e]["criteria"]) == {"drought_risk", "water_leaving", "erosion_exposure"}
    try:
        replay_table(tables, 1982, e)
        raise AssertionError("1982 should be rejected (no solar data, not simulated)")
    except ValueError as err:
        print("\n1982 rejected as expected:", err)
    print("\nOK - checks passed.")

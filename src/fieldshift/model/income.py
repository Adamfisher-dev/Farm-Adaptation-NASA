"""
income.py - Typical income of each rotation, USD per acre per year (the 'income' criterion,
playbook 6.3). Reads content/income.csv and content/income_adjustments.csv.

    net return of a year = yield x price - production cost            (cash crop)
                         - cover-crop cost + cost-share               (cover crop that winter)
                         - seed cost of a crop sown under the oats    (red clover, alfalfa)
    rotation income      = average over the rotation's years

Rotation effects (income_adjustments.csv), applied to the crop's yield or cost:
    corn after corn            yield change + extra cost (more N, rootworm control)
    3-4 year rotations         corn and soybean yield change (Marsden Farm, whole-system result)
    corn after alfalfa/clover  nitrogen credit (fertiliser saved)
    corn after a rye cover     yield change (0 if terminated in time)

Prices: "mid" (price), "low" (price_low) or "high" (price_high) - income_range() gives all three,
so a card can say "about $95/acre ($60-130 depending on prices)".

This compares rotations; it is not a profit forecast. Yields are typical county yields with
literature rotation effects, not a crop-growth model (playbook: never claim more than the tool does).

If any value a rotation needs is missing, that rotation gets no income (NaN) and the income
criterion is left out of the score, with the missing cells listed - never a guessed number.

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from fieldshift import config

INCOME_CSV = config.CONTENT_DIR / "income.csv"
ADJUSTMENTS_CSV = config.CONTENT_DIR / "income_adjustments.csv"
UNDERSEED_ROW = {"red_clover": "red_clover", "alfalfa": "alfalfa_establishment"}
LONG_ROTATION_YEARS = 3          # 3+ year rotations that add a crop other than corn/soybean get the
                                 # long-rotation (Marsden) yield effect; corn-corn-soybean does not
LEGUMES_FOR_N = {"alfalfa", "red_clover"}


# --- Loading ----------------------------------------------------------------------------
@lru_cache(maxsize=4)
def _read(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8")


def load_tables(income_path=None, adjustments_path=None) -> tuple[pd.DataFrame, dict]:
    """(crop table indexed by crop, {effect: value or NaN})."""
    ip = Path(income_path or INCOME_CSV)
    ap = Path(adjustments_path or ADJUSTMENTS_CSV)
    crops = _read(str(ip), ip.stat().st_mtime).set_index("crop")
    adj = {}
    if ap.exists():
        a = _read(str(ap), ap.stat().st_mtime)
        adj = {r.effect: pd.to_numeric(r.value, errors="coerce") for r in a.itertuples()}
    return crops, adj


def _num(crops: pd.DataFrame, crop: str, col: str):
    if crop not in crops.index:
        return np.nan
    return pd.to_numeric(crops.loc[crop, col], errors="coerce")


# --- One rotation ------------------------------------------------------------------------------
def rotation_income(plan, crops: pd.DataFrame | None = None, adj: dict | None = None,
                    price: str = "mid") -> dict:
    """Income of one rotation (crops.py plan format).

    Returns {"usd_per_acre": float or NaN, "years": [per-year breakdown], "missing": [cells needed]}.
    """
    if crops is None:
        crops, adj = load_tables()
    adj = adj or {}
    price_col = {"mid": "price", "low": "price_low", "high": "price_high"}[price]
    n = len(plan)
    missing, years = [], []
    diversified = n >= LONG_ROTATION_YEARS and any(
        c not in ("corn", "soybean") for y in plan for c in y[0].split("+"))

    def need(crop, col):
        v = _num(crops, crop, col)
        if pd.isna(v):
            missing.append(f"income.csv: {crop}.{col}")
        return v

    def effect(name, default=0.0, required=True):
        v = adj.get(name, np.nan)
        if pd.isna(v):
            if required:
                missing.append(f"income_adjustments.csv: {name}")
            return default
        return float(v)

    for i, year in enumerate(plan):
        cash, _, under = year[0].partition("+")
        cover = year[1] if len(year) > 1 else None
        prev = plan[i - 1]
        prev_cash, _, prev_under = prev[0].partition("+")
        prev_cover = prev[1] if len(prev) > 1 else None

        y, p, c = need(cash, "yield"), need(cash, price_col), need(cash, "cost_per_acre")
        yield_pct, extra_cost, n_credit = 0.0, 0.0, 0.0
        notes = []
        if cash == "corn" and n > 1 and prev_cash == "corn":
            yield_pct += effect("corn_after_corn_yield_pct")
            extra_cost += effect("corn_after_corn_extra_cost")
            notes.append("corn after corn")
        if diversified and cash in ("corn", "soybean"):
            yield_pct += effect(f"long_rotation_{cash}_yield_pct")
            notes.append(f"{n}-year rotation")
        if cash == "corn" and (prev_cash in LEGUMES_FOR_N or prev_under in LEGUMES_FOR_N):
            n_credit = effect("n_credit_after_legume")
            notes.append("N credit after legume")
        if cash == "corn" and prev_cover == "cereal_rye":
            yield_pct += effect("rye_before_corn_yield_pct")
            notes.append("after rye cover")

        cash_net = y * (1 + yield_pct / 100.0) * p - c - extra_cost + n_credit
        under_cost = need(UNDERSEED_ROW.get(under, under), "cost_per_acre") if under else 0.0
        cover_net = 0.0
        if cover:
            cover_net = -need(cover, "cost_per_acre") + (_num(crops, cover, "costshare_per_acre")
                                                         if pd.notna(_num(crops, cover, "costshare_per_acre")) else 0.0)
        total = cash_net - under_cost + cover_net
        years.append({"year_in_rotation": i + 1, "crop": cash, "cash_net": cash_net, "underseed_cost": under_cost,
                      "cover_net": cover_net, "total": total, "adjustments": notes})

    value = float(np.mean([yr["total"] for yr in years])) if not missing else np.nan
    return {"usd_per_acre": round(value, 1) if not np.isnan(value) else np.nan,
            "years": years, "missing": sorted(set(missing))}


def income_range(plan, crops=None, adj=None) -> dict:
    """{"low", "mid", "high"} USD/acre/yr for the three price columns (NaN where data are missing)."""
    if crops is None:
        crops, adj = load_tables()
    return {p: rotation_income(plan, crops, adj, p)["usd_per_acre"] for p in ("low", "mid", "high")}


# --- Many rotations (what the pipeline calls) ------------------------------------------------------
def rotation_incomes(rotations: dict, price: str = "mid", income_path=None, adjustments_path=None) -> dict:
    """{name: plan} -> {"income": {name: USD/acre/yr} for rotations with complete data,
                        "missing": {name: [cells]}, "complete": bool}.
    Pass result["income"] to pipeline.run_basic(income=...) only when complete is True: scoring
    needs a value for every rotation compared, or the income criterion is left out."""
    try:
        crops, adj = load_tables(income_path, adjustments_path)
    except FileNotFoundError as err:
        return {"income": {}, "missing": {"all": [str(err)]}, "complete": False}
    income, missing = {}, {}
    for name, plan in rotations.items():
        res = rotation_income(plan, crops, adj, price)
        if res["missing"]:
            missing[name] = res["missing"]
        else:
            income[name] = res["usd_per_acre"]
    return {"income": income, "missing": missing, "complete": not missing and bool(income)}


def missing_summary(result: dict) -> str:
    """One line listing the cells still to fill in (for notes / the evidence page)."""
    cells = sorted({c for cs in result["missing"].values() for c in cs})
    if not cells:
        return ""
    head = ", ".join(cells[:6]) + (f" and {len(cells) - 6} more" if len(cells) > 6 else "")
    return f"Income not scored yet: {len(cells)} values missing ({head})."


# --- Self-check with MADE-UP numbers (temporary files; content/ is not touched) --------------------------
if __name__ == "__main__":
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    # made-up: yield x price - cost gives corn 100, soybean 90, oats 25, wheat 45, alfalfa 140 USD/acre
    pd.DataFrame([
        ("corn", "cash", 200, "bu", 4.50, 3.80, 5.20, 800, None),
        ("soybean", "cash", 60, "bu", 11.00, 9.50, 12.50, 570, None),
        ("oats", "cash", 80, "bu", 3.50, 3.00, 4.00, 255, None),
        ("winter_wheat", "cash", 70, "bu", 6.00, 5.00, 7.00, 375, None),
        ("alfalfa", "cash", 4.5, "ton", 200, 160, 240, 760, None),
        ("cereal_rye", "cover", None, None, None, None, None, 35, 0),
        ("red_clover", "underseed", None, None, None, None, None, 20, None),
        ("alfalfa_establishment", "underseed", None, None, None, None, None, 40, None),
    ], columns=["crop", "role", "yield", "yield_unit", "price", "price_low", "price_high",
                "cost_per_acre", "costshare_per_acre"]).to_csv(tmp / "income.csv", index=False)
    pd.DataFrame({"effect": ["corn_after_corn_yield_pct", "corn_after_corn_extra_cost", "long_rotation_corn_yield_pct",
                             "long_rotation_soybean_yield_pct", "n_credit_after_legume", "rye_before_corn_yield_pct"],
                  "value": [0, 0, 0, 0, 30, 0]}).to_csv(tmp / "adj.csv", index=False)
    crops, adj = load_tables(tmp / "income.csv", tmp / "adj.csv")

    cases = {
        "C-S": ([["corn"], ["soybean"]], 95.0),
        "C-S + rye": ([["corn", "cereal_rye"], ["soybean", "cereal_rye"]], 60.0),
        "C-S-O/A-A": ([["corn"], ["soybean"], ["oats+alfalfa"], ["alfalfa"]], 86.25),
    }
    for name, (plan, expected) in cases.items():
        r = rotation_income(plan, crops, adj)
        rng = income_range(plan, crops, adj)
        print(f"{name:<10} ${r['usd_per_acre']:>6.1f}/acre (low {rng['low']:.0f}, high {rng['high']:.0f}) | "
              + "; ".join(f"{y['crop']} {y['total']:.0f}" + (f" ({', '.join(y['adjustments'])})" if y['adjustments'] else "")
                          for y in r["years"]))
        assert abs(r["usd_per_acre"] - expected) < 0.1, (name, r["usd_per_acre"], expected)

    # yield effects: corn after corn -10 % and +$40; long rotation +4 % corn / +16 % soybean
    adj2 = dict(adj, corn_after_corn_yield_pct=-10, corn_after_corn_extra_cost=40,
                long_rotation_corn_yield_pct=4, long_rotation_soybean_yield_pct=16)
    ccs = rotation_income([["corn"], ["corn"], ["soybean"]], crops, adj2)
    print("C-C-S with effects:", ccs["usd_per_acre"], [round(y["total"]) for y in ccs["years"]])
    assert abs(ccs["years"][1]["total"] - (200 * 0.90 * 4.5 - 800 - 40)) < 1e-6   # -10 %, no Marsden bonus (not diversified)
    csoaa = rotation_income([["corn"], ["soybean"], ["oats+alfalfa"], ["alfalfa"]], crops, adj2)
    assert abs(csoaa["years"][1]["total"] - (60 * 1.16 * 11 - 570)) < 1e-6        # +16 % soybean in a diversified rotation

    # the real template is still blank -> nothing is scored, and the missing cells are listed
    res = rotation_incomes({"C-S": [["corn"], ["soybean"]]})
    print("\ncontent/income.csv:", "complete" if res["complete"] else missing_summary(res))
    assert not res["complete"]
    print("\nOK - checks passed.")

"""
scoring.py - Turn each rotation's results into comparable values and a weighted score
(playbook 6.4-6.6). Driven by content/criteria.yaml: which criteria exist, where each
raw value comes from, its statistic, direction, scale and cap.

Steps
  1. raw_criteria   rotation x year tables (water_balance) + ordinal scores (rotations.py)
                    -> one raw value per rotation and criterion, in real units
                    (statistic: mean, or cvar_0.10 = mean of the worst 10 % of years)
  2. normalise      relative to the EXISTING rotation, which scores exactly 0.5 (playbook 6.5):
                      cost:    r = (x_existing - x) / max(|x_existing|, scale)
                      benefit: r = (x - x_existing) / max(|x_existing|, scale)
                      v = 0.5 + 0.5 * clip(r / cap, -1, 1)
                      ordinal: v = 0.5 + (level - level_existing) / 6
                    > 0.5 = better than now. Not min-max across candidates: adding or
                    removing a candidate must not reorder the others.
  3. criterion_weights  slider weights -> criteria (split equally within a slider, 6.4);
                    criteria with no data (income for now) are dropped and the rest renormalised
  4. score          S = V @ w, plus each criterion's contribution w_k * v_k (for the stacked bar)
  5. pareto_dominated  A dominates B if A >= B on every criterion and > on one (no weights)

Robustness (Dirichlet weights x year bootstrap, P(rank first)) builds on these
functions in bootstrap.py.

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from fieldshift import config

CRITERIA_PATH = config.CONTENT_DIR / "criteria.yaml"


# --- Loading ---------------------------------------------------------------------
@lru_cache(maxsize=4)
def _load_cached(path: str, mtime: float) -> dict:
    with open(path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    for name, c in spec["criteria"].items():
        for key in ("type", "column", "statistic", "direction", "slider"):
            if key not in c:
                raise KeyError(f"{path}: criterion {name} missing '{key}'")
        if c["slider"] not in spec["sliders"]:
            raise KeyError(f"{path}: criterion {name} uses unknown slider {c['slider']!r}")
    return spec


def load_criteria(path: str | Path | None = None) -> dict:
    """Parsed content/criteria.yaml (re-read automatically when the file changes)."""
    p = Path(path) if path else CRITERIA_PATH
    return _load_cached(str(p), p.stat().st_mtime)


# --- 1. Raw values ---------------------------------------------------------------------
def statistic(values: pd.Series, how: str, direction: str = "cost") -> float:
    """mean, or cvar_<q>: mean of the worst q share of years (worst = highest for a cost)."""
    v = pd.Series(values, dtype=float).dropna()
    if v.empty:
        return np.nan
    if how == "mean":
        return float(v.mean())
    if how.startswith("cvar_"):
        q = float(how.split("_", 1)[1])
        k = max(1, int(np.ceil(q * len(v))))
        worst = v.nlargest(k) if direction == "cost" else v.nsmallest(k)
        return float(worst.mean())
    raise ValueError(f"Unknown statistic {how!r}")


def raw_criteria(tables: dict, ordinal_scores: dict | None = None, slope_factor: float | None = None,
                 extra: dict | None = None, spec: dict | None = None) -> pd.DataFrame:
    """Raw value per rotation (rows) and criterion (columns), in real units.

    tables          {rotation_id: rotation x year table from water_balance.simulate_rotation}
    ordinal_scores  {rotation_id: Rotation.scores dict}  (n_benefit, pest_break, som_proxy)
    slope_factor    RUSLE S factor of the field (terrain.py); multiplies erosion exposure.
                    It is the same for every rotation, so it changes the reported value, not the
                    ranking (the existing rotation is scaled by the same factor).
    extra           {rotation_id: {column: value}} for 'data' criteria (income, when available)
    Missing data -> NaN (the criterion is then left out of the score).
    """
    spec = spec or load_criteria()
    ordinal_scores, extra = ordinal_scores or {}, extra or {}
    rows = {}
    for rid, table in tables.items():
        row = {}
        for name, c in spec["criteria"].items():
            col = c["column"]
            if c["type"] in ("simulated", "counted"):
                if table is None or col not in table:
                    row[name] = np.nan
                    continue
                val = statistic(table[col], c["statistic"], c["direction"])
                if name == "erosion_exposure" and slope_factor:
                    val *= slope_factor
                row[name] = val
            elif c["type"] == "literature":
                row[name] = float(ordinal_scores.get(rid, {}).get(col, np.nan))
            else:  # data
                row[name] = float(extra.get(rid, {}).get(col, np.nan))
        rows[rid] = row
    return pd.DataFrame.from_dict(rows, orient="index")[list(spec["criteria"])]


# --- 2. Normalise -------------------------------------------------------------------------
def criterion_value(x, x_existing, c: dict) -> np.ndarray:
    """THE normalisation rule (playbook 6.5) for one criterion; works on scalars or numpy arrays
    of any shape (bootstrap.py passes all replicates at once). Existing rotation -> 0.5."""
    x = np.asarray(x, dtype=float)
    xe = np.asarray(x_existing, dtype=float)
    if c.get("unit") == "ordinal_0_3":
        v = 0.5 + (x - xe) / 6.0
    else:
        if c.get("relative", True):        # change relative to the current rotation (most criteria)
            denom = np.maximum(np.abs(xe), float(c.get("scale", 1.0)))
        else:                               # absolute change in the criterion's own unit (income, $)
            denom = np.full_like(np.asarray(xe, dtype=float), float(c.get("scale", 1.0)))
        r = (xe - x) / denom if c["direction"] == "cost" else (x - xe) / denom
        v = 0.5 + 0.5 * np.clip(r / float(c.get("cap", 0.5)), -1, 1)
    return np.clip(v, 0, 1)


def normalise(raw: pd.DataFrame, existing_id: str, spec: dict | None = None) -> pd.DataFrame:
    """Values v in [0, 1], existing rotation = 0.5 on every criterion (NaN stays NaN)."""
    spec = spec or load_criteria()
    if existing_id not in raw.index:
        raise KeyError(f"Existing rotation {existing_id!r} is not in the results")
    base = raw.loc[existing_id]
    out = pd.DataFrame(index=raw.index, columns=raw.columns, dtype=float)
    for name in raw.columns:
        out[name] = criterion_value(raw[name].to_numpy(), base[name], spec["criteria"][name])
    return out


# --- 3. Weights ------------------------------------------------------------------------------
def criterion_weights(slider_weights: dict, available: list | None = None, spec: dict | None = None) -> pd.Series:
    """Slider weights -> criterion weights summing to 1.

    Each slider's weight is split equally among its criteria that have data (playbook 6.4).
    Sliders with no available criterion are dropped and the rest renormalised.
    """
    spec = spec or load_criteria()
    crit = spec["criteria"]
    available = list(crit) if available is None else list(available)
    w = {}
    for slider, sw in slider_weights.items():
        names = [n for n, c in crit.items() if c["slider"] == slider and n in available]
        for n in names:
            w[n] = w.get(n, 0.0) + float(sw) / len(names)
    s = pd.Series(w, dtype=float).reindex(available).fillna(0.0)
    total = s.sum()
    if total <= 0:                                   # nothing usable: equal weights
        s[:] = 1.0 / len(s)
    else:
        s /= total
    return s


def rank_order_centroid(n: int) -> list:
    """Weights from a priority ranking (1st..nth): w_i = (1/n) sum_{k=i}^{n} 1/k (playbook 6.4)."""
    return [sum(1.0 / k for k in range(i, n + 1)) / n for i in range(1, n + 1)]


# --- 4. Score ----------------------------------------------------------------------------------
def score(values: pd.DataFrame, weights: pd.Series) -> pd.DataFrame:
    """Weighted score per rotation + contribution of each criterion (w_k * v_k)."""
    cols = [c for c in weights.index if weights[c] > 0]
    v = values[cols]
    contrib = v.mul(weights[cols], axis=1)
    out = contrib.add_prefix("contrib_")
    out.insert(0, "score", contrib.sum(axis=1))
    return out


# --- 5. Pareto --------------------------------------------------------------------------------
def pareto_dominated(values: pd.DataFrame) -> pd.Series:
    """True where some other rotation is >= on every criterion and > on at least one."""
    v = values.dropna(axis=1, how="any").to_numpy(float)
    idx = values.index
    dom = np.zeros(len(idx), dtype=bool)
    for i in range(len(idx)):
        for j in range(len(idx)):
            if i != j and np.all(v[j] >= v[i]) and np.any(v[j] > v[i]):
                dom[i] = True
                break
    return pd.Series(dom, index=idx, name="pareto_dominated")


# --- All together ------------------------------------------------------------------------------
def score_rotations(raw: pd.DataFrame, existing_id: str, slider_weights: dict,
                    spec: dict | None = None) -> dict:
    """raw criteria -> values, weights, scores, Pareto flags, ranked (existing first in ties).

    Returns {"values", "weights", "scores" (sorted, best first), "pareto", "slider_values",
             "dropped": criteria left out for lack of data}.
    """
    spec = spec or load_criteria()
    values = normalise(raw, existing_id, spec)
    available = [c for c in values.columns if values[c].notna().all()]
    dropped = [c for c in values.columns if c not in available]
    w = criterion_weights(slider_weights, available, spec)
    sc = score(values[available], w)
    sc["pareto_dominated"] = pareto_dominated(values[available])
    sc["is_existing"] = sc.index == existing_id
    sc = sc.sort_values(["score", "is_existing"], ascending=[False, False])

    # one value per slider (mean of its criteria), for simple bar charts
    slider_values = pd.DataFrame(index=values.index)
    for slider in spec["sliders"]:
        names = [n for n in available if spec["criteria"][n]["slider"] == slider]
        if names:
            slider_values[slider] = values[names].mean(axis=1)
    return {"values": values, "weights": w, "scores": sc, "pareto": sc["pareto_dominated"],
            "slider_values": slider_values, "dropped": dropped}


# --- Self-check: playbook 6.10 toy example ----------------------------------------------------------
if __name__ == "__main__":
    toy_spec = {
        "sliders": ["drought", "soil_erosion", "pests_fertiliser"],
        "criteria": {
            "drought_risk": {"type": "simulated", "column": "d", "statistic": "mean", "direction": "cost",
                             "slider": "drought", "unit": "mm", "scale": 1.0, "cap": 0.5},
            "erosion_exposure": {"type": "counted", "column": "e", "statistic": "mean", "direction": "cost",
                                 "slider": "soil_erosion", "unit": "days", "scale": 1.0, "cap": 0.5},
            "n_benefit": {"type": "literature", "column": "n", "statistic": "fixed", "direction": "benefit",
                          "slider": "pests_fertiliser", "unit": "ordinal_0_3"},
        },
    }
    raw = pd.DataFrame({"drought_risk": [120, 125, 100], "erosion_exposure": [60, 30, 25],
                        "n_benefit": [1, 1, 3]}, index=["C-S", "+ rye", "+ oats/alfalfa"])
    res = score_rotations(raw, "C-S", {"drought": 0.4, "soil_erosion": 0.4, "pests_fertiliser": 0.2}, toy_spec)
    print("Playbook 6.10 toy example:")
    print(res["values"].round(2).to_string())
    print(res["scores"][["score", "pareto_dominated"]].round(2).to_string())
    s = res["scores"]["score"]
    assert abs(s["C-S"] - 0.50) < 1e-9
    assert abs(s["+ rye"] - 0.683) < 0.005 and abs(s["+ oats/alfalfa"] - 0.833) < 0.005
    assert [round(x, 2) for x in rank_order_centroid(5)] == [0.46, 0.26, 0.16, 0.09, 0.04]
    assert statistic(pd.Series(range(1, 21)), "cvar_0.10") == 19.5      # worst 2 of 20 years
    print("\nOK - reproduces the playbook toy example (0.50 / 0.68 / 0.83).")

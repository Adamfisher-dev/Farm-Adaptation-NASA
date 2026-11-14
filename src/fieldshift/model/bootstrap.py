"""
bootstrap.py - How sure are we? Year bootstrap + weight sampling on top of scoring.py
(playbook 6.7 and 6.9).

Why: next year's weather is unknown, and ~42 years is a small sample (the worst 10 % of
years rests on 4-5 seasons). So instead of one score per rotation we compute many:

  1. Year bootstrap   draw the weather years again WITH replacement (whole years, not days,
                      so each season stays intact). The SAME drawn years are used for every
                      rotation, so rotations are always compared on the same weather (paired).
  2. Statistic        each replicate recomputes every simulated criterion from the drawn years
                      (mean, or CVaR = mean of the worst 10 %), using all rotation phases.
  3. Weights          each replicate also draws criterion weights near the farmer's:
                      w ~ Dirichlet(alpha * w_farmer)  (alpha ~20: close to, not equal to, the sliders)
  4. Score            normalise vs the existing rotation (scoring.py rules) and score each replicate.
  => score mean and 5-95 % range per rotation, P(rank first), and a 5-95 % range for every
     raw criterion value.

Climate period (6.9): "all" years equally; "recent30" = last 30 years only; "weighted" =
exponential weights w_y = 2^-((end - y) / half_life) used as draw probabilities.
robustness() checks whether the top rotation changes between these.

Literature criteria (ordinal scores) have no year-to-year variation; they enter every
replicate unchanged. Criteria with no data (income for now) are left out.

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fieldshift.model import scoring

N_BOOT = 1000
DIRICHLET_ALPHA = 20.0
HALF_LIFE_YEARS = 15.0
RECENT_YEARS = 30
STRESSED_YEAR_DEFICIT_MM = 50.0   # a year counts as "water-stressed" if the crop missed more than
                                  # this much water in its sensitive window (about 10 days of full
                                  # crop water use). STARTING VALUE - agronomist should review.


# --- Year weights --------------------------------------------------------------------
def year_weights(years, window: str = "all", half_life: float = HALF_LIFE_YEARS,
                 recent_n: int = RECENT_YEARS) -> np.ndarray:
    """Draw probability for each year (sums to 1).
    all: equal; recent30: equal over the last recent_n years, 0 before; weighted: 2^-((end-y)/h)."""
    years = np.asarray(years, dtype=float)
    end = years.max()
    if window == "all":
        w = np.ones_like(years)
    elif window in ("recent30", "recent"):
        w = (years > end - recent_n).astype(float)
    elif window == "weighted":
        w = 2.0 ** (-(end - years) / half_life)
    else:
        raise ValueError(f"window must be all | recent30 | weighted, got {window!r}")
    return w / w.sum()


def effective_sample_size(probs) -> float:
    """How many full-weight years the weighting is worth: (sum w)^2 / sum w^2 (playbook 6.9)."""
    p = np.asarray(probs, dtype=float)
    return float(p.sum() ** 2 / (p ** 2).sum())


# --- Arrange the rotation x year tables ---------------------------------------------------
def _year_cube(tables: dict, column: str, years: np.ndarray) -> dict:
    """{rotation: array (n_years, n_phases)} of one column; rows follow `years`."""
    cube = {}
    for rid, t in tables.items():
        if column not in t:
            continue
        wide = t.pivot_table(index="year", columns="phase", values=column, aggfunc="first")
        cube[rid] = wide.reindex(years).to_numpy(float)
    return cube


def _stat_rows(x: np.ndarray, how: str, direction: str) -> np.ndarray:
    """Statistic along axis 1 of x (n_boot, n_values): mean or cvar_<q> (worst q share)."""
    if how == "mean":
        return np.nanmean(x, axis=1)
    if how.startswith("cvar_"):
        q = float(how.split("_", 1)[1])
        n = x.shape[1]
        k = max(1, int(np.ceil(q * n)))
        s = np.sort(x, axis=1)                         # ascending
        worst = s[:, n - k:] if direction == "cost" else s[:, :k]
        return worst.mean(axis=1)
    raise ValueError(f"Unknown statistic {how!r}")


# --- Core ------------------------------------------------------------------------------------
def bootstrap_raw(tables: dict, ordinal_scores: dict | None = None, slope_factor: float | None = None,
                  n_boot: int = N_BOOT, window: str = "all", half_life: float = HALF_LIFE_YEARS,
                  seed: int = 0, spec: dict | None = None, extra: dict | None = None):
    """Raw criterion values for every bootstrap replicate.

    Returns (raw array (n_boot, n_rot, n_crit), rotation ids, criterion names, years, probs).
    Replicate 0 is NOT special; all replicates are random draws.
    """
    spec = spec or scoring.load_criteria()
    ordinal_scores, extra = ordinal_scores or {}, extra or {}
    rids = list(tables)
    crits = list(spec["criteria"])
    years = np.array(sorted(set().union(*[set(t["year"]) for t in tables.values()])))
    probs = year_weights(years, window, half_life)
    rng = np.random.default_rng(seed)
    draws = rng.choice(len(years), size=(n_boot, len(years)), p=probs)   # same years for all rotations

    raw = np.full((n_boot, len(rids), len(crits)), np.nan)
    for j, name in enumerate(crits):
        c = spec["criteria"][name]
        if c["type"] in ("simulated", "counted"):
            cube = _year_cube(tables, c["column"], years)
            for i, rid in enumerate(rids):
                if rid not in cube:
                    continue
                sample = cube[rid][draws]                       # (n_boot, n_years, n_phases)
                vals = _stat_rows(sample.reshape(n_boot, -1), c["statistic"], c["direction"])
                if name == "erosion_exposure" and slope_factor:
                    vals = vals * slope_factor
                raw[:, i, j] = vals
        elif c["type"] == "literature":
            for i, rid in enumerate(rids):
                raw[:, i, j] = float(ordinal_scores.get(rid, {}).get(c["column"], np.nan))
        else:  # "data" criteria (income): one fixed value per rotation from `extra`, NaN if missing
            for i, rid in enumerate(rids):
                raw[:, i, j] = float(extra.get(rid, {}).get(c["column"], np.nan))
    return raw, rids, crits, years, probs


def _normalise_array(raw: np.ndarray, existing: int, crits: list, spec: dict) -> np.ndarray:
    """Normalise every replicate at once with scoring.criterion_value (the one shared rule)."""
    base = raw[:, existing:existing + 1, :]                     # (B, 1, C)
    v = np.empty_like(raw)
    for j, name in enumerate(crits):
        v[:, :, j] = scoring.criterion_value(raw[:, :, j], base[:, :, j], spec["criteria"][name])
    return v


def run_bootstrap(tables: dict, existing_id: str, slider_weights: dict, ordinal_scores: dict | None = None,
                  slope_factor: float | None = None, n_boot: int = N_BOOT, window: str = "all",
                  half_life: float = HALF_LIFE_YEARS, alpha: float = DIRICHLET_ALPHA,
                  sample_weights: bool = True, seed: int = 0, spec: dict | None = None,
                  extra: dict | None = None) -> dict:
    """Score distribution per rotation under year resampling (+ weight sampling).

    Returns {
      "summary":   DataFrame per rotation: score_mean, score_p05, score_p95, p_top, rank_mean
                   (sorted best first; contract 10.3 "score" = mean/p05/p95/p_top),
      "criteria":  DataFrame (rotation, criterion): value, p05, p95 in real units,
      "weights":   farmer criterion weights used, "scores": array (n_boot, n_rot),
      "window", "n_years", "n_eff", "n_boot", "dropped": criteria without data }
    """
    spec = spec or scoring.load_criteria()
    raw, rids, crits, years, probs = bootstrap_raw(tables, ordinal_scores, slope_factor, n_boot,
                                                   window, half_life, seed, spec, extra)
    if existing_id not in rids:
        raise KeyError(f"Existing rotation {existing_id!r} is not in the tables")
    avail = [j for j, _ in enumerate(crits) if not np.isnan(raw[:, :, j]).any()]
    dropped = [crits[j] for j in range(len(crits)) if j not in avail]
    names = [crits[j] for j in avail]
    v = _normalise_array(raw[:, :, avail], rids.index(existing_id), names, spec)

    w0 = scoring.criterion_weights(slider_weights, names, spec).to_numpy(float)
    rng = np.random.default_rng(seed + 1)
    if sample_weights:
        w = np.zeros((n_boot, len(names)))
        on = w0 > 0
        w[:, on] = rng.dirichlet(alpha * w0[on], size=n_boot)  # Dirichlet needs positive parameters
    else:
        w = np.tile(w0, (n_boot, 1))
    scores = np.einsum("brc,bc->br", v, w)                       # (n_boot, n_rot)

    best = scores.argmax(axis=1)
    p_top = np.bincount(best, minlength=len(rids)) / n_boot
    ranks = (-scores).argsort(axis=1).argsort(axis=1) + 1
    summary = pd.DataFrame({
        "score_mean": scores.mean(axis=0),
        "score_p05": np.percentile(scores, 5, axis=0),
        "score_p95": np.percentile(scores, 95, axis=0),
        "p_top": p_top,
        "rank_mean": ranks.mean(axis=0),
    }, index=rids).sort_values(["score_mean", "p_top"], ascending=False)

    crit_rows = []
    for i, rid in enumerate(rids):
        for j, name in enumerate(crits):
            col = raw[:, i, j]
            if np.isnan(col).all():
                continue
            crit_rows.append({"rotation": rid, "criterion": name, "value": float(np.mean(col)),
                              "p05": float(np.percentile(col, 5)), "p95": float(np.percentile(col, 95)),
                              "unit": spec["criteria"][name].get("unit", "")})
    return {
        "summary": summary,
        "criteria": pd.DataFrame(crit_rows).set_index(["rotation", "criterion"]),
        "weights": pd.Series(w0, index=names),
        "scores": scores,
        "rotations": rids,
        "window": window,
        "n_years": int(len(years)),
        "n_eff": round(effective_sample_size(probs), 1),
        "n_boot": n_boot,
        "dropped": dropped,
    }


def robustness(tables: dict, existing_id: str, slider_weights: dict, ordinal_scores: dict | None = None,
               slope_factor: float | None = None, n_boot: int = 500, seed: int = 0,
               spec: dict | None = None, extra: dict | None = None) -> dict:
    """Does the top rotation change with how past climate is weighted? (playbook 6.9)
    Contract 10.3 "robustness": recent30_same_top, weighted_same_top, note."""
    tops, p_top = {}, {}
    for window in ("all", "recent30", "weighted"):
        res = run_bootstrap(tables, existing_id, slider_weights, ordinal_scores, slope_factor,
                            n_boot=n_boot, window=window, seed=seed, spec=spec, extra=extra)
        top = res["summary"].index[0]
        tops[window], p_top[window] = top, float(res["summary"].loc[top, "p_top"])
    same30, samew = tops["recent30"] == tops["all"], tops["weighted"] == tops["all"]
    if same30 and samew:
        note = "The top option is the same whether all years, the last 30 years, or recent-weighted years are used."
    else:
        changed = [w for w, ok in (("the last 30 years", same30), ("recent-weighted years", samew)) if not ok]
        note = (f"The top option changes when using {' and '.join(changed)} "
                f"({', '.join(f'{k}: {v}' for k, v in tops.items())}) - treat the ranking as uncertain "
                "and discuss with your agronomist.")
    return {"recent30_same_top": same30, "weighted_same_top": samew, "tops": tops, "p_top": p_top, "note": note}


# --- Plain counts and per-year series for the cards ------------------------------------------
def per_year(table: pd.DataFrame, column: str) -> pd.Series:
    """One value per weather year (mean over the rotation's phases) - for charts and replay."""
    return table.groupby("year")[column].mean()


def stressed_years(table: pd.DataFrame, column: str = "drought_deficit_mm",
                   threshold: float = STRESSED_YEAR_DEFICIT_MM) -> dict:
    """'Water-stressed in N of M years': a year counts when, averaged over the rotation's
    phases, the sensitive-window deficit exceeds the threshold (contract 10.3 stressed_years)."""
    y = per_year(table, column)
    return {"n": int((y > threshold).sum()), "of": int(len(y)), "threshold_mm": threshold}


# --- Self-check ----------------------------------------------------------------------------
if __name__ == "__main__":
    import time
    import warnings
    warnings.simplefilter("ignore")
    from fieldshift import pipeline

    # 1) Synthetic: B always better than A, C worse -> P(top) of B = 1
    yrs = np.arange(1984, 2026)
    rng = np.random.default_rng(3)
    base = rng.gamma(4, 10, len(yrs))
    def tbl(scale):
        return pd.DataFrame({"year": yrs, "phase": 0, "drought_deficit_mm": base * scale,
                             "drainage_mm": 300 * scale + 0 * base, "bare_wet_days": 5 * scale + 0 * base})
    tables = {"A": tbl(1.0), "B": tbl(0.7), "C": tbl(1.2)}
    ords = {k: {"n_benefit": 1, "pest_break": 1, "som_proxy": 0} for k in tables}
    res = run_bootstrap(tables, "A", {"drought": 1, "water_quality": 1, "soil_erosion": 1}, ords, n_boot=400)
    s = res["summary"]
    assert s.loc["B", "p_top"] == 1.0 and abs(s.loc["A", "score_mean"] - 0.5) < 1e-12
    assert abs(s.loc["A", "score_p05"] - 0.5) < 1e-12 and abs(s["p_top"].sum() - 1) < 1e-12
    assert abs(effective_sample_size(year_weights(np.arange(1981, 2026), "weighted", 15)) - 34) < 1.5
    print("synthetic checks OK; n_eff (45 years, half-life 15) =",
          round(effective_sample_size(year_weights(np.arange(1981, 2026), "weighted", 15)), 1))

    # 2) Real POWER data through the pipeline (field data falls back to a typical soil if missing)
    allowed = pipeline.filter_rotations(hay_buyer=True, hay_equipment=True)
    out = pipeline.run_basic(42.18, -93.66, rotations=allowed, allow_download=False)
    ords = {n: (pipeline._LIBRARY[n].scores) for n in out["tables"]}
    weights = {"drought": 0.2, "water_quality": 0.2, "soil_erosion": 0.2, "pests_fertiliser": 0.2, "income": 0.2}
    t0 = time.perf_counter()
    res = run_bootstrap(out["tables"], out["baseline"], weights, ords,
                        out["field"]["slope"].get("rusle_s"), n_boot=N_BOOT)
    print(f"\n{len(out['tables'])} rotations x {res['n_years']} years x {res['n_boot']} replicates: "
          f"{time.perf_counter() - t0:.1f} s   (dropped: {res['dropped']})")
    print(res["summary"].round(3).head(6).to_string())
    e = out["baseline"]
    print(f"\nExisting rotation drought CVaR: "
          f"{res['criteria'].loc[(e, 'drought_risk'), 'value']:.0f} mm "
          f"(5-95 %: {res['criteria'].loc[(e, 'drought_risk'), 'p05']:.0f}-"
          f"{res['criteria'].loc[(e, 'drought_risk'), 'p95']:.0f})")
    print("Existing rotation:", stressed_years(out["tables"][e]))
    rob = robustness(out["tables"], e, weights, ords, out["field"]["slope"].get("rusle_s"), n_boot=300)
    print("Robustness:", rob["tops"], "->", rob["note"])
    assert abs(res["summary"]["p_top"].sum() - 1) < 1e-9
    assert abs(res["summary"].loc[e, "score_mean"] - 0.5) < 1e-12
    print("\nOK - checks passed.")

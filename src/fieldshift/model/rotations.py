"""
rotations.py - The rotation library, the farmer's existing rotation, the constraint
filters that decide which rotations are compared, and the ordinal (literature) scores.

Pipeline stage 3 (playbook 6.1): candidates + filters -> candidate list + removed list
with reasons; stage 6 (knowledge criteria) -> ordinal scores with sources and confidence.

Everything agronomic is read from content/rotations.yaml (base sequences, cover
modifiers, what each crop needs from the farm, removal reasons, flag texts, scores
and the rules behind them). Editing that file changes the model; this file only
holds the logic.

Library = base sequences x cover modifiers (4 x 3 = 12):
    cs     corn - soybean                            none
    csw    corn - soybean - winter wheat             rye_before_soy  cereal rye after corn, before soybean
    csorc  corn - soybean - oats (+ red clover)      rye             cereal rye in every bare winter gap
    csoaa  corn - soybean - oats/alfalfa - alfalfa   (Marsden Farm 4-year system)

Rules:
  - Never invent free sequences (no citable evidence). The only sequences are the
    library's and the farmer's own; cover modifiers are applied to either.
  - The existing rotation is always compared and never filtered out (the farmer
    already runs it). If it matches a library entry, that entry becomes "current".
  - Constraints (questions 6-9 in the app) remove rotations, each with a plain reason.
  - Openness (question 10) never removes anything; it only adds a flag, so at least
    three rotations are always compared (brief requirement).
  - Tier (display only, ranking unchanged): current / small_step (same cash crops +
    cover crop) / bigger_shift (different cash crops).

Each Rotation carries `plan`, the format crops.py and water_balance.py take, e.g.
    [["corn", "cereal_rye"], ["soybean"]]

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

from fieldshift import config
from fieldshift.model import crops as crops_mod

LIBRARY_PATH = config.CONTENT_DIR / "rotations.yaml"
LEGUMES = {"soybean", "alfalfa", "red_clover"}
SMALL_GRAINS = {"oats", "winter_wheat"}
ORDINAL_CRITERIA = ("n_benefit", "pest_break", "som_proxy")


# --- Loading the library ---------------------------------------------------------
@lru_cache(maxsize=4)
def _load_cached(path: str, mtime: float) -> dict:
    with open(path, encoding="utf-8") as f:
        lib = yaml.safe_load(f)
    for key in ("crop_requires", "requirement_reasons", "base_sequences", "cover_modifiers", "flags"):
        if key not in lib:
            raise KeyError(f"{path}: missing section '{key}'")
    for b in lib["base_sequences"]:
        missing = {"id", "name", "sequence", "scores"} - set(b)
        if missing:
            raise KeyError(f"{path}: base sequence {b.get('id')} missing {missing}")
    for fields in lib["crop_requires"].values():
        for fld in fields:
            if fld not in lib["requirement_reasons"]:
                raise KeyError(f"{path}: no requirement_reasons entry for '{fld}'")
    return lib


def load_library(path: str | Path | None = None) -> dict:
    """Parsed content/rotations.yaml (re-read automatically when the file changes)."""
    p = Path(path) if path else LIBRARY_PATH
    if not p.exists():
        raise FileNotFoundError(f"Rotation library not found: {p}")
    return _load_cached(str(p), p.stat().st_mtime)


# --- Data structure -------------------------------------------------------------
@dataclass
class Rotation:
    rotation_id: str
    name: str
    plan: list                       # crops.py format, e.g. [["corn", "cereal_rye"], ["soybean"]]
    base_id: str                     # library base, or "existing"
    cover_option: str                # none | rye_before_soy | rye
    sequence: list = field(default_factory=list)      # cash crop per year, e.g. ["corn", "soybean"]
    cover_after: list = field(default_factory=list)   # cover/underseeded crop per year or None
    tier: str | None = None          # current | small_step | bigger_shift
    is_existing: bool = False
    source: str = "library"          # library | farmer | farmer + library cover option
    sources: list = field(default_factory=list)       # citations behind this rotation
    scores: dict = field(default_factory=dict)        # ordinal 0-3: n_benefit, pest_break, som_proxy
    score_confidence: str = "low"    # high | medium | low
    requirements: list = field(default_factory=list)  # FarmInputs fields that must be True
    flags: list = field(default_factory=list)

    @property
    def evidence(self) -> str:
        return "; ".join(self.sources)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = self.evidence
        return d


# --- Helpers ----------------------------------------------------------------------
def _cash(entry: str) -> str:
    return entry.split("+")[0]


def _crops(crops):
    return crops_mod.default_crop_table() if crops is None else crops


def _kind(crop: str, crops: pd.DataFrame) -> str:
    if crop not in crops.index:
        raise KeyError(f"Unknown crop {crop!r}; supported: {list(crops.index)}")
    return crops.loc[crop, "kind"]


def _modifier(lib: dict, option: str) -> dict:
    for m in lib["cover_modifiers"]:
        if m["id"] == option:
            return m
    raise KeyError(f"Unknown cover modifier {option!r}")


def _apply_cover(cash_plan: list[str], option: str, lib: dict, crops: pd.DataFrame) -> list[list[str]]:
    """Add the cover crop to yearly entries according to the modifier's `where`.

    The cover goes only into a genuinely bare winter gap: not after an underseeded crop
    (already covered), not after a perennial (it keeps growing), and not before a
    winter annual or perennial (no gap to fill).
    """
    where = _modifier(lib, option).get("where", "none")
    cover = lib.get("cover_crop", "cereal_rye")
    n = len(cash_plan)
    plan = []
    for i, entry in enumerate(cash_plan):
        nxt = _cash(cash_plan[(i + 1) % n])
        bare_gap = ("+" not in entry
                    and _kind(_cash(entry), crops) != "perennial"
                    and _kind(nxt, crops) not in ("winter_annual", "perennial"))
        add = where == "every_bare_gap" or (where == "before_soybean" and nxt == "soybean")
        plan.append([entry, cover] if (bare_gap and add) else [entry])
    return plan


def _describe(plan) -> tuple[list, list]:
    """plan -> (sequence of cash crops, cover/underseeded crop after each year)."""
    seq, cover = [], []
    for year in plan:
        cash, _, under = year[0].partition("+")
        seq.append(cash)
        cover.append(under or (year[1] if len(year) > 1 else None))
    return seq, cover


def _canonical(plan) -> tuple:
    """Same rotation regardless of starting year: smallest cyclic shift."""
    items = [tuple(y) for y in plan]
    return min(tuple(items[i:] + items[:i]) for i in range(len(items)))


def canonical(plan) -> tuple:
    """Key that is equal for the same rotation whatever its starting year or name."""
    return _canonical([list(y) if isinstance(y, (list, tuple)) else [y] for y in plan])


def _all_crops(plan) -> set:
    return {c for y in plan for e in y for c in e.split("+")}


def _requirements(plan, lib: dict) -> list:
    reqs = []
    for c in sorted(_all_crops(plan)):
        for fld in lib["crop_requires"].get(c, []):
            if fld not in reqs:
                reqs.append(fld)
    return reqs


def _flags(plan, lib: dict, marsden: bool) -> list:
    text, flags = lib["flags"], []
    cover = lib.get("cover_crop", "cereal_rye")
    n = len(plan)
    for i, year in enumerate(plan):
        if len(year) > 1 and year[1] == cover:
            if text["cover_insurance"] not in flags:
                flags.append(text["cover_insurance"])
            if _cash(plan[(i + 1) % n][0]) == "corn" and text["rye_before_corn"] not in flags:
                flags.append(text["rye_before_corn"])
    seq, _ = _describe(plan)
    if "oats" in seq:
        flags.append(text["oats_buyer"])
    if "winter_wheat" in seq:
        flags.append(text["wheat_buyer"])
    if "alfalfa" in seq:
        flags.append(text["alfalfa"])
    if marsden:
        flags.append(text["marsden"])
    return flags


# --- Ordinal scores ------------------------------------------------------------------
def rule_scores(plan, crops: pd.DataFrame | None = None) -> dict:
    """Ordinal 0-3 scores for a cash sequence by the rules in rotations.yaml score_rules
    (before cover-crop adjustment). Used for a farmer's own rotation, and to check the
    library scores are consistent with the stated rules."""
    crops = _crops(crops)
    seq, cover = _describe(plan)
    n = len(seq)
    perennial = any(_kind(s, crops) == "perennial" for s in seq)
    corn_after_corn = any(seq[i] == "corn" and seq[i - 1] == "corn" for i in range(n)) if n > 1 else seq == ["corn"]

    if "alfalfa" in seq:
        n_benefit = 3
    elif "red_clover" in cover:
        n_benefit = 2
    elif "soybean" in seq:
        n_benefit = 1
    else:
        n_benefit = 0

    distinct = len(set(seq))
    if perennial and n >= 4:
        pest = 3
    elif distinct >= 3:
        pest = 2
    elif distinct == 2:
        pest = 1
    else:
        pest = 0
    pest = max(pest - (1 if corn_after_corn else 0), 0)

    if perennial:
        som = 3
    else:
        som = int(any(s in SMALL_GRAINS for s in seq)) + int("red_clover" in cover)
    return {"n_benefit": n_benefit, "pest_break": pest, "som_proxy": min(som, 3)}


def _adjust(scores: dict, option: str, lib: dict) -> dict:
    adj = _modifier(lib, option).get("score_adjust") or {}
    return {k: int(min(max(v + adj.get(k, 0), 0), 3)) for k, v in scores.items()}


def score_rules() -> dict:
    """The score_rules section (meaning, rule, sources) for the evidence page."""
    return load_library().get("score_rules", {})


# --- Building rotations --------------------------------------------------------------
def _make(rotation_id, name, plan, base_id, cover_option, source, sources, scores, confidence,
          lib, marsden=False):
    seq, cover = _describe(plan)
    return Rotation(rotation_id, name, plan, base_id, cover_option, seq, cover,
                    source=source, sources=list(sources), scores=scores, score_confidence=confidence,
                    requirements=_requirements(plan, lib), flags=_flags(plan, lib, marsden))


def _pretty(crop: str) -> str:
    return crop.replace("_", " ")


def library(crops: pd.DataFrame | None = None, lib: dict | None = None) -> list[Rotation]:
    """All library rotations (base x cover modifier), duplicates removed."""
    crops, lib = _crops(crops), lib or load_library()
    out, seen = [], set()
    for base in lib["base_sequences"]:
        for mod in lib["cover_modifiers"]:
            opt = mod["id"]
            plan = _apply_cover(base["sequence"], opt, lib, crops)
            key = _canonical(plan)
            if key in seen:                      # modifier added nothing new
                continue
            seen.add(key)
            rid = base["id"] + ("" if opt == "none" else f"_{opt}")
            sources = list(base.get("sources", [])) + (list(mod.get("sources", [])) if opt != "none" else [])
            out.append(_make(rid, base["name"] + mod.get("suffix", ""), plan, base["id"], opt, "library",
                             sources, _adjust(dict(base["scores"]), opt, lib),
                             base.get("confidence", "low"), lib, base.get("marsden", False)))
    return out


def rotation_from_history(crop_history: dict) -> list[str]:
    """Guess the repeating rotation from past crops (CDL), e.g.
    {2019: "corn", 2020: "soybean", 2021: "corn", ...} -> ["corn", "soybean"].
    Takes the shortest cycle that repeats exactly; otherwise returns the whole
    sequence (farmer confirms in the app). Starts the cycle at corn if present."""
    seq = [crop_history[k] for k in sorted(crop_history, key=int)]
    seq = [c for c in seq if c]
    if not seq:
        return []
    cycle = seq
    for p in range(1, len(seq) // 2 + 1):
        if all(seq[i] == seq[i + p] for i in range(len(seq) - p)):
            cycle = seq[:p]
            break
    if "corn" in cycle:
        k = cycle.index("corn")
        cycle = cycle[k:] + cycle[:k]
    return cycle


def make_existing(existing, crops: pd.DataFrame | None = None, lib: dict | None = None) -> list[Rotation]:
    """The farmer's current rotation as a Rotation (plus cover-crop variants of it when it
    is not in the library, so a 'small step' option always exists). Scored by the
    score_rules, confidence low.

    existing: list of crop names, e.g. ["corn", "soybean"] or ["corn", "corn", "soybean"],
              or a crops.py plan (list of lists) if it already includes cover crops.
    """
    crops, lib = _crops(crops), lib or load_library()
    if not existing:
        raise ValueError("Existing rotation is empty - ask the farmer to confirm it.")
    plan = [list(y) if isinstance(y, (list, tuple)) else [y] for y in existing]
    for year in plan:
        cash = _cash(year[0])
        if _kind(cash, crops) == "cover":
            raise ValueError(f"{cash!r} is a cover crop, not a cash crop")
    seq, cover = _describe(plan)
    label = "–".join(_pretty(c) for c in seq).capitalize()
    if any(cover):
        label += " + " + ", ".join(sorted({_pretty(c) for c in cover if c}))
    base_scores = rule_scores([[y[0]] for y in plan], crops)
    has_cover = any(len(y) > 1 for y in plan)
    own = _adjust(base_scores, "rye" if has_cover else "none", lib)
    out = [_make("existing", f"{label} (your current rotation)", plan, "existing", "none", "farmer",
                 [], own, "low", lib)]

    if not has_cover:                            # offer the small-step variants
        cash_plan = [y[0] for y in plan]
        seen = {_canonical(plan)}
        for mod in lib["cover_modifiers"]:
            opt = mod["id"]
            if opt == "none":
                continue
            p = _apply_cover(cash_plan, opt, lib, crops)
            if _canonical(p) in seen:
                continue
            seen.add(_canonical(p))
            out.append(_make(f"existing_{opt}", label + mod.get("suffix", ""), p, "existing", opt,
                             "farmer + library cover option", mod.get("sources", []),
                             _adjust(base_scores, opt, lib), "low", lib))
    return out


def _get(inputs, name, default=None):
    return inputs.get(name, default) if isinstance(inputs, dict) else getattr(inputs, name, default)


def build_candidates(inputs, crops: pd.DataFrame | None = None,
                     lib: dict | None = None) -> tuple[list[Rotation], list[dict]]:
    """Candidate rotations for this farm, and the removed ones with reasons.

    inputs: FarmInputs (playbook 10.2) or a dict with the same field names:
        existing_rotation, livestock_or_hay_buyer, small_grain_buyer,
        can_seed_cover, hay_equipment, openness ("yes" | "maybe" | "no").
    Returns (candidates, removed):
        candidates: existing rotation first, then the rest; each with tier set.
        removed:    [{"rotation_id", "name", "reason"}]  (contract 10.3 "removed")
    """
    crops, lib = _crops(crops), lib or load_library()
    existing_list = make_existing(_get(inputs, "existing_rotation"), crops, lib)
    existing = existing_list[0]
    ex_key = _canonical(existing.plan)
    ex_seq_key = _canonical([[s] for s in existing.sequence])

    lib_rots = []
    for rot in library(crops, lib):
        if _canonical(rot.plan) == ex_key:       # existing rotation is a library entry
            existing.rotation_id = rot.rotation_id
            existing.base_id, existing.cover_option = rot.base_id, rot.cover_option
            existing.sources, existing.flags = rot.sources, rot.flags
            existing.scores, existing.score_confidence = rot.scores, rot.score_confidence
            continue
        lib_rots.append(rot)

    # the farmer's own small-step variants come first, but only if the library does not
    # already have the same rotation (library entries carry sources and higher confidence)
    lib_keys = {_canonical(r.plan) for r in lib_rots}
    variants = [r for r in existing_list[1:] if _canonical(r.plan) not in lib_keys]
    unique = variants + lib_rots

    candidates, removed = [], []
    for rot in unique:
        reasons = [lib["requirement_reasons"][f] for f in rot.requirements if not _get(inputs, f, False)]
        if reasons:
            removed.append({"rotation_id": rot.rotation_id, "name": rot.name, "reason": "; ".join(reasons)})
            continue
        candidates.append(rot)

    # tiers (display only) and openness flag
    existing.is_existing, existing.tier = True, "current"
    for rot in candidates:
        same_cash = _canonical([[s] for s in rot.sequence]) == ex_seq_key
        rot.tier = "small_step" if same_cash else "bigger_shift"
        if _get(inputs, "openness", "maybe") == "no":
            rot.flags = rot.flags + [lib["flags"]["not_open"]]
    return [existing] + candidates, removed


# --- Counted measures (from the sequence and calendar, playbook 6.3) ---------------------
def counted_measures(rot: Rotation, crops: pd.DataFrame | None = None) -> dict:
    """Measures that come straight from the sequence/calendar (no weather):
        cycle_years            rotation length
        distinct_cash_crops    number of different cash crops        (pest_break)
        longest_same_crop_run  longest run of one cash crop, cyclic  (pest_break: rootworm, SCN)
        corn_after_corn_years  corn following corn                   (pest_break, N need)
        legume_years           years with soybean, alfalfa or clover (n_benefit)
        perennial_years        years of alfalfa                      (som_proxy)
        cover_years            years with a cover/underseeded crop   (som_proxy, erosion)
        living_cover_share     share of days with a living crop      (som_proxy, erosion)
        bare_days_per_year     mean days with no living crop
    """
    crops = _crops(crops)
    seq, cover = rot.sequence, rot.cover_after
    n = len(seq)
    doubled = seq + seq
    run = best = 0
    for i in range(len(doubled)):
        run = run + 1 if i and doubled[i] == doubled[i - 1] else 1
        best = max(best, run)
    best = min(best, n)

    # middle cycle of three, so crops crossing 1 January are complete
    start = 2001
    table = crops_mod.daily_crop_table(rot.plan, start, start + 3 * n - 1, crops=crops)
    mid = table[(table.index.year >= start + n) & (table.index.year < start + 2 * n)]
    bare = mid["role"] == "bare"
    return {
        "cycle_years": n,
        "distinct_cash_crops": len(set(seq)),
        "longest_same_crop_run": best,
        "corn_after_corn_years": sum(1 for i in range(n) if seq[i] == "corn" and seq[i - 1] == "corn"),
        "legume_years": sum(1 for s, c in zip(seq, cover) if s in LEGUMES or c in LEGUMES),
        "perennial_years": sum(1 for s in seq if _kind(s, crops) == "perennial"),
        "cover_years": sum(1 for c in cover if c),
        "living_cover_share": round(float(1 - bare.mean()), 3),
        "bare_days_per_year": round(float(bare.sum() / n), 1),
    }


# --- Self-check -------------------------------------------------------------------------
if __name__ == "__main__":
    import warnings
    warnings.simplefilter("error")   # any "no room for cover" warning from crops.py fails the check

    lib = load_library()
    # library scores in the YAML must agree with the stated rules
    for b in lib["base_sequences"]:
        expected = rule_scores([[e] for e in b["sequence"]])
        assert expected == b["scores"], f"{b['id']}: YAML scores {b['scores']} != rules {expected}"

    rots = library()
    print(f"Library: {len(rots)} rotations (from {LIBRARY_PATH.relative_to(config.ROOT)})")
    rows = []
    for r in rots:
        m = counted_measures(r)
        rows.append({"id": r.rotation_id, "plan": " | ".join("+".join(y) for y in r.plan),
                     "bare d/yr": m["bare_days_per_year"], "N": r.scores["n_benefit"],
                     "pest": r.scores["pest_break"], "SOM": r.scores["som_proxy"],
                     "conf": r.score_confidence})
    print(pd.DataFrame(rows).to_string(index=False))
    assert len(rots) == 12, "expected 4 bases x 3 cover options"

    farm = {"existing_rotation": ["corn", "soybean"], "livestock_or_hay_buyer": False,
            "small_grain_buyer": True, "can_seed_cover": True, "hay_equipment": False, "openness": "maybe"}
    cands, removed = build_candidates(farm)
    print("\nFarm without livestock/hay buyer:")
    for c in cands:
        print(f"  {c.tier:<13} {c.rotation_id:<20} {c.name}")
    for r in removed:
        print(f"  REMOVED       {r['rotation_id']:<20} {r['reason']}")
    assert cands[0].is_existing and cands[0].rotation_id == "cs"
    assert {r["rotation_id"] for r in removed} == {"csoaa", "csoaa_rye_before_soy", "csoaa_rye"}

    tight = dict(farm, small_grain_buyer=False)
    cands, _ = build_candidates(tight)
    print(f"\nNo small-grain buyer either: {[c.rotation_id for c in cands]}")
    assert len(cands) >= 3

    cands, _ = build_candidates(dict(farm, existing_rotation=["corn", "corn", "soybean"]))
    print("\nExisting corn-corn-soybean:")
    for c in cands[:3]:
        print(f"  {c.tier:<13} {c.rotation_id:<24} scores={c.scores} conf={c.score_confidence}")
    assert cands[0].scores["pest_break"] == 0       # corn after corn: 2 crops (1) minus 1

    hist = {"2019": "soybean", "2020": "corn", "2021": "soybean", "2022": "corn", "2023": "soybean"}
    assert rotation_from_history(hist) == ["corn", "soybean"]
    assert rotation_from_history({2019: "corn", 2020: "corn", 2021: "soybean",
                                  2022: "corn", 2023: "corn", 2024: "soybean"}) == ["corn", "corn", "soybean"]
    cands, _ = build_candidates(dict(farm, existing_rotation=["soybean", "corn"]))
    assert cands[0].rotation_id == "cs"
    print("\nOK - checks passed.")

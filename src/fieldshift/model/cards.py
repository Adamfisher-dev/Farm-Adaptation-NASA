"""
cards.py - The five-part card for each rotation shown to the farmer (the brief's core requirement,
playbook 6.13): why it was suggested, what evidence supports it, what benefits it may bring, where
the information gaps are, and what risks need local review.

Cards are templates filled with computed numbers + text from content/rotations.yaml - nothing is
invented at run time:
  hand-written (rotations.yaml)  one card block per base sequence (4), per cover option (3) and a
                                 fallback for a farmer's own rotation; a card = base + cover text
  computed (run_analysis result) score, chance of beating the current rotation, drainage / erosion /
                                 bare-day / drought / income changes, literature scores, risk flags,
                                 the 2012 replay, stressed years, validation, confidence, sources

    from fieldshift.model import cards
    for card in cards.build_cards(res):          # res = pipeline.run_analysis(...)
        print(cards.to_markdown(card))

No Streamlit calls in this file (project rule): the app renders the dicts / markdown.
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fieldshift.model import rotations as rot_mod

FOOTER = ("Options to explore with your agronomist - this tool supports, not replaces, your judgement "
          "and local expertise.")
TIER_TEXT = {
    "current": "Your current rotation - every option is compared with it (score 0.50).",
    "small_step": "A small step: the crops you grow now, plus a cover crop.",
    "bigger_shift": "A bigger shift: changes which crops you grow.",
}
CRITERION_WORDS = {
    "drought_risk": "drought resilience", "water_leaving": "water quality (less drainage and nitrate loss)",
    "erosion_exposure": "erosion control", "som_proxy": "soil organic matter", "n_benefit": "nitrogen supply",
    "pest_break": "breaking pest cycles", "income": "income",
}
ORDINAL_WORDS = {"n_benefit": "nitrogen from legumes", "pest_break": "pest and disease break",
                 "som_proxy": "soil organic matter outlook"}
DATA_SOURCES = ("NASA POWER daily weather 1984-2025 (~50 km grid); USDA NRCS SSURGO soil survey; USDA NASS "
                "Cropland Data Layer 2008-2025; NASA SRTM elevation; Iowa State FM 1712 / USDA NASS prices and costs")
MIN_CHANGE_PCT = 3.0            # smaller changes than this are not worth a line on the card


def _pct(new, old):
    return (new - old) / abs(old) * 100.0 if old else np.nan


def _money(v):
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def _text(block: dict | None, key: str) -> list:
    t = (block or {}).get(key) or ""
    return [t] if t.strip() else []


def _texts(res: dict, name: str) -> dict:
    """Hand-written card text for one rotation: base sequence + cover option, or the fallback."""
    lib = rot_mod.load_library()
    c = res["candidates"][name]
    bases = {b["id"]: b.get("card") or {} for b in lib["base_sequences"]}
    mods = {m["id"]: m.get("card") or {} for m in lib["cover_modifiers"]}
    base = bases.get(c.get("base_id")) or lib.get("existing_card") or {}
    mod = mods.get(c.get("cover_option"), {})
    out = {k: _text(base, k) + _text(mod, k) for k in ("why", "benefits", "gaps", "risks")}
    no_cover = not any(cv for cv in c.get("cover_after") or [])      # no cover or underseeded crop at all
    if no_cover:
        out["risks"] = _text(base, "risks_if_no_cover") + out["risks"]
    return out


def _claim(source: str) -> str:
    """Plain label for a source in the evidence list."""
    s = source.lower()
    if "marsden" in s:
        return "Iowa State Marsden Farm long-term rotation trial"
    if "sare" in s:
        return "Cover-crop guidance (SARE, Managing Cover Crops Profitably)"
    if "iowa state" in s:
        return "Iowa State University Extension guidance"
    return "Research evidence"


def _p_better(res: dict, name: str):
    scores, rids = res.get("boot_scores"), res.get("boot_rotations")
    base = res["existing"]["name"]
    if scores is None or name not in rids or base not in rids:
        return None
    return float(np.mean(scores[:, rids.index(name)] > scores[:, rids.index(base)]))


# --- One card -----------------------------------------------------------------------------------------
def build_card(res: dict, name: str) -> dict:
    base = res["existing"]["name"]
    c = res["candidates"][name]
    is_current = name == base
    tier = "current" if is_current else (c.get("tier") or "bigger_shift")
    t = _texts(res, name)
    raw, rk = res["criteria_raw"], res["ranking"]
    x, xb = raw.loc[name], raw.loc[base]
    cal = (res.get("calendar") or {}).get(name, {}).get("summary", {})
    cal_b = (res.get("calendar") or {}).get(base, {}).get("summary", {})
    inc = res.get("income") or {}
    income, ranges = inc.get("usd_per_acre") or {}, inc.get("ranges") or {}
    p_better = _p_better(res, name)

    # ---- why -------------------------------------------------------------------------------------
    why = [TIER_TEXT[tier]] + t["why"]
    if not is_current:
        vals, w = res["point_scores"]["values"], res["point_scores"]["weights"]
        gain = ((vals.loc[name, w.index] - 0.5) * w).sort_values(ascending=False)
        top = [CRITERION_WORDS.get(k, k) for k, v in gain.items() if v > 0.005][:2]
        if top:
            why.append(f"For your priorities it gains most on {' and '.join(top)}.")

    # ---- evidence ----------------------------------------------------------------------------------
    s = rk.loc[name]
    evidence = [{"claim": _claim(src), "source": src} for src in c.get("sources") or []]
    model_claim = (f"Score {s['score_mean']:.2f} (range {s['score_p05']:.2f}-{s['score_p95']:.2f}; your current "
                   "rotation = 0.50) from 1,000 replays of the 1984-2025 weather with varied prices and priority weights.")
    if p_better is not None and not is_current:
        model_claim += f" It beats your current rotation in {p_better:.0%} of those replays."
    evidence.append({"claim": model_claim, "source": "Field Shift model (FAO-56 water balance + bootstrap)"})
    val = (res.get("validation") or {}).get("sentences") or []
    probe = [v for v in val if "probe at 60 cm" in v] or val[:1]
    if probe:
        evidence.append({"claim": "Model check: " + probe[0], "source": "ISU Soil Moisture Network / NASA POWER"})
    evidence.append({"claim": "Data for this field", "source": DATA_SOURCES})

    # ---- benefits and risks from the numbers -------------------------------------------------------
    benefits, risks = list(t["benefits"]), list(t["risks"])
    if not is_current:
        d = _pct(x["water_leaving"], xb["water_leaving"])
        if d <= -MIN_CHANGE_PCT:
            benefits.append(f"About {abs(d):.0f}% less water draining from the field ({x['water_leaving']:.0f} vs "
                            f"{xb['water_leaving']:.0f} mm a year), so less nitrate lost.")
        e = _pct(x["erosion_exposure"], xb["erosion_exposure"])
        if e <= -MIN_CHANGE_PCT:
            benefits.append(f"About {abs(e):.0f}% less erosion exposure (bare soil during erosive storms).")
        elif e >= MIN_CHANGE_PCT:
            risks.append(f"About {e:.0f}% more erosion exposure than now.")
        if cal and cal_b and cal["bare_days_per_year"] < cal_b["bare_days_per_year"] - 5:
            benefits.append(f"Bare soil about {cal['bare_days_per_year']:.0f} days a year instead of "
                            f"{cal_b['bare_days_per_year']:.0f}.")
        dd = x["drought_risk"] - xb["drought_risk"]
        if dd <= -3:
            benefits.append(f"In a bad year the crops miss about {abs(dd):.0f} mm less water at their sensitive stage "
                            f"({x['drought_risk']:.0f} vs {xb['drought_risk']:.0f} mm).")
        elif dd >= 3:
            risks.append(f"In a bad year the crops miss about {dd:.0f} mm more water at their sensitive stage than now.")
        for k, label in ORDINAL_WORDS.items():
            if x[k] > xb[k]:
                benefits.append(f"Better {label} (research-based score {x[k]:.0f}/3 vs {xb[k]:.0f}/3).")
        if name in income and base in income:
            di = income[name] - income[base]
            r = ranges.get(name) or {}
            rng = f" (from {_money(r['low'])} to {_money(r['high'])} an acre depending on prices)" if r else ""
            if di >= 1:
                benefits.append(f"About {_money(di)} more per acre a year than now{rng}.")
            elif di <= -1:
                risks.append(f"About {_money(abs(di))} less per acre a year than now{rng}.")
    elif name in income:
        r = ranges.get(name) or {}
        if r:
            benefits.append(f"Return to land and management about {_money(income[name])} an acre a year "
                            f"({_money(r['low'])} to {_money(r['high'])} depending on prices).")

    # flags (rotation rules) that the card text does not already say
    covered = " ".join(risks + t["gaps"]).lower()
    skip_if = {"insurer": "insurer", "10-14 days": "10-14 days", "whole systems": "whole farming system",
               "holds the field": "hay for two seasons"}
    for f in c.get("flags") or []:
        if not any(k in f.lower() and v in covered for k, v in skip_if.items()):
            risks.append(f)
    # field-level risk flags: all on the current rotation's card; on an option's card only those that
    # differ from the current rotation (e.g. rye establishment, oats planting) - the rest are the same
    base_flags = {(f["key"], f["crop"], f["n"]) for f in (res.get("risk_flags") or {}).get(base, [])}
    for f in (res.get("risk_flags") or {}).get(name, []):
        if f["level"] in ("warn", "watch") and (is_current or (f["key"], f["crop"], f["n"]) not in base_flags):
            risks.append(f["sentence"])
    st, st_b = (res.get("stressed_years") or {}).get(name), (res.get("stressed_years") or {}).get(base)
    if st:
        extra = f" ({st_b['n']} for your current rotation)" if st_b and not is_current else ""
        risks.append(f"Water-stressed at the sensitive stage in {st['n']} of {st['of']} years{extra}.")
    rp = res.get("replay")
    if rp is not None:
        try:
            tb = rp["table"].xs("drought_deficit_mm", level="measure")
            yr = rp["year"]
            line = f"In {yr} it would have missed about {tb.loc[name, 'that_year']:.0f} mm of water at the sensitive stage"
            line += (f" (typical year {tb.loc[name, 'typical']:.0f} mm)." if is_current else
                     f", against {tb.loc[base, 'that_year']:.0f} mm for your current rotation.")
            risks.append(line)
        except (KeyError, TypeError):
            pass

    # ---- gaps -------------------------------------------------------------------------------------
    gaps = list(t["gaps"])
    conf = c.get("score_confidence", "low")
    gaps.append(f"Confidence in the research-based scores: {conf}.")
    seq = c.get("sequence") or []
    if "winter_wheat" in seq:
        gaps.append("Wheat income uses yields and prices from neighbouring states (no Iowa data).")
    if "alfalfa" in seq:
        gaps.append("Hay income uses the Iowa all-quality hay price; good-quality hay sells for more.")
    gaps.append("Weather is a ~50 km NASA POWER average, the same for every field nearby; income compares "
                "rotations at 2023-2025 prices and is not a profit forecast.")
    if res.get("risk_note"):
        gaps.append(res["risk_note"])

    headline = TIER_TEXT[tier].split(":")[0].split(" - ")[0]
    if not is_current:
        headline += f" - score {s['score_mean']:.2f}"
        if p_better is not None:
            headline += f", beats your current rotation in {p_better:.0%} of replays"
    return {"rotation": name, "tier": tier, "headline": headline, "why": why, "evidence": evidence,
            "benefits": benefits, "gaps": gaps, "risks": risks, "confidence": conf, "footer": FOOTER}


def build_cards(res: dict) -> list:
    """Cards for the rotations shown to the farmer (current + options), in display order."""
    return [build_card(res, s["name"]) for s in res["shown"]]


def to_markdown(card: dict) -> str:
    """Markdown for st.markdown(), one card."""
    out = [f"### {card['rotation']}", f"*{card['headline']}*", "", "**Why it was suggested**"]
    out += [f"- {x}" for x in card["why"]]
    out += ["", "**Evidence**"] + [f"- {e['claim']}" + (f" _(source: {e['source']})_" if e["source"] else "")
                                   for e in card["evidence"]]
    out += ["", "**Possible benefits**"] + ([f"- {x}" for x in card["benefits"]] or ["- (none beyond the current rotation)"])
    out += ["", "**Information gaps**"] + [f"- {x}" for x in card["gaps"]]
    out += ["", "**Risks to review locally**"] + ([f"- {x}" for x in card["risks"]] or ["- none flagged"])
    out += ["", f"_{card['footer']}_"]
    return "\n".join(out)


# --- Self-check ---------------------------------------------------------------------------------------
if __name__ == "__main__":
    import warnings
    warnings.simplefilter("ignore")
    from fieldshift import config, pipeline

    res = pipeline.run_analysis(*config.EXAMPLE_POINTS["sloping"],
                                {"livestock_or_hay_buyer": True, "hay_equipment": True},
                                {"income": 6, "soil_health": 8, "water_quality": 5, "drought": 4, "pests": 3}, n_boot=500)
    cards = res["cards"]
    for card in cards:
        print(to_markdown(card), "\n" + "-" * 100)
    assert len(cards) == len(res["shown"]) >= 3
    assert cards[0]["tier"] == "current" and "compared with it" in cards[0]["why"][0]
    for card in cards:
        for part in ("why", "evidence", "benefits", "gaps", "risks"):
            assert card[part], (card["rotation"], part)
        assert card["footer"] == FOOTER
    print("OK - checks passed.")

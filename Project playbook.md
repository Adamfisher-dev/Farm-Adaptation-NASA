# Field Shift — CLAUDE.md (merged project guide + weekend playbook)

Team: 2 people · Python + Streamlit · Hackathon Sat 14 – Sun 15 Nov 2026 · Judging from 16 Nov
Official challenge page: https://www.spaceappschallenge.org/2026/challenges/adapting-farms-with-nasa-data/

> Single source of truth for Claude Code: challenge requirements, design decisions, the model, the data, the code structure and the to-do list.
> Items marked **(verify)** are product names, API details or facts to check against official documentation before relying on them.
> Items marked **[playbook]** were added from the teammate's weekend playbook. Playbook figures and ratings are second-hand or from memory: verify before use.
> The 2026 Submission Guide and Judging Guide were released on 13 Nov — read them first (see To-do).
> **Method and engine are fixed:** FAO-56 water balance + year bootstrap + multi-criteria scoring (Sections 5–6). Do not replace with a rule-only engine except as the emergency fallback (Section 12).

## Rules for Claude Code
- Python only. Stack: requests, pandas, numpy, xarray, earthaccess, scikit-learn/statsmodels, plotly, folium, streamlit. No JavaScript/React unless asked.
- ~48 h: favour a working, demoable MVP. Say what is MVP vs stretch.
- Real NASA data only. Never invent data, API endpoints or parameter names; if unsure, say so and say how to verify.
- No `st.` calls in `src/`; agronomy lives in `content/` with sources; demo runs from cached data.
- Check units everywhere (mm/day vs kg m⁻² s⁻¹, MJ vs kWh, °F vs °C, inches vs mm, cm vs mm for AWC).
- Never claim more than the tool does: it **compares options**; it does not predict yield or profit.
- Frame everything as "options to explore with your agronomist"; the tool supports, never replaces, farmer judgement.
- When debugging, ask for the exact error and the code that produced it.

---

## Key decisions at a glance

| Decision | Choice | Why (details in Section 2) |
|---|---|---|
| Region | **Story County, central Iowa, USA** (corn–soybean belt) | Resources tab is built around US field-scale data; no UK farmer contact possible |
| Unit of analysis | **One field at a time**, regional climate + field soil/slope/crop history | Climate is regional; field differences come from soil, slope, history, farmer inputs |
| Front end | **Streamlit** | Fastest route to a working demo; React only if MVP is done and deployed first |
| Core method | **Physics-based simulation** (FAO-56 water balance) + **bootstrap** over past years + **multi-criteria scoring** | Explainable, defensible, no training labels needed |
| No predictive ML | No yield/outcome labels exist | An ML predictor would not be valid |
| No single threshold rule | Rules only for filters and risk flags | Brief requires ≥3 rotations with trade-offs and farmer priorities |
| Output | **Existing rotation + top 3 alternatives**, as "options to explore with your agronomist" | Brief requirement |
| Rotation library | Modular: base sequences × cover-crop options (~8–12 candidates) | Variety while every option stays valid and citable |
| Climate period | All years 1981–2025 (NASA POWER), robustness checks on recent climate | Bad-year statistics need many years |
| Future climate | Delta-change sliders (add-on); NEX-GDDP-CMIP6 lowest priority | 2050 is beyond decision horizon |
| Data access | **Download everything for the county in advance**; app runs offline | No external service can break the demo |
| Demo format **[playbook]** | **≤ 7 slides** (not the 30 s video) | A comparison cannot be shown in 30 s; slides read at the judge's pace. Confirm in 2026 guide |
| Project name **[playbook]** | Pick something distinct from "FieldShift" | Several teams already used it |

---

## Contents
1. The challenge and what judges want
2. Design decisions and reasoning
3. Our region: central Iowa
4. The farmer's journey (the app)
5. How the model works — simple version
6. How the model works — detailed specification
7. Background knowledge
8. Data
9. Data harmonisation and spatial units
10. Architecture, files and contract
11. Project ideas A–K and their status
12. Plan, time budget and timeline
13. Demo and submission
14. Tooling and workflow
15. Appendices: download walkthrough, soil.py, glossary
16. To-do list: first steps

---

## 1. The challenge and what judges want

**Task:** build a decision-support tool that combines NASA Earth observations with local soil information, crop characteristics and farmer priorities, helping farmers explore crop-rotation strategies that improve soil health and adapt to changing conditions. The tool **supports** farmer judgement and local agricultural expertise; it must never present itself as replacing them.

### Hard requirements (core deliverable)
Compare **at least three rotation strategies, one of which is the farmer's existing rotation**. For each, explain:
1. why it was suggested
2. what evidence supports it
3. what benefits it may bring
4. where the information gaps are
5. what risks need local review by farmers/agronomists

Present as **options to explore with your agronomist**, not "recommendations".

### What the tool should highlight
- When fields are typically bare
- Seasons when current crops look most vulnerable
- Rotation opportunities that break pest cycles, cut water demand, improve infiltration or add income

### Farmer priorities named in the brief
Water use, forage value, nitrogen fixing, erosion reduction, organic-matter improvement, market suitability.

### Patterns from NASA data the brief mentions **[playbook]**
Temperature, heat stress, rainfall, soil moisture, evaporation, frost risk, extreme rain, vegetation stress, long-term water trends. Named datasets "where useful": SMAP, ECOSTRESS, GPM, Landsat, MODIS, POWER, GRACE/GRACE-FO, SRTM, GEDI. (Playbook's brief detail is second-hand from other teams' READMEs; the official page blocks automated readers → confirm against the official text.)

### "Potential considerations" (treat as judging criteria)
- Plain-language explanations: evapotranspiration, soil-moisture anomaly, NDVI, frost risk, water balance.
- How satellite data differs from ground measurements and why combining them helps.
- Compare different AI/statistical approaches; explain uncertainty and where local expertise must validate results.
- Harmonise datasets of different resolutions onto common units.
- Maps of long-term trends and vulnerability zones (stretch); optional rainfall/temperature scenario sliders.
- Usable by non-technical farmers; inputs for priorities and constraints; remind users the tool supports, not replaces, local expertise.

### Submission (confirm against the 2026 Submission Guide)
- Demo: **≤ 7 slides including the title slide** (decided) OR video ≤ 30 s with English subtitles. Exceeding either limit = ineligible for Global Judging.
- Public demo link that opens with no login/password/permission.
- Public code repository.
- Clear list of NASA / partner datasets used.
- Every required field on the project page; judging and terms checkboxes ticked.
- **AI-use declaration** (last year's form asked which AI tools and how) — see Section 13.
- Submission opens Sat 09:00, closes **Sun 23:59 local time**; submission is **final** once "Submit for Judging" is pressed (last year's guide). Target submitting by **Sun 18:00**.
- Judging criteria: **Impact, Creativity, Validity, Relevance, Presentation.**

### Rules on preparation
Typical Space Apps rule: all project code/design must be created during the event; planning, discussion and data preparation in advance are fine; public data, open-source libraries and APIs allowed **(verify in the 2026 guide)**.
**[playbook] Early-work risk:** last year's form had a "Confirm all work is original" box. If any map/input code already exists locally, ask the Local Lead whether early prototyping is acceptable; if in doubt, rebuild the interface on Saturday from the design.

### Eligibility checklist **[playbook]** (confirm in 2026 guides)
- Both members registered, assigned to the same Local Event, listed on the team's Members tab.
- Project page and everything it links to in English.
- Demo and project links open without password or sign-up.
- NASA data used and named (was required for global award eligibility).
- Every source cited incl. open-source; any non-NASA code/data openly available with licence noted.
- Deck ≤ 7 slides counting the title.
- Submitted before the deadline.
- Ask the Local Lead: is there a live pitch, and when does local judging close?

---

## 2. Design decisions and reasoning

### Why Iowa instead of the Vale of York
- NASA's core datasets (POWER, SMAP, GPM, Landsat, SRTM, GRACE) are global, but the **supporting field-scale data** in the Resources tab is US-only: CDL (crop type per 30 m pixel per year), SSURGO (field-scale soils), PRISM (gridded climate).
- With CDL the farmer's existing rotation is observed fact; with SSURGO soils are field-specific. Field-level claims become credible.
- ECOSTRESS (ISS) has little or no coverage at Selby's latitude (~53.8°N); Iowa (~42°N) is fully covered.
- We cannot speak to a UK farmer this weekend, the main UK advantage.
- Iowa over western Kansas: rain-fed (simpler water model), vivid bare-field story, strong evidence base (Marsden Farm). Kansas remains an alternative with the same architecture.

### Why Streamlit, not React
- Only Python is known; Streamlit gives a web app with no API layer.
- React would add FastAPI, CORS, two deployments: ~4–8 extra hours, concentrated risk on Sunday.
- **Rule:** keep `src/` free of `st.` calls and make results JSON-shaped, so a React front end is possible later. Only start React if the Streamlit MVP is complete and deployed; always submit whichever version fully works. Do any port on a branch; leave `main` alone.
- If ever done: precompute results to static JSON and deploy React as a static site (no live backend), or follow the FastAPI outline in Appendix D.

### Why simulate each rotation (not a single condition index + thresholds)
1. The brief requires a **comparison** of ≥3 rotations with benefits/risks for each — a threshold rule outputs only one.
2. A single index can't represent **trade-offs** (rye cuts erosion but uses spring water) and has nowhere for farmer priorities to enter.
3. Thresholds would be **uncalibrated** — "why 0.25?" has no answer.
4. Rotation effects are **interactions** of field × rotation; simulation computes them from physics.
5. **Next year's weather is unknowable**; the honest question is how each rotation copes with the range of plausible years.
6. Hard thresholds are **fragile** near the cut-off.
Simulation is cheap: ~12 rotations × 45 years × 365 days ≈ 200,000 steps (<1 s in numpy).
Rules are still used for **constraint filters** and **risk flags**; a rule-based scorer is the emergency fallback if the water model fails.

### Why no predictive ML
No field-level yield/outcome labels → nothing valid to learn. ML only where justified: clustering weather regimes (comparing methods), NDVI phenology/crop classification with CDL labels (stretch).

### Decision horizon and climate
- A rotation is a **multi-year** commitment (2–4-year cycles; switching may need equipment/buyers). Realistic horizon **3–10 years**.
- Recent climate is most relevant; use all years for statistical power, then check robustness on recent climate (6.9).
- NEX-GDDP-CMIP6 (2050s) is beyond the decision horizon → optional, lowest priority.

### Field-level honesty
- **Field-level:** soil (SSURGO), slope (SRTM), crop history (CDL), NDVI (HLS).
- **Regional:** all climate inputs (POWER ≈ 50 km grid; same for every field within kilometres).
- Neighbouring fields rank differently because of soil, slope and history — not weather. Label this in the app ("climate data: regional ~50 km grid") and draw the POWER cell outline on the map.
- **[playbook]** State two limits in the app: POWER describes an area of ~50 km, not one field; its soil wetness (GWETROOT/GWETTOP) is modelled, not measured.

### Product identity **[playbook]**
Three ideas to set us apart from the many rotation planners entered:
1. **Field calendar** — months across, rotation years down, bare soil shown as empty gaps (Section 4).
2. **Replay a hard year** — pick a past year from the NASA record (e.g. 2012 drought, 2019 wet spring) and show how each rotation would have coped (Section 4, 6.14). Confirm the year stands out in our own data before demoing.
3. **Plain tier labelling** — label results as *Current*, *Small step* (existing cash crops + cover crop), *Bigger shift* (a more diverse library rotation) as a **display layer only** on top of the unchanged ranking (Section 4). Matches how farmers change: cover crop first, third crop later.
Contrast with other entries: one region in depth, field-trial evidence, plain language, honesty about uncertainty; avoid long lists of datasets and equations without a decision behind each.

---

## 3. Our region: central Iowa

**County:** Story County, Iowa (around Ames / Iowa State University), FIPS **19169**, SSURGO survey area **IA169** **(verify)**.
**Example fields (3–4, choose on the satellite map):** flat poorly drained tile-drained field; sloping erosion-prone field; lighter/drier soil; optionally a low-lying field.

### Existing rotation
**Corn–soybean**, alternating annually (dominant across the Corn Belt). Some fields run corn–corn–soy or continuous corn — the app must accept any existing sequence of supported crops.

### Real pressures
- **Long bare-soil windows:** harvest (Sep–Nov) to planting (Apr–May) → bare ~6–7 months.
- **Erosion** on slopes, especially spring storms before canopy closure.
- **Nitrate loss** through tile drainage (drinking water; Gulf of Mexico hypoxia; Iowa Nutrient Reduction Strategy).
- **Pests and weeds:** corn rootworm (rotation is main control; rotation-resistant variants exist in parts of the Corn Belt **(verify for Iowa)**); soybean cyst nematode; herbicide-resistant waterhemp.
- **Weather extremes:** 2012 drought, 2019 wet spring with widespread prevented planting, 2020 derecho.
- **Soil organic matter decline** since prairie conversion.
- **[playbook] Economics:** cost squeeze — Iowa State's 2026 cost estimates (reported as ~$4.33/bu corn after soybean and ~$10.96/bu soybean via Iowa Farm Bureau — verify against FM 1712).

### Rotation library (modular)
**Base sequences**
1. Corn–soybean (C–S) — usual existing baseline
2. Corn–soybean–winter wheat (C–S–W)
3. Corn–soybean–oats (+ red clover underseeded) (C–S–O/RC)
4. Corn–soybean–oats/alfalfa–alfalfa (C–S–O/A–A) — Marsden Farm 4-year system

**Cover-crop modifier:** none · cereal rye before soybean only (lower risk: rye before corn can reduce corn yield via N immobilisation) · cereal rye after every cash crop
**Tillage modifier (stretch):** conventional / no-till

→ 4 × 3 = **12 candidates**, each with rules and evidence. **Never generate free sequences** (no citable evidence for invented rotations). The existing rotation can be any sequence of supported crops (dropdown + custom).

### Key evidence: Marsden Farm (Iowa State long-term rotation study)
Davis et al. 2012, *PLOS ONE*: diversified 3–4-year rotations cut fertiliser and herbicide use while maintaining yields and profits. The three Marsden systems match our C–S, C–S–O/RC and C–S–O/A–A options.
**[playbook] Figures to verify against the Iowa State pages before putting in cards:**
- Corn yield ~+4%, soybean ~+16% in the longer rotations (averages).
- Synthetic N ~80–86% lower in diverse rotations (2003–2011).
- Soil erosion ~50% lower; spring nitrate in drainage water ~57% lower (diverse systems); net returns not significantly different (2008–2016).
- Soybean sudden death syndrome markedly lower in the longer rotations.
**Mandatory caveat on every Marsden-based card:** the longer rotations also received periodic cattle manure and far less herbicide, so results describe **whole systems, not rotation length alone**.
Gaps/risks: oats/alfalfa markets, livestock or hay buyers, equipment, labour.

---

## 4. The farmer's journey (the app)

1. **Find the farm** — county map (restricted to Story County so every click has data).
2. **Select the field** — draw the boundary (folium Draw via `streamlit-folium` → GeoJSON) or click inside (fallback ~400 m box).
   - Official US field boundaries (CLU) are, as far as we know, not public → drawing is the robust option. Open datasets (e.g. "Fields of The World") — check coverage **(verify)**.
   - Basemap: aerial imagery (NAIP map services or standard satellite tiles; check attribution/terms).
3. **Climate snapshot [playbook]** — immediately after the field is chosen, tiles from the field's POWER cell, each with its trend since 1981 (Theil–Sen + Mann–Kendall, 6.9): frost-free season, heat units (GDD), growing-season rain (May–Sep), longest dry spell (Jun–Aug), heavy-rain days, hot days. "Heat units" explained once in plain words. Caption: "regional ~50 km grid; soil wetness is modelled, not measured".
4. **Confirm field details** — auto-filled, farmer corrects:
   - crop history from CDL ("We see corn, soy, corn, soy 2019–2024 — right?")
   - soil from SSURGO; tile drainage guess from drainage class; slope from SRTM
   - corrections override data and are recorded ("farmer-provided")
5. **Constraints** (filters).
6. **Priorities** (weights).
7. **Results:** existing rotation + top 3 alternatives:
   - **[playbook] side-by-side compare cards** showing crop sequence, a score per priority, one line of "why", and the best match to the sliders marked; optional tier labels *Current / Small step / Bigger shift* applied to the existing rotation, the best cover-crop-only variant of it, and the best more-diverse library rotation (display only; ranking unchanged)
   - ranked table, score, probability of ranking first, robustness note
   - stacked bar of score contributions per criterion
   - raw criterion values in real units ("~40 % fewer bare-and-wet days")
   - five-part card (why / evidence / benefits / gaps / risks) + confidence badge + "check with your agronomist"
   - **field calendar [playbook]**: months across, rotation years down, bare soil as empty gaps, risk windows (spring erosion window, July pollination drought window) marked
   - outcome distributions (typical year vs 1-in-10 bad year) and a plain count, e.g. "water-stressed in 4 of 45 years"
   - **replay a hard year [playbook]**: farmer picks a past year (2012, 2019, …); app shows each rotation's indicators for that year versus its typical year (from the rotation × year table the simulation already produces)
   - removed rotations with reasons ("alfalfa options hidden: no livestock or hay buyer")
   - if the existing rotation scores best, say so honestly
   - footer on every result: "This tool supports, not replaces, your judgement and local expertise."
8. **Evidence page [playbook]** — NASA data behind this field in plain language: what each dataset measures, how it differs from a ground reading, what the tool cannot see; one chart per indicator with a caption; every number links here.
9. **(Stretch)** printable one-page "Questions to discuss with your agronomist / extension agent".

### Exactly what the farmer inputs (website)
**Step 1 — Your field**
1. Draw your field on the map (or click inside it)

**Step 2 — Check your field details** (auto-filled; correct if wrong)
2. Current rotation (pre-filled from past crop maps) — asked of everyone; it is always one of the compared options
3. Soil type (pre-filled from soil survey)
4. Tile-drained? yes / no (pre-filled guess)
5. Sloping / erosion-prone? (pre-filled from elevation)

**Step 3 — What's possible on your farm**
6. Livestock, or a nearby hay buyer? yes / no
7. Buyer for oats or wheat within reach? yes / no
8. Can you seed a cover crop after harvest (yourself or hired)? yes / no
9. Hay equipment, or can you hire it? yes / no
10. Open to trying cover crops / new crops? yes / maybe / no

**Step 4 — What matters most to you** (5 sliders, or drag into order)
11. Drought resilience
12. Soil health & erosion
13. Water quality
14. Income
15. Pests & fertiliser costs

**Slider labels [playbook] — UI wording only; the slider → criteria mapping in 6.4 is unchanged.** Optionally echo the brief's words in tooltips/labels so a judge sees the match at a glance: Drought resilience → "Water use and drought"; Soil health & erosion (same); Water quality → "Water quality (and nitrogen)"; Income → "Income and markets (incl. forage value if hay is possible)"; Pests & fertiliser → "Pest and disease breaks (and nitrogen fixing)". Brief priorities covered: water use, forage value, nitrogen fixing, erosion reduction, organic matter, market suitability.

**Optional extras (if time):** tillage system, own vs rent + lease length, planning horizon, can the farm absorb a lower-income year, risk-aversion slider.

**Info-only flags on cards (not inputs):** crop-insurance / cost-share rules on cover-crop termination **(verify)**; herbicide carryover from previous programmes; organic systems out of scope; cereal rye before corn is allowed with a warning (terminate ~10–14 days before planting corn — verify with Iowa State Extension).

### Map
- **MVP:** map as input (click/draw), POWER cell outline around the field.
- **Stretch:** overlay tab — slope / erosion risk, frost-pocket flags, SMAP anomaly cells, NASA GIBS imagery **(verify tile URL)**.
- Deployment: Streamlit Community Cloud from the public GitHub repo. Free apps sleep when idle — open the app before any judging session and once a day until results.

---

## 5. How the model works — simple version

1. **Farmer picks the field** and gives constraints and priorities.
2. **We look up the field:** soil, slope, past crops (farmer confirms).
3. **Shortlist rotations:** library + farmer's current one, minus those the farmer can't run.
4. **Replay past weather on each rotation:** pretend each rotation was grown on this field in each of the last ~45 years with that year's real weather; day by day track soil water, bare soil, crop water shortage.
5. **Summarise:** typical year and bad years for each measure.
6. **Add research-based scores** for things that can't be simulated (N from legumes, pest cycles, organic matter).
7. **Compare with the current rotation** on each measure; combine using the farmer's priorities.
8. **Check how sure we are:** nudge priorities and reshuffle weather years many times.
9. **Show** current rotation + top 3 alternatives with plain-English cards, the field calendar, and the hard-year replay.

### How we can know soil water: the bucket
The root zone is a bucket. Size = soil's plant-available water (SSURGO) × root depth. Daily:
**tomorrow's water = today's + rain − evapotranspiration − drainage − runoff.**
- **Weather thirst** (reference ET₀): Penman–Monteith from POWER's sun, temperature, humidity, wind (~5 mm on a hot windy July day, <1 mm in winter).
- **Crop thirst** (crop coefficient $K_c$): tabulated in FAO-56 (young corn ≪ grass; full-canopy corn ≈ 1.2× grass; bare soil low once surface dries).
- **Crop water use = ET₀ × $K_c$.**
- Weather and soil are identical across rotations; **only which crop (if any) is in the ground each day changes** → different $K_c$, root depth → different water use, drainage, bare days. Example: rye in April uses water → less drainage (less nitrate loss) but drier soil at corn planting in a dry spring — the trade-off emerges from arithmetic, not a hand-written rule.
- **Validation:** run the bucket with actual CDL crops and compare modelled soil water with SMAP and the ISU ground sensor near Ames.

---

## 6. How the model works — detailed specification

### 6.1 Pipeline stages
| # | Stage | Module(s) | Output |
|---|---|---|---|
| 1 | Field characterisation | `data/field.py` (uses `soil.py`, `terrain.py`, `cdl.py`) | `FieldProfile` |
| 2 | Weather ensemble | `data/power.py` | daily weather 1981–2025 for the field's POWER cell |
| 3 | Candidates + filters | `model/rotations.py` | candidate list + removed list with reasons |
| 4 | Simulation | `model/et0.py`, `crops.py`, `water_balance.py`, `indicators.py` | rotation × year table of indicators |
| 5 | Distributions | `model/bootstrap.py` | per rotation × criterion: statistic + CI + replicates |
| 6 | Knowledge criteria | `content/rotations.yaml` | ordinal scores with citations/confidence |
| 7 | Scoring | `model/scoring.py` | decision matrix → normalised values → weighted scores |
| 8 | Robustness | `model/scoring.py` | P(rank first), score ranges, Pareto flags |
| 9 | Results | `pipeline.py` | JSON-shaped result dict (10.3) |

### 6.2 Simulation details
- **Daily loop** over the full weather record for each rotation.
- **Phase offsets:** run each rotation once per starting phase (C–S: start corn and start soy; 3-year: 3 runs), so every weather year meets every crop; pool the rotation-years.
- **Crop calendar:** typical planting/harvest dates per crop (USDA Usual Planting and Harvesting Dates / NASS Crop Progress); later stretch: dates as distributions.
- **$K_c$ curve:** FAO-56 piecewise ($K_{c,\text{ini}} \to K_{c,\text{mid}} \to K_{c,\text{end}}$) with stage lengths; bare soil uses a low evaporation-only coefficient **(simplification; verify range in FAO-56)**; cereal rye not in FAO-56 → use small-grain values (flag as gap).
- **Root depth:** grows from planting to maximum; TAW capped at 1 m (SSURGO `aws0100wta` covers top 100 cm; deeper roots e.g. alfalfa → note as gap).
- **Drainage:** tile-drained → excess above field capacity drains the same day; not tiled → limited drainage rate → waterlogging days.
- **Runoff:** MVP 0 or simple intensity rule; stretch curve-number method using hydrologic soil group.
- **Snow:** POWER precipitation treated as rain (timing error at snowmelt — list as gap).
- **Year-to-year carry-over:** soil water carries across 1 January (years not fully independent; winter recharge usually refills — note).
- **Stress:** $K_s$ when depletion exceeds RAW; count stressed days in each crop's sensitive window (corn ~mid-July pollination; soybean ~August pod fill — set in `crops.csv`).

### 6.3 Criteria (what we assess)
Three types: **simulated** (daily model), **counted** (from sequence/calendar), **literature** (ordinal 0–3 with citation + confidence).

| Criterion (MVP) | Measure | Type | Summary statistic | Direction |
|---|---|---|---|---|
| `drought_risk` | stressed days / deficit in the sensitive window | simulated | **CVaR**: mean of worst 10 % of years | cost |
| `water_leaving` | annual drainage (nitrate-loss proxy) | simulated | mean | cost |
| `erosion_exposure` | bare-and-wet days (bare + heavy rain), scaled by slope; RUSLE stretch | counted + weather | mean | cost |
| `som_proxy` | living-root months + perennial years + literature score | counted + literature | fixed | benefit |
| `n_benefit` | legume years; reduced N need after legumes (Iowa State N guidance) | counted + literature | fixed (ordinal) | benefit |
| `pest_break` | longest same-crop run, years between repeats, number of crops + literature (rootworm, SCN, waterhemp) | counted + literature | fixed (ordinal) | benefit |
| `income` | typical margin over the rotation (NASS county yields adjusted by literature rotation effects; Iowa State crop budgets; cover-crop cost; hay counted only with buyer + equipment) | literature/data | mean (± price range) | benefit |

**Not scored, shown as flags/risks on cards:** cover-crop establishment probability (GDD after harvest before frost), frost after planting, hot days at pollination, too-wet-to-plant springs.
**Optional criteria:** forage value (only if livestock = yes), simplicity/workload, income stability (risk-aversion).
**Deliberately not measured:** predicted yield per year (needs a calibrated crop-growth model).
**Avoid double counting:** drainage, nitrate loss and waterlogging come from one flux → one criterion. If two criteria always move together, merge them.

### 6.4 Slider → criteria mapping
| Slider | Criteria (weight split equally within a slider) |
|---|---|
| Drought resilience | `drought_risk` |
| Soil health & erosion | `erosion_exposure` (½), `som_proxy` (½) |
| Water quality | `water_leaving` |
| Income | `income` |
| Pests & fertiliser costs | `pest_break` (½), `n_benefit` (½) |

Weights normalised to sum to 1. **Alternative input:** drag priorities into order → **rank-order centroid weights** $w_i = \frac{1}{n}\sum_{k=i}^{n}\frac{1}{k}$ (5 priorities → ≈ 0.46, 0.26, 0.16, 0.09, 0.04).

### 6.5 Normalisation (relative to the existing rotation)
Existing rotation scores exactly **0.5** on every criterion; >0.5 = better than now.
- Cost criterion: relative improvement $r = (x_\text{existing} - x)/\max(|x_\text{existing}|,\ s_k)$; benefit: sign flipped. $s_k$ = reference scale preventing division by ~0.
- Value: $v = 0.5 + \tfrac{1}{2}\,\text{clip}(r / c_k,\ -1,\ 1)$, $c_k$ = relative change mapping to 0 or 1 (default 0.5; **set from each criterion's plausible range to avoid saturation**).
- Optional non-linear value functions (keep simple): deficit penalised only beyond RAW; saturating ground-cover benefit $1 - e^{-x/\tau}$.
- Ordinal criteria: $v = 0.5 + \Delta/6$, $\Delta$ = level difference from existing (−3…+3).
- Why not min–max across candidates: adding/removing a candidate rescales and can reverse rankings.
- Weights are **swing weights**.

### 6.6 Scoring, decision matrix, Pareto
- Per rotation a **vector** $\mathbf{v}_r$; stacked → **decision matrix** $V$ (rotations × criteria).
- Score $\mathbf{S} = V\mathbf{w}$ (single number per rotation, only for ranking).
- With bootstrap: array (replicates × rotations × criteria) → scores → distribution per rotation.
- Keep the vector for explanation: contributions $w_k v_{rk}$ (stacked bar) + raw values in real units.
- **Pareto check** (no weights): A dominates B if ≥ on all criteria and > on one → flag/drop dominated rotations (~30 min).

```python
import numpy as np
# V: (n_boot, n_rot, n_crit) normalised values; w: (n_crit,) weights
S = V @ w                                                          # (n_boot, n_rot)
p_top = np.bincount(S.argmax(axis=1), minlength=S.shape[1]) / S.shape[0]
contrib = V.mean(axis=0) * w                                       # (n_rot, n_crit) explanation
```

### 6.7 Robustness to weights
Sample $\mathbf{w} \sim \text{Dirichlet}(\alpha\,\mathbf{w}_\text{farmer})$ ($\alpha$ ~20), re-rank each sample (combined with bootstrap replicates) → **P(rank first)** and score ranges. "This option comes out on top in 78 % of plausible weightings."

### 6.8 Optional quant extra: risk aversion (CVaR)
$\text{CVaR}_{0.1} = \mathbb{E}[X \mid X \ge q_{0.9}(X)]$. Risk-aversion slider $\lambda$ scores on $\mathbb{E}[X] + \lambda(\text{CVaR}_{0.1} - \mathbb{E}[X])$. ~1–2 h once the bootstrap exists.

### 6.9 Uncertainty and climate period
- **Bootstrap whole years** (not days — preserves within-season autocorrelation).
- ~45 years → P10 rests on ~4–5 seasons; **bootstrap the statistic itself** for a CI.
- **Parameter perturbation:** $K_c$, root depth, AWC within literature ranges.
- **Climate period options:**
  - MVP: equal weights, all years 1981–2025.
  - Main analysis once working: **detrend temperature** to present-day if Mann–Kendall is significant (Theil–Sen slope; shift each year by slope × (2025 − y); keep RH fixed → small VPD change, note it). Don't detrend rainfall unless clearly significant.
  - Robustness: **recent 30 years** (1996–2025) and **exponential weighting** $w_y = 2^{-(2025-y)/h}$. $n_\text{eff} = (\sum w)^2/\sum w^2$: half-life 15 y → ≈ 34 of 45; 10 y → ≈ 26.
  - Report "ranking robust to how past climate is weighted" or flag disagreement as a gap.
- **Trends shown to farmer:** Theil–Sen + Mann–Kendall on yearly summaries (last spring frost, wet spring days, hot July days, etc.).
- **What-if sliders:** +1/+2 °C, −10/−20 % summer rain.
- Every card: confidence badge + "check with your agronomist / extension agent".

### 6.10 Toy example (made-up numbers)
Weights: drought 0.4, erosion 0.4, N 0.2.

| Rotation | Drought CVaR (mm, cost) | Erosion index (cost) | N (0–3) |
|---|---|---|---|
| C–S (existing) | 120 | 60 | 1 |
| C–S + rye | 125 | 30 | 1 |
| C–S–O/A–A | 100 | 25 | 3 |

| Rotation | $v_d$ | $v_e$ | $v_N$ | $S$ |
|---|---|---|---|---|
| C–S | 0.50 | 0.50 | 0.50 | **0.50** |
| + rye | 0.46 | 1.00 | 0.50 | **0.68** |
| + oats/alfalfa | 0.67 | 1.00 (capped) | 0.83 | **0.83** |

If the farmer has no livestock/hay buyer, the alfalfa option is filtered out first → rye option tops the list; its card names the small drought penalty as a risk.

### 6.11 Validation (strong Validity evidence)
- POWER vs ISU station / PRISM (temperature, rainfall).
- Bucket model with actual CDL crops vs SMAP (anomaly correlation) and ISU in-situ soil moisture.
- Satellite vs ground explanation built from these comparisons.

### 6.12 Optional analyses
- **Weather regimes (idea G):** per-year features → k-means vs Ward vs GMM; silhouette, adjusted Rand index; rotations evaluated per regime.
- **CDL Markov transitions (idea F):** $P_{ij} = P(\text{crop}_{t+1}=j \mid \text{crop}_t=i)$.
- R → Python: `kmeans()` → `sklearn.cluster.KMeans`; `hclust(method="ward.D2")` → `scipy.cluster.hierarchy.linkage(X, "ward")`; `Mclust` → `sklearn.mixture.GaussianMixture`. Standardise features first.

### 6.13 Card generation
Cards are **templates filled with computed numbers + YAML evidence**; nothing invented at runtime. Each claim has a source; gaps include soil-data coverage, SOM uncertainty, regional climate, model simplifications. **[playbook]** Every rule that changes a score also adds one plain sentence to the explanation, kept as readable data in `content/rotations.yaml` so a judge can read it. Mark crop ratings and thresholds as "starting values — agronomist should review".

### 6.14 Climate snapshot indicators and hard-year replay **[playbook; additions, engine unchanged]**
These are **display/validation outputs** computed from the same POWER record; they do not change the scoring.

| Indicator | Computation | Use |
|---|---|---|
| Growing degree days | Apr–Oct sum of daily GDD. Playbook formula `(min(Tmax,30)+max(Tmin,10))/2 − 10` (°C) goes negative when Tmax < 10 °C → **clip Tmax to [10, 30] and take max(0, ·)**, or use the US °F convention in 7.2 | snapshot tile; cover-crop establishment flag |
| Frost-free season | days between last spring and first autumn Tmin ≤ 0 °C | snapshot; calendar planting/harvest windows |
| Growing-season rain | May–Sep total, mm | snapshot |
| Longest dry spell | longest run of days < 1 mm, Jun–Aug | snapshot; drought-at-pollination context |
| Hot days | days Tmax > 30 °C, Jul–Aug | heat-stress flag |
| Heavy-rain days | days > 25 mm, Mar–Jun | erosion-window context |
| Root-zone wetness | mean GWETROOT Apr–May and Jul–Aug | wet-spring/summer-stress context (modelled, not measured) |
Thresholds are starting suggestions: check against Iowa State Extension and cite the one used. Show each as a yearly series with Theil–Sen trend.

**Hard-year replay:** from the rotation × year table (stage 4), for a chosen year *y* show per rotation: stressed days, drainage, bare-and-wet days, relative to that rotation's own typical value and to the existing rotation. Provide a shortlist of notable years detected automatically (e.g. highest drought deficit, wettest spring) and confirm 2012 stands out before demoing it. Plain count line: "water-stressed in N of 45 years".

---

## 7. Background knowledge

### 7.1 Agronomy (US Corn Belt)
**Why rotations matter:** break pest/disease/weed cycles; nutrient cycling (soybean leaves N, corn uses lots; corn after soy typically yields more than corn after corn — the "rotation effect"); soil structure and organic matter; spread risk across windows and markets.

**Iowa crop calendar (approximate)**
| Crop | Planted | Harvested | Notes |
|---|---|---|---|
| Corn | mid-Apr – May | late Sep – Nov | heavy N user; heat/drought-sensitive at pollination (July) |
| Soybean | late Apr – early Jun | late Sep – Oct | legume, fixes N |
| Oats | Mar – Apr | Jul | often underseeded with clover/alfalfa; off the field before late-summer heat |
| Alfalfa | spring or late summer | several cuts/year, 2–4+ years | perennial legume, deep roots; needs hay equipment and a buyer |
| Winter wheat | Sep – Oct | Jul | winter cover + cash crop |
| Cereal rye (cover) | Sep – Nov | terminated before spring planting | not harvested |
| Red clover (cover) | sown with oats | grows on after oat harvest | supplies N to next corn **[playbook; verify]** |

**[playbook] Starter ratings** (1–5, from general agronomy, **unverified** — verify and source before use in `crops.csv`; they supplement, not replace, FAO-56 $K_c$/root depth/p): water need — corn 5, soybean 4, oats 3, winter wheat 3, alfalfa 4, rye 2, clover 2; soil cover — corn 2, soybean 1, oats 3, wheat 4, alfalfa 5, rye 5, clover 5; N need — corn 5, soybean 1, oats 2, wheat 3, alfalfa 1, rye 1, clover 1. Use only for literature/ordinal criteria and card text, never inside the water model.

**Bare-field windows:** harvest → spring planting; early spring before canopy closure (erosion window).

**Soil-building crops:** legumes (rhizobia fix N₂); cover crops (living roots over winter); deep-rooted perennials (alfalfa); small grains (break corn–soy pest/weed cycles).

**Soil-health vocabulary:** SOM (changes over years–decades; state "tends to improve", cite, list as gap), aggregate stability, infiltration, compaction, tile drainage.

**Income and policy (verify current status):** NRCS programmes (e.g. EQIP) have provided cover-crop cost-share; Iowa has run cover-crop incentive programmes. Oats/alfalfa markets depend on local livestock and buyers.

### 7.2 Agro-climate indicators
- **Corn GDD** (US convention, °F, base 50, cap 86): $\text{GDD} = \sum\left(\tfrac{T^*_{\max}+T^*_{\min}}{2} - 50\right)$, $T^*$ clipped to [50, 86] °F (≈ base 10 °C, cap 30 °C).
- **Frost:** $T_{\min} < 0$ °C; last spring / first autumn frost as distributions.
- **Frost scales:** regional climatology (POWER/PRISM) + local frost pockets (cold air pools in low ground; flag from SRTM; MODIS night LST shows patterns but LST ≠ air temperature).
- **Heat stress:** corn pollination (July) sensitive to heat + drought.
- **Wet springs:** multi-day totals, soil-water surplus → delayed/prevented planting, waterlogging, erosion.

### 7.3 Water balance (FAO-56)
**Reference ET₀ (Penman–Monteith):**
$$ET_0 = \frac{0.408\,\Delta (R_n - G) + \gamma \dfrac{900}{T+273} u_2 (e_s - e_a)}{\Delta + \gamma(1 + 0.34\,u_2)} \quad [\text{mm day}^{-1}]$$

| Symbol | Meaning | Units |
|---|---|---|
| $R_n$ | net radiation | MJ m⁻² day⁻¹ |
| $G$ | soil heat flux (≈ 0 daily) | MJ m⁻² day⁻¹ |
| $T$ | mean 2 m air temperature | °C |
| $u_2$ | wind speed at 2 m | m s⁻¹ |
| $e_s - e_a$ | vapour pressure deficit | kPa |
| $\Delta$ | slope of saturation vapour pressure curve | kPa °C⁻¹ |
| $\gamma$ | psychrometric constant | kPa °C⁻¹ |

**Crop ET:** $ET_c = K_c \cdot ET_0$.
**Bucket:** $D_{r,i} = D_{r,i-1} - (P_i - RO_i) - I_i + ET_{c,i} + DP_i$; $TAW = 1000(\theta_{FC} - \theta_{WP})Z_r$ = AWC (mm/m) × $Z_r$; $RAW = p \cdot TAW$; $K_s = \dfrac{TAW - D_r}{(1-p)TAW}$ when $D_r > RAW$.
Reference: Allen, Pereira, Raes & Smith (1998), *FAO Irrigation and Drainage Paper 56*.

### 7.4 Remote sensing
Satellites measure radiation; everything else is a **retrieval**.
- **NDVI** $= (\text{NIR} - \text{Red})/(\text{NIR} + \text{Red})$. Bare soil ≈ 0.1–0.2, sparse crop 0.3–0.5, dense canopy 0.7–0.9. Limits: cloud, saturation, not crop type/yield/soil health by itself.
- **HLS** (Harmonized Landsat Sentinel-2): 30 m, few-day revisit — best field-scale NDVI. Sentinel-2 native 10–20 m. MODIS/VIIRS 250–1000 m (coarse; playbook suggests MODIS NDVI via AppEEARS for demo points — acceptable as a cheap add-on, HLS preferred for field scale).
- **SMAP:** L-band passive microwave; top ~5 cm; 36/9 km; **record starts 2015**. SMAP L4: model-assimilated root-zone moisture at 9 km.
- **Soil-moisture anomaly:** $z(t) = (x(t) - \mu_{\text{doy}(t)})/\sigma_{\text{doy}(t)}$ — "unusually dry for this time of year here". Absolute satellite values are biased; variations more trustworthy.
- **NLDAS** (US, ~1/8°, hourly, from 1979 **(verify)**) / GLDAS (global, 0.25°): model soil moisture/ET with long records.
- **GPM IMERG:** merged rainfall, 0.1°, 30 min → intense-rain events.
- **GRACE/GRACE-FO:** water storage change, ~300 km+ → regional context only in Iowa.
- **ECOSTRESS:** ~70 m LST and ET/evaporative stress from the ISS; irregular overpasses.
- **SRTM:** 30 m elevation → slope, terrain position.
- **NASA POWER:** mostly reanalysis/model output (MERRA-2, CERES) on ~0.5° grid; consistent since 1981 but **not point measurements**.

### 7.5 Satellite vs ground
| | Ground sensor | Satellite |
|---|---|---|
| Measures | a point, directly | an area average, via retrieval |
| Coverage | sparse | wide, consistent |
| Depth / timing | e.g. probe at 30 cm, continuous | top 5 cm (SMAP), overpass times |

Differences are partly **representativeness error**. Ground data calibrates/validates; satellites extend coverage. In Iowa: ISU Soil Moisture Network (Iowa Environmental Mesonet), PRISM, station weather.

---

## 8. Data

### 8.1 What the data looks like
| Dataset | Format | Spatial res. | Temporal | Field-level? |
|---|---|---|---|---|
| NASA POWER | JSON/CSV per point | ~0.5° × 0.625° (met), ~1° (solar) **(verify)** | daily since 1981 | No |
| PRISM | gridded rasters | 4 km daily **(verify finer)** | daily | Partly |
| GPM IMERG | HDF5/netCDF | 0.1° | 30 min / daily | No |
| SMAP L3/L4 | HDF5 (EASE-Grid 2.0) | 36 / 9 km | daily / 3-hourly | No |
| NLDAS / GLDAS | netCDF | 1/8° / 0.25° | hourly–monthly | No |
| GRACE/GRACE-FO | netCDF monthly | ~300 km+ | monthly | No |
| HLS / Sentinel-2 | GeoTIFF per band | 10–30 m | days (cloud-limited) | **Yes** |
| ECOSTRESS | GeoTIFF/HDF5 | ~70 m | irregular | Yes (sparse) |
| SRTM | GeoTIFF DEM | 30 m | static | **Yes** |
| CDL | GeoTIFF classes | 30 m **(verify recent years)** | annual since 2008 | **Yes** |
| SSURGO | map-unit polygons + tables | field-scale | static | **Yes** |

Fields: quarter sections ≈ 65 ha (~800 m × 800 m) or smaller → hundreds of HLS pixels; tiny fraction of a POWER/SMAP cell.

POWER in pandas columns: date, T2M, T2M_MAX, T2M_MIN, T2MDEW, RH2M, WS2M, PS, PRECTOTCORR, ALLSKY_SFC_SW_DWN, CLRSKY_SFC_SW_DWN, GWETTOP, GWETROOT. Units: read from response metadata (never assume). Fill value −999.

### 8.2 Dataset triage
| Tier | Dataset | Role |
|---|---|---|
| **MVP** | NASA POWER | weather backbone: ET₀, GDD, frost, snapshot, bootstrap years |
| | CDL | field crop history → existing rotation |
| | SSURGO | AWC, drainage class, hydrologic group, K |
| | SRTM | slope |
| **Add-on** | SMAP (AppEEARS point extraction) | real satellite observation layer; satellite vs ground |
| | GPM IMERG | intense-rain events → erosion window |
| | NLDAS (instead of GLDAS for US) | long-record soil moisture |
| | MODIS NDVI via AppEEARS **[playbook]** | demo fields only; vegetation-stress/bare-period illustration (HLS preferred) |
| **Stretch** | HLS (incl. Sentinel-2) | field NDVI, bare-period detection |
| | PRISM | validate POWER |
| | NASS QuickStats | county yields/acreage |
| | ECOSTRESS | heat/water-stress snapshots |
| | NEX-GDDP-CMIP6 | 2050s outlook tab (lowest priority) |
| **Context only** | GRACE/GRACE-FO, FAO GAEZ, USDA AMS Market News | one panel / one card line |
| **Skip** | GEDI (forests), LANDFIRE, NLCD, OpenET (western states only), NWIS, CoCoRaHS, VIIRS, ERA5, NAIP (basemap only), Web Soil Survey (only as SSURGO download), Ag Data Commons | |

Submission NASA list: POWER + SRTM (MVP) + SMAP (+ MODIS NDVI if done) + any add-ons used. **[playbook]** One dataset driving every score plus one satellite product beats nine logos: name only datasets that do work, each with the decision it drives.

### 8.3 Extra (non-Resources) data
| Need | Source | Use |
|---|---|---|
| Crop water parameters | FAO-56 tables | water model (MVP) |
| Planting/harvest timing | USDA *Usual Planting and Harvesting Dates* (2010); NASS Crop Progress | calendars |
| Rotation/cover evidence | Marsden Farm (Davis et al. 2012; Iowa State Marsden pages), Iowa State Extension (cereal rye before soybean recipe; corn after rye termination timing), SARE *Managing Cover Crops Profitably* | cards (MVP) |
| Costs/income | Iowa State Ag Decision Maker "Estimated Costs of Crop Production in Iowa" (FM 1712) | income criterion |
| N credits | Iowa State nitrogen guidance | `n_benefit` |
| Erosion factors | RUSLE literature; $R$ from NRCS data or IMERG **(verify)** | erosion proxy / idea H |
| Ground truth | Iowa Environmental Mesonet: ISU Soil Moisture Network + station weather | validation |
| County boundary | US Census TIGER/cartographic boundary files | map limit |
| Basemap | NAIP map services / satellite tile layer (check terms) | field drawing |
| Scale number **[playbook]** | USDA NASS: Iowa corn and soybean acres | one sourced number for the Impact slide |

Tile drainage: no reliable public map → SSURGO drainage class as hint + farmer confirms.

### 8.4 Free and easy?
All free. Logins: **NASA Earthdata** (SRTM, SMAP, AppEEARS, NLDAS, HLS); optional **NASS QuickStats API key**. Effort hotspots: **SSURGO tables** (2–3 h, or Soil Data Access queries); **compiling crop parameters and evidence** (3–4 h reading); **RUSLE factors** (stretch). PRISM 800 m availability uncertain **(verify)**. CropScape can be slow → fallback: website download.
Licensing: US government data generally public domain → small derived files can be committed; keep large raw files out of git; don't commit copyrighted PDFs (cite links). Cite every source in the README.

### 8.5 Access routes
| Route | Request? | Wait | Use |
|---|---|---|---|
| NASA POWER API | no login | seconds | weather |
| `earthaccess` (Python) | Earthdata login | minutes | SRTM, NLDAS, SMAP, HLS files |
| Earthdata Search (website) | login | — | exploring: short names/versions, coverage |
| AppEEARS | login; queued job | minutes–hours | point/area time series as CSV (SMAP, MODIS etc.) |

- **Workflow:** find product in Earthdata Search → short name into `config.py` → download with `earthaccess` in `scripts/prefetch_data.py`.
- **Authorise archives** in Earthdata profile → Applications → Authorized Apps (e.g. "NASA GESDISC DATA ARCHIVE"). 401/403 usually means this.
- **AppEEARS:** extracts your points/area/dates/variables on NASA servers, returns small CSVs with quality flags. Slow queue — **submit requests first thing Saturday**. Confirm exact product names in the AppEEARS list (playbook named MODIS NDVI and SMAP root-zone from memory). Cite the dataset, noting AppEEARS as the route. Label the files in-app as "available for demo fields only".
- **Download everything for the county in advance**; the app never calls external services during the demo. Keep a saved copy of POWER data for demo fields as a fallback.

| Dataset | How | Size (one county) |
|---|---|---|
| POWER | 1 API call per cell (county spans 1–2 cells) | few MB |
| CDL | county GeoTIFF per year (CropScape) **(verify)** | few MB/year |
| SSURGO | Web Soil Survey download + Soil Data Access | tens of MB |
| SRTM | 1–2 tiles via earthaccess | ~25 MB each |
| PRISM | bulk download, crop | small after crop |
| SMAP / NLDAS | AppEEARS / earthaccess subset | moderate — check `g.size()` first |
| HLS | **example fields only** | can reach GBs |

---

## 9. Data harmonisation and spatial units
- **Unit of analysis:** field polygon (drawn) or ~400 m box around a clicked point.
- **Coarse layers** (POWER, GPM, SMAP, NLDAS, GRACE): containing cell (bilinear for smooth fields like temperature).
- **Fine layers** (HLS, SRTM, SSURGO, CDL): zonal statistics over the polygon; SSURGO area-weighted (numeric) / dominant + mix (categorical); CDL majority class per year.
- **Equal-area projection** for areas: CONUS Albers **EPSG:5070**.
- **Time:** daily (water balance), dekadal (NDVI), monthly (GRACE/NLDAS monthly).
- **Always aggregate fine → coarse**; never interpolate coarse data down as if it were field detail.
- **Regional map (stretch):** common ~1 km grid; coarse layers will look blocky (honest).
- **Units:** compute in SI; display °F, inches, acres, bushels/acre for US farmers.
- Tools: `xarray`, `rioxarray`, `geopandas`, `rasterstats`.

---

## 10. Architecture, files and contract

### 10.1 Repository structure
```
field-shift/
├── README.md                  # what it does, how to run, datasets (with citations), limitations, AI-use section
├── CLAUDE.md                  # this file
├── LICENSE
├── requirements.txt
├── .gitignore                 # data/raw/, large files, .netrc, node_modules/, web/dist/
├── docs/
│   ├── brief.md
│   └── project-guide.md
├── content/                   # agronomy as data, every row with a source column
│   ├── crops.csv              # Kc ini/mid/end, stage lengths, root depth, p, sow/harvest dates, sensitive window, source (+ starter ratings, flagged unverified)
│   ├── soils.csv              # fallback soil classes → AWC, drainage (farmer override)
│   ├── rotations.yaml         # library: base sequences, modifiers, constraints, ordinal scores, card text, citations, Marsden figures
│   ├── criteria.yaml          # per criterion: statistic, direction, scale s_k, cap c_k, value function
│   └── glossary.yaml          # plain-language explanations
├── sample_data/               # saved POWER (+ AppEEARS) files for demo fields
├── src/fieldshift/
│   ├── config.py              # county, bbox, FIPS, paths, baseline years, product short names, units
│   ├── data/                  # one file per SOURCE: load, clean, cache — no analysis
│   │   ├── power.py           # POWER daily weather, units checked, gaps handled            [MVP]
│   │   ├── soil.py            # SSURGO → SoilProfile                                          [MVP]
│   │   ├── terrain.py         # SRTM → slope                                                  [MVP]
│   │   ├── cdl.py             # CDL → crop sequence by year                                   [MVP]
│   │   ├── field.py           # soil/terrain/cdl → FieldProfile (+ farmer overrides)          [MVP]
│   │   ├── smap.py            # AppEEARS SMAP CSV → quality-filtered daily series             [add-on]
│   │   ├── ground.py          # ISU station soil moisture/weather                             [add-on]
│   │   └── ndvi.py            # HLS / MODIS NDVI                                              [stretch]
│   ├── model/                 # one file per METHOD
│   │   ├── et0.py             # FAO-56 Penman–Monteith                                        [MVP]
│   │   ├── crops.py           # daily Kc + root depth for a rotation & phase                  [MVP]
│   │   ├── water_balance.py   # bucket → depletion, Ks, stress, drainage                      [MVP]
│   │   ├── indicators.py      # GDD, frost, heat days, dry spell, heavy-rain days, bare days, bare-and-wet days [MVP]
│   │   ├── rotations.py       # load library, build candidates, filter by constraints         [MVP]
│   │   ├── bootstrap.py       # year bootstrap (weighted), statistics + CIs                   [MVP]
│   │   ├── scoring.py         # normalise, weights, Pareto, Dirichlet sensitivity            [MVP]
│   │   ├── replay.py          # hard-year replay from rotation × year table                  [add-on, high value]
│   │   ├── validation.py      # model/satellite/ground comparisons                            [add-on]
│   │   ├── trends.py          # Theil–Sen + Mann–Kendall, detrending                          [add-on]
│   │   ├── scenarios.py       # delta change                                                  [add-on]
│   │   ├── regimes.py         # k-means vs Ward vs GMM                                        [add-on]
│   │   └── transitions.py     # CDL Markov matrix                                             [add-on]
│   └── pipeline.py            # run_analysis(inputs) → results dict (THE contract)
├── app/
│   ├── streamlit_app.py       # entry: layout, tabs, calls pipeline (st.cache_data)
│   └── ui/
│       ├── inputs.py          # widgets → FarmInputs
│       ├── map_view.py        # folium county map, draw/click, POWER cell outline
│       ├── snapshot.py        # climate snapshot tiles                                         [playbook]
│       ├── charts.py          # plotly: calendar, distributions, contributions, sensitivity, replay
│       ├── cards.py           # five-part cards, confidence badges, agronomist flags
│       └── evidence.py        # evidence page: datasets in plain language, satellite vs ground, limits [playbook]
├── scripts/prefetch_data.py   # downloads + caches everything for the county
├── tests/
│   ├── test_et0.py            # reproduce FAO-56 worked example
│   ├── test_water_balance.py  # mass conservation ΣP − ΣET − ΣDP − ΣRO = ΔS
│   ├── test_scoring.py        # existing rotation scores 0.5; toy example reproduces
│   └── test_sanity.py         # playbook sanity checks (below)
└── data/                      # raw/ (gitignored) + processed/ (small parquet/CSV)
```

**Rule of thumb:** getting/cleaning a source → `data/`; computing from it → `model/`; scores → `scoring.py` + `criteria.yaml`. Temperature is loaded once in `power.py` and used by `et0.py`, `indicators.py` and (via ET₀) `water_balance.py`.

**Design rules:** no `st.` calls in `src/`; agronomy in `content/` with sources; demo runs from cached data; wrap pipeline calls in `@st.cache_data`. Cache NASA responses keyed on lat/lon rounded to 2 decimals.

**Build order (backend):** `config` → `power` → `et0` (+ test) → `soil` + `crops` → `water_balance` (+ test) → `indicators` → `terrain` + `cdl` + `field` → `rotations` → `bootstrap` → `scoring` (+ test) → `pipeline` → `replay`.

**Sanity checks to run once working [playbook, adapted to our engine]:**
1. Income weighted maximally, no hay buyer → C–S (or its cheap variants) at or near the top.
2. Soil health weighted maximally, hay possible → C–S–O/A–A at or near the top.
3. Switching hay buyer/equipment off removes the alfalfa options and shows why.
4. A drier NW-Iowa field scores corn-heavy rotations lower on drought than a wetter SE-Iowa one (only if a second location's POWER data is downloaded; otherwise skip).
5. Moving sliders changes the ranking sensibly and P(rank first) updates.

### 10.2 Inputs contract: `FarmInputs`
```python
from dataclasses import dataclass, field

@dataclass
class FarmInputs:
    field_geojson: dict                      # polygon in WGS84 (or a box built from a clicked point)
    existing_rotation: list[str]             # e.g. ["corn", "soybean"]; any sequence of supported crops
    overrides: dict = field(default_factory=dict)   # soil_class, tile_drained, erosion_prone (None = use data)
    livestock_or_hay_buyer: bool = False
    small_grain_buyer: bool = False
    can_seed_cover: bool = True
    hay_equipment: bool = False
    openness: str = "maybe"                  # "yes" | "maybe" | "no"
    weights: dict = field(default_factory=lambda: {
        "drought": 0.2, "soil_erosion": 0.2, "water_quality": 0.2, "income": 0.2, "pests_fertiliser": 0.2})
    climate_window: str = "all"              # "all" | "recent30" | "weighted"
    detrend_temperature: bool = False
    delta_temp_c: float = 0.0                # what-if sliders
    delta_summer_rain_pct: float = 0.0
    replay_year: int | None = None           # hard-year replay (e.g. 2012); None = off
```

### 10.3 Output contract: `run_analysis(inputs) -> dict`
```python
{
  "field": {"soil": {...SoilProfile...}, "slope_pct": ..., "crop_history": {"2019": "corn", ...},
            "power_cell": [lon_min, lat_min, lon_max, lat_max], "overridden": ["tile_drained"]},
  "snapshot": {                                   # climate snapshot tiles (6.14)
    "gdd": {"recent_mean": ..., "trend_per_decade": ..., "p_value": ...},
    "frost_free_days": {...}, "growing_season_rain_mm": {...}, "longest_dry_spell_days": {...},
    "hot_days": {...}, "heavy_rain_days": {...}},
  "results": [                                   # existing rotation first, then top 3 by score
    {"rotation_id": "cs_rye_before_soy",
     "name": "Corn–soybean + cereal rye before soybean",
     "tier": "small_step",                       # optional display label: current | small_step | bigger_shift
     "is_existing": False,
     "best_match": False,
     "score": {"mean": ..., "p05": ..., "p95": ..., "p_top": ...},
     "pareto_dominated": False,
     "criteria": {"drought_risk": {"raw": ..., "unit": "days", "v": ..., "contribution": ..., "ci": [..., ...]}, ...},
     "distributions": {"drought_risk": [...per-year values...], ...},
     "stressed_years": {"n": 4, "of": 45},       # "water-stressed in 4 of 45 years"
     "bare_months": ...,
     "calendar": [{"year_in_rotation": 1, "month": 1, "state": "bare|crop|cover", "risk": ["erosion"]}, ...],
     "replay": {"year": 2012, "criteria": {"drought_risk": {"that_year": ..., "typical": ...}, ...}},
     "card": {"why": "...", "evidence": [{"claim": "...", "source": "..."}],
              "benefits": "...", "gaps": "...", "risks": "..."},
     "confidence": "high|medium|low",
     "flags": ["Check cover-crop termination rules with your insurer"]}
  ],
  "removed": [{"rotation_id": "csoaa", "reason": "Needs livestock or a hay buyer"}],
  "robustness": {"recent30_same_top": True, "weighted_same_top": True, "note": "..."},
  "trends": {"last_spring_frost": {"slope_days_per_decade": ..., "p_value": ...}, ...}
}
```
Write a **mock version of this dict by hand first** (`tests/mock_results.json`: existing + 3 rotations, with calendar and replay), so the app can be built against it while the backend is developed.

### 10.4 Worked module spec: `soil.py` (full code in Appendix B)
- **Takes:** SSURGO polygons (`soilmu_a_ia169.shp`, key `MUKEY`), attributes CSV from Soil Data Access (`mukey, muname, aws0100wta [cm in top 100 cm], drclassdcd, hydgrpdcd, slopegradwta`), field polygon (WGS84).
- **Method:** reproject to EPSG:5070 → spatial index → intersect → area fractions $f_i$ → numeric properties area-weighted → categorical = dominant + mix → `aws0100wta` × 10 = AWC mm/m → warnings (coverage < 90 %, field outside survey, high within-field variability) → tile hint if > 30 % poorly/very poorly drained (heuristic; farmer confirms).
- **Returns:** `SoilProfile(awc_mm_per_m, drainage_class, drainage_mix, hydrologic_group, dominant_mapunit, mapunit_mix, data_coverage, likely_tiled, source, warnings)`.
- **Used by:** `water_balance.py` (TAW = AWC × $Z_r$, capped 1 m), app (tile question), cards (gaps/confidence), README.
- **Sanity range:** typical Midwest loams/silt loams ~150–250 mm/m; 20 or 2000 = units bug.
- **Override:** farmer-selected soil class → `SoilProfile` from `content/soils.csv`, marked farmer-provided.

---

## 11. Project ideas A–K and their status
Times are nominal; budget **1.5–2×**.

| Idea | Description | Status | Time |
|---|---|---|---|
| **A** Iowa Rotation Explorer | region focus, field selection, rotation library | **MVP** | ~2 h setup |
| **B** Rotation risk as a portfolio | bootstrap distributions, CVaR, weighted scoring + sensitivity | **MVP** | ~4–6 h |
| **C** Bare-field & vulnerability calendar from NDVI | HLS NDVI → planting/peak/harvest/bare; overlay IMERG, SMAP | Stretch | ~6–10 h |
| **D** Water-budget rotation scorer | FAO-56 ET₀ × $K_c$, bucket with SSURGO AWC, drainage proxy | **MVP** | ~4–6 h |
| **E** Explain-my-field | plain-English cards, confidence badges, glossary, evidence page | **MVP** (throughout) | ~2–4 h |
| **F** Real rotations from CDL | crop sequences, Markov matrix, auto-fill existing rotation | Add-on (auto-fill part is MVP) | ~2–4 h |
| **G** Weather-regime clustering | k-means vs Ward vs GMM; "compare approaches" | Add-on | ~2–3 h |
| **H** Erosion with RUSLE | $A = R \cdot K \cdot LS \cdot C \cdot P$ | Stretch | ~4–6 h |
| **I** Cover-crop window planner | $P(\text{establishes} \mid \text{seeding date})$ from GDD/frost | Add-on | ~2–3 h |
| **J** Climate stress test | delta change (add-on); NEX-GDDP-CMIP6 (optional) | Add-on / optional | — |
| **K** Replay a hard year **[playbook]** | pick a past year; per-rotation indicators vs typical; uses the existing rotation × year table | **Add-on, do first after MVP** | ~1–2 h |
| **L** Field calendar + climate snapshot **[playbook]** | months × rotation-years grid with bare gaps and risk windows; snapshot tiles with trends | **MVP (calendar), add-on (snapshot)** | ~2–3 h |

NEX-GDDP-CMIP6 notes (if ever done): temperature, precipitation, humidity, radiation, wind **(verify variable list)**; pressure from elevation; ~0.25° daily; treat 2041–2070 as plausible years, not forecasts; compare model-historical vs model-future; 3–5 models × 2 scenarios (SSP2-4.5, SSP5-8.5).

---

## 12. Plan, time budget and timeline

**Core MVP:** A + D + B + E (+ L calendar) with ≥3 rotations and five-part cards.
**Add-ons (in order):** CDL auto-fill → **K hard-year replay** → climate snapshot → SMAP validation → trends + recent-climate robustness → I → G → J-delta → F Markov.
**Stretch:** C, H, map overlays, multiple fields, printable summary, NEX-GDDP, rainfall scenario slider.

| Block | Nominal | Realistic |
|---|---|---|
| MVP: A + D + B + E (+ calendar) | ~15 h | ~22–30 h |
| Integration / app glue | — | ~6–10 h |
| Demo + submission | — | ~8 h (both, last ~4 h) |
| **Committed** | | **~36–48 person-hours** |
| Remaining for add-ons | | ~10–20 person-hours |

Two people × ~25–30 productive hours ≈ 50–60 person-hours. (Note: it was already ~11:00 Saturday when the playbook was merged — re-estimate and cut add-ons rather than MVP.)

**Gates [playbook, adapted]**
| When | Gate |
|---|---|
| Sat 09:00–10:00 | Read official page + 2026 guides; register project; **submit AppEEARS request first**; repo skeleton; contracts + mock results; deploy skeleton to Streamlit Cloud |
| Sat midday | ET₀ test passes; any Iowa click shows real NASA numbers (snapshot); app shows mock results |
| Sat ~17:00 | Target: app deployed end-to-end with ≥3 rotations on the real pipeline, or switch to the emergency fallback (below) |
| Sat 21:30 | **Feature freeze** (bugs + wording only); watch someone who has never seen the app use it for 5 min without help and fix the three worst confusions; **go/no-go on add-ons** |
| Sun 11:00–12:00 | **Code freeze**; MVP complete and deployed; README + deck drafted |
| Sun 14:00–15:30 | Open every link in a private window and on a phone; read slides aloud and cut words |
| Sun 17:30–18:00 | Final read of project page, then **Submit for Judging** (deadline 23:59) |

Four working rules: run the app before every push; push at every gate; if something is stuck for 30 min, simplify or skip it; after the freeze, fix bugs and wording only. Do any React port on a branch only after everything above is done.

**Emergency fallback:** if the water model is not working by Saturday evening, score rotations with counted + literature criteria plus simple weather indicators (bare-and-wet days, frost/heat counts, the 6.14 indicators), keep the water model as "in progress".

---

## 13. Demo and submission

### Format
**Seven slides (title included), decided; confirm against the 2026 guide.** One idea per slide, < 25 words of body text, readable on a laptop, real screenshots from the live app, English. Team name, member names and challenge name on the deck.

| # | Slide | Content |
|---|---|---|
| 1 | Title | Project name (distinct), tagline, team name, both names, challenge name |
| 2 | The problem | One Iowa farmer, one decision: keep corn–soybean or change? Cost squeeze, shifting weather, no easy way to test options; one sourced number for scale (NASS Iowa corn/soy acres) |
| 3 | What it does | Compare screen full width with three callouts |
| 4 | How NASA data drives it | Pipeline picture + table: dataset → indicator → decision it changes |
| 5 | Why you can trust it | Readable rules, Marsden Farm evidence (with whole-system caveat), year-by-year spread, validation vs SMAP/ground, what the tool does not know |
| 6 | The farmer's experience | Field calendar with an annotated bare-soil gap, and a replayed hard year |
| 7 | Impact and next steps | Who benefits, what's next, live link and repo |

(30 s video fallback storyboard if slides are not allowed: problem 4 s → draw field/auto-fill 6 s → constraints + priorities 5 s → existing vs 3 options, contributions, P(top) 7 s → one card + "check with your agronomist" 5 s → datasets + tagline 3 s.)

### Live pitch (if the Local Event runs one) **[playbook]**
Two minutes: 20 s farmer and decision, 70 s live demo (click a field, move two sliders, show the compared rotations, open the calendar, replay a hard year), 20 s why it can be trusted, 10 s close. Rehearse on the deployed app; keep screenshots ready in case the connection fails.

### Project page fields (last year's form; expect small changes) **[playbook]**
| Field | What to write |
|---|---|
| Project name | Distinct (several teams already used "FieldShift") |
| High-level summary | 3 sentences: what we built, how it answers the challenge, why it matters |
| Link to project demo | Deck's public link, openable without login |
| Link to final project | Live app; public repo linked in the description |
| Detailed description | What it does, how it works, benefits, tools and languages |
| NASA data | Each dataset, parameters used, decision each drives |
| Space agency partner & other data | USDA NASS/CDL/SSURGO, Iowa State Extension, Marsden papers, map tiles, every library |
| Use of AI | See below |

### Declaring AI use **[playbook]**
Last year's rules: state which AI tools and how; AI-generated code acknowledged in descriptive text and metadata; AI-generated images need a visible watermark; AI content cannot carry NASA branding; judges weigh originality, intent, execution.
- State plainly that Claude was used for planning, drafting code and debugging, and which decisions were the team's.
- Add an "AI use" section to the README and a comment at the top of largely AI-drafted files.
- No AI-generated images (screenshots and own diagrams only).
- **Both team members must be able to explain every file from memory.** Expect a judge to ask how one score is computed.

### Submission checklist
- [ ] Deck/demo uploaded; public link works in a private browser window and on a phone, no login
- [ ] Public GitHub repo; README with how to run, method summary, limitations, dataset list with citations, AI-use section; LICENSE file
- [ ] Live app link (Streamlit Community Cloud); app opened beforehand so it is awake
- [ ] NASA/partner datasets listed (POWER, SRTM, SMAP, + any used), each with the decision it drives
- [ ] References list covers every source, dataset, library and tool
- [ ] All project-page fields; judging + terms checkboxes; AI-use declared on page and in README
- [ ] Both members on the team's Members tab under the same Local Event
- [ ] Local Lead asked about pitch format and judging times
- [ ] Submitted by Sun 18:00 (deadline 23:59; submission is final)

### Habits that cost points (avoid) **[playbook]**
- Claiming more than the tool does (it compares; it does not predict yield or profit).
- Naming datasets that do no work.
- A demo that breaks (keep saved data; open the app before judging).
- Agronomy a judge can fault: cite every rule, label ratings as starting values, say an agronomist should review any plan.

### How to win (criteria → our move) **[playbook]**
| Criterion | Our move |
|---|---|
| Impact | Open with one sourced scale number (NASS Iowa acres), then the cost squeeze |
| Creativity | Field calendar, replayed hard year, simulation-based comparison; differ from a "best crop" recommender |
| Validity | Every rule cites a source; Marsden Farm evidence; water model validated vs SMAP/ground; year-by-year spread; limits on screen |
| Relevance | Walk the brief's checklist; one finished flow beats five half-built features |
| Presentation | One farmer's story, live-app screenshots, few words per slide |
Global awards that fit best: Best Use of Data, Best Use of Science. Local judges choose projects for global judging.

---

## 14. Tooling and workflow
- **Claude Code** (terminal / VS Code / desktop) for building and debugging in the repo. This `CLAUDE.md` is its context; it does not see the Claude chat project.
- **Claude chat project** for design decisions, physics/stats checks, explanation text, README, demo script.
- Split files so two people never edit the same file at the same time.
- Review every line of scientific code; check units.
- When debugging: share the exact error message and the code that produced it.

---

## 15. Appendices

### Appendix A — Data download walkthrough (basis for `scripts/prefetch_data.py`)

**Setup**
```bash
mkdir -p data/raw/{power,cdl,ssurgo,srtm,tiger,iem,smap,nldas} sample_data
pip install requests pandas geopandas earthaccess xarray netCDF4 rioxarray matplotlib streamlit streamlit-folium folium plotly scikit-learn scipy statsmodels pyyaml pyarrow
```

**AppEEARS (manual, queued) — submit first.** appeears.earthdatacloud.nasa.gov → Extract → Point Sample → points (centre 42.03, −93.47; nw 42.18, −93.66; se 41.89, −93.26) → dates 2015-04-01 to today → product **SPL3SMP_E** (daily; pick layers) → CSV → submit → download from Explore into `data/raw/smap/`. SPL4SMGP (3-hourly, root zone) only for a few recent years. Optionally a second request for a MODIS NDVI product at the demo points **(confirm exact product name in the AppEEARS list)**. Copy demo-field files to `sample_data/`.

**County boundary**
```python
from pathlib import Path
import requests, geopandas as gpd
RAW = Path("data/raw")
url = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"  # verify year if 404
zip_path = RAW / "tiger" / "counties.zip"
zip_path.write_bytes(requests.get(url, timeout=300).content)
counties = gpd.read_file(zip_path)
story = counties[(counties.STATEFP == "19") & (counties.COUNTYFP == "169")]
assert len(story) == 1
story.to_file(RAW / "tiger" / "story_county.geojson", driver="GeoJSON")
bbox = tuple(story.total_bounds)  # (lon_min, lat_min, lon_max, lat_max)
```

**NASA POWER**
```python
import json, pandas as pd
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "T2MDEW", "RH2M", "WS2M", "PS",
          "PRECTOTCORR", "ALLSKY_SFC_SW_DWN", "CLRSKY_SFC_SW_DWN", "GWETTOP", "GWETROOT"]
POINTS = {"centre": (42.03, -93.47), "nw": (42.18, -93.66), "se": (41.89, -93.26)}

def fetch_power(lat, lon, start="19810101", end="20251231"):
    r = requests.get(POWER_URL, params={"parameters": ",".join(PARAMS), "community": "AG",
                     "latitude": lat, "longitude": lon, "start": start, "end": end,
                     "format": "JSON"}, timeout=600)
    r.raise_for_status()                       # bad parameter name → read r.text
    js = r.json()
    df = pd.DataFrame(js["properties"]["parameter"])
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    return df.replace(-999.0, float("nan")), js

for name, (lat, lon) in POINTS.items():
    df, js = fetch_power(lat, lon)
    df.to_csv(RAW / "power" / f"power_{name}.csv")
    json.dump({k: v for k, v in js.items() if k != "properties"},
              open(RAW / "power" / f"power_{name}_meta.json", "w"), indent=2)
# Units: js["parameters"]; compare points to see whether they share a POWER cell
```

**CDL**
```python
import re
CDL_SVC = "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile"  # verify
FIPS = "19169"
for year in range(2008, 2026):
    try:
        r = requests.get(CDL_SVC, params={"year": year, "fips": FIPS}, timeout=180)
        m = re.search(r"<returnURL>(.*?)</returnURL>", r.text)
        if not m: print(year, "no URL:", r.text[:200]); continue
        (RAW / "cdl" / f"cdl_{year}_{FIPS}.tif").write_bytes(requests.get(m.group(1), timeout=600).content)
    except Exception as e:
        print(year, "failed:", e)   # fallback: CropScape website, define AOI by county
```

**SSURGO** — polygons: websoilsurvey.nrcs.usda.gov → Download Soils Data → Soil Survey Area (SSURGO) → Iowa → Story (IA169) → unzip into `data/raw/ssurgo/`. Attributes:
```python
SDA = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"  # verify
query = """
SELECT mu.mukey, mu.muname, ma.aws0100wta, ma.drclassdcd, ma.hydgrpdcd, ma.slopegradwta
FROM legend l
INNER JOIN mapunit mu ON mu.lkey = l.lkey
INNER JOIN muaggatt ma ON ma.mukey = mu.mukey
WHERE l.areasymbol = 'IA169'
"""
r = requests.post(SDA, data={"query": query, "format": "JSON+COLUMNNAME"}, timeout=180)
r.raise_for_status()                    # if error, try json={...}
rows = r.json()["Table"]
pd.DataFrame(rows[1:], columns=rows[0]).to_csv(RAW / "ssurgo" / "ia169_muaggatt.csv", index=False)
```
K factor needs a horizon-level (`chorizon`) query — later.

**SRTM**
```python
import earthaccess
earthaccess.login(strategy="interactive", persist=True)
res = earthaccess.search_data(short_name="SRTMGL1", bounding_box=bbox)
print(len(res), "granules,", round(sum(g.size() for g in res), 1), "MB")
earthaccess.download(res, str(RAW / "srtm"))
```

**NLDAS (add-on; check size first)**
```python
res = earthaccess.search_data(short_name="NLDAS_NOAH0125_M", bounding_box=bbox,
                              temporal=("1979-01-01", "2025-12-31"))   # verify short name/version
print(len(res), "files,", round(sum(g.size() for g in res) / 1024, 1), "GB")
```

**Manual:** ISU Soil Moisture Network station nearest Ames (Iowa Environmental Mesonet) → daily CSV into `data/raw/iem/` (note coordinates). Reference PDFs (FAO-56, Davis et al. 2012, SARE book, ISU budgets, USDA planting dates) into a shared folder — not the public repo.

**Sanity checks:** annual POWER rainfall plausible for central Iowa (~800–1000 mm; rough expectation); daily T2M climatology shape; CDL top classes corn (code 1) and soybean (code 5); every SSURGO polygon matches an attribute row; 2 SRTM tiles.

### Appendix B — `soil.py` reference implementation
```python
"""
soil.py — soil properties for one field from USDA NRCS SSURGO.
Inputs : SSURGO map-unit polygons (shapefile) + attributes (CSV from Soil Data Access)
Method : area-weighted overlay of map units with the field boundary
Output : SoilProfile
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry.base import BaseGeometry

EQUAL_AREA_CRS = "EPSG:5070"   # CONUS Albers equal-area: .area in m²
WGS84 = "EPSG:4326"
WET_CLASSES = {"Poorly drained", "Very poorly drained"}


@dataclass
class SoilProfile:
    awc_mm_per_m: float                    # plant-available water per metre of soil (area-weighted)
    drainage_class: str                    # dominant by area
    drainage_mix: dict[str, float]         # class -> fraction of field area
    hydrologic_group: str                  # dominant hydrologic soil group (A–D)
    dominant_mapunit: str
    mapunit_mix: dict[str, float]
    data_coverage: float                   # fraction of field with valid AWC
    likely_tiled: bool                     # hint only — farmer confirms
    source: str = "USDA NRCS SSURGO, survey area IA169 (muaggatt table)"
    warnings: list[str] = field(default_factory=list)


def load_ssurgo(polygons_path: Path, attributes_csv: Path) -> gpd.GeoDataFrame:
    """Join SSURGO polygons to attributes; project to equal-area. Call once, then cache."""
    polys = gpd.read_file(polygons_path)
    attrs = pd.read_csv(attributes_csv, dtype={"mukey": str})
    polys["MUKEY"] = polys["MUKEY"].astype(str)
    merged = polys.merge(attrs, left_on="MUKEY", right_on="mukey", how="left")
    # aws0100wta = cm of available water in top 100 cm -> ×10 = mm per metre of soil
    merged["awc_mm_per_m"] = pd.to_numeric(merged["aws0100wta"], errors="coerce") * 10.0
    return merged.to_crs(EQUAL_AREA_CRS)


def _area_mix(pieces: gpd.GeoDataFrame, column: str) -> dict[str, float]:
    shares = pieces.groupby(column)["frac"].sum()
    if shares.empty:
        return {}
    shares = shares / shares.sum()
    return shares.sort_values(ascending=False).round(3).to_dict()


def field_soil_profile(field_geom: BaseGeometry, ssurgo: gpd.GeoDataFrame) -> SoilProfile:
    """Area-weighted soil summary for one field (polygon in WGS84)."""
    fld = gpd.GeoDataFrame(geometry=[field_geom], crs=WGS84).to_crs(EQUAL_AREA_CRS)
    field_area = fld.area.iloc[0]

    idx = ssurgo.sindex.query(fld.geometry.iloc[0], predicate="intersects")
    if len(idx) == 0:
        raise ValueError("Field is outside the downloaded SSURGO survey area.")
    pieces = gpd.overlay(ssurgo.iloc[idx], fld, how="intersection")
    pieces["frac"] = pieces.area / field_area

    warnings: list[str] = []
    mapped = pieces["frac"].sum()
    if mapped < 0.98:
        warnings.append(f"Only {mapped:.0%} of the field lies inside the soil survey area.")

    valid = pieces.dropna(subset=["awc_mm_per_m"])
    coverage = valid["frac"].sum()
    if coverage == 0:
        raise ValueError("No water-capacity data for any part of this field.")
    if coverage < 0.9:
        warnings.append(f"Soil water data covers only {coverage:.0%} of the field.")
    awc = (valid["awc_mm_per_m"] * valid["frac"]).sum() / coverage

    var = ((valid["awc_mm_per_m"] - awc) ** 2 * valid["frac"]).sum() / coverage
    if awc > 0 and var ** 0.5 / awc > 0.25:
        warnings.append("Soil water capacity varies a lot within this field; consider treating parts separately.")

    drainage_mix = _area_mix(pieces, "drclassdcd")
    hydgroup_mix = _area_mix(pieces, "hydgrpdcd")
    mapunit_mix = _area_mix(pieces, "muname")
    wet_share = sum(f for c, f in drainage_mix.items() if c in WET_CLASSES)

    return SoilProfile(
        awc_mm_per_m=round(float(awc), 1),
        drainage_class=next(iter(drainage_mix), "Unknown"),
        drainage_mix=drainage_mix,
        hydrologic_group=next(iter(hydgroup_mix), "Unknown"),
        dominant_mapunit=next(iter(mapunit_mix), "Unknown"),
        mapunit_mix=mapunit_mix,
        data_coverage=round(float(coverage), 3),
        likely_tiled=wet_share > 0.3,     # heuristic, confirmed by farmer
        warnings=warnings,
    )
```

### Appendix C — Plain-language glossary
| Term | Meaning |
|---|---|
| **Evapotranspiration (ET)** | Water leaving the field to the air: evaporation from soil + water released by plants through leaves |
| **Reference ET (ET₀)** | How much water a standard patch of well-watered grass would use today — "how thirsty the weather is" |
| **Crop coefficient ($K_c$)** | How thirsty a crop is compared with that grass at its current growth stage |
| **AWC / TAW / RAW** | Water the soil can hold for plants (per metre) / total in the root zone / the part roots can extract easily |
| **Depletion ($D_r$)** | How far the root zone is below "full" (field capacity) |
| **Tile drainage** | Buried pipes that carry excess water (and nitrate) out of the field |
| **NDVI** | Satellite index of how green and leafy the ground is (bare ≈ 0.1, dense crop ≈ 0.8) |
| **Soil-moisture anomaly** | How unusually wet or dry the soil is for this time of year here |
| **Reanalysis** | Weather "reconstructed" by combining a weather model with observations (e.g. NASA POWER/MERRA-2) |
| **Retrieval** | Estimating a quantity (e.g. soil moisture) from what a satellite actually measures (radiation) |
| **Representativeness error** | Difference between a point sensor and a satellite pixel because they measure different areas |
| **CDL** | USDA map of which crop grew on every 30 m pixel each year |
| **SSURGO / map unit** | USDA soil survey; a map unit is a mapped soil type polygon with linked properties |
| **Hydrologic soil group** | A (drains fast, little runoff) to D (drains slowly, more runoff) |
| **GDD / heat units** | Accumulated warmth that drives crop development |
| **Frost-free season** | Days between the last spring frost and first autumn frost |
| **Cover crop** | Crop grown between cash crops to protect and feed soil, not harvested |
| **Legume** | Plant (soy, alfalfa, clover) whose root bacteria fix nitrogen from the air |
| **RUSLE** | Standard US equation estimating soil erosion from rain, soil, slope, cover and practices |
| **Bootstrap** | Resampling the past years many times to see the range of possible outcomes |
| **CVaR** | Average outcome in the worst X % of years ("how bad are the bad years") |
| **Hard-year replay** | Re-running each rotation through one specific past year (e.g. 2012 drought) to see how it would have coped |
| **Decision matrix** | Table of rotations × criteria values |
| **Pareto dominance** | Option A beats B on every measure → B is never the better choice |
| **Swing weight** | How much you care about moving from worst to best on a criterion's scale |
| **Rank-order centroid** | Formula turning a priority ranking into weights |
| **Dirichlet sampling** | Drawing random weight sets near the farmer's to test ranking robustness |
| **Effective sample size** | How many "full-weight" years a weighted set of years is worth |
| **Detrending** | Shifting old years' temperatures to today's average while keeping their day-to-day pattern |
| **Theil–Sen / Mann–Kendall** | Robust trend slope / test for whether a trend is real |

### Appendix D — Optional React/FastAPI port outline **[playbook]**
Only after the Streamlit version is submitted-ready; on a branch; keep the Streamlit link as the submission unless the port passes the same checks. Expect an afternoon, not an hour.
- Core (`src/fieldshift`) must never import Streamlit; takes plain arguments, returns plain dicts.
- Layout: `core/` (or `src/`), `app/` (Streamlit, keeps working), `api/main.py` (FastAPI), `web/` (Vite + React + react-leaflet + recharts).
- API: `GET /api/climate?lat&lon` → snapshot; `POST /api/analyse` with `FarmInputs` JSON → `run_analysis` output. CORS: allow `http://localhost:5173` and the deployed site; http vs https mismatches cause CORS errors.
- React: one `farm` object in `useState`; `useEffect` posts to the API debounced ~300 ms; components `FieldMap`, `FarmForm`, `PrioritySliders`, `CompareCards`, `FieldCalendar` (12-column CSS grid), `EvidencePanel`.
- Deploy: API on Render (`uvicorn api.main:app --host 0.0.0.0 --port $PORT`), web on Vercel/Netlify with `VITE_API_URL`. Free tiers sleep — open both before judging.
- Common issues: grey map (Leaflet CSS not imported / container has no height); missing marker icon (use `CircleMarker`); slow first click (NASA fetch → loading state + server cache); huge commits (gitignore `node_modules/`, `web/dist/`).

---

## 16. To-do list: first steps

### 09:00–10:00 — both together
- [ ] Read the **2026 Submission Guide and Judging Guide**: demo limits, deadline time, AI-use declaration, preparation rules. Update Sections 1 and 13 if anything differs.
- [ ] Read the official challenge page (the playbook could not open it) and confirm the ≥3-rotation requirement and priority list.
- [ ] Register project on the Space Apps page (both on the team, Field Shift challenge, same Local Event); choose a distinct project name.
- [ ] Ask the Local Lead: live pitch? local judging times? is early prototyping acceptable?
- [ ] **Submit the AppEEARS request(s) first** (SMAP; optionally MODIS NDVI) — slow queue.
- [ ] **Data status check:** which downloads from Appendix A are done? List what's missing.
- [ ] Create public GitHub repo with the Section 10.1 skeleton, `.gitignore`, `requirements.txt`, LICENSE; deploy the skeleton to Streamlit Cloud.
- [ ] Commit `docs/project-guide.md` and `docs/brief.md`; commit this `CLAUDE.md`.
- [ ] **Agree the contracts** (10.2–10.3) and write `tests/mock_results.json` by hand (existing + 3 rotations, with calendar and replay).
- [ ] Pick the 3–4 example fields on the satellite map; record coordinates in `config.py`.
- [ ] Confirm slide deck (≤ 7 slides) as the demo format.

### Morning blocks (split of who does what: decide manually)
Backend:
- [ ] `config.py`; finish missing downloads (POWER first) → `scripts/prefetch_data.py`.
- [ ] `data/power.py`: load cached CSV, check units from metadata, handle −999.
- [ ] `model/et0.py` + `tests/test_et0.py` against the FAO-56 worked example.
- [ ] `model/indicators.py` incl. the 6.14 snapshot indicators (fix the GDD clipping).
- [ ] Start `data/soil.py` (Appendix B) and test on one example field.

App & content:
- [ ] `content/crops.csv` from FAO-56 (corn, soybean, oats, alfalfa, winter wheat, cereal rye proxy, red clover, bare) + Iowa calendar dates + sensitive windows + source column; starter ratings flagged unverified.
- [ ] `content/rotations.yaml`: 4 base sequences × 3 cover options, constraints, ordinal scores (N, pest, SOM) with citations; Marsden figures (verified) + whole-system caveat.
- [ ] `app/streamlit_app.py` skeleton reading `mock_results.json`: field step, climate snapshot, inputs, compare cards, field calendar, five-part cards, footer disclaimer.
- [ ] `app/ui/map_view.py`: county map with draw/click (`streamlit-folium`).

### Milestones
- [ ] **Sat midday** — ET₀ test passes; any Iowa click shows real NASA snapshot; app shows mock results; content tables half done.
- [ ] **Sat ~17:00** — water balance + mass-conservation test for one field; FieldProfile from real data; inputs → pipeline end to end; app deployed.
- [ ] **Sat 21:30** — rotations + bootstrap + scoring working; app on real pipeline; sanity checks run; **feature freeze + go/no-go on add-ons** (else emergency fallback, Section 12); first-time-user test.
- [ ] **Sun 11:00–12:00** — code freeze; MVP complete and deployed; hard-year replay in if on track.
- [ ] **Sun 11:00–15:30** — README (incl. AI use, limits, datasets), deck (7 slides), project-page text; repo public; every link opens in a private window and on a phone.
- [ ] **Sun by 18:00** — final read of project page, **Submit for Judging**.

# Orbital Acre - model description

Technical description of the analysis behind the app: what each part computes, from which data, with
which settings. The short version is in the [README](../README.md). All code is in `src/fieldshift/`;
all agronomic values and settings are in `content/` with their sources.

Entry point: `pipeline.run_analysis(lat, lon, answers, weights)` returns one dictionary with everything
the app shows (field, candidates, ranking, verdict, cards, calendar, risk flags, replay, validation,
trends, income). `pipeline.what_if(result)` adds the scenario table.

---

## 1. Field characterisation (`data/`)

| Module | Source | Output |
|---|---|---|
| `power.py` | NASA POWER daily point API (AG community), cell of ~0.5 x 0.625 deg | daily T2M, T2M_MAX, T2M_MIN, T2MDEW, RH2M, WS2M, PS, PRECTOTCORR, ALLSKY/CLRSKY_SFC_SW_DWN, GWETTOP, GWETROOT; units checked against the response metadata; -999 -> missing |
| `soil.py` | USDA NRCS SSURGO via Soil Data Access (live), area-weighted over the field | plant-available water (aws0100wta x 10, mm/m), drainage class, hydrologic group, slope; for untiled fields: restrictive-layer Ksat, saturation minus field capacity (top 1 m), share of the field with an April-June water table < 1 m |
| `terrain.py` | NASA SRTM GL1 (30 m), elevation smoothed over 5 x 5 cells | slope cross-check (SSURGO slope is used for scoring: SRTM's ~1 m noise is as large as the slopes here) |
| `cdl.py` | USDA NASS Cropland Data Layer 2008-2025 | majority crop per year in the field; guessed current rotation (shortest repeating cycle) |
| `ground.py` | Iowa Environmental Mesonet | ISU Soil Moisture Network AEEI4 (30/60/127 cm, frozen days removed); NWS COOP IA0203 daily weather (high and rain shifted one day back: morning observer) |
| `smap.py`, `ndvi.py`, `appeears.py` | NASA SMAP L3/L4 and HLS via AppEEARS point extraction | quality-filtered daily soil moisture; clear-sky field NDVI (3 x 3 pixels, median) |
| `field.py` | all of the above | `FieldProfile`; the farmer's answers override the data |

## 2. Reference evapotranspiration (`model/et0.py`)

FAO-56 Penman-Monteith, daily (Allen et al. 1998, eq. 6):

ET0 = [0.408 Delta (Rn - G) + gamma 900/(T+273) u2 (es - ea)] / [Delta + gamma (1 + 0.34 u2)]

Tmean = (Tmax + Tmin)/2; es from Tmax and Tmin; ea from dew point; net radiation from POWER solar
radiation, extraterrestrial radiation and clear-sky radiation; G = 0; negative values set to 0.
Reproduces the FAO-56 Example 18 (3.88 vs 3.9 mm/day). POWER solar data start in 1984, so the water
model runs 1984-2025 (42 years).

## 3. Crop calendar (`model/crops.py`, `content/crops.csv`)

For a rotation and a starting phase: which crop is in the field each day, its crop coefficient Kc
(FAO-56 piecewise curve Kc_ini -> Kc_mid -> Kc_end, stages stretched to the Iowa planting-harvest window),
root depth (linear growth to the crop maximum, capped at 1 m) and depletion fraction p. Cover crops are
sown 3 days after harvest and terminated 14 days before the next planting; underseeded clover/alfalfa
take over at oat harvest; alfalfa uses Kc_mid in the growing season and a dormant Kc in winter. Each
harvested crop has a yield-sensitive window (corn pollination, soybean pod fill, small-grain heading,
alfalfa summer regrowth). Values: FAO-56 Tables 11, 12, 22 and typical Iowa dates (marked to verify).

## 4. Soil-water balance (`model/water_balance.py`)

Daily two-layer bucket over the top 1 m (root zone + below the roots; the boundary moves with root
depth, conserving water):

1. Rain minus runoff enters the root zone (runoff 0 by default; optional SCS curve number, TR-55).
2. Crop water use ETa = Ks x Kc x ET0, with the FAO-56 stress coefficient
   Ks = (TAW - Dr) / ((1 - p) TAW) when depletion Dr exceeds RAW = p x TAW, TAW = AWC x root depth,
   p adjusted by 0.04 (5 - ETc); bare soil evaporates in proportion to how full its top layer is.
3. Water above field capacity moves down; above the whole profile's capacity it drains - the same day on
   tile-drained fields; on untiled fields at the SSURGO Ksat rate, and not at all in April-June when most
   of the field has a spring water table within 1 m. Water beyond saturation runs off.

Mass balance closes to ~1e-12 mm over 42 years (tested). Per year it reports: water missed in the
sensitive window (drought), drainage (nitrate-loss proxy), runoff, waterlogged days, bare days, and
bare days with erosive rain (> 12.7 mm, the RUSLE threshold). Each rotation is run in every phase so
every weather year meets every crop.

## 5. Candidates and research-based scores (`model/rotations.py`, `content/rotations.yaml`)

Library: 4 base sequences (corn-soybean; + winter wheat; + oats/red clover; + oats/alfalfa-alfalfa, the
Marsden Farm systems) x 3 cover options (none; cereal rye before soybean; rye in every bare winter) = 12,
plus the farmer's own rotation and its cover-crop variants. Constraints (hay buyer and equipment, grain
buyer, can seed a cover crop) remove options with a stated reason; at least three are always compared.
Ordinal 0-3 scores for nitrogen from legumes, pest break and soil organic matter follow written rules
with sources (`score_rules` in the YAML), confidence medium (Marsden-backed) or low.

## 6. Income (`model/income.py`, `content/income.csv`, `income_adjustments.csv`)

Per year: yield x price - cost (Iowa State FM 1712 / A1-20 budgets, Story County yields, Iowa prices,
straw where sold), minus cover-crop cost plus cost-share, minus seed for crops sown under oats; rotation
effects: corn after corn (yield and cost), Marsden yield bonus only in rotations with oats/clover or
alfalfa, nitrogen credit after alfalfa or red clover, rye before corn. Shown as **return to land and
management** (land rent added back; $281/acre Story County 2026); the after-rent figure is also given.
Low / mid / high price columns give the price range.

## 7. Scoring (`model/scoring.py`, `content/criteria.yaml`)

Criteria: drought (CVaR of the worst 10 % of years), water leaving (mean drainage), erosion exposure
(bare-and-wet days x the field's RUSLE slope factor), soil organic matter, nitrogen, pest break (0-3),
income. Each is normalised **against the current rotation**, which scores exactly 0.5:

r = (x_now - x) / max(|x_now|, scale)  (costs; sign flipped for benefits),  v = 0.5 + 0.5 clip(r / cap, -1, 1)

ordinal criteria v = 0.5 + (level - level_now)/6; income is compared in dollars (counts fully up to
$100/acre). Slider weights are split equally among each slider's criteria; score = sum of w x v.
Not min-max scaling, so adding or removing a candidate cannot reorder the others. Pareto-dominated
options are flagged. Reproduces the playbook's worked example (0.50 / 0.68 / 0.83).

## 8. Uncertainty (`model/bootstrap.py`)

1,000 replicates; in each: the 42 weather years are resampled with replacement (whole years, the same
years for every rotation), every simulated criterion is recomputed, one price level is drawn within each
crop's low-high range (shared across crops), and criterion weights are drawn near the farmer's
(Dirichlet, alpha = 20). Output per rotation: mean score, 5-95 % range, chance of ranking first; the
verdict says how often the best option beats the current rotation (current best / close call / worth
exploring). Robustness: the top option is recomputed with only the last 30 years and with recent-weighted
years (half-life 15 years, ~34 effective years).

## 9. What the farmer sees

- **Top options** (`pipeline.top_options`): best small step (current crops + cover) + best bigger shifts,
  at most one version per base rotation; the full ranking is kept.
- **Cards** (`model/cards.py`): hand-written text per base sequence and cover option (rotations.yaml)
  plus computed numbers - why, evidence (sources, score range, chance of beating the current rotation,
  validation), benefits (drainage, erosion, bare days, drought, scores, income), gaps (confidence, data
  caveats), risks (flags, risk flags, stressed years, 2012 replay).
- **Field calendar** (`model/calendar.py`, `content/calendar.yaml`): 24 half-months x rotation years;
  state = bare / cover / partial / full canopy; marks for erosion (exposed soil + erosive storms in >= 1
  year in 3), drought (sensitive window, with how often stressed), waterlogging, frost after planting.
- **Risk flags** (`model/risks.py`, `content/risks.yaml`): cover-crop establishment (autumn warmth after
  harvest), frost after planting, heat at the sensitive stage, too wet to plant (rain days calibrated to
  the Ames gauge, or waterlogging) - each with how often it happened in 42 years.
- **Hard-year replay** (`model/replay.py`): any simulated year (default 2012) vs each rotation's typical
  year and vs the current rotation, per crop.
- **Scenarios** (`model/scenarios.py`): delta change on the real weather (+1/+2 C on all temperatures and
  dew point; -10/-20 % June-August rain), ET0 recomputed, all options re-run.
- **Trends** (`model/trends.py`): Theil-Sen slope + Mann-Kendall test for every climate indicator;
  optional detrending of temperature to today's level before the water model.

## 10. Validation (`model/validation.py`)

Anomaly comparisons (wetter/drier than normal for the time of year, April-October) because point probes,
9 km satellite pixels and the modelled root zone measure different things; weather compared daily
(temperature) and monthly (rain). Results are in the README. NDVI vs modelled Kc checks the crop calendar
(green-up and brown-down dates interpolated between clear images).

## 11. Tests

`python -m pytest`: 65 offline tests - FAO-56 example, mass balance, data parsers, unit tests for every
model file, and the playbook sanity checks (income-first without hay keeps corn-soybean on top;
soil-first with hay puts the Marsden 4-year rotation in the top 3; switching hay off removes alfalfa
with a reason; moving the sliders changes the ranking; the result has everything the app shows).

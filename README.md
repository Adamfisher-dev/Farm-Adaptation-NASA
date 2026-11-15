# Orbital Acre

**NASA Space Apps Challenge 2026 - Field Shift: Adapting Farms with NASA Data**

Orbital Acre helps an Iowa farmer compare crop rotations for one field. It combines NASA Earth
observations with the field's soil, slope and crop history and the farmer's own priorities, then shows
the **current rotation and the three most promising alternatives** - each with why it was suggested,
the evidence behind it, its likely benefits, the information gaps and the risks to review locally.

> These are **options to explore with your agronomist**. The tool compares rotations; it does not predict
> yields or profit, and it supports - never replaces - the farmer's judgement and local expertise.

- **Live app:** [link]
- **Demo slides:** [link]
- **Team:** [names]

---

## What it does

1. **Pick a field** in Story County, Iowa (the corn-soybean belt) on the map.
2. **Field details are filled in from data** and the farmer corrects them: soil (USDA SSURGO),
   slope (SSURGO, cross-checked with NASA SRTM), crops grown since 2008 (USDA Cropland Data Layer) and a
   guessed current rotation ("We see corn, soybean, corn, soybean... is that right?").
3. **The farmer says what is possible** (livestock or hay buyer, hay equipment, grain buyer, can seed a
   cover crop, open to new crops) and **what matters most** (drought resilience, soil health and erosion,
   water quality, income, pests and fertiliser).
4. **Results:**
   - a plain verdict ("Option X beats your current rotation in 98% of plausible years, prices and
     weightings" - or, honestly, "your current rotation is already as good as any option");
   - the current rotation plus a **small step** (same crops + a cover crop) and two **bigger shifts**,
     each as a five-part card;
   - a **field calendar**: what is in the field every half-month, with erosion, drought, waterlogging
     and frost risk marks from this field's 42 years of weather;
   - a **hard-year replay** (e.g. the 2012 drought) and **what-if** scenarios (+1/+2 C, -10/-20 % summer rain);
   - **climate trends** at the field and the **evidence**: which data drive what, and how well the model
     matches ground measurements.

## How it works

```
Field polygon ─┬─ NASA POWER weather 1984-2025 ── FAO-56 reference evapotranspiration (ET0)
               ├─ USDA SSURGO soil survey ─────── water capacity, drainage, water table
               ├─ SSURGO slope + NASA SRTM ────── erosion exposure
               └─ USDA CDL crop history ────────── current rotation
                                     │
   12 candidate rotations (4 sequences x 3 cover-crop options) + the farmer's own, filtered by constraints
                                     │
   Daily soil-water model for every rotation, every year, every rotation phase
   → drought shortfall at the crop's sensitive stage, drainage (nitrate loss), erosion exposure, waterlogging
                                     │
   + research-based scores (nitrogen, pest break, soil organic matter) + income (Iowa State budgets)
                                     │
   Scoring against the CURRENT rotation (= 0.5) with the farmer's priority weights
   → 1,000 replays of the weather years, prices and weights (uncertainty, chance of ranking first)
                                     │
   Current + top 3 options → five-part cards, field calendar, risk flags, replay, what-if, validation
```

- **Physics, not a black box.** The core is the FAO-56 water balance (Allen et al. 1998): a daily soil
  "bucket" filled by rain and emptied by crop water use and drainage. Weather and soil are the same for
  every rotation; only *which crop is in the ground each day* changes - so trade-offs (e.g. a rye cover
  crop uses spring water but cuts drainage and erosion) come out of the arithmetic, not hand-written rules.
- **No predictive machine learning.** There are no field-level outcome data to learn from, so the tool
  simulates and compares instead of predicting.
- **Every year counts.** Each rotation is run through all 42 years (1984-2025) in every phase, so every
  weather year meets every crop. Bad years are summarised by the average of the worst 10 % (CVaR).
- **Honest uncertainty.** Weather years, crop prices and priority weights are resampled 1,000 times; each
  option gets a score range and a chance of ranking first, and the tool checks that the top option holds
  when only recent or recent-weighted years are used.

Full technical detail: [docs/model.md](docs/model.md).

## NASA and other data

| Dataset | What we use | What it drives |
|---|---|---|
| **NASA POWER** daily (MERRA-2 meteorology, CERES solar; AG community) | temperature, dew point, wind, pressure, solar radiation, rain, modelled soil wetness, 1981-2025 | ET0, the water model, climate trends, risk flags, scenarios, validation |
| **NASA SRTM** GL1 v003 (30 m) | elevation | slope cross-check |
| **NASA SMAP** SPL3SMP_E v006 / SPL4SMGP v008 (via AppEEARS) | surface and root-zone soil moisture at the example fields | validation of the water model |
| **NASA HLS** v2.0 HLSL30 + HLSS30 (via AppEEARS) | field NDVI | validation of the crop calendar |
| USDA NRCS **SSURGO** (Soil Data Access; Story County survey IA169 saved locally, map units on a 30 m grid) | water capacity, drainage class, hydrologic group, slope, Ksat, saturation, spring water table | soil-water bucket size, tile-drainage guess, untiled drainage, erosion |
| USDA NASS **Cropland Data Layer** 2008-2025 (CropScape; 2018 via the Microsoft Planetary Computer copy) | crop grown each year | current rotation, model runs with real crops for validation |
| Iowa Environmental Mesonet: ISU Soil Moisture Network (AEEI4), NWS station Ames 5 SE (IA0203) | soil moisture at 30/60 cm, daily temperature and rain | validation; calibration of rain-day counts |
| Iowa State University Extension FM 1712 (2026 costs), FM 1851 (2026 cash rent), A1-12 (county yields), A3-10 (custom rates); USDA NASS crop values; USDA WASDE; IDALS cover-crop cost-share; USDA AMS hay auction reports | yields, prices, costs, rent, cost-share, straw | income |
| Davis et al. 2012 (Marsden Farm), FAO-56, USDA TR-55, RUSLE, SARE | crop parameters, rotation effects, research-based scores | model parameters and card evidence |

Every number in `content/` has a source column or note; values still to be confirmed are marked
`verified: false` / "(verify)" and the cards say so.

## How well does it match reality?

Checked against independent measurements (`model/validation.py`):

| Check | Result |
|---|---|
| ET0 against the FAO-56 worked example | 3.88 vs 3.9 mm/day |
| NASA POWER vs NWS station Ames 5 SE (1981-2025) | daily max temperature bias +0.1 C, typical error 3.3 C, r = 0.97; **monthly rain r = 0.93** |
| NASA POWER vs automated ISU station (2013-2025) | max temperature error 1.8 C, r = 0.99 |
| Modelled soil wetness vs ISU soil probe at 60 cm (~10-26 km away) | day-to-day departures from normal r = 0.52-0.54; monthly 0.64-0.68 |
| Modelled soil wetness vs NASA POWER root-zone wetness | r = 0.62-0.65 |
| Modelled soil wetness vs **NASA SMAP** L3 surface soil moisture (9 km, recommended-quality retrievals, 2015-2025) | day-to-day departures from normal **r = 0.59-0.64; monthly 0.74-0.82** (1,323 days) |
| HLS crop-calendar comparison | code ready; runs once the AppEEARS extraction is in `sample_data/` |

The model gets wet and dry periods right; it is not a measurement of one field. Two of the three SMAP
9 km cells around the example fields (the ones covering Ames and the Skunk River valley) never have
recommended-quality retrievals - urban area and water spoil the signal - so the comparison uses the
nearest cell with good data, within 15 km. Station rain readings are
aligned to calendar days (morning observer), and NASA POWER's rain-day count is calibrated to the gauge
(POWER has ~35 % more light-rain days than a rain gauge).

## Limitations and information gaps

- **Soil map resolution:** the county soil survey is used on a 30 m grid (survey lines simplified by ~5 m);
  field results match the live USDA query within 0.5 mm/m water capacity and give the same drainage class.
- **Regional weather:** NASA POWER is a ~50 km average, the same for every field nearby. Fields differ in
  the results through soil, slope and crop history, not weather.
- **Water model simplifications:** snow is treated as rain; crop planting and harvest dates are fixed
  (they do not shift with weather or warming); single crop coefficient; uniform soil to 1 m.
- **Untiled fields:** drainage comes from SSURGO Ksat and the spring water table; waterlogging on poorly
  drained untiled soils is an upper bound (SSURGO gives the highest spring water table).
- **Research-based scores** (nitrogen, pest break, soil organic matter) are ordinal starting values from
  written rules with sources - an agronomist should review them. Soil organic matter changes over years
  to decades and is not measured.
- **Marsden Farm** results describe whole farming systems (the longer rotations also had manure and far
  less herbicide), not rotation length alone.
- **Income** compares rotations at 2023-2025 prices (shown as return to land and management, i.e. before
  land rent); it is not a profit forecast. Wheat uses neighbouring-state yields and prices (no Iowa data);
  hay uses the Iowa all-quality price; herbicide savings in longer rotations are not counted.
- **Scenarios** are delta-change stress tests, not forecasts: no CO2 effect, sunshine and wind unchanged,
  income held fixed.
- **Risk-flag thresholds** (rye establishment warmth, heat at pollination, "too wet to plant") are starting
  values to be checked against Iowa State guidance.
- **Sensitive windows** differ in length between crops (22-31 days), which slightly affects the drought
  comparison.

## Run it

```
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app/app.py
```

The app runs from committed data - NASA POWER, SMAP and the Story County soil survey in `sample_data/`,
SRTM, CDL and ground-station data in `data/raw/` - so it needs no live service for fields in Story County.
(Outside the county it would query USDA Soil Data Access live, falling back to a typical soil after 8 s.)

```
python -m pytest            # 65 tests (offline), incl. the FAO-56 example and the playbook sanity checks
python scripts/check_et0.py
python scripts/check_water_balance.py
```

Refreshing the data: `scripts/prefetch_power.py` (NASA POWER) and `scripts/prefetch_field_data.py`
(`soilmap` = county soil survey + example-field soils, `ssurgo`, `srtm`, `cdl`, `ground`, `nasa` = SMAP +
HLS via AppEEARS; SRTM and AppEEARS need a NASA Earthdata login).

## Repository layout

```
app/                    Streamlit app (no model code)
content/                agronomy and settings as data, each with sources:
                        crops.csv, rotations.yaml (library, scores, card text), criteria.yaml,
                        income.csv, income_adjustments.csv, soils.csv, calendar.yaml, risks.yaml, glossary.yaml
src/fieldshift/
  config.py             region, years, data paths, NASA product names
  data/                 one file per data source: power, soil, terrain, cdl, field, ground, smap, ndvi, appeears
  model/                one file per method: et0, crops, water_balance, rotations, scoring, bootstrap,
                        income, calendar, risks, replay, scenarios, trends, indicators, validation, cards
  pipeline.py           run_analysis(): field -> rotations -> water model -> scores -> cards
sample_data/            committed NASA POWER downloads (+ SMAP / HLS extracts)
data/raw/               committed SRTM, CDL, ground-station downloads
scripts/                data download and check scripts
tests/                  pytest suite
docs/model.md           technical description of the model
```

## Use of AI

We used **Claude (Anthropic), through Claude Code**, throughout the project: to plan the method, draft and
debug code (the model, data and app files), check units and equations, and draft documentation and card
text. Files drafted with AI say so in their header ("AI use: drafted with Claude (Anthropic); reviewed by
the team"). The team chose the region, the approach (physics-based simulation with uncertainty rather than
a single index or a predictive model), the data sources and every agronomic choice, reviewed the code,
and checked results against data and against the FAO-56 example. No AI-generated images are used.

## Licence

Code: [MIT](LICENSE). Data belong to their providers and are used under their terms (NASA and US
government data are public domain or free to use with credit); see the sources above.

## References

- Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998). *Crop evapotranspiration*. FAO Irrigation and Drainage Paper 56.
- Davis, A.S. et al. (2012). Increasing cropping system diversity balances productivity, profitability and environmental health. *PLOS ONE* 7(10): e47149.
- USDA NRCS (1986). *Urban Hydrology for Small Watersheds*, TR-55.
- Renard, K.G. et al. (1997). *Predicting Soil Erosion by Water: RUSLE*. USDA Agriculture Handbook 703.
- McCool, D.K. et al. (1987). Revised slope steepness factor for the Universal Soil Loss Equation. *Trans. ASAE* 30(5).
- SARE (2007). *Managing Cover Crops Profitably*, 3rd ed.
- Gray, M.E. et al. (2009). Adaptation and invasiveness of western corn rootworm. *Annual Review of Entomology* 54: 303-321.
- Iowa State University Extension and Outreach: Ag Decision Maker FM 1712, FM 1851, A1-12, A1-20, A3-10 (2026).
- NASA POWER (power.larc.nasa.gov); NASA Earthdata / AppEEARS (SMAP, HLS, SRTM); USDA NRCS Soil Data Access;
  USDA NASS CropScape and QuickStats; Iowa Environmental Mesonet (mesonet.agron.iastate.edu).
- Open-source software: Python, pandas, NumPy, SciPy, GeoPandas, rasterio, Shapely, PyYAML, requests,
  Streamlit, Folium, streamlit-folium, pytest.

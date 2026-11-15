# Orbital Acre

**Find the best crop rotation for your farm - tested on 40 years of NASA weather.**

NASA Space Apps Challenge 2026 · **Field Shift: Adapting Farms with NASA Data** · Lincoln local event

- **Live app:** https://orbitalacre.streamlit.app/
- **Team:** A&L Orbital - Adam and Leo
<!-- - **Demo slides / video:** add link -->

---

## The problem

Most Iowa fields grow corn and soybean, year after year. That leaves the soil bare for half the year,
loses nitrate to drainage and leaves farms exposed to drought and heavy spring rain - risks that are
growing as the climate changes. Longer rotations and cover crops help, but a farmer has no easy way to
see what they would mean for **their own field**.

## What Orbital Acre does

1. **Pick your field** on a satellite map of Story County, Iowa.
2. **Tell us about your farm** - what you grow now (pre-filled from USDA crop maps), what you can do
   (hay, grain buyers, cover crops) and what matters most to you.
3. **Get your best rotation**, compared with what you grow now:
   - a clear recommendation with its fit for your priorities, return over costs and how often it came out best;
   - **why** it suits the field, its **benefits** and its **risks**, from published research;
   - a **calendar** of what is in the field each month, cover crops included;
   - a **hard-year replay** - e.g. the 2012 drought on your field;
   - a **climate check** - does the choice still hold if summers get 2 °C warmer and 20 % drier?
   - **proof**: how well the model matches NASA satellites and ground sensors;
   - a **one-page PDF report** to take to an agronomist or lender.

These are options to explore with an agronomist. The tool compares rotations; it does not forecast
yields or profit.

## NASA data at the core

| NASA data | What it does in Orbital Acre |
|---|---|
| **NASA POWER** daily weather, 1981-2025 | Drives the water model, drought and wet-year risks, climate trends and the climate check |
| **NASA SRTM** 30 m elevation | Checks each field's slope (erosion risk) |
| **NASA SMAP** soil moisture from space (via AppEEARS) | Checks that the water model gets wet and dry periods right |
| **NASA HLS** Landsat + Sentinel-2 greenness (via AppEEARS) | Checks the crop calendar (code ready; runs once the extract is added) |

Plus USDA soil survey (SSURGO), USDA Cropland Data Layer (crops since 2008), Iowa State University
crop budgets and prices, and the Marsden Farm rotation trial (Davis et al. 2012).

## Does it match reality?

| Check | Agreement |
|---|---|
| Our soil-water model vs **NASA SMAP** satellite soil moisture (2015-2025) | **0.74-0.81** month to month |
| Our model vs NASA POWER root-zone wetness | 0.68-0.71 month to month |
| Our model vs Iowa State buried soil probe at 60 cm | 0.63-0.68 month to month |
| NASA POWER vs the Ames weather station (1981-2025) | daily highs **0.97**, monthly rain **0.93** |
| Reference evapotranspiration vs the FAO-56 worked example | 3.88 vs 3.9 mm/day |

(Correlation of departures from normal, April-October; 1.00 = perfect.)

## How it works

- **A daily soil-water model, not a black box.** The FAO-56 water balance (Allen et al. 1998): rain fills
  the soil, crops use it, the rest drains away. Weather and soil stay the same; only the crop in the
  ground each day changes - so trade-offs come out of the physics, not hand-written rules.
- **Every year counts.** Each of 12 candidate rotations (4 crop sequences x 3 cover-crop options), plus
  the farmer's own, is run through every year from 1984 to 2025.
- **Your priorities decide.** Drought, water quality, soil health, income and pests are weighted by the
  farmer and scored against their current rotation.
- **Honest uncertainty.** Weather years, prices and weights are resampled 1,000 times, giving each option
  a range and a chance of coming out best.

Full detail: [docs/model.md](docs/model.md).

## Limits

- Story County, Iowa only (where the model is validated).
- NASA POWER weather is a ~50 km average; fields differ through soil, slope and crop history.
- Income uses typical 2023-2025 yields, prices and costs (before land rent) - it compares, not forecasts.
- Research-based scores and some values are starting points marked for expert review in `content/`.
- The climate check is a stress test on real weather made warmer or drier, not a forecast.

## Run it

```
python -m venv venv
venv\Scripts\Activate.ps1          # macOS/Linux: source venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app/app.py
python -m pytest                   # 65 tests
```

All data for Story County is committed (`sample_data/`, `data/raw/`), so the app runs without
downloading anything. Refresh scripts are in `scripts/` (SRTM and AppEEARS need a NASA Earthdata login).

## Project layout

```
app/              Streamlit app: map, questionnaire, results, PDF report
content/          agronomy as data, with sources: crops, rotations, income, soils, risks
src/fieldshift/   data/ (one file per source), model/ (one file per method), pipeline.py
sample_data/      committed NASA POWER, SMAP and soil-survey extracts
scripts/          data download and check scripts
tests/            pytest suite
docs/model.md     technical description
```

## Use of AI

We used **Claude (Anthropic), through Claude Code**, to help plan the method, draft and debug code, check
units and equations, and draft text. Files drafted with AI say so in their header. The team chose the
region, the approach, the data sources and every agronomic choice, reviewed the code and checked the
results against data. No AI-generated images are used.

## Licence and references

Code: [MIT](LICENSE). Data belong to their providers (NASA and US government data are public domain or
free to use with credit).

- Allen, R.G. et al. (1998). *Crop evapotranspiration*. FAO Irrigation and Drainage Paper 56.
- Davis, A.S. et al. (2012). Increasing cropping system diversity balances productivity, profitability and environmental health. *PLOS ONE* 7(10): e47149.
- Iowa State University Extension, Ag Decision Maker FM 1712, FM 1851, A1-12 (2026).
- SARE (2007). *Managing Cover Crops Profitably*, 3rd ed.
- NASA POWER (power.larc.nasa.gov); NASA Earthdata / AppEEARS (SMAP, HLS, SRTM); USDA NRCS Soil Data
  Access; USDA NASS CropScape; Iowa Environmental Mesonet.

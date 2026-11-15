"""pipeline.py - Orchestration only: field -> data -> model -> scores. No agronomy or maths here.

Who does what (playbook 10.1):
    data/field.py          FieldProfile: soil (SSURGO), slope (SRTM), crop history (CDL), POWER cell
    data/power.py          daily weather;  model/et0.py  reference ET
    model/rotations.py     library, existing rotation, constraint filters, ordinal scores (content/rotations.yaml)
    model/water_balance.py rotation x year table per rotation
    model/scoring.py       normalise vs existing rotation, weights, score, Pareto (content/criteria.yaml)
    model/indicators.py    climate snapshot + notable years

The functions below keep the names app/app.py already calls (ROTATIONS, BASELINE,
filter_rotations, run_basic, basic_scores, WATER_COLUMNS), now backed by those modules.

    from fieldshift import pipeline
    out = pipeline.run_basic(42.03, -93.47)
    table = pipeline.basic_scores(out, {"drought": 0.4, "water_quality": 0.3, "soil_health": 0.3})

No Streamlit calls in this file (project rule).
"""

from __future__ import annotations

import warnings

import pandas as pd

from fieldshift import config
from fieldshift.data import field as field_mod
from fieldshift.data.power import load_power
from fieldshift.model import rotations as rot_mod
from fieldshift.model import income as income_mod
from fieldshift.model import scoring
from fieldshift.model import trends as trends_mod
from fieldshift.model.et0 import et0_from_power
from fieldshift.model.indicators import notable_years, snapshot, yearly_indicators
from fieldshift.model.water_balance import simulate_rotation

# --- Rotation library (from content/rotations.yaml via rotations.py) -----------------------
_LIBRARY = {r.name: r for r in rot_mod.library()}
ROTATIONS = {name: r.plan for name, r in _LIBRARY.items()}          # name -> crops.py plan
BASELINE = next(name for name, r in _LIBRARY.items() if r.rotation_id == "cs")
DEFAULT_EXISTING = ["corn", "soybean"]   # until the app asks for / confirms the existing rotation

# App slider keys -> criteria.yaml sliders
APP_SLIDERS = {"drought": "drought", "water_quality": "water_quality", "soil_health": "soil_erosion",
               "income": "income", "pests": "pests_fertiliser"}

# Water-model outputs shown in the app: column -> (label, unit, lower_is_better)
WATER_COLUMNS = {
    "drought_deficit_mm": ("Water deficit in sensitive window", "mm/yr", True),
    "drought_stress_days": ("Drought-stress days in sensitive window", "days/yr", True),
    "drainage_mm": ("Drainage (nitrate-loss proxy)", "mm/yr", True),
    "bare_wet_days": ("Bare days with erosive rain", "days/yr", True),
    "waterlogged_days": ("Waterlogged days", "days/yr", True),
    "bare_days": ("Days with no living cover", "days/yr", True),
    "runoff_mm": ("Runoff", "mm/yr", True),
}


# --- Candidates ------------------------------------------------------------------------------
def farm_inputs(want_cover=True, hay_buyer=True, hay_equipment=True, open_to_new=True,
                small_grain_buyer=True, existing_rotation=None) -> dict:
    """App answers -> the FarmInputs fields rotations.build_candidates reads.
    The app does not ask about a grain buyer yet, so small_grain_buyer defaults to True
    (oat/wheat options stay, each with a 'confirm a buyer' flag)."""
    return {
        "existing_rotation": existing_rotation or DEFAULT_EXISTING,
        "livestock_or_hay_buyer": hay_buyer,
        "hay_equipment": hay_equipment,
        "small_grain_buyer": small_grain_buyer,
        "can_seed_cover": want_cover,
        "openness": "yes" if open_to_new else "no",
    }


MIN_COMPARED = 3        # the existing rotation + at least two others (brief requirement)


def candidates(want_cover=True, hay_buyer=True, hay_equipment=True, open_to_new=True,
               current_crops=None, small_grain_buyer=True, existing_rotation=None):
    """(candidate Rotation objects, removed [{rotation_id, name, reason}]).

    If the farmer is not open to new crops and lists current crops, rotations with
    other cash crops are removed too (cover crops still allowed, since they are asked separately),
    but never below MIN_COMPARED: openness is a preference, not a constraint (rotations.py rule;
    the brief asks for at least three rotations), so the closest ones stay, flagged 'not_open'.
    """
    inputs = farm_inputs(want_cover, hay_buyer, hay_equipment, open_to_new, small_grain_buyer,
                         existing_rotation)
    cands, removed = rot_mod.build_candidates(inputs)
    if not open_to_new and current_crops:
        # cover crop and red clover (sown with the oats, no extra field operation - rotations.yaml)
        # are not "new crops"
        current = {c.lower().replace(" ", "_") for c in current_crops} | {"cereal_rye", "red_clover"}
        keep, other = [], []
        for r in cands:
            crops = {c for y in r.plan for e in y for c in e.split("+")}
            (keep if r.is_existing or crops <= current else other).append(r)
        if len(keep) < MIN_COMPARED:          # top up with the fewest new crops first
            other.sort(key=lambda r: len({c for y in r.plan for e in y for c in e.split("+")} - current))
            keep += other[:MIN_COMPARED - len(keep)]
        kept = {r.name for r in keep}
        removed += [{"rotation_id": r.rotation_id, "name": r.name, "reason": "Uses crops you do not grow now"}
                    for r in cands if r.name not in kept]
        cands = [r for r in cands if r.name in kept]
    for r in cands:                            # farmer variants become available by name too
        ROTATIONS.setdefault(r.name, r.plan)
        _LIBRARY.setdefault(r.name, r)
    return cands, removed


def filter_rotations(want_cover=True, hay_buyer=True, hay_equipment=True, open_to_new=True,
                     current_crops=None, small_grain_buyer=True) -> dict:
    """{name: plan} of the rotations this farm can run (existing rotation first)."""
    cands, _ = candidates(want_cover, hay_buyer, hay_equipment, open_to_new, current_crops,
                          small_grain_buyer)
    return {r.name: r.plan for r in cands}


# --- Data ---------------------------------------------------------------------------------------
def load_weather(lat, lon, allow_download=True):
    """POWER data + daily ET0 for the cell containing (lat, lon)."""
    df, meta = load_power(lat, lon, allow_download=allow_download)
    geom = meta.get("geometry") or {}
    coords = geom.get("coordinates") or []
    elevation = coords[2] if len(coords) > 2 else None   # None -> estimated from PS
    rs_units = meta.get("units", {}).get("ALLSKY_SFC_SW_DWN", "MJ/m^2/day")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        et0 = et0_from_power(df, meta["cell"]["centre"][0], elevation, rs_units=rs_units)
    return df, meta, et0


def field_profile(lat, lon, geojson=None, overrides=None):
    """FieldProfile from a drawn polygon (geojson) or a ~400 m box around (lat, lon).
    Falls back to farmer answers / typical values when local data files are missing."""
    geom = field_mod.field_geometry(geojson=geojson) if geojson else field_mod.field_geometry(point=(lat, lon))
    return field_mod.build_field_profile(geom, overrides=overrides)


# --- Run -------------------------------------------------------------------------------------------
def run_basic(lat, lon, rotations=None, awc_mm_per_m=None, tile_drained=None, allow_download=True,
              geojson=None, overrides=None, use_runoff=False, income=None, profile=None,
              detrend_temperature=False, income_ranges=None, delta_temp_c=0.0, summer_rain_pct=0.0):
    """Everything the app shows, as plain Python / pandas objects.

    Soil water capacity, tile drainage and slope come from the field profile (SSURGO/SRTM)
    unless given here. use_runoff=True turns on curve-number runoff from the field's
    hydrologic soil group (off by default: playbook MVP).
    income: {rotation name: USD per acre per year} (from an income module / content table);
    rotations without a value leave the income criterion out of the score.
    """
    unique, seen = {}, set()
    for name, plan in (rotations or ROTATIONS).items():  # same crops under two names -> run once
        key = rot_mod.canonical(plan)
        if key not in seen:
            seen.add(key)
            unique[name] = plan
    rotations = unique
    # the baseline (0.5 on every criterion) is the existing rotation; find it by its crops, not
    # its name ("Corn–soybean" and "Corn–soybean (your current rotation)" are the same rotation)
    base_key = rot_mod.canonical(ROTATIONS[BASELINE])
    baseline = next((n for n, p in rotations.items() if rot_mod.canonical(p) == base_key), None)
    if baseline is None:                                 # always compare against the baseline
        baseline = BASELINE
        rotations = {BASELINE: ROTATIONS[BASELINE], **rotations}
    df, meta, et0 = load_weather(lat, lon, allow_download)
    detrend_report = None
    model_df = df
    if detrend_temperature:            # playbook 6.9: past years at today's temperatures (water model only)
        model_df, detrend_report = trends_mod.detrend_temperature(
            df.loc[str(config.WATER_START_YEAR):str(config.WATER_END_YEAR)], end_year=config.WATER_END_YEAR)
    if delta_temp_c or summer_rain_pct:   # what-if sliders (scenarios.py): shift the weather the model uses
        from fieldshift.model import scenarios as scen_mod
        model_df = scen_mod.apply_delta(model_df, delta_temp_c, summer_rain_pct)
    if detrend_temperature or delta_temp_c or summer_rain_pct:
        geom = meta.get("geometry") or {}
        coords = geom.get("coordinates") or []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            et0 = et0_from_power(model_df, meta["cell"]["centre"][0], coords[2] if len(coords) > 2 else None,
                                 rs_units=meta.get("units", {}).get("ALLSKY_SFC_SW_DWN", "MJ/m^2/day"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        prof = profile or field_profile(lat, lon, geojson, overrides)
    awc = float(awc_mm_per_m if awc_mm_per_m is not None else prof.awc_mm_per_m)
    tiled = bool(tile_drained if tile_drained is not None else prof.tile_drained)
    wbp, drainage_note = drainage_params(prof.soil, tiled)
    hsg = prof.hydrologic_group if use_runoff else None

    yearly = yearly_indicators(df)
    start, end = config.WATER_START_YEAR, config.WATER_END_YEAR

    tables, rows, ordinal, dailies = {}, [], {}, {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, plan in rotations.items():
            t = simulate_rotation(plan, model_df["PRECTOTCORR"], et0, awc, tiled, start, end,
                                  hydrologic_group=hsg, rotation_id=name, keep_daily=True, **wbp)
            dailies[name] = t.attrs.pop("daily", None)
            tables[name] = t
            rows.append({"rotation": name, **t[list(WATER_COLUMNS)].mean().to_dict()})
            lib = _LIBRARY.get(name)
            ordinal[name] = lib.scores if lib else rot_mod.rule_scores(plan)
    water = pd.DataFrame(rows).set_index("rotation")
    extra = {n: {"income_usd_per_acre": float(v)} for n, v in (income or {}).items() if n in tables}
    criteria_raw = scoring.raw_criteria(tables, ordinal, slope_factor=prof.slope.get("rusle_s"), extra=extra)

    return {
        "cell": meta["cell"],
        "loaded_from": meta["loaded_from"],
        "unit_warnings": meta["unit_warnings"],
        "years": {"weather": [int(yearly.index.min()), int(yearly.index.max())],
                  "water_model": [start, end]},
        "soil": {"awc_mm_per_m": awc, "tile_drained": tiled, "hydrologic_group": prof.hydrologic_group,
                 "source": prof.sources.get("soil", "typical value"),
                 "drainage": wbp, "drainage_note": drainage_note},
        "field": prof.to_dict(),
        "snapshot": snapshot(yearly),
        "notable_years": notable_years(yearly),
        "yearly": yearly,
        "water": water,
        "tables": tables,                 # rotation x year table per rotation (bootstrap, replay)
        "daily": dailies,                 # {rotation: {phase: daily stressed/sensitive/waterlogged}} (calendar)
        "model_weather": model_df,        # weather the water model used (detrended / scenario if asked)
        "weather": df,                    # daily NASA POWER as recorded (validation, charts)
        "trends": trends_mod.climate_trends(df),   # per-indicator trend table with sentences (raw weather)
        "detrend": detrend_report,        # None unless detrend_temperature=True
        "what_if": {"delta_temp_c": delta_temp_c, "summer_rain_pct": summer_rain_pct},
        "meta": {"latitude": meta["cell"]["centre"][0],
                 "elevation_m": ((meta.get("geometry") or {}).get("coordinates") or [None, None, None])[2],
                 "rs_units": meta.get("units", {}).get("ALLSKY_SFC_SW_DWN", "MJ/m^2/day")},
        "et0": et0,                       # daily reference ET, mm/day
        "criteria_raw": criteria_raw,     # raw criterion values in real units
        "ordinal_scores": ordinal,        # 0-3 literature scores per rotation (rotations.py)
        "extra": extra,                   # 'data' criteria per rotation (income)
        "income_ranges": income_ranges or {},   # {rotation: {low, mid, high}} for price uncertainty
        "baseline": baseline,
    }


# --- Scores --------------------------------------------------------------------------------------
def score_details(out: dict, weights: dict, baseline: str | None = None) -> dict:
    """Full scoring.score_rotations result for the app's slider weights."""
    sliders = {APP_SLIDERS.get(k, k): v for k, v in weights.items()}
    return scoring.score_rotations(out["criteria_raw"], baseline or out["baseline"], sliders)


def basic_scores(out: dict, weights: dict, baseline: str | None = None) -> pd.DataFrame:
    """One row per rotation: a 0-1 value per app slider (0.5 = same as the baseline) + score,
    best first. Sliders without data yet (income) are left out and the rest renormalised."""
    if isinstance(out, pd.DataFrame):
        raise TypeError("basic_scores now takes the dict returned by run_basic(), not out['water']")
    res = score_details(out, weights, baseline)
    back = {v: k for k, v in APP_SLIDERS.items()}
    table = res["slider_values"].rename(columns=back)
    table["score"] = res["scores"]["score"]
    return table.sort_values("score", ascending=False)


def robust_scores(out: dict, weights: dict, n_boot: int = 1000, window: str = "all",
                  baseline: str | None = None, with_robustness: bool = True) -> dict:
    """Year bootstrap + weight sampling (model/bootstrap.py): score mean / 5-95 % range /
    P(rank first) per rotation, criterion ranges, 'stressed in N of M years', and whether the
    top option changes with how past climate is weighted."""
    from fieldshift.model import bootstrap
    sliders = {APP_SLIDERS.get(k, k): v for k, v in weights.items()}
    baseline = baseline or out["baseline"]
    ordinal = out["ordinal_scores"]
    slope = out["field"]["slope"].get("rusle_s")
    samples = income_price_samples(out, n_boot)
    res = bootstrap.run_bootstrap(out["tables"], baseline, sliders, ordinal, slope,
                                  n_boot=n_boot, window=window, extra=out.get("extra"), extra_samples=samples)
    res["stressed_years"] = {n: bootstrap.stressed_years(t) for n, t in out["tables"].items()}
    if with_robustness:
        res["robustness"] = bootstrap.robustness(out["tables"], baseline, sliders, ordinal, slope,
                                                 extra=out.get("extra"),
                                                 extra_samples=income_price_samples(out, 500))
    res["price_uncertainty"] = samples is not None
    return res


def replay(out: dict, year: int) -> dict:
    """Hard-year replay (model/replay.py) for the rotations in a run_basic() result."""
    from fieldshift.model import replay as rp
    tables = out["tables"]
    return {
        "year": int(year),
        "suggested_years": rp.suggest_years(tables, out["baseline"], weather_notable=out["notable_years"]),
        "table": rp.replay_table(tables, year, out["baseline"]),
        "contract": rp.contract_block(tables, year),
        "sentence": rp.sentence(tables, year, out["baseline"]),
    }


# --- Which options to show ------------------------------------------------------------------------
def top_options(out: dict, ranking, k: int = 3) -> list[dict]:
    """The options shown next to the existing rotation (playbook 4: current / small step / bigger shift).

    ranking: rotation names best first (e.g. robust_scores(...)["summary"].index).
    Rules (display only - the ranking itself is unchanged and can be shown in full):
      1. at most one version per base rotation (same cash crops, whatever the cover crops),
         so the farmer sees genuinely different choices;
      2. the best "small step" (existing cash crops + a cover crop) is always included if one exists;
      3. the remaining places go to the best "bigger shifts" (different cash crops).
    Returns [{"name", "tier", "rank"}] in display order: small step first, then bigger shifts by rank.
    """
    base = out["baseline"]
    tables = out["tables"]
    names = [n for n in ranking if n != base and n in tables]

    def cash_key(name):
        plan = ROTATIONS.get(name) or _LIBRARY[name].plan
        return rot_mod.canonical([[y[0]] for y in plan])

    base_cash = cash_key(base)
    rank = {n: i + 1 for i, n in enumerate(ranking)}
    small = [n for n in names if cash_key(n) == base_cash]
    bigger, seen = [], {base_cash}
    for n in names:
        key = cash_key(n)
        if key not in seen:
            seen.add(key)
            bigger.append(n)
    picks = ([{"name": small[0], "tier": "small_step", "rank": rank[small[0]]}] if small else [])
    for n in bigger:
        if len(picks) >= k:
            break
        picks.append({"name": n, "tier": "bigger_shift", "rank": rank[n]})
    for n in small[1:]:                      # not enough different bigger shifts: fill with small steps
        if len(picks) >= k:
            break
        picks.append({"name": n, "tier": "small_step", "rank": rank[n]})
    return picks


# --- Validation (model/validation.py + data/smap.py) ------------------------------------------------
def validate(out: dict, smap_path=None, ndvi_path=None, smap_max_km: float = 15.0,
             ndvi_max_km: float = 0.5, probe_max_km: float = 50.0) -> dict:
    """Check the water model against NASA SMAP soil moisture, POWER's modelled root-zone wetness,
    and the crop calendar against HLS satellite greenness (NDVI).

    SMAP is 9 km, so the nearest example point within smap_max_km is used. HLS is 30 m and
    field-specific, so NDVI is only used when this field IS an example field (within ndvi_max_km).
    The model is run with the crops actually grown (CDL history) when available; otherwise the
    existing rotation stands in (flagged in notes - crop timing may then not match the images).
    Returns {"available", "notes", "comparisons": {name: compare_soil result},
             "ndvi": compare_ndvi result or None, "sentences"}.
    """
    import math
    from fieldshift.data import ndvi as ndvi_mod
    from fieldshift.data import smap as smap_mod
    from fieldshift.model import validation as val

    notes, sentences = [], []
    lat, lon = out["field"]["centroid"]
    pid = smap_mod.nearest_point(lat, lon)
    plat, plon = config.EXAMPLE_POINTS[pid]
    km = math.hypot((plat - lat) * 110.5, (plon - lon) * 111.3 * math.cos(math.radians(lat)))

    sm = nd = None
    if km <= smap_max_km:
        try:
            sm = smap_mod.load_smap(pid, smap_path or config.SMAP_DAILY_CSV)
        except (FileNotFoundError, ValueError) as err:
            notes.append(f"SMAP not available yet: {err}")
    else:
        notes.append(f"No SMAP point within {smap_max_km:.0f} km (nearest: {pid}, {km:.0f} km).")
    if km <= ndvi_max_km:
        try:
            nd = ndvi_mod.load_ndvi(pid, ndvi_path or config.HLS_NDVI_CSV)["ndvi"]
        except (FileNotFoundError, ValueError) as err:
            notes.append(f"HLS NDVI not available yet: {err}")
    else:
        notes.append("Satellite greenness (HLS) is only extracted for the example fields; "
                     "this field is not one of them.")
    probes = {}
    try:
        from fieldshift.data import ground
        st = config.ISUSM_STATION
        probe_km = math.hypot((st["lat"] - lat) * 110.5, (st["lon"] - lon) * 111.3 * math.cos(math.radians(lat)))
        if probe_km > probe_max_km:     # different weather and soil: the comparison would say nothing about this field
            notes.append(f"The ISU soil-moisture probe ({st['id']}) is {probe_km:.0f} km from this field, too far "
                         "to check the model against; it is only used for fields in central Iowa.")
        else:
            for depth in ("30cm", "60cm"):
                probes[depth] = ground.load_soil_moisture(depth)
    except (FileNotFoundError, ValueError, ImportError) as err:
        notes.append(f"ISU soil-probe data not available: {err}")
    obs = [s for s in (sm, nd, *probes.values()) if s is not None]
    if obs:
        first, last = min(s.index.min().year for s in obs), max(s.index.max().year for s in obs)
    else:   # no satellite files yet: still compare with POWER's modelled root-zone wetness over the CDL years
        cdl_years = [int(y) for y in out["field"].get("crop_history", {})]
        first, last = (min(cdl_years), max(cdl_years)) if cdl_years else (config.WATER_END_YEAR - 9, config.WATER_END_YEAR)
    years = list(range(max(first, config.WATER_START_YEAR), min(last, config.WATER_END_YEAR) + 1))
    hist = {str(y): c for y, c in out["field"].get("crop_history", {}).items()}
    guess = out["field"].get("existing_rotation_guess")
    cycle = len(guess) if guess else 2
    filled = []
    for y in years:                      # a missing CDL year (e.g. 2018) -> same crop as one cycle earlier/later
        if str(y) not in hist and hist:
            for alt in (y - cycle, y + cycle):
                if str(alt) in hist:
                    hist[str(y)] = hist[str(alt)]
                    filled.append(f"{y} (as {alt})")
                    break
    if filled:
        notes.append(f"CDL has no map for {', '.join(filled)}; that year's crop is assumed from the "
                     f"{cycle}-year rotation cycle.")
    if not all(str(y) in hist for y in years):
        guess = out["field"].get("existing_rotation_guess") or [[c] for c in DEFAULT_EXISTING]
        seq = [y[0] if isinstance(y, (list, tuple)) else y for y in guess]
        hist = {str(y): seq[i % len(seq)] for i, y in enumerate(years)}
        notes.append("Crop history for these years is not available: the model uses the existing rotation "
                     f"({'-'.join(seq)}) as a stand-in, so crop timing may not match reality.")
    hist = {y: hist[str(y)] for y in map(str, years)}
    daily = val.run_actual_crops(out["weather"]["PRECTOTCORR"], out["et0"], hist,
                                 out["soil"]["awc_mm_per_m"], out["soil"]["tile_drained"],
                                 **out["soil"].get("drainage", {}))
    notes += daily.attrs.get("notes", [])
    model = daily["wetness_root"]

    comparisons = {}
    labels = {"sm_rootzone_l4": "SMAP Level 4 root-zone soil moisture (0-100 cm, satellite + model)",
              "sm_surface_l3": "SMAP Level 3 surface soil moisture (top 5 cm, satellite)",
              "sm_surface_l4": "SMAP Level 4 surface soil moisture"}
    if sm is not None:
        for col, label in labels.items():
            if col in sm and sm[col].notna().sum() >= val.MIN_PAIRS:
                comparisons[col] = val.compare_soil(model, sm[col], name=label)
    if "GWETROOT" in out["weather"]:
        comparisons["power_gwetroot"] = val.compare_soil(
            model, out["weather"]["GWETROOT"].loc[str(years[0]):str(years[-1])],
            name="NASA POWER modelled root-zone wetness (GWETROOT)")
    for depth, series in probes.items():
        comparisons[f"isusm_{depth}"] = val.compare_soil(
            model, series, name=f"the ISU soil-moisture probe at {depth.replace('cm', ' cm')} depth "
                                f"(station {config.ISUSM_STATION['id']}, {probe_km:.0f} km away)")
    if probes and probe_km > 25:
        notes.append(f"The ISU soil probe is {probe_km:.0f} km from this field - comparison is only indicative.")
    sentences += [val.sentence(c) for c in comparisons.values()]

    weather = None                      # NASA POWER vs the NWS station, in the station's own POWER cell
    try:
        from fieldshift.data import ground
        cs = config.CLIMATE_STATION
        station = ground.load_station_weather()
        power_st, _ = load_power(cs["lat"], cs["lon"], allow_download=False)
        weather = val.compare_weather(power_st, station)
        weather["station"] = f"{cs['id']} ({cs['name']}), morning readings aligned to calendar days"
        sentences.append(val.weather_sentence(weather))
        try:                            # second, automated station (calendar days, shorter record)
            st = config.ISUSM_STATION
            power_isu, _ = load_power(st["lat"], st["lon"], allow_download=False)
            weather_isu = val.compare_weather(power_isu, ground.load_isusm_weather())
            weather["isusm_station"] = {k: weather_isu[k] for k in ("tmax", "tmin", "rain_daily", "rain_monthly")}
        except (FileNotFoundError, ValueError, KeyError) as err:
            notes.append(f"ISU station weather not compared: {err}")
    except (FileNotFoundError, ValueError, KeyError, ImportError) as err:
        notes.append(f"Ground weather station comparison not available: {err}")
    ndvi_res = None
    if nd is not None:
        ndvi_res = val.compare_ndvi(daily, nd)
        sentences.append(val.ndvi_sentence(ndvi_res))
    return {"available": True, "point": pid, "distance_km": round(km, 1), "years": [years[0], years[-1]],
            "notes": notes, "comparisons": comparisons, "ndvi": ndvi_res, "weather": weather,
            "sentences": sentences}


# --- Everything for one field, in the playbook order (6.1) ---------------------------------------------
def run_analysis(lat: float, lon: float, answers: dict | None = None, weights: dict | None = None,
                 geojson=None, income: dict | None = None, n_boot: int = 1000, replay_year: int | None = None,
                 allow_download: bool = True) -> dict:
    """Field -> existing rotation -> candidates -> water model -> scores -> uncertainty -> what to show.

    answers (all optional; the farmer's answers win over the data):
        existing_rotation  e.g. ["corn", "soybean"]  (else the CDL guess, else corn-soybean)
        soil_class, tile_drained, erosion_prone      (field overrides, see data/field.py)
        livestock_or_hay_buyer, hay_equipment, small_grain_buyer, can_seed_cover (True/False),
        openness ("yes" | "maybe" | "no"), current_crops (only used when openness == "no")
    weights: app slider weights {drought, water_quality, soil_health, income, pests}
    income:  {rotation name: USD per acre per year}, when an income module exists
    """
    answers = dict(answers or {})
    weights = weights or {k: 1.0 for k in APP_SLIDERS}
    overrides = {k: answers.get(k) for k in ("soil_class", "tile_drained", "erosion_prone", "existing_rotation")
                 if answers.get(k) is not None}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        prof = field_profile(lat, lon, geojson, overrides)

    existing_from = "farmer" if answers.get("existing_rotation") else "CDL guess" if prof.existing_rotation_guess else "default"
    existing = answers.get("existing_rotation") or prof.existing_rotation_guess or DEFAULT_EXISTING
    existing = [y[0] if isinstance(y, (list, tuple)) and len(y) == 1 else y for y in existing]
    if "corn" in existing and not answers.get("existing_rotation"):      # read it from the corn year
        k = existing.index("corn")
        existing = existing[k:] + existing[:k]

    cands, removed = candidates(
        want_cover=answers.get("can_seed_cover", True),
        hay_buyer=answers.get("livestock_or_hay_buyer", False),
        hay_equipment=answers.get("hay_equipment", False),
        open_to_new=answers.get("openness", "maybe") != "no",
        current_crops=answers.get("current_crops"),
        small_grain_buyer=answers.get("small_grain_buyer", True),
        existing_rotation=existing)
    rotations = {c.name: c.plan for c in cands}
    income_note, income_ranges, income_all_costs = "", {}, {}
    if income is None:                        # content/income.csv, once it is filled in
        inc = income_mod.rotation_incomes(rotations)
        if inc["complete"]:
            income = inc["income"]
            income_ranges = {n: income_mod.income_range(p) for n, p in rotations.items()}
            income_all_costs = income_mod.rotation_incomes(rotations, basis="all_costs")["income"]
        else:
            income_note = income_mod.missing_summary(inc)
    out = run_basic(lat, lon, rotations=rotations, allow_download=allow_download, geojson=geojson,
                    detrend_temperature=bool(answers.get("detrend_temperature", False)),
                    delta_temp_c=float(answers.get("delta_temp_c", 0.0) or 0.0),
                    summer_rain_pct=float(answers.get("delta_summer_rain_pct", 0.0) or 0.0),
                    overrides=overrides, income=income, profile=prof, income_ranges=income_ranges)
    out["baseline"] = cands[0].name if cands[0].name in out["tables"] else out["baseline"]

    robust = robust_scores(out, weights, n_boot=n_boot)
    point = score_details(out, weights)
    ranking = list(robust["summary"].index)
    picks = top_options(out, ranking)
    verdict_info = verdict(robust, out["baseline"])
    from fieldshift.model import calendar as calendar_mod
    shown_names = [out["baseline"]] + [p["name"] for p in picks]
    calendars = {n: calendar_mod.field_calendar(rotations[n], out["model_weather"], out["et0"],
                                                out["soil"]["awc_mm_per_m"], out["soil"]["tile_drained"],
                                                dailies=out["daily"].get(n), wb_kwargs=out["soil"]["drainage"])
                 for n in shown_names if n in rotations}
    from fieldshift.model import risks as risks_mod
    risk_flags = {n: risks_mod.risk_flags(rotations[n], out["model_weather"], out["daily"].get(n))
                  for n in shown_names if n in rotations}
    by_name = {c.name: c for c in cands}
    year = replay_year or 2012
    res = {
        "field": out["field"],
        "existing": {"rotation": existing, "from": existing_from, "name": out["baseline"]},
        "candidates": {c.name: c.to_dict() for c in cands},
        "removed": removed,
        "shown": [{"name": out["baseline"], "tier": "current"}] + picks,
        "verdict": verdict_info,          # is any option really better than the current rotation?
        "calendar": calendars,            # field calendar (half-months x rotation years) per shown rotation
        "risk_flags": risk_flags,         # field-specific risk flags per shown rotation (model/risks.py)
        "risk_note": risks_mod.unverified_note([f for fl in risk_flags.values() for f in fl]),
        "ranking": robust["summary"],
        "point_scores": point,
        "criteria_raw": out["criteria_raw"],
        "criteria_ranges": robust["criteria"],
        "stressed_years": robust["stressed_years"],
        "robustness": robust.get("robustness"),
        "replay": replay(out, year),
        "validation": validate(out),
        "snapshot": out["snapshot"],
        "trends": out["trends"],
        "detrend": out["detrend"],
        "drought_trend": trends_mod.result_trend(
            out["tables"][out["baseline"]], "drought_deficit_mm",
            "Water missed by your current rotation at its sensitive stage", "mm"),
        "notable_years": out["notable_years"],
        "flags": {n: by_name[n].flags for n in by_name},
        "dropped_criteria": robust["dropped"],
        "income": {"usd_per_acre": income or {}, "ranges": income_ranges, "note": income_note,
                   "basis": income_mod.BASES[income_mod.BASIS],
                   "all_costs_usd_per_acre": income_all_costs,
                   "land_rent_note": "Return over all costs also subtracts land rent ($281/acre, Story County "
                                     "2026, Iowa State FM 1851); at 2026 prices that is often negative."},
        "weights": weights,
        "run": out,                      # everything else (tables, weather, ...) for charts
        "boot_scores": robust["scores"],  # bootstrap replicate scores (cards: chance of beating the current one)
        "boot_rotations": robust["rotations"],
    }
    from fieldshift.model import cards as cards_mod
    res["cards"] = cards_mod.build_cards(res)   # five-part cards for the rotations shown (model/cards.py)
    return res


# --- Price uncertainty and the overall verdict ----------------------------------------------------------
PRICE_SEED = 11


def income_price_samples(out: dict, n_boot: int, seed: int = PRICE_SEED):
    """Per-replicate income for every rotation: one price level u ~ Uniform(0, 1) per replicate,
    shared by all crops and rotations (crop prices tend to move together), mapped to
    price_low (u=0) -> price (u=0.5) -> price_high (u=1). Income is linear in each crop's price,
    so it is interpolated from the rotation's low / mid / high income. Costs stay fixed.
    Assumption (document on the evidence page): prices anywhere in the recent low-high range are
    equally likely. Returns None when income ranges are not available for every rotation."""
    ranges = out.get("income_ranges") or {}
    if not ranges or any(n not in ranges for n in out["tables"]):
        return None
    import numpy as np
    u = np.random.default_rng(seed).uniform(size=n_boot)
    return {n: {"income_usd_per_acre": np.interp(u, [0.0, 0.5, 1.0],
                                                 [ranges[n]["low"], ranges[n]["mid"], ranges[n]["high"]])}
            for n in out["tables"]}


def verdict(robust: dict, baseline: str) -> dict:
    """Is any option really better than the current rotation? (playbook 4: 'if the existing rotation
    scores best, say so honestly'). Uses the bootstrap replicates: share of plausible years / weightings /
    prices in which the best alternative beats the current rotation."""
    import numpy as np
    summary, scores, rids = robust["summary"], robust["scores"], robust["rotations"]
    alts = [n for n in summary.index if n != baseline]
    if not alts:
        return {"kind": "only_current", "message": "No alternative rotation fits the farm's constraints."}
    best = alts[0]
    p_better = float(np.mean(scores[:, rids.index(best)] > scores[:, rids.index(baseline)]))
    if summary.index[0] == baseline or p_better < 0.5:
        kind = "current_best"
        msg = ("For your priorities, your current rotation scores as well as or better than every option: "
               f"the closest one ({best}) beats it in only {p_better:.0%} of plausible years, prices and "
               "weightings. The options below are shown for comparison - each has trade-offs worth "
               "discussing with your agronomist.")
    elif p_better < 0.8:
        kind = "close_call"
        msg = (f"A close call: {best} beats your current rotation in {p_better:.0%} of plausible years, "
               "prices and weightings - not clearly better. Worth discussing with your agronomist.")
    else:
        kind = "options_better"
        msg = (f"{best} beats your current rotation in {p_better:.0%} of plausible years, prices and "
               "weightings - an option worth exploring with your agronomist.")
    return {"kind": kind, "best_alternative": best, "p_better": round(p_better, 3), "message": msg}


# --- What-if scenarios (model/scenarios.py) -------------------------------------------------------------
def what_if(res: dict, scenarios: dict | None = None, rotations: list | None = None) -> dict:
    """The rotations shown to the farmer under the +1/+2 C and -10/-20 % summer-rain scenarios
    (scenarios.SCENARIOS). Separate from run_analysis so the app can load it in its own tab.
    res: the dict returned by run_analysis."""
    from fieldshift.model import scenarios as scen_mod
    out = res["run"]
    names = rotations or [s["name"] for s in res["shown"]]
    plans = {n: res["candidates"][n]["plan"] for n in names}
    sliders = {APP_SLIDERS.get(k, k): v for k, v in res["weights"].items()}
    income = {n: v for n, v in (res["income"]["usd_per_acre"] or {}).items() if n in plans}
    if len(income) != len(plans):
        income = None
    m = out["meta"]
    return scen_mod.run_scenarios(
        out["weather"], plans, out["soil"]["awc_mm_per_m"], out["soil"]["tile_drained"], m["latitude"],
        res["existing"]["name"], sliders, {n: out["ordinal_scores"][n] for n in plans},
        slope_factor=out["field"]["slope"].get("rusle_s"), income=income, scenarios=scenarios,
        elevation_m=m["elevation_m"], rs_units=m["rs_units"], wb_kwargs=out["soil"].get("drainage"))


# --- Drainage of untiled fields from SSURGO -------------------------------------------------------------
SPRING_MONTHS = (4, 5, 6)      # SSURGO wtdepaprjunmin describes the April-June water table
SHALLOW_MAJORITY = 0.5         # the field (one bucket) counts as having a high spring water table when
                               # most of its area does


def drainage_params(soil: dict, tiled: bool) -> tuple[dict, str]:
    """Water-model drainage settings for this field (empty dict = water_balance defaults).

    Tiled: tiles remove excess water the same day, so nothing to set.
    Untiled, with SSURGO hydraulics:
      drainage capacity  = Ksat of the most restrictive layer in the top 1.5 m (mm/day)
      April-June         = 0 if most of the field (>= SHALLOW_MAJORITY) has a water table within 1 m
                           (SSURGO wtdepaprjunmin): the root zone then sits on saturated soil and water
                           cannot drain out of the bottom; otherwise the Ksat rate
      max surplus        = water the top metre holds between field capacity and saturation
    """
    if tiled:
        return {}, "Tile-drained: excess water leaves through the tiles the same day."
    ks, dr, share = soil.get("ksat_mm_day"), soil.get("drainable_mm"), soil.get("spring_wt_shallow_share")
    if not ks or dr is None or share is None:
        return {}, ("Untiled field without SSURGO drainage data: default drainage used "
                    f"({wb_defaults()['untiled_drain_mm_day']:.0f} mm/day, {wb_defaults()['max_surplus_mm']:.0f} mm "
                    "above field capacity) - treat waterlogging results as rough.")
    high_wt = share >= SHALLOW_MAJORITY
    params = {"untiled_drain_mm_day": ks, "max_surplus_mm": max(dr, 1.0)}
    if high_wt:
        params["untiled_drain_by_month"] = {m: 0.0 for m in SPRING_MONTHS}
    spring_txt = (f"none in April-June, because {share:.0%} of the field has a spring water table within 1 m"
                  if high_wt else f"also in spring (only {share:.0%} of the field has a spring water table within 1 m)")
    note = (f"Untiled: drainage up to {ks:.0f} mm/day (SSURGO restrictive-layer Ksat), {spring_txt}; the soil "
            f"holds {dr:.0f} mm above field capacity before water runs off (SSURGO saturation - field capacity).")
    return params, note


def wb_defaults() -> dict:
    from fieldshift.model import water_balance as wb
    return {"untiled_drain_mm_day": wb.UNTILED_DRAIN_MM_DAY, "max_surplus_mm": wb.MAX_SURPLUS_MM}

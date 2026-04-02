# Phase 5 — Real-World Data Integration Report

**Sprint:** Phase 5  
**Date:** 2025-07-12  
**Status:** ✅ Complete

---

## What was done

### 1. Real-world destination fixtures (62 airports)

Replaced 40 fictional destinations (VTX, MRD, CRL…) with 62 real-world airports
sourced from OurAirports `airports.csv`. Airports were selected for geographic
diversity, distance tiers, and global hub coverage.

**Script:** `scripts/helper_generate_destinations.py`  
**Output:** `services/sim-orchestrator/fixtures/destinations.json`

Distance tiers from KART (38.75°N, 27.08°W):

- Domestic (< 1 500 km): 6 airports — Azores regional (PDL, TER, HOR…)
- Short-haul (1 500–4 000 km): 27 airports — Europe + North Africa (LHR, CDG, MAD, FRA…)
- Long-haul (> 4 000 km): 29 airports — Americas, Africa, Middle East, Asia (JFK, GRU, NBO, DXB…)

### 2. Real-world airline fixtures (15 airlines)

Replaced 12 fictional airlines with 15 real carriers from OpenFlights `airlines.dat`
and `routes.dat`. Fleet data is derived from equipment codes in the routes dataset.

**Script:** `scripts/helper_generate_airlines.py`  
**Output:** `services/sim-orchestrator/fixtures/airlines.json`

Airlines: BA, AF, LH, IB, KL, TP, FR, U2, AA, UA, DL, EK, ET, LA, S4.

### 3. Historical METAR replay (weather-service)

New module `services/weather-service/services/historical.py` — loads IEM Mesonet
CSV files (30 days of hourly METAR data) and replays them keyed to simulation time.

Features:

- Cyclic day wrapping (day 31 wraps to day 1)
- Fahrenheit → Celsius, statute miles → metres, inHg → hPa
- IFR category classification from visibility + ceiling (CAVOK/VMC/IMC/LIFR)
- Binary search for closest observation at any sim time

### 4. Live METAR fetch (weather-service)

New module `services/weather-service/services/live_metar.py` — fetches real-time
METAR from the Aviation Weather Center public API (no API key required).

Features:

- 30-minute real-time cache
- Graceful fallback to stale cache on network failure
- JSON response parsing with cloud/ceiling/visibility/wind extraction

### 5. Weather source switching

`WEATHER_SOURCE` env var controls mode: `simulated` (default), `historical`, `live`.

The weather consumer dispatches to the appropriate source at hourly boundaries,
with the FSM continuing to run transitions between observations.

---

## Issues and fixes

### Major hub airports missing on first run

**Problem:** The country-diversity-first selection algorithm picked obscure airports
(e.g., Reykjavik over London, Dakar over Paris) because it prioritised having one
airport per country before considering hub importance.

**Fix:** Added a `MUST_INCLUDE` set of ~20 iconic hub airports (LHR, JFK, CDG, GRU,
NBO, DXB, IST, MAD, FRA, AMS, LIS, CMN…) with a 10× weight boost. Selection now
runs in three passes: must-includes first, then country diversity, then top-weighted fill.

### Mock patching across test modules

**Problem:** `@patch("services.live_metar.httpx.Client")` string targets broke when
test files ran in sequence because the `services` package gets replaced between
service imports (e.g., flight-service → weather-service).

**Fix:** Used `patch.object(_live.httpx, "Client", ...)` to target the actual module
reference held by the imported module, bypassing string-based resolution.

### KART's natural geography

KART sits in the mid-Atlantic (Azores). Only 6 airports exist within 1 500 km.
This is realistic — the "domestic" tier is naturally small for an ocean-based hub.
No fix needed; just something to be aware of in simulation.

---

## Test coverage

| Suite                      | Count   | Result      |
| -------------------------- | ------- | ----------- |
| Existing unit tests        | 476     | ✅ Pass     |
| New historical METAR tests | 20      | ✅ Pass     |
| New live METAR tests       | 11      | ✅ Pass     |
| **Total**                  | **507** | **✅ Pass** |

Ruff lint: clean on `services/weather-service/`, `services/sim-orchestrator/`, `scripts/`.  
Docker build: weather-service image builds successfully with httpx.  
Dashboard build: `npm run build` succeeds (no TypeScript breakage).

---

## Files changed

| File                                                   | Action                                       |
| ------------------------------------------------------ | -------------------------------------------- |
| `scripts/helper_generate_destinations.py`              | Created — destination fixture generator      |
| `scripts/helper_generate_airlines.py`                  | Created — airline fixture generator          |
| `services/weather-service/services/historical.py`      | Created — historical METAR replay            |
| `services/weather-service/services/live_metar.py`      | Created — live METAR fetch                   |
| `services/weather-service/kafka/consumer.py`           | Modified — 3-mode weather source dispatch    |
| `services/weather-service/routers/weather.py`          | Modified — `/weather/source` endpoint        |
| `services/weather-service/requirements.txt`            | Modified — added httpx                       |
| `services/sim-orchestrator/fixtures/destinations.json` | Regenerated — 62 real airports               |
| `services/sim-orchestrator/fixtures/airlines.json`     | Regenerated — 15 real airlines               |
| `docker-compose.yml`                                   | Modified — weather env vars + data volume    |
| `data/README.md`                                       | Rewritten — comprehensive data pipeline docs |
| `scripts/README.md`                                    | Updated — new script documentation           |
| `ROADMAP.md`                                           | Updated — Phase 5 marked complete            |
| `tests/unit/test_weather_historical.py`                | Created — 20 tests                           |
| `tests/unit/test_weather_live_metar.py`                | Created — 11 tests                           |
| `docs/lessons-learned/phase-5-real-world-data-plan.md` | Created — implementation plan                |

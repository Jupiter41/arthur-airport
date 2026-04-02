# Phase 5 — Real-World Data Integration Plan

## Overview

Replace fictional airlines, destinations, and weather with real-world data from:

- **OpenFlights**: Real airline identities, real route networks, real aircraft types
- **OurAirports**: Real destination airports with IATA/ICAO codes, coordinates, types
- **IEM Mesonet**: Historical METAR weather data (30-day CSV)
- **Aviation Weather Center**: Live METAR/TAF data (optional, API-based)

## Current State

- `data/ourairports/airports.csv` — 85K airports, already used by `helper_generate_destination_coordinates.py`
- `data/openflights/airlines.dat` — 6K airlines (CSV, no header)
- `data/openflights/routes.dat` — 68K route records
- `data/openflights/planes.dat` — 246 aircraft types
- `data/weather/EGLL_30days.csv` — 1.4K METAR observations from Heathrow
- `data/weather/LFPG_30days.csv` — historical METAR from CDG
- Fixtures currently use 12 fictional airlines, 40 fictional destinations, 8 aircraft types

## Implementation Steps

### Step 1: Helper script — generate real airlines fixture

Create `scripts/helper_generate_airlines.py`:

- Read `data/openflights/airlines.dat` (columns: ID, Name, Alias, IATA, ICAO, Callsign, Country, Active)
- Filter: Active == "Y", has IATA code (2 chars), has name
- Select ~15-20 diverse airlines: mix of full-service, low-cost, regional, cargo
- Weighted by realistic market share for a mid-Atlantic hub
- Output: `services/sim-orchestrator/fixtures/airlines.json` (same schema as current)

### Step 2: Helper script — generate real destinations fixture

Create `scripts/helper_generate_destinations.py`:

- Read `data/ourairports/airports.csv`
- Filter: large_airport + medium_airport, has IATA code
- Compute great-circle distance from KART (38.75°N, 27.0833°W)
- Filter by distance: 200–12,000 km
- Weight: 5:1 large vs medium, distance-based (more short/medium-haul)
- Classify: <1500km domestic/short-haul, 1500-4000km medium-haul, >4000km long-haul
- Select ~80 destinations with realistic diversity (Europe, Americas, Africa, Asia)
- Output: `services/sim-orchestrator/fixtures/destinations.json` (same schema enriched with lat/lon)

### Step 3: Helper script — generate real aircraft types fixture

Create `scripts/helper_generate_aircraft_types.py`:

- Read `data/openflights/planes.dat` (Name, IATA, ICAO)
- Map to our existing 8 types with real data, keep same schema
- Add a few more types if routes demand it
- Output: `services/sim-orchestrator/fixtures/aircraft_types.json` (validated against current schema)

### Step 4: Weather service — historical METAR replay mode

Add `WEATHER_SOURCE` env var to weather-service:

- `simulated` (default) — existing FSM behavior
- `historical` — replay METAR from CSV file (`WEATHER_HISTORY_FILE` env var)
- `live` — fetch from Aviation Weather Center API

For `historical` mode:

- Parse the IEM Mesonet CSV format (station, valid, tmpf, dwpf, relh, drct, sknt, etc.)
- Convert to WeatherParams: visibility, wind, ceiling, temperature, QNH, phenomena
- Classify into CAVOK/VMC/IMC/LIFR categories
- Advance through the CSV keyed on sim_time (map sim hours to historical hours)
- Fall back to FSM if CSV data runs out

For `live` mode:

- Fetch from `https://aviationweather.gov/api/data/metar?ids={ICAO}&format=json`
- Parse JSON response into WeatherParams
- Cache for 30 min (METAR update interval)
- Fall back to FSM on fetch failure

### Step 5: Update destinations.json schema

Add `latitude_deg` and `longitude_deg` to each destination for geospatial features.
The schedule generator already computes `flight_duration_minutes` from `distance_nm`.

### Step 6: Update download_all.sh

Add any new data sources and document refresh procedure.

### Step 7: Update data/README.md

Document the new data pipeline and helper scripts.

### Step 8: Docker/config integration

- Add `WEATHER_SOURCE`, `WEATHER_HISTORY_FILE` env vars to docker-compose.yml
- Mount weather CSV into weather-service container
- Document in docs/infra/DOCKER.md

### Step 9: Validation

- Rebuild containers, verify schedule generation uses real airlines/destinations
- Check dashboard shows real IATA codes and airline names
- Verify weather METAR displays correctly
- Run unit tests, ruff, npm build

## Non-goals (out of scope)

- Real-time flight tracking APIs (FlightAware, OpenSky) — commercial/complex
- Real passenger data — always synthetic
- ADS-B integration — future phase

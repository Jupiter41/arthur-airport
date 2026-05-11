# `data/` — Reference Datasets

Static reference data used by the sim-orchestrator to generate realistic schedules, populate destination pools, and drive simulation parameters. All datasets are free, open-licensed, and can be refreshed without code changes.

---

## Data pipeline

Helper scripts in `scripts/` transform raw CSV data into service-ready JSON fixtures:

```
data/ourairports/airports.csv  ──→  scripts/helper_generate_destinations.py
                                      └→ services/sim-orchestrator/fixtures/destinations.json
                                      └→ dashboards/art-dashboard/src/data/destinationCoordinates.ts

data/openflights/airlines.dat  ──→  scripts/helper_generate_airlines.py
data/openflights/routes.dat          └→ services/sim-orchestrator/fixtures/airlines.json

data/weather/EGLL_30days.csv   ──→  weather-service (historical mode, mounted via Docker volume)
```

To regenerate fixtures after refreshing data:

```bash
python scripts/helper_generate_destinations.py
python scripts/helper_generate_airlines.py
python scripts/helper_generate_destination_coordinates.py
```

---

## Current Datasets

### OurAirports _(downloaded)_

|             |                                                          |
| ----------- | -------------------------------------------------------- |
| **License** | Public Domain (CC0)                                      |
| **Source**  | https://ourairports.com/data/                            |
| **Refresh** | Monthly snapshot, updated automatically by the community |

| File                      | Rows    | Used for                                             |
| ------------------------- | ------- | ---------------------------------------------------- |
| `airports.csv`            | ~85,000 | Destination pool — lat/lon, IATA codes, airport type |
| `runways.csv`             | ~45,000 | Runway length, surface, ILS availability per airport |
| `airport-frequencies.csv` | ~28,000 | ATC frequencies _(future: radio comms simulation)_   |
| `navaids.csv`             | ~11,000 | Navigation aids _(future: route waypoints)_          |
| `countries.csv`           | ~250    | Country names for passenger nationality mapping      |
| `regions.csv`             | ~3,900  | Regional grouping for schedule generation            |

**Key columns used from `airports.csv`:**

| Column          | Description                                                          |
| --------------- | -------------------------------------------------------------------- |
| `ident`         | ICAO code (e.g. `EGLL`)                                              |
| `iata_code`     | IATA code (e.g. `LHR`)                                               |
| `type`          | `large_airport` \| `medium_airport` \| `small_airport` \| `heliport` |
| `name`          | Full airport name                                                    |
| `latitude_deg`  | WGS84 latitude                                                       |
| `longitude_deg` | WGS84 longitude                                                      |
| `elevation_ft`  | Elevation above sea level                                            |
| `iso_country`   | ISO 3166-1 alpha-2 country code                                      |
| `municipality`  | City name                                                            |

**Filtering for destination pool** (see `scripts/helper_generate_destinations.py`):

```python
df = df[df["type"].isin(["large_airport", "medium_airport"])]
df = df[df["iata_code"].notna() & (df["iata_code"] != "")]
df = df[(df["distance_km"] >= 200) & (df["distance_km"] <= 12000)]
```

---

### OpenFlights — Airlines, Routes, Aircraft _(downloaded)_

|             |                                   |
| ----------- | --------------------------------- |
| **License** | Open Database License (ODbL)      |
| **Source**  | https://openflights.org/data.html |
| **Format**  | CSV (direct download, no API key) |
| **Refresh** | Infrequent (community-maintained) |

| File           | Rows    | Used for                               |
| -------------- | ------- | -------------------------------------- |
| `airlines.dat` | ~6,000  | Real airline names, IATA/ICAO codes    |
| `routes.dat`   | ~68,000 | Aircraft equipment mapping per airline |
| `planes.dat`   | ~246    | Aircraft type names _(reference)_      |

**Used by:** `scripts/helper_generate_airlines.py` → `fixtures/airlines.json`

---

### IEM Mesonet — Historical METAR _(downloaded)_

|             |                                                                  |
| ----------- | ---------------------------------------------------------------- |
| **License** | Public Domain (US Government data)                               |
| **Source**  | https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py        |
| **Format**  | CSV with ~30 columns including raw METAR, temp, wind, visibility |
| **History** | 30-day rolling window (configurable in `download_all.sh`)        |

| File              | Rows   | Station | Used for                           |
| ----------------- | ------ | ------- | ---------------------------------- |
| `EGLL_30days.csv` | ~1,440 | EGLL    | Historical weather replay (London) |
| `LFPG_30days.csv` | ~1,440 | LFPG    | Historical weather replay (Paris)  |

**Used by:** weather-service in `historical` mode (`WEATHER_SOURCE=historical`).

Set `WEATHER_HISTORY_FILE` to switch between stations:

```bash
WEATHER_SOURCE=historical WEATHER_HISTORY_FILE=/app/data/weather/LFPG_30days.csv docker compose up
```

---

### Aviation Weather Center — Live METAR _(API, no download needed)_

|             |                                       |
| ----------- | ------------------------------------- |
| **License** | Public Domain (US Government)         |
| **Source**  | https://aviationweather.gov/data/api/ |
| **Format**  | JSON REST API                         |
| **History** | Limited (~24–48 hours max)            |

```bash
curl "https://aviationweather.gov/api/data/metar?ids=EGLL&format=json"
```

**Used by:** weather-service in `live` mode (`WEATHER_SOURCE=live`).

No API key required. Results are cached for 30 real minutes.

```bash
WEATHER_SOURCE=live WEATHER_LIVE_ICAO=EGLL docker compose up
```

---

## Refreshing all data

```bash
bash data/download_all.sh
python scripts/helper_generate_destinations.py
python scripts/helper_generate_airlines.py
python scripts/helper_generate_destination_coordinates.py
```

---

### Iowa State Mesonet (IEM) — Historical METAR Archive

|             |                                                          |
| ----------- | -------------------------------------------------------- |
| **License** | Public Domain (NOAA / ASOS derived data)                 |
| **Source**  | https://mesonet.agron.iastate.edu/request/download.phtml |
| **Format**  | CSV (no API key required)                                |
| **History** | Decades of global METAR data                             |

Canonical source for historical METAR data.

```bash
# ── IEM Mesonet — 30-day METAR history ────────────────────────────────────────

BASE="https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

START=$(date -u -d "30 days ago" +"%Y %m %d")
END=$(date -u +"%Y %m %d")

read Y1 M1 D1 <<< "$START"
read Y2 M2 D2 <<< "$END"

# Heathrow (Atlantic proxy)
curl -o data/weather/EGLL_30days.csv \
  "$BASE?station=EGLL&data=all&tz=UTC&format=onlycomma&latlon=no&report_type=3\
&year1=$Y1&month1=$M1&day1=$D1&year2=$Y2&month2=$M2&day2=$D2"

# Paris CDG (Continental proxy)
curl -o data/weather/LFPG_30days.csv \
  "$BASE?station=LFPG&data=all&tz=UTC&format=onlycomma&latlon=no&report_type=3\
&year1=$Y1&month1=$M1&day1=$D1&year2=$Y2&month2=$M2&day2=$D2"
```

**Query parameters:**

| Parameter     | Value       | Notes                          |
| ------------- | ----------- | ------------------------------ |
| `format`      | `onlycomma` | Clean CSV output (no comments) |
| `report_type` | `3`         | METAR only                     |
| `tz`          | `UTC`       | Consistent timestamps          |

**Used for:**

- Historical weather scenarios
- FSM calibration
- ML / LSTM training datasets

---

### adsb.lol — Live ADS-B Data (Primary)

|             |                                   |
| ----------- | --------------------------------- |
| **License** | Community / Free                  |
| **Source**  | https://www.adsb.lol/             |

**Used for:**

- Real-time aircraft positions on the world map overlay
- Track comparison with simulated great-circle arcs
- No authentication required, no rate limits

---

### OpenSky Network — Historical Flight Data (Fallback ADS-B)

|             |                                   |
| ----------- | --------------------------------- |
| **License** | CC BY 4.0                         |
| **Source**  | https://opensky-network.org/data/ |

**Used for:**

- Fallback ADS-B source when adsb.lol is unavailable
- Historical tracks from Zenodo monthly dumps for calibration
- Real schedule distributions
- Trajectory validation

---

### BTS (US DOT) — On-Time Performance & Passenger Statistics

|             |                                          |
| ----------- | ---------------------------------------- |
| **License** | Public Domain (US government)            |
| **Source**  | https://www.transtats.bts.gov/           |

**Key datasets:**

- **T-100 Domestic/International Segment** — monthly passenger counts by route
- **On-Time Performance** — departure/arrival delays, cancellation reasons
- **Air Carrier Statistics** — load factors, seat capacity

**Used for:**

- Calibrating simulated passenger volumes per route
- Validating delay distributions against real-world patterns
- Historical on-time performance benchmarks

**Local files:**

| File                          | Notes                                         |
| ----------------------------- | --------------------------------------------- |
| `data/bts/T100_sample.csv`    | 24-row demo segment (Luxembourg ⇄ Frankfurt) |
| `data/bts/README.md`          | Download steps for the full T-100 dataset     |

Activate at runtime:

```bash
PASSENGER_SOURCE=bts_historical \
PASSENGER_BTS_FILE=/app/data/bts/T100_sample.csv \
docker compose up passenger-service
```

The dashboard `Data Sources → Passenger Flow` switch performs the same swap
without restarting the service.

---

### FAA ASRS — Aviation Safety Reporting System

|             |                                                |
| ----------- | ---------------------------------------------- |
| **License** | Public Domain (US government, NASA-operated)   |
| **Source**  | https://asrs.arc.nasa.gov/search/database.html |

ASRS is the canonical anonymous incident-reporting database for U.S. civil
aviation. Public summaries provide per-category event rates that we use to
calibrate the digital twin's probabilistic incident injector against
real-world frequencies.

**Used for:**

- The `asrs_historical` calibration preset in
  `services/sim-orchestrator/fixtures/incident_calibrations.json`
- Adds two extra incident categories observed in ASRS data: `bird_strike`
  and `medical_emergency`.

Switch the active calibration at runtime:

```bash
# Default: simulated (heuristic, more visible incidents)
INCIDENT_SOURCE=simulated docker compose up sim-orchestrator

# Or via the API
curl -X POST http://localhost:3000/api/v1/sim/incident-source \
  -H 'content-type: application/json' \
  -d '{"source":"asrs_historical"}'
```

The dashboard `Data Sources → Incident Calibration` card exposes the same
toggle.

---

### TimeZoneDB — Airport Time Zones

|             |                                 |
| ----------- | ------------------------------- |
| **License** | CC BY 3.0                       |
| **Source**  | https://timezonedb.com/download |

```bash
curl -o data/timezones.zip "https://timezonedb.com/files/timezonedb.csv.zip"
unzip data/timezones.zip -d data/timezones/
```

**Used for:**

- Local time display
- UTC offset computation

---

## Folder Structure

```
data/
├── README.md
├── ourairports/
├── openflights/
├── weather/
├── opensky/
└── timezones/
```

---

## Quick Download — All Datasets

```bash
mkdir -p data/{ourairports,openflights,weather,opensky,timezones}

# OurAirports
BASE="https://davidmegginson.github.io/ourairports-data"
curl -o data/ourairports/airports.csv "$BASE/airports.csv"

# OpenFlights
BASE="https://raw.githubusercontent.com/jpatokal/openflights/master/data"
curl -o data/openflights/routes.dat "$BASE/routes.dat"

# IEM Weather
BASE="https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

START=$(date -u -d "30 days ago" +"%Y %m %d")
END=$(date -u +"%Y %m %d")

read Y1 M1 D1 <<< "$START"
read Y2 M2 D2 <<< "$END"

curl -o data/weather/EGLL_30days.csv \
  "$BASE?station=EGLL&data=all&tz=UTC&format=onlycomma&latlon=no&report_type=3\
&year1=$Y1&month1=$M1&day1=$D1&year2=$Y2&month2=$M2&day2=$D2"
```

---

## License Summary

| Dataset          | License       | Attribution required | Commercial use |
| ---------------- | ------------- | :------------------: | :------------: |
| OurAirports      | CC0           |          No          |       ✅       |
| OpenFlights      | ODbL          |         Yes          |       ✅       |
| Aviation Weather | Public Domain |          No          |       ✅       |
| IEM Mesonet      | Public Domain |          No          |       ✅       |
| adsb.lol         | Community     |          No          |       ✅       |
| OpenSky Network  | CC BY 4.0     |         Yes          |       ✅       |
| BTS (US DOT)     | Public Domain |          No          |       ✅       |
| TimeZoneDB       | CC BY 3.0     |         Yes          |   ⚠️ Limited   |

---

> **Note:** All datasets are used for simulation and educational purposes only.
> No safety-critical or operational decisions should rely on this data.

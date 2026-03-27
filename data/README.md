# `data/` — Reference Datasets

Static reference data used by the sim-orchestrator to generate realistic schedules, populate destination pools, and drive simulation parameters. All datasets are free, open-licensed, and can be refreshed without code changes.

---

## Current Datasets

### OurAirports _(already downloaded)_

|             |                                                          |
| ----------- | -------------------------------------------------------- |
| **License** | Public Domain (CC0)                                      |
| **Source**  | https://ourairports.com/data/                            |
| **Refresh** | Monthly snapshot, updated automatically by the community |

| File                      | Rows    | Used for                                             |
| ------------------------- | ------- | ---------------------------------------------------- |
| `airports.csv`            | ~74,000 | Destination pool — lat/lon, IATA codes, airport type |
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

**Filtering for destination pool** (see `docs/architecture/SIMULATION.md §6.3`):

```python
df = df[df["type"].isin(["large_airport", "medium_airport"])]
df = df[df["iata_code"].notna() & (df["iata_code"] != "")]
df = df[(df["distance_km"] >= 200) & (df["distance_km"] <= 12000)]
```

---

## Recommended Additional Datasets

### OpenFlights — Airlines, Routes, Aircraft

|             |                                   |
| ----------- | --------------------------------- |
| **License** | Open Database License (ODbL)      |
| **Source**  | https://openflights.org/data.html |
| **Format**  | CSV (direct download, no API key) |
| **Refresh** | Infrequent (community-maintained) |

```bash
curl -o data/openflights/airlines.dat \
  https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat

curl -o data/openflights/routes.dat \
  https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat

curl -o data/openflights/planes.dat \
  https://raw.githubusercontent.com/jpatokal/openflights/master/data/planes.dat
```

**Used for:**

- `airlines.dat` → Realistic airline identities
- `routes.dat` → Real-world network topology
- `planes.dat` → Aircraft types and equipment mapping

---

### Aviation Weather Center — METAR/TAF _(live only)_

|             |                                       |
| ----------- | ------------------------------------- |
| **License** | Public Domain (US Government)         |
| **Source**  | https://aviationweather.gov/data/api/ |
| **Format**  | JSON REST API                         |
| **History** | Limited (~24–48 hours max)            |

```bash
curl "https://aviationweather.gov/api/data/metar?ids=EGLL&format=json"
curl "https://aviationweather.gov/api/data/metar?ids=EGLL&format=json&hours=24"
```

**Used for:**

- Live simulation weather (`WEATHER_SOURCE=live`)
- Real-time METAR ingestion

> ⚠️ The `hours` parameter is capped (~48h). This API **cannot** be used for historical datasets.

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

### OpenSky Network — Historical Flight Data

|             |                                   |
| ----------- | --------------------------------- |
| **License** | CC BY 4.0                         |
| **Source**  | https://opensky-network.org/data/ |

**Used for:**

- Real schedule distributions
- Trajectory validation

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
| OpenSky Network  | CC BY 4.0     |         Yes          |       ✅       |
| TimeZoneDB       | CC BY 3.0     |         Yes          |   ⚠️ Limited   |

---

> **Note:** All datasets are used for simulation and educational purposes only.
> No safety-critical or operational decisions should rely on this data.

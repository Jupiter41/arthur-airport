# HOW-TO — Create Your Own Airport

The simulation is driven by a single configuration file:

```
config/airport.yaml
```

This file controls the airport identity, physical infrastructure, flight schedule
generation, and flight type distribution. All services read their operational
parameters from this file at startup.

---

## Quick start

```bash
# 1. Edit the config
nano config/airport.yaml

# 2. Validate before running
python scripts/helper_validate_airport_config.py --path config/airport.yaml

# 3. Optional: preview as JSON
python scripts/helper_validate_airport_config.py --path config/airport.yaml --json

# 4. Start the simulation
docker compose up --build
```

---

## Configuration reference

### `identity` — Airport identification

| Field      | Type   | Default                          | Description                                                              |
| ---------- | ------ | -------------------------------- | ------------------------------------------------------------------------ |
| `name`     | string | `"Arthur International Airport"` | Full airport name — displayed in dashboard header and API responses      |
| `iata`     | string | `"ART"`                          | IATA 3-letter code — used as home origin/destination in flight schedules |
| `icao`     | string | `"KART"`                         | ICAO 4-letter code — used in METAR/TAF generation and ADS-B lookups      |
| `timezone` | string | `"America/Arthur"`               | IANA timezone identifier — cosmetic only, simulation runs in UTC         |

```yaml
identity:
  name: "Arthur International Airport"
  iata: "ART"
  icao: "KART"
  timezone: "America/Arthur"
```

### `infrastructure` — Physical layout

| Field                | Type      | Default        | Constraints                             | Description                                                          |
| -------------------- | --------- | -------------- | --------------------------------------- | -------------------------------------------------------------------- |
| `terminals`          | int       | `3`            | 1–26                                    | Number of terminals — labelled A, B, C, etc.                         |
| `gates_per_terminal` | list[int] | `[14, 14, 14]` | each ≥ 1, length must match `terminals` | Number of gates per terminal — gates are numbered `A01`, `B14`, etc. |
| `runways`            | list      | _(see below)_  | at least 1                              | Runway pairs                                                         |

**Runway fields:**

| Field      | Type   | Default | Description                                                                        |
| ---------- | ------ | ------- | ---------------------------------------------------------------------------------- |
| `id`       | string | —       | Runway designator, e.g. `"09L/27R"` for a pair or `"09L"` for a single direction   |
| `length_m` | int    | `3500`  | Runway length in metres (≥ 500)                                                    |
| `ils`      | bool   | `false` | Whether the runway has ILS (Instrument Landing System) — affects IMC/LIFR capacity |

```yaml
infrastructure:
  terminals: 3
  gates_per_terminal: [14, 14, 14]
  runways:
    - id: "09L/27R"
      length_m: 3500
      ils: true
    - id: "09R/27L"
      length_m: 3500
      ils: false
```

**How runways work:** Each `id` with a `/` separator defines a pair — the first
direction (e.g. `09L`) is used for departures, the second (`27R`) for arrivals.
A single direction entry is used for both.

### `simulation` — Schedule generation

| Field                 | Type           | Default                 | Constraints | Description                                                                                               |
| --------------------- | -------------- | ----------------------- | ----------- | --------------------------------------------------------------------------------------------------------- |
| `daily_flight_target` | int            | `420`                   | 20–5000     | Total flights generated per simulated day (departures + arrivals)                                         |
| `load_factor_mean`    | float          | `0.80`                  | 0.1–0.99    | Mean passenger load factor — higher means fuller planes. Uses a Beta distribution with concentration 10.0 |
| `peak_hours`          | list[int]      | `[7, 8, 9, 17, 18, 19]` | hours 0–23  | Hours with increased incident probability (1.8× multiplier)                                               |
| `hourly_weights`      | dict[int, int] | _(see below)_           | —           | Relative flight volume per hour — controls the shape of the daily schedule                                |

**Hourly weights** define how flights are distributed across the day. Each key is
an hour (0–23) and the value is a relative weight. Hours not listed get zero flights.
The weights are normalized internally, so only the ratios matter.

Default distribution (peaks at 08:00 and 17:00):

```yaml
simulation:
  hourly_weights:
    5: 2 # early morning ramp-up
    6: 8
    7: 14 # morning peak
    8: 16 # ← busiest hour
    9: 12
    10: 10
    11: 9
    12: 8 # midday trough
    13: 9
    14: 10
    15: 10
    16: 12
    17: 15 # evening peak
    18: 14
    19: 10
    20: 7
    21: 5
    22: 3 # last departures
```

### `flight_types` — Traffic mix

| Field                 | Type  | Default | Description                                                |
| --------------------- | ----- | ------- | ---------------------------------------------------------- |
| `domestic`            | float | `0.42`  | Short-haul domestic flights                                |
| `international_short` | float | `0.28`  | Medium-haul international flights (< 6h)                   |
| `international_long`  | float | `0.18`  | Long-haul international flights (> 6h)                     |
| `cargo`               | float | `0.08`  | Freight-only flights (no passengers, different turnaround) |
| `charter`             | float | `0.04`  | Charter flights                                            |

Values **must sum to 1.0** (±0.01 tolerance). A validation error is raised otherwise.

Cargo and charter are assigned probabilistically during schedule generation. The
remaining flights are classified as domestic / international_short / international_long
based on the destination distance.

```yaml
flight_types:
  domestic: 0.42
  international_short: 0.28
  international_long: 0.18
  cargo: 0.08
  charter: 0.04
```

### `airlines` — Airline overrides (optional)

Override or extend the airline fixtures. Each entry matches by `code` and updates
the corresponding airline in the fixture file. Market shares are normalized at runtime.

| Field          | Type   | Required | Description                                                       |
| -------------- | ------ | -------- | ----------------------------------------------------------------- |
| `code`         | string | yes      | IATA 2-letter airline code — must match a fixture airline         |
| `name`         | string | yes      | Airline display name                                              |
| `market_share` | float  | yes      | Relative market share (0.0–1.0) — normalized against all airlines |
| `hub_terminal` | string | no       | Preferred terminal letter for this airline's flights              |

```yaml
airlines:
  - code: "AX"
    name: "Artex Airways"
    market_share: 0.22
    hub_terminal: "B"
```

---

## Runtime-tuneable parameters

Beyond `airport.yaml`, many operational parameters can be adjusted at runtime via
the Settings UI or `PATCH /api/v1/sim/settings`. These do not require a restart.

| Parameter                         | Default         | Category   | What it controls                                          |
| --------------------------------- | --------------- | ---------- | --------------------------------------------------------- |
| `weather_lock`                    | `null`          | Weather    | Lock weather to CAVOK/VMC/IMC/LIFR (null = automatic FSM) |
| `wind_kt`                         | `15`            | Weather    | Default wind speed in knots                               |
| `lanes_a` / `lanes_b` / `lanes_c` | `4` / `3` / `4` | Security   | Number of open security lanes per terminal                |
| `mct_minutes`                     | `45`            | Passengers | Minimum connection time in minutes                        |
| `screening_units`                 | `6`             | Baggage    | Number of baggage screening units                         |
| `sorting_capacity`                | `1800`          | Baggage    | Sorting matrix throughput (bags/hour)                     |
| `dg_false_positive_rate`          | `0.003`         | Baggage    | Dangerous goods false alarm rate                          |
| `crew_delay_probability`          | `0.05`          | Noise      | Probability of crew readiness delay per flight            |
| `ctot_probability_peak`           | `0.10`          | Noise      | Probability of ATC slot delay during peak hours           |
| `noshow_rate`                     | `0.03`          | Noise      | Passenger no-show rate                                    |
| `equipment_failure_rate`          | `0.01`          | Noise      | Ground equipment failure rate per flight                  |
| `diversion_rate`                  | `0.003`         | Noise      | Flight diversion rate                                     |
| `runway_incursion_rate`           | `0.005`         | Incidents  | Hourly probability of runway incursion                    |
| `baggage_fire_rate`               | `0.008`         | Incidents  | Hourly probability of baggage fire                        |
| `security_breach_rate`            | `0.010`         | Incidents  | Hourly probability of security breach                     |
| `system_failure_rate`             | `0.015`         | Incidents  | Hourly probability of system failure                      |

---

## Scenario examples

### Normal day — balanced traffic

A typical day at a medium-sized international airport. Dual peaks at morning and
evening, moderate load factor, standard incident rates.

```yaml
identity:
  name: "Arthur International Airport"
  iata: "ART"
  icao: "KART"
  timezone: "America/Arthur"

infrastructure:
  terminals: 3
  gates_per_terminal: [14, 14, 14]
  runways:
    - id: "09L/27R"
      length_m: 3500
      ils: true
    - id: "09R/27L"
      length_m: 3500
      ils: false

simulation:
  daily_flight_target: 420
  load_factor_mean: 0.80
  peak_hours: [7, 8, 9, 17, 18, 19]
  hourly_weights:
    5: 2
    6: 8
    7: 14
    8: 16
    9: 12
    10: 10
    11: 9
    12: 8
    13: 9
    14: 10
    15: 10
    16: 12
    17: 15
    18: 14
    19: 10
    20: 7
    21: 5
    22: 3

flight_types:
  domestic: 0.42
  international_short: 0.28
  international_long: 0.18
  cargo: 0.08
  charter: 0.04
```

### Special event day — concert or sports match

A large event near the airport causes a passenger surge in the afternoon/evening.
Higher load factors, concentrated evening peak, more charter flights.

```yaml
simulation:
  daily_flight_target: 520 # 24% more flights
  load_factor_mean: 0.92 # nearly full planes
  peak_hours: [7, 8, 15, 16, 17, 18, 19, 20] # extended evening peak
  hourly_weights:
    5: 1
    6: 5
    7: 10
    8: 12
    9: 8
    10: 6
    11: 5
    12: 5
    13: 6
    14: 8
    15: 14 # post-event surge starts early
    16: 18
    17: 20 # ← busiest hour (event departures)
    18: 18
    19: 14
    20: 10
    21: 8
    22: 5

flight_types:
  domestic: 0.48
  international_short: 0.22
  international_long: 0.10
  cargo: 0.05
  charter: 0.15 # charter spike for group travel
```

**Runtime tuning:** After starting, set `weather_lock: "CAVOK"` in settings
and increase security lanes (`lanes_a: 6, lanes_b: 5, lanes_c: 6`) to handle
the surge.

### Bad weather day — winter storm

Low visibility and high winds reduce runway capacity and cause cascading delays.
Fewer flights are scheduled because airlines pre-cancel thin routes.

```yaml
simulation:
  daily_flight_target: 320 # 24% fewer flights (pre-cancellations)
  load_factor_mean: 0.85 # rebooking consolidation
  peak_hours: [7, 8, 9, 17, 18, 19]
  hourly_weights:
    6: 4
    7: 10
    8: 14
    9: 12
    10: 10
    11: 9
    12: 8
    13: 9
    14: 10
    15: 10
    16: 12
    17: 14
    18: 12
    19: 8
    20: 5
    21: 3
```

**Runtime tuning:** Lock weather to `IMC` or `LIFR` via settings, increase
wind to `wind_kt: 35`, and raise `diversion_rate: 0.01` for more diversions.
The simulation will automatically reduce runway capacity and trigger holding
patterns.

### Cargo hub — overnight freight peak

A cargo-oriented airport (like Memphis or Louisville) with overnight operations
and minimal passenger traffic during the day.

```yaml
infrastructure:
  terminals: 2
  gates_per_terminal: [20, 10] # T-A is cargo, T-B is passenger
  runways:
    - id: "09L/27R"
      length_m: 4000
      ils: true
    - id: "09R/27L"
      length_m: 3500
      ils: true

simulation:
  daily_flight_target: 380
  load_factor_mean: 0.60 # many half-empty passenger flights
  peak_hours: [0, 1, 2, 3, 4, 22, 23] # overnight peaks for cargo
  hourly_weights:
    0: 16 # overnight cargo peak
    1: 18 # ← busiest hour
    2: 14
    3: 10
    4: 8
    5: 4
    6: 6 # passenger morning
    7: 8
    8: 8
    9: 6
    10: 4
    11: 4
    12: 4
    13: 4
    14: 4
    15: 4
    16: 6
    17: 8
    18: 6
    19: 4
    20: 4
    21: 6
    22: 12 # evening cargo
    23: 14

flight_types:
  domestic: 0.15
  international_short: 0.10
  international_long: 0.10
  cargo: 0.55 # majority cargo
  charter: 0.10
```

### Large international hub — Heathrow-scale

A major hub airport with 5 terminals, 2 long runways, very high traffic density,
and a long-haul heavy flight mix.

```yaml
identity:
  name: "Heathrow International Airport"
  iata: "LHR"
  icao: "EGLL"
  timezone: "Europe/London"

infrastructure:
  terminals: 5
  gates_per_terminal: [28, 32, 26, 60, 10]
  runways:
    - id: "09L/27R"
      length_m: 3902
      ils: true
    - id: "09R/27L"
      length_m: 3660
      ils: true

simulation:
  daily_flight_target: 1300
  load_factor_mean: 0.88
  peak_hours: [6, 7, 8, 9, 17, 18, 19, 20]
  hourly_weights:
    5: 4
    6: 14
    7: 18
    8: 18
    9: 16
    10: 14
    11: 12
    12: 12
    13: 12
    14: 14
    15: 14
    16: 16
    17: 18
    18: 16
    19: 12
    20: 8
    21: 6
    22: 4

flight_types:
  domestic: 0.20
  international_short: 0.35
  international_long: 0.35
  cargo: 0.08
  charter: 0.02

airlines:
  - code: "BA"
    name: "British Airways"
    market_share: 0.45
    hub_terminal: "E"
```

### Small regional airport — single terminal, one runway

A small regional airport with limited infrastructure but high domestic traffic.

```yaml
identity:
  name: "Regional City Airport"
  iata: "RCA"
  icao: "KRCA"
  timezone: "America/Chicago"

infrastructure:
  terminals: 1
  gates_per_terminal: [8]
  runways:
    - id: "18/36"
      length_m: 2500
      ils: false

simulation:
  daily_flight_target: 80
  load_factor_mean: 0.72
  peak_hours: [7, 8, 17, 18]
  hourly_weights:
    6: 6
    7: 16
    8: 18
    9: 10
    10: 6
    11: 4
    12: 4
    13: 4
    14: 6
    15: 8
    16: 12
    17: 18
    18: 14
    19: 8
    20: 4

flight_types:
  domestic: 0.75
  international_short: 0.15
  international_long: 0.00
  cargo: 0.05
  charter: 0.05
```

---

## Config resolution order

The sim-orchestrator looks for the config file in this order:

1. `AIRPORT_CONFIG_PATH` environment variable (if set)
2. `config/airport.yaml` relative to the repository root
3. `/app/config/airport.yaml` inside the Docker container

In docker-compose, the sim-orchestrator mounts `./config` to `/app/config`.

If no config file is found, the simulation uses built-in defaults (Arthur
International Airport with 3 terminals, 42 gates, 2 runways, 420 flights/day).

---

## Validation

Always validate before running to catch configuration errors early:

```bash
# Validate and show normalized output
python scripts/helper_validate_airport_config.py --path config/airport.yaml

# Expected output:
# ✔ Config loaded from config/airport.yaml
# ✔ Identity: Arthur International Airport (ART / KART)
# ✔ Infrastructure: 3 terminals, 42 gates, 2 runway pairs
# ✔ Simulation: 420 flights/day, load factor 0.80
# ✔ Flight types sum: 1.00

# JSON output for programmatic use
python scripts/helper_validate_airport_config.py --path config/airport.yaml --json
```

Common validation errors:

- `gates_per_terminal length must match terminals` — ensure the list has exactly as many entries as `terminals`
- `flight_types weights must sum to ~1.0` — ensure the five type percentages add up to 1.0 (±0.01)
- `peak_hours contains invalid values` — all hours must be 0–23

---

## Verify runtime behaviour

After starting the stack:

```bash
# Check sim status shows your airport
curl http://localhost:8006/api/v1/sim/status | python3 -m json.tool

# Check METAR uses your ICAO code
curl http://localhost:8004/api/v1/weather/metar

# Check flight count matches your target
curl http://localhost:8001/api/v1/flights | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(f'Flights: {len(d)}')"
```

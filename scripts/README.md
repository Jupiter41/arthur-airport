# Scripts

Helper scripts for operating and testing the Arthur Airport digital twin.

Related documentation:

- [README.md](../README.md)
- [TIMELINE.md](../TIMELINE.md)
- [ROADMAP.md](../ROADMAP.md)
- [services/sim-orchestrator/README.md](../services/sim-orchestrator/README.md)

---

## scenario-runner.sh

CLI wrapper for the scenario engine REST API. Requires `curl` and `python3`.

The scenario engine and lifecycle UX were expanded in Sprint 11 and Sprint 12:

- [docs/lessons-learned/sprint-11-scenario-engine.md](../docs/lessons-learned/sprint-11-scenario-engine.md)
- [docs/lessons-learned/sprint-12-scenarios-page-lifecycle.md](../docs/lessons-learned/sprint-12-scenarios-page-lifecycle.md)

### Usage

```bash
# List all available scenarios
./scripts/scenario-runner.sh list

# Show a specific scenario definition
./scripts/scenario-runner.sh show "Cascade recovery"

# Run a scenario (default speed: 600x)
./scripts/scenario-runner.sh run "Cascade recovery"

# Run at a specific speed
./scripts/scenario-runner.sh run "Runway incursion during peak hour" --speed 3600

# Check active scenario status
./scripts/scenario-runner.sh active

# Stop an active scenario
./scripts/scenario-runner.sh stop

# List past results
./scripts/scenario-runner.sh results

# Get detailed result for a specific run
./scripts/scenario-runner.sh result <run_id>
```

### Environment

| Variable  | Default                 | Description                      |
| --------- | ----------------------- | -------------------------------- |
| `SIM_URL` | `http://localhost:8006` | Base URL of the sim-orchestrator |

### Prerequisites

- The full stack or at minimum `neo4j`, `kafka`, and `sim-orchestrator` must be running
- `curl` and `python3` must be available on PATH

---

## smoke-test.sh

Quick health check for all services. Verifies each service responds to `/health`.

```bash
./scripts/smoke-test.sh
```

---

## lint-augmented-assign.py

Python linter checking for augmented assignment patterns in Cypher queries.

```bash
python3 scripts/lint-augmented-assign.py
```

---

## lint-cypher.py

Validates Cypher query strings embedded in Python source files.

```bash
python3 scripts/lint-cypher.py
```

---

## helper_validate_airport_config.py

Validates `config/airport.yaml` and prints normalized runtime values used by `sim-orchestrator`.

```bash
# Validate default config (config/airport.yaml)
python scripts/helper_validate_airport_config.py

# Validate a specific file
python scripts/helper_validate_airport_config.py --path config/airport.yaml

# Print normalized data as JSON (for scripts/automation)
python scripts/helper_validate_airport_config.py --json

# Example output
$ python scripts/helper_validate_airport_config.py --path config/airport.yaml

Airport config is valid.
Name: Arthur International Airport
Codes: ART/KART
Terminals: 3 (A, B, C)
Total gates: 42
Runways: 2 pairs (09L/27R, 09R/27L)
Daily flights: 420
Load factor: 0.80
Peak hours: [7, 8, 9, 17, 18, 19]
Airlines: 1 configured
```

### Before running docker compose

Always validate your config before running `docker compose up --build`. This catches YAML syntax errors and constraint violations early:

```bash
python scripts/helper_validate_airport_config.py --path config/airport.yaml
# Exit status 0 = valid ✅
# Exit status 1 = invalid (see error message above) ❌
```

---

## helper_generate_destination_coordinates.py

Generates the dashboard destination airport coordinate lookup from `data/ourairports/airports.csv`.

Output:

- `dashboards/art-dashboard/src/data/destinationCoordinates.ts`

```bash
# Generate with defaults
python scripts/helper_generate_destination_coordinates.py

# Use custom paths
python scripts/helper_generate_destination_coordinates.py \
	--airports-csv data/ourairports/airports.csv \
	--output dashboards/art-dashboard/src/data/destinationCoordinates.ts
```

---

## helper_generate_destinations.py

Generates real-world destinations fixture from OurAirports airport data. Replaces fictional
destinations with real IATA codes, names, coordinates, and distance-based weights.

Output:

- `services/sim-orchestrator/fixtures/destinations.json`

```bash
# Generate 80 destinations (default)
python scripts/helper_generate_destinations.py

# Generate a different count
python scripts/helper_generate_destinations.py --count 60

# Custom paths
python scripts/helper_generate_destinations.py \
	--airports-csv data/ourairports/airports.csv \
	--count 80 \
	--output services/sim-orchestrator/fixtures/destinations.json
```

Selection criteria:

- Large + medium airports with IATA codes within 200–12,000 km of KART
- Distance-based classification: <1,500 km → domestic, 1,500–4,000 km → short-haul, >4,000 km → long-haul
- Major hub airports (LHR, JFK, CDG, etc.) always included
- Geographic diversity: one airport per country first, then top-weighted fill

---

## helper_generate_airlines.py

Generates real-world airlines fixture from OpenFlights data. Uses a hand-picked list of
15 airlines suited for a mid-Atlantic hub, with fleet data from real route equipment.

Output:

- `services/sim-orchestrator/fixtures/airlines.json`

```bash
# Generate with defaults (15 airlines)
python scripts/helper_generate_airlines.py

# Custom count
python scripts/helper_generate_airlines.py --count 20

# Custom paths
python scripts/helper_generate_airlines.py \
	--airlines-dat data/openflights/airlines.dat \
	--routes-dat data/openflights/routes.dat \
	--output services/sim-orchestrator/fixtures/airlines.json
```

Airlines are selected from:

- European flag carriers (BA, AF, LH, IB, KL, TP)
- Low-cost (FR, U2)
- North American (AA, UA, DL)
- Long-haul (EK, ET, LA)
- Regional (S4 — SATA International, Azores-based)

---

## helper_test_speed_modes.sh

Manual test script for verifying the three simulation speed modes (REALTIME, FAST, BULK).
Switches between 60×, 600×, and 3600× and checks that the mode field in `/sim/status`
transitions correctly.

```bash
./scripts/helper_test_speed_modes.sh
```

Related:

- [docs/lessons-learned/sprint-15-high-speed-simulation-modes.md](../docs/lessons-learned/sprint-15-high-speed-simulation-modes.md)
- [PLAN-HIGH-SPEED.md](../PLAN-HIGH-SPEED.md)

---

## helper_test_debug_endpoints.sh

End-to-end test of all debug injection endpoints in the sim-orchestrator.
Tests flight injection, passenger injection, baggage injection, Cypher console,
entity inspector, snapshot create/list, and ADS-B states.

```bash
./scripts/helper_test_debug_endpoints.sh
```

Requires: `curl`, `python3`, and all services running via `docker compose up`.

---

## helper_validate_schedule_distribution.py

Standalone validation of the flight schedule departure slot distribution.
Generates 210 departure slots using the same hourly weight algorithm as `sim-orchestrator`
and prints an hourly histogram with validation checks.

```bash
python3 scripts/helper_validate_schedule_distribution.py
```

Checks verified:

- Total slot count equals 210
- Morning peak (07–09) > 30 flights
- Evening peak (17–19) > 30 flights
- No flights before 05:00 or after 23:00
- Mid-day (10–16) between 60 and 120 flights
- All slots are 5-minute aligned

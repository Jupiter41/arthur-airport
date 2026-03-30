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

# Scripts

Helper scripts for operating and testing the Arthur Airport digital twin.

---

## scenario-runner.sh

CLI wrapper for the scenario engine REST API. Requires `curl` and `python3`.

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

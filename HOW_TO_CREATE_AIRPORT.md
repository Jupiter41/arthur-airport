# HOW-TO — Create Your Own Airport

This project now supports a config-driven airport setup through one file:

- config/airport.yaml

## 1. Validate your config first

Run:

```bash
python scripts/helper_validate_airport_config.py --path config/airport.yaml
```

JSON preview:

```bash
python scripts/helper_validate_airport_config.py --path config/airport.yaml --json
```

## 2. Configure airport identity

Edit:

```yaml
identity:
  name: "Heathrow International Airport"
  iata: "LHR"
  icao: "EGLL"
  timezone: "Europe/London"
```

## 3. Configure infrastructure

```yaml
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
```

Notes:
- terminals must match the number of values in gates_per_terminal.
- Each runway pair id may contain one direction ("09L") or two directions ("09L/27R").

## 4. Configure simulation defaults

```yaml
simulation:
  daily_flight_target: 1300
  load_factor_mean: 0.88
  peak_hours: [6, 7, 8, 17, 18, 19, 20]
```

These values are used by sim-orchestrator at startup:
- daily_flight_target controls generated flight volume.
- load_factor_mean drives Beta distribution parameters for passenger generation.
- peak_hours affects probabilistic incident injection multipliers.

## 5. Optional airline overrides

```yaml
airlines:
  - code: "BA"
    name: "British Artex Airways"
    market_share: 0.45
    hub_terminal: "A"
```

Overrides update fixture airlines by code and normalize market shares.

## 6. Run the stack

```bash
docker compose up --build
```

The sim-orchestrator reads config/airport.yaml from:
- AIRPORT_CONFIG_PATH if provided
- config/airport.yaml in repo root
- /app/config/airport.yaml in container

In docker-compose, sim-orchestrator mounts ./config to /app/config.

## 7. Verify runtime behavior

```bash
curl http://localhost:8006/api/v1/sim/status
curl http://localhost:3000/api/v1/airport -H "Authorization: Bearer <token>"
curl http://localhost:8004/api/v1/weather/metar
```

Expected:
- sim status and gateway aggregate expose your airport identity.
- seeded flights use your configured home IATA as origin/destination home code.
- METAR/TAF station code follows the active airport ICAO.

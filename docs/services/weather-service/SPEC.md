# weather-service — specification

**Language:** Python 3.11+  
**Framework:** FastAPI  
**Port:** 8004  
**Responsibility:** Runs the airport weather state machine, generates realistic METAR-format weather reports, computes runway capacity impacts, and broadcasts weather changes to all consuming services.

---

## 1. Domain responsibilities

- Own and advance the weather FSM (CAVOK → VMC → IMC → LIFR and back)
- Generate synthetic METAR strings on each weather state change
- Compute runway capacity recommendations based on current conditions
- Produce `WeatherStateChanged` and `METARIssued` events to Kafka
- Maintain a rolling history of weather states (last 48 simulated hours)
- Expose REST endpoints for current conditions, forecast, and history
- Provide a METAR/TAF text feed for display in dashboards

---

## 2. Weather state machine

See `SIMULATION.md` for the full transition matrix. This service implements and owns that FSM.

### FSM evaluation

On each `SimClockTick` that crosses an hour boundary (simulated), the service evaluates a state transition:

```python
def evaluate_transition(current: WeatherCategory, sim_hour: int) -> WeatherCategory:
    row = TRANSITION_MATRIX[current]
    return random.choices(list(row.keys()), weights=list(row.values()))[0]
```

Transitions that jump more than one severity level (e.g. `LIFR` → `CAVOK`) are rejected and re-sampled.

### Parameter generation

After any state change, new meteorological parameters are sampled (see `SIMULATION.md §4` for the full sampling spec). The service then:

1. Persists the new `WeatherState` node to Neo4j
2. Links it to the previous node via `PREVIOUS_WEATHER`
3. Updates the `Airport`->`CURRENT_WEATHER` pointer
4. Emits `WeatherStateChanged` to `weather.events`
5. Emits `METARIssued` with a formatted METAR string

---

## 3. METAR generation

The service generates a valid METAR-format string from the current weather parameters.

### Format

```
KART {day}{hour}{minute}Z {wind_direction}{wind_speed}[G{gust}]KT
{visibility} {phenomena} {cloud_layers} {temp}/{dewpoint} Q{qnh}
```

### Example outputs

```
KART 151428Z 27028G42KT 8000 TS RA BKN015 OVC050 04/02 Q1002
KART 150600Z 09005KT CAVOK 18/12 Q1018
KART 151905Z 18015KT 3000 -RA OVC010 08/06 Q0998
KART 152210Z 24045G60KT 0200 +BLSN VV002 M02/M05 Q0982
```

Cloud layer codes are generated from ceiling height:
- `FEW` (1–2 oktas), `SCT` (3–4 oktas), `BKN` (5–7 oktas), `OVC` (8 oktas)
- Layer heights are rounded to the nearest 100 ft below 10,000 ft

### TAF generation (simplified)

A 6-hour TAF is generated on each hour boundary based on the current state and the next expected transitions:

```
TAF KART {issue_time}Z {valid_from}/{valid_to}
    {wind} {visibility} {phenomena} {cloud}
    TEMPO {from}/{to} {degraded_conditions}
    BECMG {from}/{to} {improved_conditions}
```

---

## 4. Runway capacity output

On each `WeatherStateChanged`, the service computes and includes runway capacity recommendations in the event payload:

| Category | Arrival rate (mvts/hr) | Departure rate | Config |
|---|---|---|---|
| `CAVOK` | 32 | 32 | independent parallel |
| `VMC` | 28 | 28 | independent parallel |
| `IMC` | 18 | 16 | dependent: ILS 09L only |
| `LIFR` | 8 | 6 | CAT III ILS 09L only |

Wind-specific reductions:
- Crosswind > 25 kt: rate × 0.85
- Crosswind > 35 kt: rate × 0.60 (single runway ops)
- Tailwind > 10 kt: rate × 0.70 (runway direction change required)

---

## 5. Kafka

### Consumed topics

| Topic | Event type | Action |
|---|---|---|
| `sim.clock` | `SimClockTick` | Evaluate hourly FSM transition; update METAR |

### Produced topics

| Topic | Event type | Trigger |
|---|---|---|
| `weather.events` | `WeatherStateChanged` | FSM state transition |
| `weather.events` | `METARIssued` | Every simulated 30 minutes |

---

## 6. REST API

Base path: `/api/v1`

#### `GET /weather/current`
Current weather conditions at KART.

Response `200`:
```json
{
  "id": "uuid",
  "sim_time": "2024-06-15T14:28:00Z",
  "category": "IMC",
  "visibility_m": 2800,
  "wind_direction": 270,
  "wind_speed_kt": 28,
  "wind_gust_kt": 42,
  "ceiling_ft": 900,
  "temperature_c": 4.2,
  "dew_point_c": 2.1,
  "qnh_hpa": 1002,
  "phenomena": ["TS", "RA"],
  "runway_impact": {
    "category": "reduced_rate",
    "arrival_rate": 18,
    "departure_rate": 16,
    "active_runway": "09L",
    "ils_required": true
  },
  "metar_raw": "KART 151428Z 27028G42KT 2800 TS RA BKN009 OVC050 04/02 Q1002"
}
```

---

#### `GET /weather/metar`
Latest METAR string (plain text, for display widgets).

Response `200 text/plain`:
```
KART 151428Z 27028G42KT 2800 TS RA BKN009 OVC050 04/02 Q1002
```

---

#### `GET /weather/taf`
Current TAF (plain text).

Response `200 text/plain`:
```
TAF KART 151400Z 1514/1520 27025G35KT 3000 RA BKN015
    TEMPO 1515/1517 27042G55KT 0800 +TSRA BKN008 OVC020
    BECMG 1518/1520 27015KT 6000 -RA FEW025
```

---

#### `GET /weather/history`
Rolling weather history.

Query parameters:

| Parameter | Type | Description |
|---|---|---|
| `hours` | integer | Lookback window in simulated hours (default: 12, max: 48) |

Response `200`:
```json
{
  "from": "2024-06-15T02:00:00Z",
  "to":   "2024-06-15T14:28:00Z",
  "states": [
    {
      "category": "CAVOK",
      "from": "2024-06-15T02:00:00Z",
      "to":   "2024-06-15T08:00:00Z",
      "duration_minutes": 360
    },
    {
      "category": "VMC",
      "from": "2024-06-15T08:00:00Z",
      "to":   "2024-06-15T11:00:00Z",
      "duration_minutes": 180
    },
    {
      "category": "IMC",
      "from": "2024-06-15T11:00:00Z",
      "to":   "2024-06-15T14:28:00Z",
      "duration_minutes": 208
    }
  ]
}
```

---

#### `GET /weather/impact`
Current operational impact summary for the flight operations dashboard.

Response `200`:
```json
{
  "category": "IMC",
  "severity": "moderate",
  "summary": "Instrument conditions. Reduced arrival rate. ILS runway 09L only.",
  "arrival_rate": 18,
  "departure_rate": 16,
  "holding_stack_depth": 4,
  "delayed_by_weather": 12,
  "cancelled_by_weather": 0,
  "crosswind_kt": 28,
  "crosswind_limit_kt": 35,
  "operations_normal": false
}
```

---

### WebSocket

#### `WS /ws/weather`
Streams `WeatherStateChanged` and `METARIssued` events. Useful for the flight board and ground ops dashboards.

---

## 7. Configuration

| Env variable | Default | Description |
|---|---|---|
| `NEO4J_URI` | `bolt://neo4j:7687` | |
| `NEO4J_USER` | `neo4j` | |
| `NEO4J_PASSWORD` | `art-digital-twin` | |
| `KAFKA_BROKERS` | `kafka:9092` | |
| `METAR_INTERVAL_SIM_MINUTES` | `30` | How often to emit a new METAR |
| `INITIAL_WEATHER_CATEGORY` | `CAVOK` | Starting state at sim day 1 |
| `LOG_LEVEL` | `INFO` | |

---

## 8. Health & observability

### Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness |
| `GET /ready` | Readiness |
| `GET /metrics` | Prometheus |

### Key Prometheus metrics

| Metric | Type | Description |
|---|---|---|
| `weather_category` | Gauge | Current category encoded as int (0=CAVOK, 1=VMC, 2=IMC, 3=LIFR) |
| `weather_state_transitions_total` | Counter | Transitions labelled by `from`, `to` |
| `runway_arrival_rate` | Gauge | Current capacity (movements/hr) |
| `runway_departure_rate` | Gauge | Current departure capacity |
| `holding_stack_depth` | Gauge | Arrivals currently in holding |
| `flights_delayed_by_weather_total` | Counter | Cumulative weather-caused delays |
| `wind_speed_kt` | Gauge | Current wind speed |
| `visibility_m` | Gauge | Current visibility |

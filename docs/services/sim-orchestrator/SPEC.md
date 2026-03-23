# sim-orchestrator — specification

**Language:** Python 3.11+  
**Framework:** FastAPI (control API) + asyncio (simulation loop)  
**Port:** 8006  
**Responsibility:** Drives the simulation clock, seeds all initial data, coordinates day boundaries, and injects probabilistic events. The conductor of the entire digital twin.

---

## 1. Domain responsibilities

- Maintain and broadcast the virtual simulation clock via `sim.clock`
- Seed flight schedules, passenger manifests, and baggage records at startup and each day boundary
- Coordinate probabilistic event injection timing (delegating actual creation to incident-service)
- Expose a control API for operators to pause, resume, reset, and tune the simulation
- Provide a simulation health dashboard endpoint

---

## 2. Simulation loop

The orchestrator runs a single async loop with the following rhythm:

```
while sim_running:
    advance sim_time by 1 sim-minute
    emit SimClockTick to sim.clock
    
    if crossed hour boundary:
        evaluate probabilistic event injection
        
    if crossed day boundary:
        seed next day's schedule
        
    sleep(real_seconds_per_sim_minute)
```

Where:
```
real_seconds_per_sim_minute = 60 / speed_multiplier
```

At the default speed of 60×, this is 1 real second per simulated minute, meaning one simulated hour passes every real minute.

---

## 3. Startup sequence

On first startup (or after a reset), the orchestrator executes the following sequence before starting the simulation loop:

```
1. Wait for Neo4j to be ready (health check with exponential backoff, max 60s)
2. Wait for Kafka to be ready
3. Check if airport graph exists in Neo4j
   → if not: seed airport structure (Airport, Terminals, Gates, Runways)
4. Set sim_time = Day 1, 06:00
5. Seed Day 1 flight schedule (emit to flights.schedule)
6. Generate passengers and baggage for all Day 1 flights (write directly to Neo4j)
7. Set initial weather state = CAVOK (emit WeatherStateChanged)
8. Start simulation loop
```

### Airport structure seed

Run once. Creates the following Neo4j nodes:
- 1 `Airport` node (KART)
- 3 `Terminal` nodes (A, B, C)
- 42 `Gate` nodes (A01–A14, B01–B14, C01–C14)
- 2 `Runway` nodes (09L/27R and 09R/27L as paired entries: 4 runway direction nodes total)

---

## 4. Schedule generation

See `SIMULATION.md §3` for the full algorithm. The orchestrator:

1. Loads fixtures from `fixtures/` at startup
2. Runs the schedule generation algorithm
3. Writes all `Flight` nodes directly to Neo4j
4. Writes all `Passenger` and `Baggage` nodes to Neo4j
5. Emits a single `FlightScheduleSeeded` batch event to `flights.schedule`

Day N+1 schedule is generated at `23:30 sim time` on day N, so flight-service always has the next day's flights loaded before midnight.

---

## 5. Probabilistic event injection

On each simulated hour boundary, the orchestrator evaluates event injection:

```python
async def evaluate_probabilistic_events(sim_time: datetime, context: SimContext):
    modifiers = compute_modifiers(sim_time, context)
    
    for event_type, base_prob in BASE_PROBABILITIES.items():
        effective_prob = base_prob * modifiers.get(event_type, 1.0)
        
        # Apply suppression window
        if context.recent_incident_within_hours(event_type, hours=2):
            effective_prob *= SUPPRESSION_FACTOR  # 0.3
        
        if random.random() < effective_prob:
            await inject_event(event_type, context)
```

When an injection is decided, the orchestrator emits an `InjectIncident` event to `incidents.inject`. The incident-service owns actual incident creation — the orchestrator only fires the trigger.

---

## 6. REST API

Base path: `/api/v1`

#### `GET /sim/status`
Full current simulation status.

Response `200`:
```json
{
  "running": true,
  "paused": false,
  "sim_time": "2024-06-15T14:32:00Z",
  "real_time": "2024-06-15T10:15:03Z",
  "speed_multiplier": 60,
  "day_number": 1,
  "tick_number": 512,
  "real_elapsed_seconds": 512,
  "sim_elapsed_minutes": 512,
  "active_incidents": 1,
  "weather_category": "IMC",
  "flights_today": 210,
  "passengers_today": 29840
}
```

---

#### `PATCH /sim/speed`
Change simulation speed.

Request body:
```json
{ "speed_multiplier": 600 }
```

Valid values: `1`, `10`, `60`, `600`, `3600`

Response `200`: updated status.

---

#### `POST /sim/pause`
Pause the simulation clock. All services stop advancing state.

Response `200`: `{ "paused": true, "sim_time": "..." }`

---

#### `POST /sim/resume`
Resume after pause.

Response `200`: `{ "paused": false, "sim_time": "..." }`

---

#### `POST /sim/reset`
Full reset: wipe all data from Neo4j, reset sim_time to Day 1 06:00, reseed everything.

Request body:
```json
{ "confirm": true }
```

Response `200`: `{ "reset": true, "new_sim_time": "2024-06-15T06:00:00Z" }`

> ⚠ This is destructive. All Neo4j data and Kafka offsets are wiped. The `confirm: true` field is required.

---

#### `POST /sim/inject`
Manually inject a hazardous incident. Proxied to `incidents.inject` topic.

Request body:
```json
{
  "type": "runway_incursion",
  "severity": "critical",
  "location": "runway-09L",
  "description": "Optional override description."
}
```

Response `201`:
```json
{ "injected": true, "type": "runway_incursion", "sim_time": "..." }
```

---

#### `GET /sim/schedule`
Current day's flight schedule.

Query parameters: `terminal`, `direction`, `status`

Response `200`:
```json
{
  "sim_day": 1,
  "sim_date": "2024-06-15",
  "total_flights": 420,
  "flights": [ ... ]
}
```

---

#### `GET /sim/metrics`
Simulation performance metrics.

Response `200`:
```json
{
  "tick_latency_ms_avg": 12,
  "tick_latency_ms_p99": 45,
  "kafka_produce_lag_ms": 3,
  "neo4j_write_latency_ms_avg": 8,
  "events_produced_total": 14823,
  "missed_ticks": 0,
  "sim_time_drift_ms": 0
}
```

---

## 7. Configuration

| Env variable | Default | Description |
|---|---|---|
| `NEO4J_URI` | `bolt://neo4j:7687` | |
| `NEO4J_USER` | `neo4j` | |
| `NEO4J_PASSWORD` | `art-digital-twin` | |
| `KAFKA_BROKERS` | `kafka:9092` | |
| `SIM_SPEED_MULTIPLIER` | `60` | Initial speed |
| `SIM_START_TIME` | `2024-06-15T06:00:00Z` | Simulation epoch |
| `FIXTURES_PATH` | `/app/fixtures` | Seed data directory |
| `DAILY_FLIGHT_TARGET` | `420` | Target daily movements |
| `DAILY_LOAD_FACTOR_MEAN` | `0.80` | Mean pax load factor |
| `SUPPRESSION_FACTOR` | `0.3` | Post-incident probability multiplier |
| `LOG_LEVEL` | `INFO` | |

---

## 8. Health & observability

### Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness |
| `GET /ready` | Readiness: Neo4j + Kafka + all services reachable |
| `GET /metrics` | Prometheus |

### Key Prometheus metrics

| Metric | Type | Description |
|---|---|---|
| `sim_tick_total` | Counter | Total clock ticks emitted |
| `sim_tick_latency_ms` | Histogram | Real time per tick |
| `sim_speed_multiplier` | Gauge | Current speed setting |
| `sim_day_number` | Gauge | Current simulated day |
| `sim_events_injected_total` | Counter | Probabilistic events fired by type |
| `sim_schedule_seeds_total` | Counter | Day schedules seeded |

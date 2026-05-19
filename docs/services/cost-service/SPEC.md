# ROADMAP — Cost model

## Arthur International Airport Digital Twin

Adding a full financial layer to the twin: from raw cost accumulation to prescriptive
financial recommendations. Every task is scoped for a single agent session.

Before starting any task, the agent must read:

- `CLAUDE.md`
- `docs/architecture/OVERVIEW.md`
- `docs/architecture/DATA_MODEL.md`
- `docs/architecture/EVENT_BUS.md`
- The relevant `SPEC.md` and `SKILL.md` for each service touched

---

## Overview

```
Phase 1  Cost data model & constants          → Neo4j schema + reference tables
Phase 2  Cost service                         → new microservice, Kafka consumer
Phase 3  Per-category cost engines            → 6 cost calculators
Phase 4  Revenue model                        → 5 revenue streams
Phase 5  Neo4j cost graph & queries           → cost records linked to entities
Phase 6  REST API & WebSocket                 → expose cost data to the gateway
Phase 7  Cost dashboard                       → new React page /cost
Phase 8  Prescriptive financial layer         → cost-aware recommendations
Phase 9  Real data calibration                → replace synthetic rates with real sources
```

---

## Phase 1 — Cost data model & constants

### Task 1.1 — Cost reference tables (fixtures)

**File to create:** `services/sim-orchestrator/fixtures/cost_rates.json`

Create a JSON fixture containing all configurable cost parameters.
The file must be structured so every rate can be overridden at runtime via the
settings UI without restarting the service. Include:

**Aircraft MTOW table (kg):**

```json
{
  "mtow_kg": {
    "B738": 79016,
    "A320": 78000,
    "A321": 93500,
    "B77W": 352400,
    "A333": 230000,
    "A332": 242000,
    "E195": 52290,
    "DH8D": 29257,
    "AT75": 22800
  }
}
```

**Airport fees:**

```json
{
  "airport_fees": {
    "landing_rate_per_tonne_eur": 12.0,
    "gate_rate_per_hour_eur": 150.0,
    "passenger_departure_fee_eur": 12.0,
    "cargo_rate_per_kg_eur": 0.25
  }
}
```

**EU Regulation 261/2004 compensation tiers:**

```json
{
  "eu261": [
    {
      "min_delay_minutes": 120,
      "max_distance_km": 99999,
      "assistance_only": true
    },
    {
      "min_delay_minutes": 180,
      "max_distance_km": 1500,
      "compensation_eur": 250
    },
    {
      "min_delay_minutes": 180,
      "max_distance_km": 3500,
      "compensation_eur": 400
    },
    {
      "min_delay_minutes": 180,
      "max_distance_km": 99999,
      "compensation_eur": 600
    },
    {
      "min_delay_minutes": 240,
      "max_distance_km": 3500,
      "compensation_eur": 400
    },
    {
      "min_delay_minutes": 240,
      "max_distance_km": 99999,
      "compensation_eur": 600
    }
  ]
}
```

**Delay costs (Eurocontrol Standard Inputs methodology):**

```json
{
  "delay_costs": {
    "crew_overtime_per_member_per_hour_eur": 200.0,
    "crew_counts": {
      "narrow": 6,
      "wide": 10,
      "regional": 4
    },
    "fuel_price_per_kg_eur": 0.9,
    "holding_burn_kg_per_hour": {
      "narrow": 2400,
      "wide": 6000,
      "regional": 800
    }
  }
}
```

**Ground handling rates (per operation/per turnaround):**

```json
{
  "ground_handling": {
    "pushback_eur": 350,
    "catering_narrow_eur": 1500,
    "catering_wide_eur": 5000,
    "stairs_eur": 200,
    "jetbridge_eur": 300,
    "cleaning_narrow_eur": 600,
    "cleaning_wide_eur": 1200,
    "baggage_loader_per_bag_eur": 3.5
  }
}
```

**Incident base costs:**

```json
{
  "incident_costs": {
    "runway_incursion": { "direct_eur": 25000, "response_eur": 15000 },
    "baggage_fire": { "direct_eur": 40000, "response_eur": 20000 },
    "security_breach": { "direct_eur": 80000, "response_eur": 30000 },
    "system_failure": { "direct_eur": 8000, "response_eur": 2000 },
    "severe_weather": { "direct_eur": 0, "response_eur": 5000 }
  }
}
```

**Staffing costs:**

```json
{
  "staffing": {
    "security_officer_per_hour_eur": 35.0,
    "checkin_agent_per_hour_eur": 28.0,
    "gate_agent_per_hour_eur": 28.0,
    "ground_crew_per_hour_eur": 25.0
  }
}
```

**Revenue rates:**

```json
{
  "revenue": {
    "retail_spend_per_pax_per_hour_airside_eur": 12.0,
    "parking_per_vehicle_per_day_eur": 25.0,
    "slot_fee_eur": 2000.0
  }
}
```

**Verification:** load the JSON with `json.loads()` and assert all keys exist.

---

### Task 1.2 — Cost Neo4j schema

**Files to create/edit:**

- `services/cost-service/db/neo4j.py` (new service, create full file)
- `docs/architecture/DATA_MODEL.md` (append new node definitions)

Add the following Neo4j node and relationship definitions.

**`CostRecord` node** — one record per cost event:

| Property      | Type          | Description                                                                                                                                                                        |
| ------------- | ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`          | String (UUID) | unique                                                                                                                                                                             |
| `category`    | Enum          | `landing_fee`, `gate_fee`, `passenger_fee`, `eu261_compensation`, `crew_overtime`, `holding_fuel`, `ground_handling`, `incident_direct`, `incident_response`, `staffing`, `energy` |
| `amount_eur`  | Float         | cost amount (positive = cost, negative = revenue)                                                                                                                                  |
| `currency`    | String        | `"EUR"`                                                                                                                                                                            |
| `sim_time`    | String (ISO)  | when the cost was incurred                                                                                                                                                         |
| `sim_day`     | Integer       | day number in simulation                                                                                                                                                           |
| `description` | String        | human-readable label                                                                                                                                                               |
| `is_revenue`  | Boolean       | true if this is a revenue record                                                                                                                                                   |

**Relationships:**

```cypher
(CostRecord)-[:FOR_FLIGHT]->(Flight)      // cost linked to a specific flight
(CostRecord)-[:FOR_TERMINAL]->(Terminal)  // cost linked to a terminal
(CostRecord)-[:CAUSED_BY]->(Incident)    // cost caused by an incident
(CostRecord)-[:FOR_DAY {day: int}]->(Airport) // daily rollup
```

**Constraints and indexes:**

```cypher
CREATE CONSTRAINT cost_record_id IF NOT EXISTS
  FOR (c:CostRecord) REQUIRE c.id IS UNIQUE;
CREATE INDEX cost_record_category IF NOT EXISTS
  FOR (c:CostRecord) ON (c.category);
CREATE INDEX cost_record_sim_day IF NOT EXISTS
  FOR (c:CostRecord) ON (c.sim_day);
```

**Verification:** run `MATCH (c:CostRecord) RETURN count(c)` after a 5-minute sim run.
Expected: > 0.

---

## Phase 2 — Cost service scaffold

### Task 2.1 — Create the cost-service microservice

**Files to create:**

```
services/cost-service/
├── main.py
├── requirements.txt
├── Dockerfile
├── db/
│   └── neo4j.py        (from Task 1.2)
├── kafka/
│   ├── consumer.py
│   └── producer.py
├── services/
│   ├── cost_engine.py  (Phase 3)
│   └── revenue_engine.py (Phase 4)
└── routers/
    └── costs.py        (Phase 6)
```

**`main.py`:** standard FastAPI app with lifespan pattern (see `docs/skills/python-service.SKILL.md`).

- Port: `8007`
- Exposes: `GET /health`, `GET /ready`, `GET /metrics`
- On startup: connect to Neo4j, connect to Kafka, create constraints/indexes, load `cost_rates.json`

**`requirements.txt`:**

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
pydantic>=2.7.0
neo4j>=5.20.0
confluent-kafka>=2.4.0
prometheus-fastapi-instrumentator>=6.1.0
python-dotenv>=1.0.0
```

**`Dockerfile`:** use the standard template from `docs/infra/DOCKER.md §4`.
Expose port 8007.

**`docker-compose.yml` additions:**

```yaml
cost-service:
  <<: *python-service
  build: ./services/cost-service
  ports:
    - "8007:8007"
  depends_on:
    neo4j:
      condition: service_healthy
    kafka:
      condition: service_healthy
    flight-service:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8007/health"]
    interval: 10s
    timeout: 5s
    retries: 5
```

**Verification:** `docker compose up cost-service` → `curl http://localhost:8007/health` returns `{"status":"ok"}`.

---

### Task 2.2 — Kafka consumer setup

**File:** `services/cost-service/kafka/consumer.py`

The cost service consumes five topics. It must **never produce state changes** —
it is read-only from a domain perspective. It only writes `CostRecord` nodes to Neo4j
and produces to `cost.events`.

Topics to subscribe:

```python
TOPICS = [
    "sim.clock",         # SimClockTick — for staffing/energy accumulation per tick
    "flights.events",    # FlightStatusChanged, FlightCancelled — trigger cost calculations
    "incidents.events",  # IncidentCreated, IncidentStatusChanged — incident costs
    "baggage.events",    # BaggageStatusChanged — per-bag handling costs
    "passengers.events", # PassengerStatusChanged — for dwell time revenue tracking
]
```

Dispatch map:

```python
async def dispatch(envelope: dict):
    match envelope["event_type"]:
        case "SimClockTick":
            await on_clock_tick(envelope["payload"], sim_time)
        case "FlightStatusChanged":
            await on_flight_status_changed(envelope["payload"], sim_time)
        case "FlightCancelled":
            await on_flight_cancelled(envelope["payload"], sim_time)
        case "IncidentCreated":
            await on_incident_created(envelope["payload"], sim_time)
        case "IncidentStatusChanged":
            await on_incident_resolved(envelope["payload"], sim_time)
        case "BaggageStatusChanged":
            await on_baggage_status_changed(envelope["payload"], sim_time)
        case "PassengerStatusChanged":
            await on_passenger_status_changed(envelope["payload"], sim_time)
        case _:
            pass
```

**Consumer group id:** `"cost-service"`

**Verification:** consume 10 messages from `flights.events` and log them without error.

---

### Task 2.3 — cost.events Kafka topic and producer

**File:** `services/cost-service/kafka/producer.py`

Add `cost.events` to the topic catalogue in `docs/architecture/EVENT_BUS.md`.

Event schema — `CostRecorded`:

```json
{
  "event_type": "CostRecorded",
  "payload": {
    "cost_record_id": "uuid",
    "category": "eu261_compensation",
    "amount_eur": 18600.0,
    "is_revenue": false,
    "flight_id": "uuid",
    "incident_id": "uuid",
    "description": "EU261 compensation — 847 pax × €600 (long-haul, delay 4h12m)",
    "sim_time": "2024-06-15T14:32:00Z",
    "sim_day": 1
  }
}
```

Also add `cost.events` consumer to the api-gateway so cost events are forwarded
to WebSocket clients that subscribe to `"costs"`.

---

## Phase 3 — Per-category cost engines

### Task 3.1 — Landing and airport fees engine

**File:** `services/cost-service/services/cost_engine.py`

Triggered by: `FlightStatusChanged` where `new_status == "at_gate"` (arrival landed and docked).

Implement these three functions:

```python
def compute_landing_fee(aircraft_type: str, rates: dict) -> float:
    """
    landing_fee = rate_per_tonne × (MTOW_kg / 1000)
    Source: Eurocontrol CRCO methodology, ACI Airport Charges Report
    """
    mtow = rates["mtow_kg"].get(aircraft_type, 78_000)
    rate = rates["airport_fees"]["landing_rate_per_tonne_eur"]
    return round(rate * (mtow / 1_000), 2)

def compute_passenger_fee(pax_count: int, rates: dict) -> float:
    """
    passenger_fee = pax_count × per_pax_fee
    Only for departing flights (arrivals do not pay departure fee)
    """
    return round(pax_count * rates["airport_fees"]["passenger_departure_fee_eur"], 2)

def compute_gate_fee(gate_occupancy_minutes: int, rates: dict) -> float:
    """
    gate_fee = (occupancy_minutes / 60) × hourly_rate
    Triggered when ASSIGNED_TO relationship is removed (flight departs gate)
    """
    hours = gate_occupancy_minutes / 60
    return round(hours * rates["airport_fees"]["gate_rate_per_hour_eur"], 2)
```

Write one `CostRecord` per fee type, all linked to the flight via `FOR_FLIGHT`.

**Verification:** after a 30-minute sim run at 60×, query:

```cypher
MATCH (c:CostRecord)
WHERE c.category IN ['landing_fee', 'gate_fee', 'passenger_fee']
RETURN c.category, count(c), avg(c.amount_eur)
```

Expected: all three categories present with realistic average amounts.

---

### Task 3.2 — EU261 delay compensation engine

**File:** `services/cost-service/services/cost_engine.py` (add to existing file)

Triggered by: `FlightStatusChanged` where `new_status == "delayed"` AND `delay_minutes >= 180`,
OR `FlightCancelled`.

The cost service must fetch the flight's route distance from Neo4j to apply the correct
compensation tier. Distance is stored on the `Flight` node as `distance_km` (add this
field to the flight-service seeding if not already present — compute it from origin/destination
lat/lon using the haversine formula).

```python
def compute_eu261(delay_minutes: int, distance_km: float,
                   pax_count: int, rates: dict) -> tuple[float, str]:
    """
    Returns (compensation_eur, description)
    Source: EU Regulation 261/2004 — public law, no license required
    https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32004R0261
    """
    if delay_minutes < 180:
        return 0.0, "below EU261 threshold"

    for tier in sorted(rates["eu261"],
                        key=lambda t: t["min_delay_minutes"], reverse=True):
        if (delay_minutes >= tier["min_delay_minutes"] and
                distance_km <= tier["max_distance_km"] and
                not tier.get("assistance_only", False)):
            amount = tier["compensation_eur"] * pax_count
            desc = (f"EU261 — {pax_count} pax × €{tier['compensation_eur']} "
                    f"({distance_km:.0f} km, delay {delay_minutes}min)")
            return round(amount, 2), desc

    return 0.0, "EU261 not applicable"
```

Note: cancellations always trigger EU261 regardless of delay_minutes.
Write the record with `category = "eu261_compensation"`, linked to the flight.

**Verification:**

```cypher
MATCH (c:CostRecord {category: 'eu261_compensation'})
RETURN count(c) AS count, sum(c.amount_eur) AS total, avg(c.amount_eur) AS avg
```

Expected after 1 sim-day at 60×: at least 5–15 EU261 records (delays are common).

---

### Task 3.3 — Holding fuel cost engine

**File:** `services/cost-service/services/cost_engine.py`

Triggered by: `SimClockTick` — check all flights currently in `approach` status with
`holding_stack = true` (add this flag to flight-service if not present, or derive
from `runway_queue_depth > 0` AND `status == "approach"`).

```python
def compute_holding_cost_per_tick(aircraft_type: str,
                                   delta_minutes: int,
                                   rates: dict) -> float:
    """
    holding_cost = burn_rate_kg_per_min × delta_minutes × fuel_price_per_kg
    Source: Eurocontrol Standard Inputs for Cost-Benefit Analyses
    https://www.eurocontrol.int/publication/standard-inputs-eurocontrol-cost-benefit-analyses
    """
    family = ("wide" if aircraft_type in {"B77W", "A333", "A332", "A359"}
              else "regional" if aircraft_type in {"DH8D", "E195", "AT75"}
              else "narrow")
    burn_per_hour = rates["delay_costs"]["holding_burn_kg_per_hour"][family]
    burn_per_min  = burn_per_hour / 60
    price         = rates["delay_costs"]["fuel_price_per_kg_eur"]
    return round(burn_per_min * delta_minutes * price, 2)
```

Accumulate per tick rather than per event to avoid flooding Neo4j.
Batch holding cost records: write one `CostRecord` per flight per 5 sim-minutes
of holding (not per tick).

Also emit a `MinimumFuelWarning` passenger alert when `holding_minutes > 30`
(the flight service should already handle this — cost-service just tracks the cost).

**Verification:** inject a runway incursion incident, run for 30 sim-minutes.

```cypher
MATCH (c:CostRecord {category: 'holding_fuel'})
RETURN count(c), sum(c.amount_eur)
```

Expected: holding cost records present, amounts in €500–5,000 range per affected flight.

---

### Task 3.4 — Ground handling cost engine

**File:** `services/cost-service/services/cost_engine.py`

Triggered by: `turnaround.task.completed` events (from the turnaround task graph,
Phase 1.3 of ROADMAP2.md). If that topic is not yet implemented, subscribe to
`FlightStatusChanged` where `new_status == "at_gate"` and compute a bundled
ground handling cost from the aircraft type.

```python
def compute_ground_handling(aircraft_type: str,
                              bag_count: int,
                              rates: dict) -> dict[str, float]:
    """
    Returns itemised ground handling costs per turnaround.
    Source: IATA Ground Handling Agreement (SGHA) rate structures.
    Rates are synthetic but within published industry ranges.
    """
    r = rates["ground_handling"]
    is_wide = aircraft_type in {"B77W", "A333", "A332", "A359"}
    return {
        "pushback":        r["pushback_eur"],
        "catering":        r["catering_wide_eur"] if is_wide else r["catering_narrow_eur"],
        "cleaning":        r["cleaning_wide_eur"] if is_wide else r["cleaning_narrow_eur"],
        "jetbridge":       r["jetbridge_eur"],
        "baggage_loading": round(bag_count * r["baggage_loader_per_bag_eur"], 2),
    }
```

Write one `CostRecord` per line item, all linked to the flight.

**Verification:**

```cypher
MATCH (c:CostRecord)
WHERE c.category = 'ground_handling'
RETURN c.description, count(c), avg(c.amount_eur)
ORDER BY avg(c.amount_eur) DESC
```

---

### Task 3.5 — Incident cost engine

**File:** `services/cost-service/services/cost_engine.py`

Triggered by: `IncidentCreated` (direct costs fire immediately) and
`IncidentStatusChanged` (resolved) (response costs computed from TTR duration).

```python
def compute_incident_direct_cost(incident_type: str, rates: dict) -> float:
    return rates["incident_costs"][incident_type]["direct_eur"]

def compute_incident_response_cost(incident_type: str,
                                    ttr_minutes: int,
                                    rates: dict) -> float:
    base = rates["incident_costs"][incident_type]["response_eur"]
    # Response cost scales with duration: base covers first 30 min,
    # each additional 15 min adds 25% of base
    extra_periods = max(0, (ttr_minutes - 30) // 15)
    return round(base * (1 + extra_periods * 0.25), 2)
```

Write `CAUSED_BY` relationship to the Incident node.
Also sum the EU261 exposure across all flights affected by the incident
(query `(i:Incident)-[:AFFECTS]->(f:Flight)` and sum their individual EU261 records).

**Verification:** inject a `runway_incursion` incident, wait for resolution.

```cypher
MATCH (c:CostRecord)-[:CAUSED_BY]->(i:Incident {type: 'runway_incursion'})
RETURN c.category, c.amount_eur, c.description
```

---

### Task 3.6 — Staffing cost engine

**File:** `services/cost-service/services/cost_engine.py`

Triggered by: `SimClockTick` — accumulate staffing costs every simulated hour.

```python
def compute_staffing_cost_per_hour(security_lanes_open: dict,
                                    active_flights_boarding: int,
                                    checkin_desks_open: int,
                                    rates: dict) -> dict[str, float]:
    """
    Staffing cost = headcount × hourly_rate × delta_hours
    security_lanes_open: {"A": 4, "B": 3, "C": 4}
    """
    r = rates["staffing"]
    total_lanes = sum(security_lanes_open.values())
    return {
        "security":  total_lanes * r["security_officer_per_hour_eur"],
        "checkin":   checkin_desks_open * r["checkin_agent_per_hour_eur"],
        "gate":      active_flights_boarding * r["gate_agent_per_hour_eur"],
    }
```

The cost service must read current security lane counts from the passenger-service
state (available at `GET /api/v1/flow/summary`) or from a cached Kafka event.
Write one `CostRecord` per category per hour, linked to the terminal.

---

## Phase 4 — Revenue model

### Task 4.1 — Retail and F&B revenue engine

**File:** `services/cost-service/services/revenue_engine.py`

Triggered by: `SimClockTick` — accumulate retail revenue based on passengers
currently in `airside` status and their dwell time.

```python
def compute_retail_revenue_per_tick(airside_pax_count: int,
                                     delta_minutes: int,
                                     rates: dict) -> float:
    """
    retail_revenue = pax_airside × spend_per_pax_per_hour × (delta_min / 60)
    Insight: security delays INCREASE retail revenue (longer dwell time airside).
    Source: ACI World Airport Report — avg airside retail spend per pax.
    """
    hourly_rate = rates["revenue"]["retail_spend_per_pax_per_hour_airside_eur"]
    return round(airside_pax_count * hourly_rate * (delta_minutes / 60), 2)
```

Write with `is_revenue = True`. This creates the non-obvious insight: a security
queue delay that keeps passengers airside longer actually increases retail revenue.
The prescriptive engine should surface this tradeoff.

---

### Task 4.2 — Landing fee and passenger fee revenue

Landing fees and passenger fees (from Task 3.1) are costs _to the airline_ but
_revenue to the airport_. In the P&L view, they must appear on both sides.

Modify Task 3.1: when writing landing fees and passenger fees, create a second
`CostRecord` with `is_revenue = True` and `amount_eur` negated (negative cost =
revenue). Link this record `FOR_DAY` to the airport node.

This gives a complete P&L: sum all `CostRecord.amount_eur` where `is_revenue = False`
for costs, all where `is_revenue = True` for revenue.

---

### Task 4.3 — Slot and cargo revenue

**File:** `services/cost-service/services/revenue_engine.py`

- **Slot revenue:** emit one revenue record per departure (`FlightStatusChanged → departed`)
  where the flight was a Level 3 coordinated slot: `amount = rates["revenue"]["slot_fee_eur"]`
- **Cargo revenue:** for `FlightType == "cargo"`, compute `cargo_weight_kg × rate_per_kg`.
  Cargo weight = `seat_capacity × 0.7 × 100` kg (rough estimate if not explicitly modelled).

---

## Phase 5 — Neo4j cost graph & queries

### Task 5.1 — Cost aggregation queries

**File:** `services/cost-service/db/queries.py`

Implement these Cypher queries as Python functions. Each returns a structured dict.

```python
async def daily_pnl(sim_day: int) -> dict:
    """Full P&L for a given simulated day."""
    # MATCH (c:CostRecord {sim_day: $day})
    # RETURN c.is_revenue, c.category, sum(c.amount_eur) AS total
    # ORDER BY c.is_revenue, total DESC

async def flight_cost_breakdown(flight_id: str) -> dict:
    """All costs and revenues linked to a specific flight."""
    # MATCH (c:CostRecord)-[:FOR_FLIGHT]->(f:Flight {id: $fid})
    # RETURN c.category, c.amount_eur, c.description, c.is_revenue

async def incident_total_cost(incident_id: str) -> dict:
    """Direct cost + response cost + all EU261 from affected flights."""
    # MATCH (c:CostRecord)-[:CAUSED_BY]->(i:Incident {id: $iid})
    # UNION
    # MATCH (i:Incident {id: $iid})-[:AFFECTS]->(f:Flight)
    # MATCH (c:CostRecord {category: 'eu261_compensation'})-[:FOR_FLIGHT]->(f)
    # RETURN sum(c.amount_eur) AS total

async def most_expensive_incidents(sim_day: int, limit: int = 5) -> list:
    """Rank incidents by total financial impact."""

async def hourly_cost_curve(sim_day: int) -> list:
    """Cost and revenue per simulated hour — feeds the dashboard chart."""

async def terminal_pnl(terminal_id: str, sim_day: int) -> dict:
    """P&L breakdown for a specific terminal."""
```

**Verification:** run each query against a 1-day simulation and assert non-empty results.

---

### Task 5.2 — Running cost totals (in-memory cache)

**File:** `services/cost-service/services/cost_engine.py`

Maintain a live in-memory accumulator to serve the WebSocket without querying Neo4j
on every tick:

```python
_running_totals = {
    "total_cost_eur":    0.0,
    "total_revenue_eur": 0.0,
    "net_eur":           0.0,
    "by_category":       defaultdict(float),
    "eu261_exposure":    0.0,
    "last_updated":      None,
}

def record_cost(amount: float, category: str, is_revenue: bool = False):
    if is_revenue:
        _running_totals["total_revenue_eur"] += amount
    else:
        _running_totals["total_cost_eur"] += amount
        _running_totals["by_category"][category] += amount
    _running_totals["net_eur"] = (
        _running_totals["total_revenue_eur"] -
        _running_totals["total_cost_eur"]
    )
```

Rebuilt from Neo4j on service restart.

---

## Phase 6 — REST API & WebSocket

### Task 6.1 — Cost REST endpoints

**File:** `services/cost-service/routers/costs.py`

Add to `docs/services/cost-service/SPEC.md` (create this file) then implement:

| Method  | Path                                    | Description                                           |
| ------- | --------------------------------------- | ----------------------------------------------------- |
| `GET`   | `/api/v1/costs/summary`                 | Running totals: total cost, revenue, net, by category |
| `GET`   | `/api/v1/costs/pnl?day=1`               | Full P&L for a simulated day                          |
| `GET`   | `/api/v1/costs/flight/{id}`             | All costs for a specific flight                       |
| `GET`   | `/api/v1/costs/incident/{id}`           | Total financial impact of an incident                 |
| `GET`   | `/api/v1/costs/incidents/ranking?day=1` | Top 5 most expensive incidents                        |
| `GET`   | `/api/v1/costs/hourly?day=1`            | Cost curve per simulated hour                         |
| `GET`   | `/api/v1/costs/terminal/{id}?day=1`     | P&L per terminal                                      |
| `GET`   | `/api/v1/costs/rates`                   | Current cost rate table (from fixtures)               |
| `PATCH` | `/api/v1/costs/rates`                   | Override a cost rate at runtime                       |
| `WS`    | `/ws/costs`                             | Live stream of `CostRecorded` events                  |

**`GET /api/v1/costs/summary` response:**

```json
{
  "sim_time": "2024-06-15T14:32:00Z",
  "sim_day": 1,
  "total_cost_eur": 847320.5,
  "total_revenue_eur": 1124800.0,
  "net_eur": 277479.5,
  "margin_pct": 24.7,
  "by_category": {
    "eu261_compensation": 187600.0,
    "ground_handling": 142300.0,
    "staffing": 89400.0,
    "holding_fuel": 28100.0,
    "incident_direct": 65000.0,
    "landing_fee": -312000.0,
    "passenger_fee": -198400.0,
    "retail_revenue": -614400.0
  },
  "eu261_exposure_eur": 187600.0,
  "largest_incident_cost_eur": 65000.0
}
```

---

### Task 6.2 — API gateway proxy

**File:** `services/api-gateway/src/proxy.ts`

Add cost-service to the gateway proxy routes:

```typescript
app.use(
  "/api/v1/costs",
  createProxyMiddleware({
    target: process.env.COST_SERVICE_URL ?? "http://cost-service:8007",
    changeOrigin: true,
    on: {
      error: (err, req, res: any) =>
        res.status(502).json({ error: "cost-service unavailable" }),
    },
  }),
);
```

Add `COST_SERVICE_URL` to gateway env in `docker-compose.yml`.
Add `cost-service` to `GET /api/v1/health/services`.
Add cost summary to `GET /api/v1/airport` aggregate endpoint.

---

## Phase 7 — Cost dashboard

### Task 7.1 — Cost overview page (`/cost`)

**File:** `dashboards/art-dashboard/src/pages/CostDashboard.tsx`

Add a new route `/cost` to the dashboard router. The page has five sections:

**Section 1 — Live P&L ticker (top bar)**

```
TOTAL COST: €847,320    REVENUE: €1,124,800    NET: +€277,480 (▲24.7%)
EU261 EXPOSURE: €187,600    LARGEST INCIDENT: €65,000
```

Updates every sim-minute from WebSocket (`costs` topic).

**Section 2 — Cost breakdown donut chart**
Recharts `PieChart` showing cost by category. Click a slice to filter the
records table below.

**Section 3 — Hourly cost/revenue bar chart**
Recharts `BarChart` with two series (cost / revenue) per simulated hour.
Shows the morning and evening peaks clearly.

**Section 4 — Flight cost table**
Sortable table: flight number, airline, aircraft type, total cost, EU261 liability,
handling cost, gate fee. Click a row to open the flight detail drawer with cost breakdown.

**Section 5 — Incident financial impact table**
One row per incident: type, severity, duration, direct cost, EU261 caused, total impact.
Sorted by total impact descending.

**WebSocket subscriptions:** `["costs", "incidents", "flights"]`

**Spec to create:** `docs/dashboards/COST_DASHBOARD.md`
Follow the format of existing dashboard specs.

---

### Task 7.2 — Cost indicators in existing dashboards

Add cost context to existing dashboards without requiring navigation to `/cost`:

- **Flight board:** add a `€` column to the flight table showing total cost per flight (EU261 + handling). Red if EU261 is triggered.
- **Incident console:** add total financial impact to each incident card: `💸 €65,000 estimated impact`
- **Ground ops:** add a live cost ticker to the status bar: `Today: -€847K costs / +€1.1M revenue`
- **Passenger flow:** add a note to the connection risk list showing EU261 exposure per at-risk passenger group: `7 pax at risk — potential EU261 liability: €4,200`

---

## Phase 8 — Prescriptive financial layer

### Task 8.1 — Cost-aware recommendation engine

**File:** `services/cost-service/services/recommendations.py`

Extend the existing recommendation engine (Phase 2 of ROADMAP2.md) to include
financial projections. Each recommendation must now include:

```python
@dataclass
class FinancialRecommendation:
    action: str
    description: str
    cost_eur: float           # cost of implementing the action
    saving_eur: float         # projected saving if action is taken
    net_benefit_eur: float    # saving - cost
    confidence: float         # 0.0 – 1.0
    payback_sim_minutes: int  # how quickly the saving materialises
    expiry_sim_time: str      # after which the action is no longer actionable
```

**Implement these five financially-aware recommendations:**

1. **Open security lane:**
   - Cost: `staffing_rate × expected_duration_hours`
   - Saving: EU261 exposure avoided (from LightGBM forecast × affected flights × pax count × compensation tier)
   - Trigger: forecast wait > 20 min AND at least one flight boarding within 60 sim-min

2. **Hold connecting flight:**
   - Cost: `delay_minutes × pax_count_on_held_flight × delay_cost_per_min`
   - Saving: EU261 avoided for the connection cluster × compensation tier
   - Trigger: connection cluster > 5 pax AND inbound delay > MCT−15 min

3. **Gate reassignment:**
   - Cost: passenger walk time delta × discomfort factor (€2/min/pax)
   - Saving: avoided boarding delay × crew overtime saved
   - Trigger: gate conflict detected with > 15 sim-min exposure

4. **Ground delay program:**
   - Cost: delay cost per held flight × number of flights held
   - Saving: holding fuel avoided × aircraft in holding stack
   - Trigger: weather reduces capacity below 60% AND holding stack > 4

5. **Open additional make-up carousel:**
   - Cost: €0 (resource reallocation, no direct cost)
   - Saving: per-flight delay avoided × aircraft type delay cost
   - Trigger: make-up utilisation > 85% with departure within 45 sim-min

**Expose at:** `GET /api/v1/costs/recommendations`

---

### Task 8.2 — What-if financial projections

**File:** `services/cost-service/services/what_if.py`

Add financial output to the existing what-if endpoint (`POST /analysis/what-if`
in the main incident-service or a new cost-service endpoint).

After the shadow simulation runs N minutes forward, compute the projected
financial delta versus the baseline (do-nothing) scenario:

```python
@dataclass
class FinancialWhatIfResult:
    action_description: str
    projection_minutes: int
    baseline_cost_eur: float
    action_cost_eur: float      # cost of taking the action
    projected_cost_eur: float   # total cost if action is taken
    net_saving_eur: float       # baseline - projected - action_cost
    eu261_baseline_eur: float
    eu261_projected_eur: float
    confidence: float
```

Add this output to the what-if UI panel in the incident dashboard.

---

### Task 8.3 — Scenario financial report

**File:** `services/cost-service/services/report.py`

Add a financial section to the auto-generated incident/scenario report:

```markdown
## Financial Impact

| Category           | Amount       |
| ------------------ | ------------ |
| Direct costs       | €40,000      |
| EU261 compensation | €187,600     |
| Holding fuel       | €28,100      |
| Crew overtime      | €12,600      |
| **Total cost**     | **€268,300** |
| Revenue lost       | €14,200      |
| **Net impact**     | **€282,500** |

Equivalent to: 2.1 days of average airport revenue.
Could have been reduced to €89,000 (−67%) by applying the recommended
ground delay program 8 minutes earlier.
```

---

## Phase 9 — Real data calibration

### Task 9.1 — Calibrate incident probabilities from BTS data

**File:** `services/sim-orchestrator/services/calibration.py`

Download US DOT Bureau of Transportation Statistics on-time data (free, public domain):

```
https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FGJ
```

Parse the CSV to extract:

- Cancellation rate by airline and route type → calibrates `PROB_X_PER_HR` in incident-service
- Delay cause breakdown (carrier, weather, NAS, security, aircraft) → calibrates delay reason weights
- Average delay duration by cause → calibrates TTR ranges

Write the calibrated values back to `cost_rates.json` as a `calibrated_from_bts` section.

---

### Task 9.2 — Calibrate weather FSM from Mesonet data

**File:** `services/weather-service/services/calibration.py`

Download 30 days of Iowa State Mesonet data for a reference station:

```bash
curl -G "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py" \
  --data-urlencode "station=EGLL" \
  --data-urlencode "data=all" \
  --data-urlencode "year1=2024" --data-urlencode "month1=1" --data-urlencode "day1=1" \
  --data-urlencode "year2=2024" --data-urlencode "month2=1" --data-urlencode "day2=31" \
  --data-urlencode "tz=Etc/UTC" \
  --data-urlencode "format=comma" \
  -o data/weather/EGLL_jan2024.csv
```

Classify each METAR observation into CAVOK/VMC/IMC/LIFR using visibility and ceiling.
Compute the empirical transition matrix (probability of transitioning from state X to state Y
in one hour). Write the fitted matrix back to `cost_rates.json` as `calibrated_weather_fsm`.

---

### Task 9.3 — Live fuel price feed

**File:** `services/cost-service/services/fuel_price.py`

Jet-A1 prices fluctuate. Add a daily price fetch from the IATA Jet Fuel Price Monitor
(free weekly data, no API key):

```
https://www.iata.org/en/publications/economics/fuel-monitor/
```

Parse the HTML table (BeautifulSoup) or use the PLATTS/Argus free weekly spot price.
Update `cost_rates.json["delay_costs"]["fuel_price_per_kg_eur"]` once per simulated day.

If the fetch fails, fall back to the hardcoded rate (0.90 EUR/kg). Never crash on
a missing price feed.

---

## Verification checklist — full cost model

Run the following after completing all phases. All checks must pass before the cost model
is considered production-ready.

```bash
# 1. Cost service healthy
curl http://localhost:8007/health | jq .status
# expected: "ok"

# 2. Cost events flowing on Kafka
docker compose exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic cost.events --max-messages 5 | jq .event_type
# expected: "CostRecorded" × 5

# 3. Cost records in Neo4j after 30 sim-min
docker compose exec neo4j cypher-shell -u neo4j -p art-digital-twin \
  "MATCH (c:CostRecord) RETURN c.category, count(c) ORDER BY count(c) DESC"
# expected: all 6 cost categories present

# 4. EU261 triggered by delay
# Manually delay a flight > 3 hours then check:
# MATCH (c:CostRecord {category: 'eu261_compensation'}) RETURN count(c)
# expected: >= 1

# 5. P&L endpoint returns non-zero values
curl http://localhost:3000/api/v1/costs/summary | \
  jq '{cost: .total_cost_eur, revenue: .total_revenue_eur, net: .net_eur}'
# expected: all non-zero

# 6. Financial recommendation triggered
# Run at 600x for 10 real minutes, then:
curl http://localhost:3000/api/v1/costs/recommendations | jq '.[0]'
# expected: at least one recommendation with net_benefit_eur > 0

# 7. Cost dashboard loads
# Open http://localhost:5173/cost
# expected: P&L ticker shows non-zero values, donut chart renders
```

---

## Data sources reference

| Source                      | URL                                                                                                          | License          | Used in        |
| --------------------------- | ------------------------------------------------------------------------------------------------------------ | ---------------- | -------------- |
| EU Regulation 261/2004      | [eur-lex.europa.eu](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32004R0261)                    | Public law       | Task 3.2       |
| Eurocontrol Standard Inputs | [eurocontrol.int](https://www.eurocontrol.int/publication/standard-inputs-eurocontrol-cost-benefit-analyses) | Free download    | Tasks 3.3, 3.5 |
| Eurocontrol CRCO rates      | [eurocontrol.int/crco](https://www.eurocontrol.int/crco)                                                     | Free             | Task 3.1       |
| Iowa State Mesonet          | [mesonet.agron.iastate.edu](https://mesonet.agron.iastate.edu)                                               | Public Domain    | Task 9.2       |
| BTS On-Time Performance     | [transtats.bts.gov](https://www.transtats.bts.gov)                                                           | Public Domain    | Task 9.1       |
| IATA Fuel Monitor           | [iata.org/fuel-monitor](https://www.iata.org/en/publications/economics/fuel-monitor/)                        | Free (weekly)    | Task 9.3       |
| ACI Airport Charges Report  | [aci.aero](https://aci.aero/data-centre)                                                                     | Free summary     | Tasks 3.1, 3.4 |
| ICAO Doc 9562               | [icao.int](https://store.icao.int/en/airport-economics-manual-doc-9562)                                      | Paid (reference) | Background     |

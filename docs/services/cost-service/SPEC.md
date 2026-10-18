# cost-service — Specification

**Port:** 8008  
**Language:** Python 3.11 / FastAPI  
**Status:** Functional ledger; remaining accounting/intelligence gaps in `ROADMAP_REAL_LDT.md`

---

## 1. Domain responsibilities

The cost-service is a **read-only financial layer** that observes domain events via Kafka and
computes associated costs and revenues. It owns financial/carbon records and their
delivery metadata; it does not mutate operational domain entities.

### Durable event accounting (Real LDT G1)

Each supported input event is processed in one Neo4j managed transaction. That
transaction commits its `CostRecord`/`CarbonRecord` nodes and relationships,
`CostInbox` event identity, `CostRuntime` calculation checkpoint and `CostOutbox`
events together. A locked singleton runtime record serializes competing workers;
failed transactions leave no partial charges or seen-event marker. Runtime state
includes gate occupancy starts and staffing hour, and is restored on restart.
Running summaries are published to the in-process cache only after commit.

Kafka offsets are committed after processing. A new consumer group starts from
the earliest retained records; an existing group's committed positions are kept.
Missing input event IDs use the
stable broker topic/partition/offset identity; direct processing requires an ID.
Malformed envelopes are rejected without financial effects. Unhandled fact types
have no financial effect and do not need an inbox entry. Transient processing
errors retry the same message before later messages are consumed.

An independent outbox worker publishes `CostRecorded`, `CarbonRecorded` and
`FinancialEventProcessed` to `cost.events`. The last event identifies the source
event and created record IDs, including checkpoint-only changes. Its `sim_day`
uses the source billing day for late facts, matching their records rather than
the currently selected summary day. Outbox entries are deleted only after
broker acknowledgement. A crash after broker delivery
but before deletion may redeliver the same `event_id`; downstream consumers must
deduplicate it. This guarantees atomic financial persistence, not exactly-once
Kafka delivery or atomicity in the other domain services.

Existing ledger records are preserved: the first durable runtime checkpoint
initializes its summaries from Neo4j. Older in-memory gate starts cannot be
reconstructed by this migration; new starts survive restart. Fee cost/revenue
perspectives remain as currently exposed pending the separate G2 accounting work.
No historical data loss/duplication from the old implementation is repaired
automatically. Per-process summary caches reflect their latest committed input;
they are not a cross-replica coherent read cache. Kafka redelivery is supported;
simulation rewinds with new event IDs still require a separate simulation-epoch
policy. These limits remain distinct from transaction rollback and input dedup.

The bounded checkpoint retains the selected simulation day and seven most recent
other days. A missing day's financial/carbon totals are rebuilt from the ledger
inside the same transaction before applying new effects, including when the clock
selects an evicted day or a late event revisits one. Summary eviction never deletes
ledger records or resets a day's charges. This preserves projection correctness;
it does not define a new simulation epoch or deduplicate newly identified rewind
events against earlier business activity.

Core capabilities:

- **Real-time cost accumulation** — landing fees, gate fees, passenger departure fees, ground
  handling, holding fuel, staffing, incident costs, EU261 compensation
- **Revenue tracking** — landing fee revenue, passenger fee revenue, retail revenue, slot fees
- **Running P&L** — in-memory running totals, rebuilt from Neo4j on restart
- **Financial recommendations** — prescriptive cost-aware recommendations based on current state
- **Neo4j aggregation queries** — daily P&L, per-flight breakdown, incident impact, hourly curves,
  terminal P&L

---

## 2. Cost categories

| Category               | Trigger                                        | Calculation                                                         |
| ---------------------- | ---------------------------------------------- | ------------------------------------------------------------------- |
| `landing_fee`          | FlightStatusChanged → `at_gate` (arrival)      | `MTOW_kg / 1000 × rate_per_tonne`                                  |
| `passenger_fee`        | FlightStatusChanged → `departed`               | `pax_count × per_pax_fee`                                           |
| `gate_fee`             | FlightStatusChanged → gate release             | `(occupancy_minutes / 60) × hourly_rate`                            |
| `eu261_compensation`   | FlightStatusChanged → `delayed` (≥180 min)     | EU Reg 261/2004 tiers based on distance + delay                     |
| `eu261_compensation`   | FlightCancelled                                | Always triggers at max applicable tier                              |
| `holding_fuel`         | SimClockTick (every 5 min)                     | `burn_rate_kg/h × minutes × fuel_price_eur/kg` per holding flight   |
| `ground_handling`      | FlightStatusChanged → `at_gate` (arrival)      | Pushback + catering + cleaning + jetbridge + baggage loading        |
| `incident_direct`      | IncidentCreated                                | Fixed cost per incident type                                        |
| `incident_response`    | IncidentStatusChanged → `resolved`             | Base + 25% per extra 15-min beyond 30 min TTR                       |
| `staffing`             | SimClockTick (hourly)                          | Per-staff-type × lanes/desks open (peak/off-peak)                   |
| `retail_revenue`       | SimClockTick (every 10 min)                    | `airside_pax × hourly_rate × (minutes / 60)`                       |
| `slot_revenue`         | FlightStatusChanged → `departed`               | Fixed slot fee per departure                                        |

---

## 3. Data model

### CostRecord node

| Property      | Type          | Description                                |
| ------------- | ------------- | ------------------------------------------ |
| `id`          | String (UUID) | Unique identifier                          |
| `category`    | String        | One of the categories listed in §2         |
| `amount_eur`  | Float         | Cost amount (always positive)              |
| `currency`    | String        | Always `"EUR"`                             |
| `sim_time`    | String (ISO)  | When the cost was incurred                 |
| `sim_day`     | Integer       | Day number in simulation                   |
| `description` | String        | Human-readable label                       |
| `is_revenue`  | Boolean       | `true` for revenue records                 |
| `rates_version` | String (SHA-256) | Effective financial table content identity; absent on legacy records |

### Relationships

```
(CostRecord)-[:FOR_FLIGHT]->(Flight)
(CostRecord)-[:FOR_TERMINAL]->(Terminal)
(CostRecord)-[:CAUSED_BY]->(Incident)
(CostRecord)-[:FOR_DAY {day: int}]->(Airport)
```

### Constraints and indexes

```cypher
CREATE CONSTRAINT cost_record_id IF NOT EXISTS
  FOR (c:CostRecord) REQUIRE c.id IS UNIQUE;
CREATE INDEX cost_record_category IF NOT EXISTS
  FOR (c:CostRecord) ON (c.category);
CREATE INDEX cost_record_sim_day IF NOT EXISTS
  FOR (c:CostRecord) ON (c.sim_day);
```

---

## 4. Reference data

### Versioned rate contract (Real LDT G2, 2026-10-18)

`services/_common/data/cost_rates.json` is the sole synthetic default table.
The cost owner stores the effective table and its SHA-256 content version in
`CostRuntime.document`. Startup seeds defaults only when no table exists.
`PATCH /rates` validates the entire candidate before committing it, under the
same runtime lock as financial processing, together with a `CostRatesUpdated`
outbox event. Rejected patches have no effects. GET reads the committed table;
each financial input uses the table in its transaction, including across replicas.
Rate events use the latest consumed simulation clock, or the fixed synthetic
epoch `2026-01-01T00:00:00Z` before the first tick. Optional fuel refreshes use
this same persistence path. Existing charges are never repriced.
Rates are selected at processing/claim time; historical event-time tariff tables
are not reconstructed for late inputs.

Planning reads this graph snapshot once on first job claim (shared defaults if
cost has not initialized). It persists the full table and content version in its
scenario before computing. Recovery and replay children retain these rates;
new independent scenarios select the current committed table. This freezes rate
inputs, not schedule/weather/model files or accounting perspectives. Default
reference constants are derived from the same shared table.
Overrides held only in memory by pre-A22 deployments cannot be recovered on
upgrade; operators must reapply them. Existing committed charges remain intact.

Effective rates are restored from Neo4j; the shared default table seeds a new
runtime. `PATCH /api/v1/costs/rates` commits validated overrides. Rate categories:

- **mtow_kg** — per aircraft type maximum takeoff weight
- **airport_fees** — landing, gate, passenger departure, cargo rates
- **eu261** — EU Regulation 261/2004 compensation tiers
- **delay_costs** — crew overtime, fuel burn rates per aircraft family
- **ground_handling** — pushback, catering, cleaning, jetbridge, baggage loading
- **incident_costs** — direct + response costs per incident type
- **staffing** — hourly rates per staff type (security, check-in, gate, ground)
- **revenue** — retail spend per pax, parking, slot fees
- **planning_assumptions** — delay valuation and annualization used by planning

Aircraft are classified into three families for cost calculations:
- **wide**: B77W, A333, A332, A359
- **regional**: DH8D, E195, AT75
- **narrow**: everything else (default)

---

## 5. Kafka

### Consumed topics

| Topic              | Events consumed                              | Action                                           |
| ------------------ | -------------------------------------------- | ------------------------------------------------ |
| `sim.clock`        | `SimClockTick`                               | Holding fuel, staffing, retail revenue            |
| `flights.events`   | `FlightStatusChanged`, `FlightCancelled`     | Landing/gate/pax fees, EU261, ground handling     |
| `incidents.events` | `IncidentCreated`, `IncidentStatusChanged`   | Incident direct + response costs                 |
| `baggage.events`   | `BaggageStatusChanged`                       | (reserved for future per-bag cost tracking)       |
| `passengers.events`| `PassengerStatusChanged`                     | (reserved for future dwell-time revenue tracking) |

**Consumer group:** `cost-service`

### Produced topic

| Topic          | Event           | Payload                                                    |
| -------------- | --------------- | ---------------------------------------------------------- |
| `cost.events`  | `CostRecorded`  | `cost_record_id`, `category`, `amount_eur`, `is_revenue`, `flight_id`, `incident_id`, `description`, `sim_time`, `sim_day` |

---

## 6. REST API

All endpoints are prefixed with `/api/v1/costs`.

| Method  | Path                          | Description                              |
| ------- | ----------------------------- | ---------------------------------------- |
| `GET`   | `/summary`                    | Running totals: cost, revenue, net, by category, EU261 exposure, margin % |
| `GET`   | `/pnl?day=N`                  | Full P&L for simulated day N             |
| `GET`   | `/flight/{flight_id}`         | All costs/revenues linked to a flight    |
| `GET`   | `/incident/{incident_id}`     | Total financial impact of an incident    |
| `GET`   | `/incidents/ranking?day=N`    | Top incidents by cost impact             |
| `GET`   | `/hourly?day=N`               | Cost/revenue curve per simulated hour    |
| `GET`   | `/terminal/{terminal_id}`     | P&L per terminal                         |
| `GET`   | `/rates`                      | Current cost rate table                  |
| `PATCH` | `/rates`                      | Override cost rates at runtime           |
| `GET`   | `/recommendations`            | Financial recommendations                |

---

## 7. Recommendations engine

Generates prescriptive recommendations based on running totals:

| Action                 | Trigger threshold                  | Logic                                |
| ---------------------- | ---------------------------------- | ------------------------------------ |
| `open_security_lane`   | EU261 exposure > €10,000           | Extra lane cost vs 30% EU261 saving  |
| `ground_delay_program` | Holding fuel costs > €5,000        | Admin cost vs 50% fuel saving        |
| `gate_reassignment`    | Ground handling costs > €50,000    | Pax walk cost vs 10% handling saving |
| `open_makeup_carousel` | Total costs > €100,000             | Free action vs 2% total saving       |

Each recommendation includes: `cost_eur`, `saving_eur`, `net_benefit_eur`, `confidence`,
`payback_sim_minutes`, `expiry_sim_time`.

---

## 8. Configuration

| Variable         | Default                  | Description               |
| ---------------- | ------------------------ | ------------------------- |
| `NEO4J_URI`      | `bolt://neo4j:7687`      | Neo4j connection          |
| `NEO4J_USER`     | `neo4j`                  | Neo4j user                |
| `NEO4J_PASSWORD`  | `art-digital-twin`      | Neo4j password            |
| `KAFKA_BROKERS`  | `kafka:9092`             | Kafka broker address      |
| `LOG_LEVEL`      | `INFO`                   | Logging level             |
| `OTEL_ENABLED`   | `false`                  | Enable OpenTelemetry      |

---

## 9. Health & observability

| Endpoint   | Description                                           |
| ---------- | ----------------------------------------------------- |
| `/health`  | Always returns `{"status": "ok"}`                     |
| `/ready`   | Checks Neo4j + Kafka connectivity                     |
| `/metrics` | Prometheus metrics via `prometheus-fastapi-instrumentator` |

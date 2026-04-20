# Improvements — Sprint 23 Code Audit

Comprehensive code audit covering all 7 Python microservices, the API gateway, the React
dashboard, Docker Compose configuration, and test infrastructure.

---

## Summary

| Severity | Found | Fixed |
| -------- | ----- | ----- |
| High     | 4     | 4     |
| Medium   | 6     | 6     |
| Low      | 2     | 1     |

---

## HIGH — Logic Bugs & Broken Features

### H1 · Network delay propagation never worked

**Files:** `services/flight-service/kafka/producer.py`, `services/flight-service/kafka/consumer.py`, `services/sim-orchestrator/kafka/consumer.py`

The sim-orchestrator's multi-airport network delay propagation was completely broken:

1. `FlightStatusChanged` events never included `direction` or `destination_iata` fields
2. The sim-orchestrator consumer read fields from the Kafka envelope level instead of the
   inner `payload` object

**Fix:** Added `direction` and `destination_iata` to the `FlightStatusChanged` producer and
all 6 callsites. Fixed the sim-orchestrator consumer to extract `payload["payload"]`.

### H2 · Dashboard never received sim clock or analysis events

**File:** `dashboards/art-dashboard/src/hooks/useWebSocket.ts`

The WebSocket subscribe message was missing `"sim"` and `"analysis"` topics. The dashboard
relied on heartbeat messages as a fallback for time display, and analysis events
(bottlenecks, recommendations) never reached the UI.

**Fix:** Added `"sim"` and `"analysis"` to the topics array.

### H3 · OTEL tracing silently broken for 5 of 7 services

**File:** `docker-compose.yml`

Five services (flight, weather, incident, sim-orchestrator, analysis) defined their own
`environment:` block, which in YAML completely replaces the `x-python-service` anchor's
environment — silently dropping `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_ENABLED`. No
service had `OTEL_SERVICE_NAME`, so all reported as "unknown-service" in Jaeger.

**Fix:** Added `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_ENABLED`, and per-service
`OTEL_SERVICE_NAME` to every overriding environment block.

### H4 · API gateway rejected "analysis" WebSocket subscriptions

**File:** `services/api-gateway/src/websocket.ts`

The `VALID_TOPICS` set was missing `"analysis"`, so clients could never subscribe to analysis
events even though the gateway consumed them from Kafka.

**Fix:** Added `"analysis"` to `VALID_TOPICS`.

---

## MEDIUM — Performance, Security, Correctness

### M1 · Idempotency eviction was non-deterministic

**Files:** `services/{flight,passenger,baggage}-service/kafka/consumer.py`

All three services used `set.pop()` to evict old event IDs when the idempotency set
exceeded its limit. `set.pop()` removes an arbitrary element, so recent event IDs could
be evicted while very old ones remained — defeating the purpose of idempotency tracking.

**Fix:** Added a `deque` alongside the set to track insertion order. Eviction now removes
the oldest event ID first (FIFO).

### M2 · Security queue O(n) membership check

**File:** `services/passenger-service/services/security.py`

`enqueue()` used `if passenger_id not in self.queue` where `self.queue` is a `list` —
an O(n) scan on every enqueue call. With thousands of passengers queued, this was a hot-path
performance issue.

**Fix:** Added shadow `_queue_set` and `_sa_queue_set` for O(1) membership checks,
updated in `enqueue()`, `drain()`, and the periodic Neo4j reconciliation.

### M3 · `get_active_flights()` scanned all flights from all days

**File:** `services/flight-service/db/neo4j.py`

The query had no time-window filter, so it returned all flights in active states regardless
of when they were scheduled. At 420 flights/day, this grew linearly with simulation duration.

**Fix:** Added a ±24h window filter on `f.scheduled_time` relative to `sim_time`.

### M4 · Cypher f-string injection risk

**File:** `services/passenger-service/db/neo4j.py`

`update_passenger_status()` and `bulk_update_status()` interpolated `new_status` directly
into Cypher via `f"{new_status}_at"`. While status values come from controlled code paths,
the f-string interpolation pattern poses an injection risk if the input surface ever widens.

**Fix:** Added `_VALID_STATUSES` frozenset allowlist. Both functions now raise `ValueError`
for any status not in the allowlist before constructing the Cypher query.

### M5 · `datetime.utcnow()` deprecated

**Files:** All producers + clock.py, snapshot.py, scenario_engine.py, whatif.py, report.py

`datetime.utcnow()` is deprecated since Python 3.12 and returns naive datetimes.

**Fix:** Replaced with `datetime.now(timezone.utc)` across all service files.

### M6 · analysis-service consumed one message at a time

**File:** `services/analysis-service/kafka/consumer.py`

Used `.poll(0.5)` which returns a single message. At high simulation speeds (~600× or bulk),
the analysis service fell behind on event processing.

**Fix:** Switched to `.consume(num_messages=50, timeout=0.5)` for batch processing.

---

## LOW — Cleanup

### L2 · Duplicate `_producer` declaration

**File:** `services/passenger-service/kafka/producer.py`

Module-level `_producer: Producer | None = None` was declared twice (lines 15 and 24).
The second one shadowed the first, wasting a line and confusing linters.

**Fix:** Removed the duplicate declaration.

---

## Future Improvements (Not Implemented)

These are opportunities identified during the audit that don't warrant immediate fixing:

1. **Shared idempotency module** — The FIFO eviction logic is now duplicated across 3
   services. Extract to a shared `_common/idempotency.py` module.

2. **Structured logging** — All services use plain-text logging. Switching to JSON structured
   logging (e.g., `python-json-logger`) would improve log aggregation in Grafana/Loki.

3. **Consumer health checks** — Kafka consumers run in background threads with no health
   signal. If a consumer thread dies, the service continues serving HTTP but processes no
   events. Add a liveness check (e.g., last-processed timestamp exposed via `/health`).

4. **Schema registry** — Event schemas are implicit (Python dicts). Adding a schema registry
   (or at least Pydantic models for all event types) would catch envelope mismatches at
   produce time rather than at consume time.

5. **Neo4j connection pooling tuning** — Default driver settings may not be optimal for the
   burst-heavy access pattern during high-speed simulation ticks.

6. **WebSocket reconnection backoff** — The dashboard WebSocket reconnects on a fixed
   interval. Implementing exponential backoff with jitter would reduce thundering-herd
   reconnection storms.

7. **Test coverage for analysis-service** — Currently has no unit or integration tests.
   The bottleneck detection, recommendation engine, and anomaly detector are untested.

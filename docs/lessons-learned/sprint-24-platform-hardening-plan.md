# Sprint 24 — Platform Hardening & Shared Infrastructure

## Overview

Seven improvements identified in Sprint 23 audit. Consolidation, reliability, and test coverage.

## Tasks

### T1: Shared idempotency module

- Create `services/_common/idempotency.py` with `IdempotencyTracker` class (FIFO deque + set)
- Configurable `max_size`
- Replace duplicated logic in flight/passenger/baggage consumer state classes
- Update `tests/unit/test_idempotency.py` to test the shared class directly

### T2: Structured logging consolidation

- Already implemented via `_logging.py` per service (copy of `_template/_logging.py`)
- **Actual work**: no-op — all services already use structlog+JSONRenderer identically
- Just verify all services import from their local `_logging.py`

### T3: Consumer health checks

- Add `last_message_time: datetime | None` to each consumer module
- Update it on every successfully processed message
- Expose in `/health` as `consumer_last_message_age_seconds`
- In `/ready`, flag unhealthy if consumer alive but no messages in >120 seconds AND sim running

### T4: Schema registry (Pydantic event models)

- Create `services/_common/events.py` with Pydantic models:
  - `EventEnvelope` (shared base)
  - Per-event payload models (FlightStatusChanged, SimClockTick, etc.)
- Typed `produce_event()` that validates before sending
- Consumers: validate on ingest with `.model_validate()`

### T5: Neo4j connection pooling tuning

- Add `max_connection_pool_size`, `connection_acquisition_timeout`, `max_connection_lifetime` to driver constructor
- Env-configurable via `NEO4J_POOL_SIZE` etc.
- Apply to all 7 Python services' `db/neo4j.py`

### T6: WebSocket reconnection jitter

- Current: exponential backoff (1s base, 30s cap) — already good
- Add: random jitter (±25%) to prevent thundering herd
- One-line change in `scheduleReconnect`

### T7: Analysis-service test coverage

- `tests/unit/test_analysis_detectors.py` — test all 6 detector functions
- `tests/unit/test_analysis_recommender.py` — test recommendation generation
- `tests/unit/test_analysis_anomaly.py` — test anomaly detection

## Implementation order

T1 → T5 → T6 → T3 → T4 → T7 → T2 (verify) → validate

## Status

- [ ] T1: Shared idempotency
- [ ] T2: Structured logging (verify)
- [ ] T3: Consumer health checks
- [ ] T4: Schema registry
- [ ] T5: Neo4j pooling
- [ ] T6: WS jitter
- [ ] T7: Analysis tests
- [ ] Docker rebuild + validation
- [ ] CI/CD checks

# Sprint 23 — Comprehensive Code Audit & Fixes

## Audit Findings — Prioritized

### HIGH SEVERITY

| #   | Issue                               | File                                                 | Description                                                                                                                                                                                                                                                     |
| --- | ----------------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| H1  | Network delay propagation broken    | `services/sim-orchestrator/kafka/consumer.py`        | Reads `direction`, `new_status`, `delay_minutes`, `flight_number`, `destination_iata` from envelope level — should be `payload["payload"]`. Plus `direction` and `destination_iata` are NOT in FlightStatusChanged payload at all. Network cascade never fires. |
| H2  | Dashboard missing "sim" WS topic    | `dashboards/art-dashboard/src/hooks/useWebSocket.ts` | Subscribe message doesn't include `"sim"` — SimClockTick events never reach the dashboard. Relied on heartbeat as fallback.                                                                                                                                     |
| H3  | OTEL tracing silently broken        | `docker-compose.yml`                                 | 5 services override `environment:` block, losing `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_ENABLED`. No `OTEL_SERVICE_NAME` set for any Python service.                                                                                                           |
| H4  | "analysis" topic not in API gateway | `services/api-gateway/src/websocket.ts`              | Not in VALID_TOPICS. Dashboard registers handlers for analysis events but can never subscribe.                                                                                                                                                                  |

### MEDIUM SEVERITY

| #   | Issue                                     | File                                                            | Description                                                                                  |
| --- | ----------------------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| M1  | Idempotency eviction is non-deterministic | `services/{flight,passenger,baggage}-service/kafka/consumer.py` | `set.pop()` removes arbitrary elements, not oldest. Recent duplicates could be re-processed. |
| M2  | Security queue O(n) membership check      | `services/passenger-service/services/security.py`               | `if passenger_id not in self.queue` on a `list` — O(n) on hot path.                          |
| M3  | `get_active_flights()` unbounded scan     | `services/flight-service/db/neo4j.py`                           | No time-window filter — scans all flights from all days.                                     |
| M4  | Cypher f-string injection risk            | `services/passenger-service/db/neo4j.py`                        | `ts_field = f"{new_status}_at"` interpolated into Cypher. Add allowlist validation.          |
| M5  | `datetime.utcnow()` deprecated            | All producer files                                              | Should use `datetime.now(timezone.utc)` per Python 3.12+ guidance.                           |
| M6  | analysis-service polls 1 msg at a time    | `services/analysis-service/kafka/consumer.py`                   | Uses `.poll(0.5)` instead of `.consume(batch_size)` — falls behind at high speed.            |

### LOW SEVERITY

| #   | Issue                                        | File                                           | Description                              |
| --- | -------------------------------------------- | ---------------------------------------------- | ---------------------------------------- |
| L1  | WS broadcast swallows exceptions             | All service `main.py`                          | No logging on failed WS sends.           |
| L2  | Duplicate `_producer` declaration            | `services/passenger-service/kafka/producer.py` | Module-level `_producer` declared twice. |
| L3  | Dashboard BaggageStatusChanged handler no-op | `useWebSocket.ts`                              | `updateZone(scanZone, {})` does nothing. |

## Plan

### Phase 1 — Fix H1 (network delay propagation)

1. Add `direction` and `destination_iata` to `FlightStatusChanged` producer payload
2. Fix sim-orchestrator consumer to read from `payload["payload"]` (inner payload)

### Phase 2 — Fix H2+H3+H4 (WebSocket topics + OTEL config)

1. Add `"sim"` and `"analysis"` to dashboard WS subscribe topics
2. Add `"analysis"` to API gateway VALID_TOPICS
3. Fix docker-compose: add OTEL vars + OTEL_SERVICE_NAME to all services that override environment

### Phase 3 — Fix M1+M2+M3+M4 (performance + safety)

1. Replace `set.pop()` with OrderedDict-based FIFO eviction in all 3 services + test
2. Add set-based O(1) membership check for security queue
3. Add 24h time-window filter to `get_active_flights()`
4. Add status allowlist validation before Cypher interpolation

### Phase 4 — Fix M5+M6+L1+L2 (cleanup)

1. Replace `datetime.utcnow()` with `datetime.now(timezone.utc)` in all producers
2. Switch analysis-service consumer to batch consume pattern
3. Add debug logging to WS broadcast errors
4. Remove duplicate `_producer` declaration

### Phase 5 — IMPROVEMENTS.md + lessons-learned

## Status

- [x] H1: Network delay propagation — added direction/destination_iata to FlightStatusChanged, fixed sim-orchestrator inner payload extraction
- [x] H2: Dashboard WS topics — added "sim" and "analysis" to subscribe array
- [x] H3: OTEL docker-compose fix — restored OTEL vars + added OTEL_SERVICE_NAME to 5 services
- [x] H4: API gateway analysis topic — added "analysis" to VALID_TOPICS
- [x] M1: Idempotency FIFO eviction — replaced set.pop() with deque-backed FIFO in 3 services
- [x] M2: Security queue O(1) check — added shadow sets for O(1) membership in SecurityCheckpoint
- [x] M3: Active flights time window — added ±24h filter to get_active_flights()
- [x] M4: Cypher injection allowlist — added \_VALID_STATUSES frozenset guard
- [x] M5: datetime.utcnow() → now(utc) — replaced in all producers + 5 service modules
- [x] M6: analysis-service batch consume — switched from poll(0.5) to consume(50, 0.5)
- [x] L2: Duplicate producer declaration — removed from passenger-service
- [x] IMPROVEMENTS.md — created at project root
- [ ] CI/CD checks pass

# Phase 2 — Prescriptive Digital Twin: Completion Report

**Date:** 2025-07-17  
**Scope:** P2-1 through P2-4 (23 roadmap items)  
**Status:** ✅ All items implemented

---

## What was built

A new **analysis-service** (port 8007) that transforms the project from a passive
simulation into an active decision-support system. It consumes all domain Kafka
topics, maintains an in-memory operational state, and runs detection / recommendation
/ what-if / autonomous cycles on every sim-clock tick.

### 2.1 — Bottleneck detection engine

Six detector functions with configurable thresholds:

| Detector | Trigger |
|---|---|
| Security queue | Wait forecast > 20 sim-min |
| Gate utilisation | Free gates < 2 while flights queued |
| Baggage throughput | Make-up carousel > 90% for > 5 sim-min |
| Connection cluster | ≥ 5 pax on same delayed inbound + same connection |
| Ground vehicle | Vehicle type utilisation > 85% |
| Runway capacity | Weather reduces capacity below 60% |

Auto-resolution: each tick checks whether the triggering condition has cleared.

**Files:** `services/analysis-service/models/domain.py`, `services/analysis-service/services/detectors.py`

### 2.2 — Recommendation engine

Generates ranked recommendations per bottleneck type:

- **Security:** open lane, early gate call, redirect check-in
- **Gate:** reassign gate, delay taxi, swap departures
- **Connection:** hold flight, fast-track cluster, rebook passengers
- **Runway/weather:** ground delay program
- **Baggage:** redirect carousel, expedite sorting
- **Vehicle:** redistribute fleet, defer low-priority tasks

Top 3 exposed via REST, all pushed to WebSocket + Kafka.

**Files:** `services/analysis-service/services/recommender.py`, `services/analysis-service/routers/analysis.py`

### 2.3 — What-if analysis engine

- `POST /api/v1/analysis/what-if` forks state into a shadow simulation
- 14 action simulators (open_lane, reassign_gate, hold_flight, etc.)
- KPI projection: delay minutes, missed connections, queue depth, cascade depth, gate utilisation, baggage throughput, confidence score
- Multi-action comparison: up to 3 parallel projections
- Query log with 500-entry cap for future confidence calibration
- Max projection horizon: 120 sim-minutes

**Files:** `services/analysis-service/services/whatif.py`

### 2.4 — Autonomous operations mode

- Toggle + threshold + interval configurable via `PATCH /api/v1/analysis/autonomous`
- Evaluates top recommendation each cycle; auto-applies if confidence > threshold
- Safety guards block: `GROUND_DELAY_PROGRAM`, `REBOOK_PASSENGERS`, flight cancellation, runway closure
- Action log (200-entry cap) with timestamp, action details, confidence score
- Kafka event `AutonomousActionApplied` broadcast on each auto-action

**Files:** `services/analysis-service/services/autonomous.py`

---

## Integration points

### API Gateway

- Upstream `analysis` → `http://analysis-service:8007`
- Proxy route: `/api/v1/analysis/*`
- Health check: included in `/health` aggregation
- Kafka relay: `analysis.events` topic forwarded to WebSocket clients

### Docker Compose

- New `analysis-service` container (port 8007)
- New `analysis.events:3:1` Kafka topic
- Depends on: `neo4j`, `kafka`, `kafka-init`
- `ANALYSIS_SERVICE_URL` env var injected into gateway

### Prometheus

- Scrape target added at `analysis-service:8007`
- Metrics: `bottlenecks_active`, `bottlenecks_detected_total`, `recommendations_generated_total`, `recommendations_applied_total`, `whatif_queries_total`, `whatif_duration_seconds`, `autonomous_actions_total`

### Dashboard

- **Zustand store:** `analysisStore.ts` — bottlenecks + recommendations state
- **API hooks:** `useBottlenecksQuery`, `useRecommendationsQuery`, `useAutonomousSettingsQuery`
- **WebSocket:** handles `BottleneckDetected`, `BottleneckResolved`, `RecommendationGenerated`, `AutonomousActionApplied`
- **Incident Console:** `RecommendationFeed` component (bottleneck cards + recommendation cards with Apply button)
- **Incident Console:** `WhatIfPanel` component (multi-action comparison with KPI table)
- **Settings:** `AutonomousSection` component (toggle, threshold slider, interval input, action log)

---

## Validation

| Check | Result |
|---|---|
| `ruff check services/analysis-service/` | ✅ All checks passed |
| `ruff check services/` (all Python) | ✅ All checks passed |
| `npm run build` (dashboard) | ✅ Built successfully |
| `npm run build` (api-gateway) | ✅ Built successfully |
| Docker build | ⏳ Docker Desktop not running; deferred to next `docker compose up --build` |

---

## Architecture decisions

1. **Dedicated service, not embedded in existing ones.** The analysis-service is a
   read-side aggregate that consumes all domain events but never writes to Neo4j.
   This keeps domain services (flight, passenger, baggage, etc.) unaware of the
   prescriptive layer and avoids circular dependencies.

2. **Shadow simulation via deep copy.** What-if uses `copy.deepcopy()` on the
   OperationalState dataclass rather than forking actual Kafka consumers. This is
   simpler and sufficient for projection horizons up to 120 min.

3. **No direct service HTTP calls.** The analysis-service only reads from Kafka
   and Neo4j. Recommendations are advisory events; the gateway relays them to UI.
   "Applying" a recommendation is done by the operator pressing Apply in the UI,
   which calls the relevant domain service through the gateway.

4. **Safety-first autonomous mode.** Dangerous actions (GDP, rebook, cancel) are
   hardcoded as blocked. The threshold and interval are configurable but default
   to conservative values (0.80 confidence, 5 sim-minutes).

---

## File inventory

```
services/analysis-service/
├── Dockerfile
├── requirements.txt
├── main.py
├── metrics.py
├── __init__.py
├── db/
│   ├── __init__.py
│   └── neo4j.py
├── kafka/
│   ├── __init__.py
│   ├── consumer.py
│   └── producer.py
├── models/
│   ├── __init__.py
│   └── domain.py
├── routers/
│   ├── __init__.py
│   └── analysis.py
└── services/
    ├── __init__.py
    ├── autonomous.py
    ├── detectors.py
    ├── recommender.py
    ├── state.py
    └── whatif.py
```

**Modified files:**
- `docker-compose.yml` — analysis-service container + topic + gateway env
- `services/api-gateway/src/proxy.ts` — analysis upstream + route
- `services/api-gateway/src/health.ts` — analysis health check
- `services/api-gateway/src/aggregate.ts` — analysis aggregate endpoint
- `services/api-gateway/src/kafka.ts` — analysis.events topic mapping
- `infra/prometheus/prometheus.yml` — analysis scrape target
- `dashboards/art-dashboard/src/stores/analysisStore.ts` — new store
- `dashboards/art-dashboard/src/hooks/useApi.ts` — analysisApi module
- `dashboards/art-dashboard/src/hooks/useQueries.ts` — analysis queries
- `dashboards/art-dashboard/src/hooks/useWebSocket.ts` — analysis events
- `dashboards/art-dashboard/src/pages/IncidentConsole/IncidentConsolePage.tsx` — RecommendationFeed
- `dashboards/art-dashboard/src/pages/IncidentConsole/WhatIfPanel.tsx` — new component
- `dashboards/art-dashboard/src/pages/Settings/SettingsPage.tsx` — AutonomousSection
- `ROADMAP.md` — all P2 checkboxes marked

---

## Next steps

- Start Docker Desktop and run `docker compose up --build` to verify full-stack integration
- Run a scenario and observe bottleneck detection → recommendation → what-if flow
- Enable autonomous mode and verify safety guards block dangerous actions
- Tune detector thresholds based on observed simulation behaviour
- Phase 2.5 (3D models & layouts) can proceed in parallel
- Phase 3 (multi-airport network) depends on Phase 2 being stable

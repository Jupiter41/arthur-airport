# Sprint 40 — Lessons Learned

**Date:** 2025-07-17  
**Focus:** UI improvements, documentation, architecture diagrams, deduplication

---

## What was done

### 1. Cost Dashboard (Phase 7)

Added a full Cost Dashboard page to the React frontend:

- **Types**: `CostSummary`, `CostPnL`, `FlightCostBreakdown`, `HourlyCostPoint`,
  `IncidentCostRanking`, `FinancialRecommendation` added to `types.ts`
- **API client**: `costsApi` added to `useApi.ts` covering all cost-service REST endpoints
- **Zustand store**: `costStore.ts` for WebSocket event handling
- **React Query hooks**: `useCostDashboardQueries()` in `useQueries.ts`
- **WebSocket handler**: `CostRecorded` event handler added, invalidates cost queries
- **Page**: `CostDashboard/CostDashboardPage.tsx` with:
  - 5 KPI cards (total cost, revenue, net P&L, EU261 exposure, categories)
  - Hourly cost vs revenue area chart
  - Cost breakdown donut chart
  - Category bar chart (horizontal)
  - Incident cost ranking table
  - Financial recommendations panel
- **Routing**: `/costs` route in App.tsx, nav item under "Ops" dropdown in HeaderBar

### 2. BTS.md root document

Created `BTS.md` at project root explaining:
- What BTS is and the T-100 dataset
- Architecture data flow (sim-orchestrator calibration + passenger-service adapter)
- File locations in the repository
- Implementation status table
- How to add new data
- Limitations

### 3. Architecture diagrams updated

Updated both `ARCHITECTURE_DIAGRAM.md` and `graph.mmd` to include:
- cost-service in the Services subgraph (port 8008)
- Cost Dashboard in the Frontend subgraph
- `cost.events` Kafka topic
- All cost-service Kafka consumption edges (sim.clock, flights.events, incidents.events, baggage.events, passengers.events)
- Gateway → cost-service HTTP proxy
- cost-service → Neo4j storage
- cost-service → Prometheus metrics
- CostRecords in Neo4j graph description
- Kafka event flow diagram updated with cost-service

### 4. Deduplication — `wait_for_neo4j_ready`

Added `wait_for_neo4j_ready()` to `_common/infra.py` — a generic retry-with-backoff function
that accepts `init_fn` and `close_driver_fn` callbacks. Converted cost-service to use it as
proof-of-concept. Other services can be migrated incrementally.

### 5. Test infrastructure fix

Fixed `tests/conftest.py` to add `services/` directory to `sys.path` so that `_common` package
is importable during unit tests. This was necessary because cost-service's `db/neo4j.py` now
imports from `_common.infra`.

### 6. Cost-service SPEC updated

Updated SPEC.md status from "Phases 1–6 complete" to "Phases 1–7 complete" to reflect the
new dashboard.

---

## Gotchas encountered

1. **recharts Tooltip formatter types**: The `Formatter<ValueType, NameType>` type in recharts
   expects `ValueType | undefined`, not `number`. Solution: accept `unknown` and cast internally.

2. **PowerShell `-replace` is case-insensitive**: Using PowerShell's `-replace` operator to fix
   TypeScript code broke `tickFormatter` → `tickformatter`. Lesson: don't use PowerShell regex
   replace on case-sensitive code — use the file editor tools instead.

3. **SimStore accessor**: The sim store uses `status.day_number`, not a top-level `dayNumber`.
   Always check store shape before using accessors.

4. **`_common` import in tests**: When services import from `_common`, the test conftest must
   ensure `services/` is on `sys.path`. This wasn't needed before because no service was actually
   importing from `_common` at the module level.

---

## CI results

- **Unit tests**: 667 passed
- **ruff**: All checks passed
- **Cypher linter**: No issues (199 files, 111 with Cypher)
- **Augmented assign linter**: No issues
- **Dashboard build**: Successful (6.58s)
- **Gateway build**: Successful
- **TypeScript type-check**: Clean (no errors)

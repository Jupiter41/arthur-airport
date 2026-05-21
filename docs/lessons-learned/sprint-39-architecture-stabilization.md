# Sprint 39 — Architecture stabilization, cost-service docs, code deduplication

## Scope

| # | Task | Status |
|---|------|--------|
| 1 | Fix dashboard `npm ci` failure | ✅ Done |
| 2 | BTS adapter — update docs to reflect implementation status | ✅ Done |
| 3 | Write proper cost-service SPEC.md | ✅ Done |
| 4 | Write cost-service SKILL.md | ✅ Done |
| 5 | Extract shared infrastructure to `_common/` | ✅ Done |
| 6 | Fix BTS module logging (stdlib → structlog) | ✅ Done |
| 7 | Add `_common` usage to cost-service | ✅ Done |
| 8 | Update architecture docs (OVERVIEW, DATA_MODEL, EVENT_BUS, DATA_SOURCES) | ✅ Done |
| 9 | Fix Cypher compatibility issues | ✅ Done |
| 10 | Fix Cypher linter false positive on regex patterns | ✅ Done |

---

## 1. Dashboard `npm ci` failure

### Root cause

`package-lock.json` was out of sync with `package.json` — `esbuild@0.27.7` was missing
from the lock file. This caused CI to fail on `npm ci`.

### Fix

Ran `npm install` in `dashboards/art-dashboard/` to regenerate the lock file, then
verified `npm ci` succeeds. Also verified `npm run build` produces a clean build (837 modules).

---

## 2. BTS adapter status

### Finding

The `DATA_SOURCES.md` documented BTS historical as "adapter specced, not yet implemented",
but in fact:
- `services/passenger-service/services/bts_adapter.py` — full adapter with CSV loading,
  sample data generation, hourly disaggregation, REST endpoints
- `services/sim-orchestrator/services/bts_calibration.py` — calibration module that
  feeds BTS data into schedule generation and passenger load factors

### Fix

Updated `DATA_SOURCES.md`:
- Changed BTS status from "not yet implemented" to "overlay + sim-orchestrator calibration"
- Replaced stub example code with reference to the actual implementation files
- Added documentation of the dual BTS integration (passenger-service overlay + sim-orchestrator calibration)

---

## 3. Cost-service documentation

### Problem

`docs/services/cost-service/SPEC.md` was a copy of `ROADMAP_COST.md` — the full roadmap
document, not a proper specification following the same format as other service SPECs.

### Fix

Replaced with a proper SPEC document covering:
- Domain responsibilities (§1)
- Cost categories table with triggers and calculations (§2)
- CostRecord data model and Neo4j relationships (§3)
- Reference data and aircraft classification (§4)
- Kafka consumed/produced topics (§5)
- REST API endpoint inventory (§6)
- Recommendations engine with thresholds (§7)
- Configuration variables (§8)
- Health & observability (§9)

Also created `services/cost-service/SKILL.md` covering:
- Architecture (passive financial observer pattern)
- Key patterns (running totals, dual-entry accounting, aircraft families, tick-based accumulation)
- Common gotchas (structlog, sim_day extraction, session management)
- File layout
- Testing

---

## 4. Code deduplication

### Finding

`wait_for_neo4j` is duplicated 8 times (one per service) and `wait_for_kafka` is duplicated
8 times. Each implementation is slightly different but follows the same retry-with-backoff
pattern.

### Fix — incremental

Created `services/_common/infra.py` with `wait_for_kafka_broker()` — a generic, parameterized
retry utility. Updated cost-service to use it as a proof of concept. Other services can be
migrated incrementally.

Also added `_common.consumer_health.ConsumerHealthTracker` to cost-service's Kafka consumer,
matching the pattern used by all other services. Added `get_consumer_health()` function.

### Remaining duplication (documented for future sprints)

- `wait_for_neo4j` across 8 services — harder to extract because each service has a
  different `init_neo4j()` function that initializes the driver and creates service-specific
  constraints/indexes. Would need a callback-based approach.
- Kafka producer boilerplate (init, close, check, wait) across all services — similar
  envelope construction and delivery patterns.

---

## 5. BTS logging fix

Both `services/passenger-service/services/bts_adapter.py` and
`services/sim-orchestrator/services/bts_calibration.py` used `import logging` (stdlib)
instead of `import structlog`. This is the same class of bug that crashed cost-service
in sprint 38. Fixed both to use structlog.

---

## 6. Architecture documentation updates

### OVERVIEW.md
- Added `cost-service` to the service map table (port 8008)
- Updated system context to mention cost-service as a separate layer

### DATA_MODEL.md
- Added `CostRecord` node definition to node catalogue (§2)
- Added cost relationships to relationship catalogue (§3): `FOR_FLIGHT`, `FOR_TERMINAL`,
  `CAUSED_BY`, `FOR_DAY`
- Added CostRecord constraint and indexes to §5

### EVENT_BUS.md
- Added `cost.events` topic to topic catalogue (§2)
- Added `CostRecorded` event schema (§4)
- Updated consumers list for `flights.events`, `passengers.events`, `baggage.events`,
  `incidents.events` to include cost-service
- Updated partition/consumer group table accordingly

---

## 7. Cypher compatibility fixes

- `analysis-service/db/neo4j.py:169` — Changed `f.status NOT IN [...]` to `NOT f.status IN [...]`
  (Neo4j 5 CE compatibility)
- `lint-cypher.py` — Fixed false positive on regex strings containing Cypher keywords. Added
  skip logic for strings that look like regex patterns (containing `[\\()|?+*^$]` metacharacters).
  Also added `# noqa: cypher` comment support.

---

## CI validation

| Check | Result |
|-------|--------|
| `python -m ruff check services/ tests/ scripts/` | ✅ All checks passed |
| `npm run build` (api-gateway) | ✅ Clean compile |
| `npm run build` (art-dashboard) | ✅ Built in 6.7s (837 modules) |
| `npm ci` (art-dashboard) | ✅ 406 packages installed |
| `python -m pytest tests/unit/ -q` | ✅ 667 passed in 3.4s |
| `lint-augmented-assign.py` | ✅ 0 issues |
| `lint-cypher.py` | ✅ 0 issues |

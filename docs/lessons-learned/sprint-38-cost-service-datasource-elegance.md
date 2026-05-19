# Sprint 38 — Cost-service fix, data-source refactor & code elegance

## Scope

| # | Task | Status |
|---|------|--------|
| 1 | Fix cost-service startup crash | ✅ Done |
| 2 | Improve test coverage (behaviour focus) | ✅ Done |
| 3 | Refactor flexible data-source logic | ✅ Done |
| 4 | Code elegance & maintainability | ✅ Done |

---

## 1. Cost-service crash fix

### Root cause

All 8 Python files in `cost-service` used `logging.getLogger(__name__)` (stdlib) but called the
logger with keyword arguments (`logger.warning("msg", attempt=x, error=str(e))`), which is a
structlog convention. The stdlib `Logger._log()` rejects unknown keyword arguments with a
`TypeError`.

### Fix

Replaced `import logging` / `logging.getLogger()` with `import structlog` / `structlog.get_logger()`
in all 8 files:

- `main.py`
- `db/neo4j.py`
- `db/queries.py`
- `kafka/producer.py`
- `kafka/consumer.py`
- `routers/costs.py`
- `services/cost_engine.py`
- `services/recommendations.py`

Also cleaned up:
- 4 unused imports removed
- 1 unused variable (`speed`) removed
- 2 `datetime.utcnow()` → `datetime.now(timezone.utc)` deprecation fixes

### Lesson

When adding a new service, check that the logging library matches the call-site style. The
`_template/` service correctly uses structlog, but `cost-service` was written with stdlib calls
using structlog-style kwargs.

---

## 2. Behaviour-focused test suite

### New test files

| File | Tests | Coverage |
|------|-------|----------|
| `tests/unit/test_cost_engine.py` | 49 | All pure calculator functions, aircraft family classification, running totals accumulation |
| `tests/unit/test_cost_recommendations.py` | 20 | All 4 recommendation types, threshold boundaries, net-benefit calculations, schema validation |
| `tests/unit/test_data_source_registry.py` | 31 | Protocol compliance, registration, switching, error handling, adapter retrieval |

**Total new tests: 100** (667 total across the project, all passing)

### Design principles applied

- Tests verify **observable behaviour**, not implementation details
- Each test class covers a single business concept
- `autouse` fixtures reset shared state (`_running_totals`) between tests
- Real `cost_rates.json` fixture loaded from service directory — no mocked config
- Adapter stubs implement the `DataSourceAdapter` protocol for type safety

---

## 3. Shared data-source framework

### Problem

Three services (weather, passenger, sim-orchestrator) each had independent, incompatible
implementations of data-source switching logic — different state shapes, different API responses,
no shared vocabulary.

### Solution

Created `services/_common/data_sources.py` with:

- **`DataSourceAdapter`** — Python `Protocol` defining `source_id`, `label`, `is_loaded`, `load()`
- **`SimulatedSourceAdapter`** — Default adapter (always loaded, no-op)
- **`DataSourceRegistry`** — Generic registry managing adapters per theme, with `register()`,
  `switch()`, `get_active()`, `list_sources()`, `info()` methods

### Integration

Each service wraps its existing source logic in a thin adapter class (3–5 lines) and initialises
a registry alongside its existing state. The registry's `_active` field is synced when the service
switches sources through its existing mechanism. This is **additive** — no existing behaviour
was changed.

Services integrated:
- `weather-service` — `_HistoricalAdapter`, `_LiveAdapter`
- `passenger-service` — `_BTSHistoricalAdapter`
- `sim-orchestrator` — `_ASRSHistoricalAdapter`

### Documentation

Updated `docs/architecture/DATA_SOURCES.md` with framework description and integration guide.

---

## 4. Code elegance

### conftest.py module isolation

The test `import_service_module()` function only cleared `services.*` and `db.*` module caches
between test imports. Added `kafka.*`, `routers.*`, and `metrics.*` to prevent cross-service
module collisions when multiple services share the same internal package names.

### Lint fixes

- Removed 10 unused imports across test files (auto-fixed by `ruff --fix`)
- Added `# noqa: E402` to 2 necessary post-`sys.path` imports

---

## CI validation

| Check | Result |
|-------|--------|
| `python -m ruff check services/ tests/ scripts/` | ✅ All checks passed |
| `npm run build` (api-gateway) | ✅ Clean compile |
| `npm run build` (art-dashboard) | ✅ Built in 7s (837 modules) |
| `python -m pytest tests/unit/ -q` | ✅ 667 passed in 1.2s |

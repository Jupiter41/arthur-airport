# Lessons Learned — 2026-05-22

## Tasks completed

- **Task 1**: Fixed BTS passenger flow showing 0 passengers
- **Task 2**: Fixed bottlenecks and recommendations always showing 0
- **Task 3**: Added demo incident injection button in AutonomousPanel
- **Task 4**: Implemented ROADMAP_PLANNING.md Phase 2 (P2.1–P2.3) + Phase 3 (P3.1–P3.3)

---

## Root cause: BTS 0-passenger bug

**Problem**: `bts_adapter.py` hardcoded `_home_iata = "LUX"` and sample data used `"LUX"` routes, but the airport is fictional `"ART"`. The `get_flow_at()` method filters by home airport → 0 matches → 0 passengers.

**Fix**: Default to `os.getenv("AIRPORT_IATA", "ART")`, generate sample data using `self._home_iata`, and add fallback logic: if loaded CSV has no matching home routes, supplement with sample data.

**Lesson**: When building adapters for a fictional airport, never hardcode a real airport IATA code as the default. Always derive from config.

---

## Root cause: 0-bottleneck bug

Three compounding issues:

1. **analysis-service was `full` profile only** — never ran in light mode (`docker compose up --build`), so bottleneck/recommendation endpoints returned nothing or 503.
2. **No incident-aware detector** — even when analysis-service ran, it had no detector for active incidents, so injected incidents produced 0 bottlenecks.
3. **Frontend silent errors** — AutonomousPanel fetched from analysis-service only; if it was down, errors were swallowed and 0 was displayed.

**Fix**: Removed `profiles: [full]` from analysis-service in docker-compose.yml. Added `_detect_active_incidents()` detector and `_recs_active_incident()` recommender. Made frontend query both analysis-service and cost-service as dual sources.

**Lesson**: Services that provide data to the main dashboard should never be gated behind optional profiles. Frontend should always show diagnostic info when a backend is unreachable.

---

## Planning Phase 2 architecture decisions

1. **Pure-function engine** — `PlanningSimEngine.run_day()` takes infrastructure config + adapter data, returns `DayResult`. No I/O, no Kafka, no Neo4j. Deterministic with same seed.

2. **Manual percentile calculation** — Used sorted-list interpolation instead of numpy to avoid adding a heavy dependency to planning-service. `aggregate_kpi()` is ~20 lines of pure Python.

3. **In-memory scenario store** — Scenarios and results stored in Python dicts (not Neo4j) for Phase 2. Neo4j persistence is a future task.

4. **Background task execution** — `POST /scenarios` returns 201 immediately, runs simulation via `BackgroundTasks` + `asyncio.to_thread()`.

5. **Performance** — 420-flight day simulates in < 500ms. 21 unit tests pass in < 1s.

---

## Port mismatch gotcha

planning-service runs on port **8009**, not 8008 as the SPEC says. cost-service already occupies 8008. The SPEC needs updating.

---

## Stats

- 21 new unit tests for planning engine (all pass)
- 722 total unit tests (all pass)
- `ruff check .` clean
- `npm run build` clean

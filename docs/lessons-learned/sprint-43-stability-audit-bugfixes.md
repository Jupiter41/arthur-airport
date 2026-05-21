# Sprint 43 — Stability Audit & Cross-Service Bug Fixes

**Date:** 2025-05-21  
**Focus:** Full codebase audit, silent failure prevention, BULK mode logic, cost data integrity, frontend hardening

---

## Changes Made

### 1. Silent Consumer Crash Prevention (All Services)

**Bug:** All Python services used bare `asyncio.create_task(run_consumer())` without a `done_callback`. If the Kafka consumer crashed (e.g. due to API mismatches — as happened with cost-service in sprint 42), the exception was silently swallowed and the service appeared healthy while producing no output.

**Fix:** Added `done_callback` error logging to all service consumer tasks:

| Service           | File    | Task                     |
| ----------------- | ------- | ------------------------ |
| flight-service    | main.py | `run_consumer()`         |
| flight-service    | main.py | `adsb.start_polling()`   |
| passenger-service | main.py | `run_consumer()`         |
| baggage-service   | main.py | `run_consumer()`         |
| weather-service   | main.py | `run_consumer()`         |
| incident-service  | main.py | `run_consumer()`         |
| sim-orchestrator  | main.py | `clock.run_clock_loop()` |
| cost-service      | main.py | _(already had it)_       |

**Pattern applied:**

```python
consumer_task = asyncio.create_task(run_consumer())

def _consumer_done(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("kafka consumer crashed", exc_info=exc)

consumer_task.add_done_callback(_consumer_done)
```

---

### 2. BULK→non-BULK Forced Flush Fix (flight, passenger, baggage)

**Bug:** When the simulation exits BULK mode (e.g. BULK→REALTIME), a final `BulkStateSnapshot` should be emitted to flush accumulated state to the dashboard. The function `_maybe_emit_*_bulk_snapshot()` had this logic:

```python
force = _state.last_mode == "BULK" and _state.current_mode != "BULK"
```

However, the function was only called inside `if is_bulk:`, which is `False` when leaving BULK mode. The force-flush was unreachable.

**Fix:** Changed the call site to also invoke on BULK→non-BULK transition:

```python
leaving_bulk = _state.last_mode == "BULK" and _state.current_mode != "BULK"
if is_bulk or leaving_bulk:
    await _maybe_emit_flight_bulk_snapshot(sim_time, status_counts)
```

Applied to:

- `services/flight-service/kafka/consumer.py`
- `services/passenger-service/kafka/consumer.py`
- `services/baggage-service/kafka/consumer.py`

---

### 3. sim-orchestrator Status Endpoint — Elapsed Time Fix

**Bug:** The `/api/v1/sim/status` endpoint returned:

```python
"real_elapsed_seconds": state["tick_number"],  # Wrong: tick_number = sim minutes
"sim_elapsed_minutes": state["tick_number"],   # Correct
```

`real_elapsed_seconds` was set to `tick_number` (which represents simulated minutes), making it semantically identical to `sim_elapsed_minutes`.

**Fix:**

```python
"real_elapsed_seconds": int(state["tick_number"] * 60 / max(state["speed_multiplier"], 1)),
"sim_elapsed_minutes": state["tick_number"],
```

At 60× speed: 163 ticks → 163 sim minutes → 163 real seconds.

---

### 4. Cost Data Integrity — Sanity Guard

**Bug:** Corrupt `CostRecord` nodes with amounts of €150 quadrillion were persisted from a previous session where cost rates had been patched to extreme values via the rate editor. The `rebuild_running_totals()` function summed all records, producing absurd totals (€2.5 × 10¹⁹).

**Fix:**

1. Deleted 1,378 corrupt records: `MATCH (c:CostRecord) WHERE c.amount_eur > 10000000 DETACH DELETE c`
2. Added sanity guard in `cost_engine.py`:

```python
MAX_SINGLE_COST_EUR = 1_000_000

async def _write_and_emit(record, ...):
    if abs(record["amount_eur"]) > MAX_SINGLE_COST_EUR:
        logger.warning("cost record exceeds sanity limit — skipped", ...)
        return
```

**Result:** Cost summary went from €2.5×10¹⁹ → €5M (correct).

---

### 5. Frontend Fixes

| Issue                             | File                  | Fix                                                                                |
| --------------------------------- | --------------------- | ---------------------------------------------------------------------------------- |
| Timer leak in CostRateModal       | CostRateEditor.tsx    | Added `useRef` + `useEffect` cleanup for feedback timeout                          |
| Null crash on `avg_delay_minutes` | ScenariosPage.tsx     | Added `?? 0` fallback: `(active.latest_metrics.avg_delay_minutes ?? 0).toFixed(1)` |
| Unsafe type casts in comparisons  | SourceComparisons.tsx | Replaced `as number` casts with `Number(...) \|\| 0`                               |
| `res.json()` crash on 204         | useApi.ts             | Added guard for 204/empty responses: return `undefined`                            |

---

## Verification

- **Ruff:** `python -m ruff check services/` → All checks passed
- **TypeScript:** `npx tsc --noEmit` → Clean (exit 0)
- **Vite build:** `npm run build` → Success (exit 0)
- **Docker:** All 10 services healthy after rebuild
- **Cost validation:** Summary shows €5M costs / €3.7M revenue (correct)
- **Sim status:** `real_elapsed_seconds` and `sim_elapsed_minutes` now diverge correctly

---

## Key Lessons

1. **`asyncio.create_task()` without error handling is a silent failure landmine.** This is the second time it has caused a production-invisible crash (sprint 42: cost-service consumer, now: systemically present in all services). Establishing a project-wide pattern of always adding a `done_callback` prevents entire categories of debugging sessions.

2. **Guard conditional blocks must not gate the transition logic they contain.** The BULK snapshot was gated by `if is_bulk:` but contained transition-exit logic (`force = last_mode == "BULK" and current_mode != "BULK"`). Transition guards should be separate from steady-state guards.

3. **Cost sanity limits are essential when rates are user-configurable.** A €1M ceiling per record is reasonable for any single-flight cost. Without it, a rate editor mistake can corrupt the entire financial history irreversibly.

4. **TypeScript `as T` casts hide null/undefined at runtime.** Replace `value as number` with `Number(value) || 0` for defense-in-depth when consuming API responses with optional fields.

5. **Timer/timeout memory leaks in React modals:** Always store timer IDs in `useRef` and clear in an `useEffect` cleanup. Modals can close before timeouts fire, triggering setState-after-unmount warnings.

---

## Known Issues (Not Fixed — Documented for Future)

| #   | Issue                                                                 | Severity | Location         |
| --- | --------------------------------------------------------------------- | -------- | ---------------- |
| 1   | `gate_fee` cost never triggered — no gate release event consumed      | Medium   | cost_engine.py   |
| 2   | Staffing costs use hardcoded resource counts instead of Neo4j queries | Low      | cost_engine.py   |
| 3   | Retail revenue uses hardcoded airside pax counts                      | Low      | cost_engine.py   |
| 4   | `_last_staffing_hour` not rebuilt from Neo4j on restart               | Low      | cost_engine.py   |
| 5   | Scenario reset opens new Neo4j session per loop iteration             | Low/Perf | sim-orchestrator |
| 6   | WebSocket connect failures silently swallowed in most services        | Low      | \*/main.py       |
| 7   | Consumer thread in sim-orchestrator not joined on shutdown            | Low      | sim-orchestrator |

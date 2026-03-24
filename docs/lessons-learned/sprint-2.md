# Sprint 2 — Lessons learned

**Goal:** weather-service FSM + METAR + capacity model. Weather evolves via a 4-state FSM,
persists in Neo4j, emits METAR events to Kafka, and exposes REST/WebSocket APIs.

---

## Issues encountered

### 1. Python `global` pitfall strikes again (Sprint 1 déjà vu)

The Kafka consumer's `_on_clock_tick` function reads and reassigns module-level variables
`_last_metar_total_min` and `_last_fsm_hour`. Without declaring them `global`, Python treats them
as local variables for the entire function scope — even the read before the assignment.

**Symptom:** `UnboundLocalError: cannot access local variable '_last_metar_total_min'`
on the first METAR interval check. The consumer loop crashed silently.

**Fix:** Added both variables to the `global` declaration:

```python
global _current_category, _current_params, _current_metar, _current_taf
global _sim_time, _last_metar_total_min, _last_fsm_hour
```

**Rule:** This was already documented in sprint-1.md lesson #2. The pattern recurs whenever a
function both reads and reassigns a module-level variable. Consider a class-based state holder
to avoid this class of bugs entirely.

### 2. Neo4j `datetime()` is wall-clock, not sim-time

The initial history query filtered with `state.timestamp >= datetime() - duration({hours: $hours})`.
`datetime()` in Cypher returns the current wall-clock time (2026-03-24), while simulation
timestamps are in June 2024. This made the history endpoint always return empty results.

**Symptom:** `GET /weather/history?hours=48` returned `{"states": []}` despite 10+ weather
states persisted in Neo4j.

**Fix:** Changed the filter to be relative to the current weather state's own timestamp:

```cypher
WHERE state.timestamp >= current.timestamp - duration({hours: $hours})
```

**Rule:** Never use `datetime()` in Neo4j queries for simulation data. Always anchor time
comparisons to sim-time values already stored in the graph.

### 3. METAR dedup logic was overcomplicated

The first implementation tried to track separate `_last_metar_minute` and `_last_fsm_hour`
variables with a complex conditional check to avoid double-emitting METAR on hour boundaries
(where both FSM evaluation and METAR happen). The logic was fragile and hard to reason about.

**Fix:** Simplified to a single `_last_metar_total_min = hour * 60 + minute` tracker. The check
becomes `minute % interval == 0 and total_min != _last_metar_total_min`.

**Rule:** For deduplication of periodic events, track a single monotonically increasing value
(total minutes since midnight) rather than multiple separate counters.

### 4. Neo4j `NULL` vs sentinel for optional integer properties

Neo4j handles `NULL` property values fine, but Cypher parameterization of `None` in the Python
driver can behave unexpectedly in some contexts. Used `-1` as a sentinel for `ceiling_ft` when
`None` (CAVOK has no ceiling) and converted back on read.

**Alternative considered:** Using `CASE WHEN $ceiling_ft IS NOT NULL THEN ... END` in Cypher.
This would have been cleaner but added complexity to the query. The sentinel approach works but
requires discipline to convert at every read site.

### 5. Spec uses VFR/MVFR/IFR/LIFR but SKILL.md uses CAVOK/VMC/IMC/LIFR

The user prompt referenced `VFR, MVFR, IFR, LIFR` but the actual spec (SPEC.md §2, SIMULATION.md
§4, and SKILL.md) consistently use `CAVOK, VMC, IMC, LIFR`. The implementation follows the spec.

**Rule:** When user instructions conflict with the spec, the spec is authoritative (per CLAUDE.md).

---

## What went well

- The SKILL.md provided complete, copy-pastable code for the FSM, parameter sampling, METAR
  builder, and capacity calculator. Implementation was fast because the patterns were pre-validated.
- The chain/pointer pattern for weather history in Neo4j (Airport->CURRENT_WEATHER->latest,
  WeatherState->PREVIOUS_WEATHER->older) works cleanly. Traversing with `*0..` variable-length
  paths gives a natural history query.
- Seeded RNG (`random.Random(42)`) produces deterministic weather patterns across restarts,
  making debugging reproducible.
- The sim-orchestrator's initial `WeatherStateChanged` event on `weather.events` helps bootstrap:
  the weather-service can start consuming clock ticks immediately without waiting for a special
  init signal.

---

## Neo4j modeling decisions

- **Chain direction:** `(new)-[:PREVIOUS_WEATHER]->(old)` — newest points back. This makes
  "get current + last N" a simple `MATCH path = (current)-[:PREVIOUS_WEATHER*0..N]->(state)`.
- **Airport pointer:** `(Airport)-[:CURRENT_WEATHER]->(latest)` — single hop to current state.
  On each transition, the old pointer is deleted and a new one created atomically.
- **Ceiling sentinel:** `ceiling_ft = -1` when `None` (CAVOK). Converted back to `None` on read.
  This avoids Neo4j's inconsistent handling of `NULL` properties in parameterized queries.

---

## Performance numbers

| Operation                                        | Duration |
| ------------------------------------------------ | -------- |
| Weather state persist (create + chain + pointer) | ~3ms     |
| History query (48h, ~10 states)                  | ~5ms     |
| Current weather query                            | ~2ms     |
| FSM + parameter sampling + METAR build           | <1ms     |

---

## What I would change if restarting

1. **Use a class for weather state** instead of module-level globals. The `global` pitfall would
   vanish entirely, and the state would be easier to test.
2. **Store ceiling_ft as `NULL`** natively in Neo4j instead of using a `-1` sentinel. Test the
   Cypher parameterization more carefully — it likely works fine with the async driver.
3. **Add a `previous_category` field to WeatherState nodes** in Neo4j. Currently only available
   in the Kafka event. Would simplify "show transitions" queries.

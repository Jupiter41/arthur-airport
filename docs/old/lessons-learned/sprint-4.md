# Sprint 4 — Lessons learned

**Goal:** baggage-service with multi-zone conveyor pipeline, dangerous goods screening,
flight cancellation offload, system failure halt/resume, Kafka consumer/producer, REST API,
and WebSocket.

---

## Issues encountered

### 1. Induction timing — bags stuck in `dropped_off`

The initial `get_dropped_off_baggage_for_departures()` Neo4j query filtered for flights in
`['scheduled', 'boarding', 'delayed']` status. By the time baggage-service started consuming
`SimClockTick` events, the sim-orchestrator had already seeded all day-1 flights and advanced
the clock far enough that every departure flight had reached `airborne`. The query returned
zero bags on every tick.

**Symptom:** All 42,355 bags remained in `dropped_off` status indefinitely. The induction,
screening, sorting, and loading zones were permanently empty.

**Fix:** Two changes:

1. Broadened the query to include all non-cancelled departure flights (removed flight status
   filter entirely).
2. Added fast-track logic: bags linked to flights that have already departed (`airborne`,
   `departed`, `landed`, `arrived`) skip the conveyor pipeline and go directly to `in_hold`.

```python
# Fast-track: already-departed flights → skip pipeline
if flight_status in ("airborne", "departed", "landed", "arrived"):
    await update_baggage_status(tag, "in_hold", sim_time)
    await emit_baggage_status_changed(tag, "dropped_off", "in_hold", flight_id, sim_time)
    continue
```

**Rule:** Never assume a particular ordering between service startup and simulation clock
progress. Services must handle the case where they start mid-simulation with historical data
already materialized. Query filters on entity status should be lenient at induction boundaries
and strict at transition boundaries.

### 2. Kafka event envelope field naming — `sim_time` not `timestamp`

When injecting a test `IncidentCreated` event, the consumer silently discarded it. The
consumer's `_dispatch()` method extracts `envelope.get("sim_time")` and returns early if it's
missing. The injected event used `timestamp` as the field name instead of `sim_time`.

**Symptom:** Injected incident event produced to `incidents.events` topic, confirmed via Kafka
UI, but baggage-service showed no reaction. No error logs (the event was silently dropped by
the null check on `sim_time_str`).

**Fix:** Changed the test event envelope to use the correct `sim_time` field name matching the
`EventEnvelope` model.

**Rule:** The event envelope contract (`EventEnvelope` Pydantic model) is authoritative for
field names. All producers — including test scripts and integration harnesses — must use the
exact same field names. Consider adding a `logger.debug()` when events are dropped for
missing required envelope fields to aid future debugging.

### 3. `incidents.events` topic not pre-created — harmless but noisy warnings

The baggage-service consumer subscribes to `incidents.events` at startup. If the
incident-service hasn't produced any events yet, Kafka returns `UNKNOWN_TOPIC_OR_PART` errors
in the consumer logs. These are non-fatal — Kafka auto-creates the topic when the first
message is produced — but they clutter the startup logs.

**Symptom:** Repeated `UNKNOWN_TOPIC_OR_PART: incidents.events` warnings during the first few
minutes of service startup.

**Fix:** No code change needed (self-resolves). Documented as expected behavior.

**Rule:** For topics that may not exist at consumer startup time, accept that
`UNKNOWN_TOPIC_OR_PART` warnings are normal. Alternatively, ensure all topics are pre-created
in `docker-compose.yml` via the Kafka init container (preferred for production-like setups).

### 4. Terminal output buffer overflow during Docker builds

Long Docker compose builds fill the terminal scrollback buffer. After `docker compose up
--build`, the build output from all 8+ services consumes so much buffer that subsequent
command outputs (e.g., `curl` results) are pushed out of view immediately.

**Symptom:** Commands appear to produce no output because their results scroll past before
they can be read.

**Fix:** Redirect all verification command output to files (`> /tmp/result.txt`) and read
files afterward. Also use `docker compose up --build -d` (detached mode) to avoid interleaved
build output.

**Rule:** When running multi-service Docker builds followed by verification commands, always
redirect output to files or use detached mode. Never rely on terminal scrollback for result
capture.

### 5. Conveyor throughput modeling — zone ordering matters

The `advance_tick()` method processes zones in reverse pipeline order: arrival → make-up →
sorting → screening → induction. This prevents artificial buildup at intermediate zones.
If zones were processed front-to-back (induction first), bags would enter screening before
screening had a chance to drain, causing unrealistic queue inflation.

**Symptom:** No bug (caught during design), but worth documenting the reasoning.

**Rule:** In pipeline simulations, always drain downstream zones before filling upstream ones.
This ensures each zone has capacity to accept output from the zone before it.

---

## Design decisions

### Zone-based in-memory conveyor vs Neo4j-only tracking

Bags in transit through the conveyor are tracked in-memory (`ConveyorSystem` with per-zone
`deque` queues) rather than writing every zone transition to Neo4j. Only terminal state
transitions (`dropped_off` → `inducted`, `screening` → `flagged`, `sorting` → `loaded`, etc.)
are persisted to Neo4j and emitted as Kafka events.

**Rationale:** At 31 zones processing up to 600 bags/hour each, writing every zone hop to
Neo4j would generate thousands of writes per tick. The in-memory model provides sub-millisecond
zone transitions while Neo4j captures the audit trail for durable state.

**Tradeoff:** Zone contents are lost on service restart. This is acceptable because:

- Bags in zones can be re-inducted on next startup from their Neo4j-stored status
- The conveyor is a transient processing pipeline, not a source of truth

### DG detection rates as per-class constants

Detection rates are hardcoded per DG class (class 2: 0.88, class 3: 0.91, class 8: 0.95,
class 9: 0.72) rather than configurable via environment variables. Only the false positive
rate is env-configurable (`FALSE_POSITIVE_RATE`).

**Rationale:** The per-class rates model real-world screening equipment capabilities and should
only change if the simulation model changes. The false positive rate is more likely to be
tuned during testing.

### Batch induction limit (500 bags per tick)

The `_induct_new_bags()` function limits induction to 500 bags per tick to prevent CPU spikes
from processing thousands of bags in a single clock event.

**Rationale:** With 42,000+ bags and 30-second tick intervals, processing all eligible bags
at once would block the consumer loop. The 500-bag batch limit spreads the work across
multiple ticks while maintaining realistic throughput (500 bags per 30 seconds ≈ 60,000/hr,
far exceeding the 1,800/hr combined induction capacity of 3 belts).

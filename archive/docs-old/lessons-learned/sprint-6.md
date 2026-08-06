# Lessons learned — Sprint 6 (incident-service)

## Cascade complexity

1. **Cascade depth tracking per-chain** — Each incident chain tracks its own depth counter
   independently. Two simultaneous incidents at depth 0 do not share counters. The cascade
   engine passes `cascade_depth + 1` to each child, and the child carries that forward.

2. **Linear cascade chains dominate** — In practice, cascade rules produce linear chains
   (runway_incursion → runway_closure_holding_stack → departure_ground_stop → gate_congestion).
   Branching cascades (one parent spawning multiple children) are theoretically possible but
   rare with the current rule table. This simplifies the tree-building logic in the REST API.

3. **Cascade tree reconstruction from Neo4j** — Building a hierarchical tree from flat
   `SPAWNED*0..5` query results requires grouping by depth and linking by location. The
   location-based heuristic works for single-chain cascades but would need SPAWNED relationship
   traversal for multi-branch trees.

---

## Cycle prevention

4. **Set-based dedup is sufficient** — Using a `_cascaded_incidents: set[str]` to track which
   parent IDs have already been cascaded prevents infinite loops. Each incident ID is unique
   (UUID), so the same incident cannot cascade twice. This is simpler and more reliable than
   graph-based cycle detection (which would need full traversal).

5. **Set memory growth** — The dedup set grows unbounded in long simulations. Added a simple
   eviction strategy: when the set exceeds 50,000 entries, discard the oldest half. In practice,
   even at 3600× speed for days, the set stays well below this threshold.

---

## TTR timing

6. **TTR counts down once per SimClockTick (1 sim-minute)** — This means a TTR of 15 sim-minutes
   takes exactly 15 ticks to resolve. At 60× speed, that's 15 real seconds — fast enough for
   testing, slow enough to observe.

7. **`None` TTR for weather and congestion** — Severe weather and security congestion incidents
   have `ttr_remaining = None` and are auto-resolved by external signals (WeatherStateChanged → VMC,
   or congestion clearing). The `tick_ttr` function correctly skips these.

8. **Children auto-resolve with parent** — When a parent resolves, `resolve_children()` runs a
   single Cypher query that sets `status = 'resolved'` on all descendant incidents. This avoids
   orphaned active children after the root cause is resolved.

---

## Protocol activation

9. **Protocol mapped by type+severity** — Simple dict lookup (`PROTOCOLS[type][severity]`).
   Only 6 protocol codes exist. System failures and security congestion have empty protocol
   strings, which is intentional — they don't trigger emergency protocols.

10. **IncidentAlert on every status change** — Per spec, alerts fire on creation AND on every
    status transition (contain, resolve). This ensures dashboards update in real-time. The alert
    payload includes severity, protocol, and dashboard color.

---

## Kafka ordering and duplication

11. **Idempotency via `event_id` set** — Same pattern as all other services. Maximum 20,000
    entries with eviction. Works well because the consumer group offset is "latest" and we don't
    replay history.

12. **Consumer processes 5 topics** — More topics than any other service. No ordering issues
    because each topic handles independent concerns (clock, inject, weather, baggage, passengers).

13. **Cascaded events produced synchronously** — When `create_incident()` cascades, it produces
    `IncidentCreated`, `IncidentAlert`, and `IncidentCascaded` events serially in a single tick.
    This means a deep cascade generates multiple events within one SimClockTick. At depth 4
    (runway_incursion full chain), that's 12+ events in one tick — not a bottleneck.

---

## Report generation

14. **Reports are generated on-demand, not stored** — `build_report()` queries Neo4j every time.
    For resolved incidents, the data is stable, so caching would be an obvious optimization.
    For active incidents, the report reflects current state (flights affected so far, cascade
    count so far).

15. **`total_flights_affected` is 0 for non-connected incidents** — The AFFECTS relationship
    is not created automatically because incident-service does not write to Flight nodes (domain
    ownership). The count relies on other services creating AFFECTS edges, which doesn't happen
    automatically in the current architecture. A future improvement would be to have flight-service
    create these relationships when it receives IncidentCreated events.

---

## Python global variable pitfall (fourth occurrence!)

16. **`UnboundLocalError` on `_ws_clients -= disconnected`** — Python treats `_ws_clients` as a
    local variable in `ws_broadcast()` because of the augmented assignment operator (`-=`). Fixed
    by adding `global _ws_clients`. This is the same bug documented in sprint-3 and sprint-5.
    Consider adding a linting rule to catch this pattern.

---

## What I would redesign

- **AFFECTS relationships** — Have incident-service create AFFECTS relationships to flights by
  reading runway assignments from Neo4j (read-only) when an incident is created at a runway.
  Currently, the `total_flights_affected` in reports is always 0 unless another service creates
  the edges.

- **Cascade delay** — The `delay_sim_min` field in cascade rules is currently ignored (all
  cascades fire instantly). Implementing delayed cascades would require a pending-cascade queue
  checked on each tick, adding complexity for marginal realism.

- **Alert lifecycle** — Alerts accumulate in memory with no expiry. A max age or resolution-based
  cleanup would prevent the alert list from growing unbounded during long simulations.

- **Protocol conflict resolution** — The spec mentions `FULL_EVACUATION` overrides all others,
  but the current implementation doesn't track active protocols globally. Each incident
  independently activates its protocol. A global protocol state manager would be needed for
  true override semantics.

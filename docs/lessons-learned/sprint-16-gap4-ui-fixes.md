# Sprint 16 — Gap 4 Baggage Conveyor + UI/UX Fixes

**Date:** 2025-07-14

---

## Summary

Implemented remaining Gap 4 ROADMAP items (GAP-4-5 through GAP-4-8) for the baggage conveyor
system, fixed multiple frontend bugs (Mapbox, Leaflet, flight board, passenger flow), added a
terminal activity panel to Ground Ops, and resolved a Neo4j property warning.

---

## Changes made

### Backend — baggage-service

| File                   | Change                                                                                                                                                                                                                                                                  |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `kafka/consumer.py`    | Terminal-based arrival carousel assignment via `arrival_carousel_for_terminal()` instead of `hash(flight_id) % 6 + 1`. Added conveyor delay detection every 5 ticks: checks overloaded make-up zones and emits `ConveyorDelay` events. Per-segment load metric updates. |
| `kafka/producer.py`    | New `emit_conveyor_delay()` function — emits `ConveyorDelay` event type on `baggage.events` topic.                                                                                                                                                                      |
| `services/conveyor.py` | Added `overflow_count` field and `is_overloaded` property to `ZoneState`. New `get_overloaded_makeup_zones()` method on `ConveyorSystem` — returns zones exceeding 5-minute throughput capacity with estimated delay.                                                   |
| `services/spatial.py`  | `arrival_carousel_for_terminal()` now used for carousel routing (GAP-4-7).                                                                                                                                                                                              |
| `routers/baggage.py`   | Fixed `conveyor_status` endpoint: `get_zone_summary()` returns `list[dict]`, not `dict` — was crashing on `.values()`.                                                                                                                                                  |
| `metrics.py`           | Added 3 new Prometheus metrics: `conveyor_segment_load` (Gauge, zone_id), `conveyor_transit_queue` (Gauge), `conveyor_delay_total` (Counter, terminal).                                                                                                                 |

### Backend — sim-orchestrator

| File                   | Change                                                                                                                |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `services/schedule.py` | Added `arrival_estimated_time: null` to CREATE Flight Cypher query — fixes Neo4j warning about non-existent property. |

### Frontend — dashboards/art-dashboard

| File                    | Change                                                                                                                                                                                                                                       |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.env` (new)            | Created with `VITE_MAPBOX_TOKEN` — Vite reads `.env` from its own project root, not the repo root.                                                                                                                                           |
| `Dockerfile`            | Added `ARG/ENV VITE_MAPBOX_TOKEN` so Docker builds also pass the token.                                                                                                                                                                      |
| `WorldMapPage.tsx`      | Leaflet fallback: replaced `L.circleMarker` dots with `L.divIcon` containing rotated SVG plane icons (matches heading). Enhanced flight detail panel: status colors, delay bars, scheduled/estimated times, passenger count, route category. |
| `FlightBoardPage.tsx`   | Fixed strikethrough condition: now compares `formatTime(estimated) !== formatTime(scheduled)` instead of just `delay_minutes > 0`. Prevents showing ~~12:30~~ 12:30 when times are the same.                                                 |
| `PassengerFlowPage.tsx` | KPIBar shows overall capacity percentage with progress bar. Security queue chart split into dual layout (queue depth + wait time side by side). ZoneCell shows remaining slots. ZoneDetailPanel has capacity progress bar with color coding. |
| `GroundOpsPage.tsx`     | New `TerminalActivityPanel` component: per-terminal gate view with assigned flight, PAX boarding progress bar, BAG loading progress bar, flight details (direction, destination, aircraft, delay).                                           |
| `types.ts`              | Added `seat_capacity: number` to `Flight` interface.                                                                                                                                                                                         |

### Infrastructure / docs

| File                                 | Change                                                                                                                             |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `docker-compose.yml`                 | Dashboard build uses `args: { VITE_MAPBOX_TOKEN }` to pass token into Docker build context.                                        |
| `docs/infra/MONITORING.md`           | Added `conveyor_segment_load`, `conveyor_transit_queue`, `conveyor_delay_total`, `envelope_invalid_total` to §3.4 Baggage metrics. |
| `tests/unit/test_metric_contract.py` | Added the 3 new baggage metrics to `EXPECTED_METRICS` catalogue.                                                                   |
| `ROADMAP.md`                         | Marked GAP-4-5, GAP-4-6, GAP-4-7, GAP-4-8 as done.                                                                                 |

---

## Issues found and fixed

1. **Mapbox token not loading** — Vite reads `.env` from its own project root (`dashboards/art-dashboard/`), not the repo root. The token was in `/.env` but Vite never saw it. Fix: created `dashboards/art-dashboard/.env`.

2. **Leaflet fallback showed dots, not planes** — The Leaflet fallback path used `L.circleMarker` which renders as colored dots. Fix: switched to `L.divIcon` with an inline SVG `<path>` of a plane silhouette, rotated via CSS `transform: rotate(${heading}deg)`.

3. **Strikethrough times when estimated = scheduled** — `delay_minutes > 0` could be true due to rounding while `formatTime(estimated)` and `formatTime(scheduled)` showed the same value, creating a confusing ~~12:30~~ 12:30 display. Fix: added `formatTime(est) !== formatTime(sched)` to the condition.

4. **Neo4j property warning** — `arrival_estimated_time` was accessed in queries but never set on flight creation. Fix: initialized to `null` in the CREATE Cypher.

5. **Carousel hash routing** — `hash(flight_id) % 6 + 1` spread arrivals across all carousels regardless of terminal. Fix: used `arrival_carousel_for_terminal()` which maps terminal A→1-2, B→3-4, C→5-6.

6. **conveyor_status endpoint crash** — `get_zone_summary()` returns `list[dict]`, but the router called `.values()` on it (dict method). Fix: iterate over the list directly.

7. **Metric contract test failure** — New metrics in `metrics.py` weren't in the test's `EXPECTED_METRICS` dict or MONITORING.md. Fix: added to both.

---

## Tests run

| Suite                                   | Result        |
| --------------------------------------- | ------------- |
| `ruff check` (Python lint)              | ✅ Pass       |
| `npx tsc --noEmit` (TypeScript)         | ✅ Pass       |
| `npm run build` (Vite production build) | ✅ Pass       |
| `pytest tests/unit/ -x -q`              | ✅ 476 passed |

---

## Remaining Gap 4 items

- **GAP-4-1** — Model conveyor topology as directed graph in Neo4j (structural, requires Neo4j schema changes + seed data)
- **GAP-4-2** — Assign check-in zones to induction belts in fixture data (depends on GAP-4-1)

These are architectural and involve Neo4j schema additions. Best approached as a dedicated sprint.

---

## Key learnings

- **Vite `.env` location matters**: always place `.env` in the Vite project root, not the monorepo root. For Docker, pass the token as a build arg.
- **Leaflet `L.divIcon` is the right tool for custom markers**: it accepts raw HTML, so you can embed rotated SVGs with no image dependencies.
- **Metric contract tests are strict**: any new Prometheus metric must be added to both `MONITORING.md` and the `EXPECTED_METRICS` dict in `test_metric_contract.py`.
- **Always compare formatted time strings** for display decisions, not raw numeric fields — rounding and timezone formatting can make "different" values look identical.

# Sprint 27 — FIDS Status, Baggage Belt, World Map Fixes

**Date**: 2025-07-15  
**Scope**: Three UI/backend bugs from PROMPT.md

---

## Bug 1: "All departed and arrived flights shown as Arrived"

**Root cause**: The FSM correctly transitions departure flights to `arrived` when
they reach their destination. The `StatusBadge` component rendered every
`arrived` status identically, regardless of direction.

**Fix** (dashboard only):
- `StatusBadge.tsx` — added `direction` prop; when `status === "arrived"` and
  `direction === "departure"`, the label reads **COMPLETED** instead of ARRIVED.
- `FlightBoardPage.tsx` — passed `direction` to every `<StatusBadge>` call
  (FlightRow, FlightDetailDrawer) and added a "Completed" counter in
  `FlightStats` with its own `<StatPill>`.

**Lesson**: The FSM was working correctly. The bug was purely presentational.
Always check whether the display layer distinguishes semantically different
states before modifying service code.

---

## Bug 2: "Arrival belts 100% — no baggage operations"

**Root cause** (two issues):

1. **Stale dashboard data** — `useBaggageTrackerQueries()` had no
   `refetchInterval`. The dashboard fetched zone data once on mount, showed the
   peak-arrival snapshot (100 %), and never refreshed.
2. **Premature status jump** — When a flight reached `at_gate`, every bag was
   immediately set to `on_carousel` in Neo4j *and* placed in the in-memory
   conveyor queue. The conveyor drains at 10 bags/belt/tick, but Neo4j already
   showed all bags as `on_carousel`, creating a disconnect: "100 % belt but no
   operations visible".

**Fix**:
- `useQueries.ts` — added `refetchInterval: 5_000` to the `map`, `summary`, and
  `flagged` queries so the dashboard polls every 5 s.
- `consumer.py` — bags now transition `in_hold → arrived` (queued on belt). The
  conveyor drain handler performs `arrived → on_carousel → collected` when the
  belt processes each bag, keeping Neo4j and the in-memory queue in sync.

**Lesson**: Real-time dashboards must always have a `refetchInterval` (or
WebSocket push) to avoid stale snapshots. Status transitions in the database
should mirror the physical process: don't jump to a downstream state before the
conveyor actually processes the item.

---

## Bug 3: "World map doesn't display"

**Root cause**: If the Mapbox access token is invalid or expired, the map
constructor fires but the `load` event never arrives. No error handler existed,
so the component rendered an empty container with no fallback.

**Fix** (`WorldMapPage.tsx`):
- Added `mapboxFailed` state, used to toggle `hasMapboxToken` to `false`.
- Added `map.on("error", ...)` handler: detects token / auth / style errors →
  removes the broken map instance → sets `mapboxFailed = true`, which triggers a
  re-render that takes the Leaflet fallback path.
- Added a 10 s timeout: if `map.loaded()` is still `false` after 10 s, the same
  fallback fires (covers network-hang scenarios).

**Lesson**: Always pair external-service initialization with an error handler
and a timeout fallback. A valid-looking token can expire at any time; the UI
must degrade gracefully.

---

## Files changed

| File | Change |
|------|--------|
| `dashboards/art-dashboard/src/components/StatusBadge.tsx` | Added `direction` prop, "COMPLETED" label |
| `dashboards/art-dashboard/src/pages/FlightBoard/FlightBoardPage.tsx` | Pass `direction`, add Completed stat pill |
| `dashboards/art-dashboard/src/hooks/useQueries.ts` | `refetchInterval: 5_000` on baggage queries |
| `services/baggage-service/kafka/consumer.py` | Two-step arrival belt flow (`arrived` → `on_carousel` → `collected`) |
| `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx` | Mapbox error handler + timeout fallback to Leaflet |

## CI status

- `ruff check services/` — all passed
- `npm run build` (dashboard) — built successfully
- `tsc --noEmit` — no type errors

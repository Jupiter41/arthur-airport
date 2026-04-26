# Lessons Learned — Sprint 26: Dashboard Fixes (Heatmap, Weather, Vehicle Depot, Pax Counts)

**Date**: 2026-04-25  
**Scope**: flight-service, passenger-service, dashboard (GroundOpsPage, PassengerFlowPage)

---

## Issues Fixed

### 1. Airborne flights showing 0 passengers / 0 baggage

**Root cause**: The `pax_boarded` Cypher query in `flight-service/db/neo4j.py` only counted passengers with `status = 'boarded'`. After a flight departs, passengers transition from `boarded` → `departed_airport`, so the count drops to near-zero.

**Fix**: Changed the query to count both statuses:
```cypher
-- Before
sum(CASE WHEN p.status = 'boarded' THEN 1 ELSE 0 END) AS pax_boarded

-- After
sum(CASE WHEN p.status IN ['boarded', 'departed_airport'] THEN 1 ELSE 0 END) AS pax_boarded
```

Applied to both `get_all_flights()` (list query) and `get_flight_by_id()` (detail query). The `get_boarded_percentage()` function was NOT changed — it correctly counts only `boarded` status for the FSM's boarding threshold check.

**Validation**: BA573 (arrived departure, 167 pax) — old: 0, new: 167.

### 2. Airport Heatmap zones at 473%+ capacity

**Root cause**: Zone capacity constants in `passenger-service/services/zones.py` were far too low for the simulation's throughput. With ~420 flights/day and ~50K passengers:

| Zone | Old Capacity | Observed Peak | New Capacity |
|---|---|---|---|
| check-in-A/B/C | 200 | ~2,350 | 2,000 |
| security-A/B/C | 120 | ~378 | 500 |
| airside-A/B/C | 800 | ~1,621 | 2,000 |
| carousel-1..6 | 150 | ~1,431 | 400 |
| baggage-claim | 900 | — | 1,500 |
| customs | 500 (default) | ~749 | 800 |

**Fix**: Updated `ZONE_CAPACITIES` dict and `DEFAULT_CAROUSEL_CAPACITY` to match observed simulation peaks. These values represent comfortable maximum occupancy; the heatmap turns red above ~85%.

**Validation**: check-in-A went from 473.5% → 26.1%, security-A from 207.5% → 35.4%.

### 3. Vehicle Depot box overflow

**Root cause**: The SVG depot box was 120px wide with 5 vehicle types at 24px spacing = 120px total content — items overflowed the box boundaries.

**Fix**: Widened box from 120×40 to 180×48 px, increased item spacing from 24px to 34px, shifted Y position up slightly to prevent bottom clipping.

**File**: `dashboards/art-dashboard/src/pages/GroundOps/GroundOpsPage.tsx`

### 4. Weather legend not clear

**Root cause**: The weather panel showed only aviation category acronyms (CAVOK, VMC, IMC, LIFR) without explaining what they mean. Non-aviation users had no way to interpret them.

**Fix**:
- Added human-readable descriptions below each category badge (e.g., "Clear skies, visibility >10 km")
- Added visibility and ceiling values to the detail section
- Added a 4-line category legend at the bottom with color-coded dots and descriptions
- Current category is highlighted in white/bold

**File**: `dashboards/art-dashboard/src/pages/GroundOps/GroundOpsPage.tsx`

---

## Files Modified

| File | Change |
|---|---|
| `services/flight-service/db/neo4j.py` | `pax_boarded` counts `departed_airport` status too |
| `services/passenger-service/services/zones.py` | Zone capacities scaled to sim throughput |
| `dashboards/art-dashboard/src/pages/GroundOps/GroundOpsPage.tsx` | Vehicle depot wider, weather legend with descriptions + visibility/ceiling |

## CI Results

- `ruff check services/` — All checks passed
- `npx tsc --noEmit` — No errors
- `npm run build` — Build succeeded (10s)

## Key Takeaway

Display queries and FSM queries serve different purposes. The flight FSM needs `status = 'boarded'` to evaluate boarding progress. The display API needs `status IN ['boarded', 'departed_airport']` to show how many passengers actually boarded before the flight departed. Always distinguish between "operational" and "informational" queries.

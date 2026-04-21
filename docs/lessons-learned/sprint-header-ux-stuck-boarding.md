# Sprint — Header UX & Stuck Boarding Flights

**Date:** 2026-04-21  
**Status:** Completed

---

## Issues Fixed

### 1. Dropdown menus not appearing in header

**Root cause:** The top-level `AppShell` container in `App.tsx` had `overflow-hidden`, which clipped absolute-positioned dropdown menus extending below the header.

**Fix:** Removed `overflow-hidden` from the outer `div.h-screen` in `AppShell`. The `main` content area retains its own `overflow-hidden` so page content is still properly contained.

**File:** `dashboards/art-dashboard/src/App.tsx`

### 2. Header too cluttered / export button unclear

**Root cause:** All status indicators (weather, connection, incidents, sim clock, sim controls, export) plus nav + logo were crammed into a single flex row with no visual grouping. The export button showed only a `⬇` symbol with no label.

**Fix:**

- **Three-zone layout**: Left (logo + nav), center (weather, hidden below `xl`), right (status + controls)
- **Visual separators**: Added `w-px` dividers between groups
- **Export button**: Added "Export" text label (hidden below `sm`), kept download icon
- **Removed subtitle**: "Arthur International" text removed from header to reduce noise
- **Fixed z-index**: Bumped to `z-[100]` for reliable dropdown layering
- **Fixed height**: Set `h-12` for consistent header sizing

**File:** `dashboards/art-dashboard/src/components/HeaderBar.tsx`

### 3. Flights stuck at BOARDING with 0 baggage loaded

**Root cause:** Consumer speed mismatch. The flight-service consumer processes ticks much faster than passenger-service and baggage-service consumers. When the sim starts (or after a restart), the flight-service rapidly advances flights to `boarding` state, but passenger/baggage services are still processing earlier ticks. This means:

- Passengers remain `booked` (never checked in) because passenger-service hasn't reached those ticks yet
- Baggage stays `dropped_off` (never inducted) because baggage-service is similarly behind
- The flight FSM requires `boarded_pct >= 0.95` to transition to `departed`
- With 0% boarded, flights accumulate delay indefinitely until 180 min → cancelled

This created a cascade: early flights filled the cancellation quota, later flights had no gates, leading to more delays.

**Fix:** Added grace departure logic to `_eval_boarding()` in the flight state machine. After extended delays, the boarding threshold is progressively lowered:

| Delay     | Threshold              | Rationale                                 |
| --------- | ---------------------- | ----------------------------------------- |
| 0-29 min  | 95% (standard)         | Normal boarding completion                |
| 30-59 min | 80%                    | Late passengers, door close approaching   |
| 60-89 min | 50%                    | Extended delay, depart with available pax |
| 90+ min   | 0% (depart regardless) | Doors close, go                           |

This matches real-world operations where airlines close doors and depart after holding long enough, even with missing passengers/bags.

**File:** `services/flight-service/services/state_machine.py`

**Verification:**

- Before fix: ~65 flights stuck at `boarding`, max delay 179 min
- After fix: 27 flights at `boarding`, max delay 76 min (actively boarding, not stuck)
- Old stuck flights (100+ min) all departed via grace departure

---

## Key Insight

The consumer speed mismatch is architectural: flight-service processes ticks faster because it only does Neo4j reads and simple FSM evaluation, while passenger-service does complex Neo4j read/write cycles per tick (check-in, security, boarding pipelines). The grace departure mechanism is the correct fix because it makes the system tolerant of these inherent processing speed differences — the FSM should not assume all services process at the same speed.

---

## Files Modified

| File                                                    | Change                                                     |
| ------------------------------------------------------- | ---------------------------------------------------------- |
| `dashboards/art-dashboard/src/App.tsx`                  | Removed `overflow-hidden` from outer container             |
| `dashboards/art-dashboard/src/components/HeaderBar.tsx` | Three-zone header layout, export button label, z-index fix |
| `services/flight-service/services/state_machine.py`     | Grace departure logic in `_eval_boarding()`                |
| `scripts/helper_check_flights.sh`                       | New diagnostic script for flight states + consumer lag     |

## CI Results

- `ruff check services/` — All checks passed
- `npx tsc --noEmit` — No errors
- `npm run build` — Build succeeded

# Sprint: Debug Endpoints, ADS-B, Dashboard Polish & Test Fixes

**Date:** 2026-04-08
**Scope:** Bug fixes, infrastructure, UI polish, test maintenance

---

## Issues Fixed

### 1. Debug flight injection — `KeyError: 'seats'` (Critical)

**Root cause:** `routers/debug.py` line 440 used `ac["seats"]` but the `aircraft_types.json` fixture uses `seat_capacity`. Similarly, `ac.get("body", "narrow")` referenced a nonexistent `body` key — the fixture has `wide_body` (boolean).

**Fix:** Changed to `ac["seat_capacity"]` and `"wide" if ac.get("wide_body") else "narrow"`.

**File:** `services/sim-orchestrator/routers/debug.py`

### 2. Baggage tag collision — `ConstraintError` on inject (Critical)

**Root cause:** `generate_baggage()` in `services/sim-orchestrator/services/baggage.py` hardcoded `tag_counter = 1`, producing tags starting from `0000000001` every time. Collides with tags from previous seeds.

**Fix:** Introduced `_unique_tag_start()` using timestamp + random jitter for globally-unique starting offsets. Applied to both departure and arrival baggage generation.

**File:** `services/sim-orchestrator/services/baggage.py`

### 3. ADS-B endpoint unreachable — route ordering (Critical)

**Root cause:** `GET /flights/adsb-states` was defined **after** `GET /flights/{flight_id}` in `services/flight-service/routers/flights.py`. FastAPI matched `adsb-states` as a `{flight_id}` path parameter, returning "Flight not found".

**Fix:** Moved the `adsb-states` route before the `{flight_id}` route.

**File:** `services/flight-service/routers/flights.py`

### 4. ADS-B polling never starts in Docker (Medium)

**Root cause:** `ADSB_ENABLED` defaults to `"false"` and was not overridden in `docker-compose.yml`. The flight-service never started the OpenSky polling loop.

**Fix:** Added explicit `ADSB_ENABLED: "true"` in the flight-service environment block in `docker-compose.yml`.

**File:** `docker-compose.yml`

### 5. Missing `httpx` dependency (Medium)

**Root cause:** The ADS-B module (`services/flight-service/services/adsb.py`) imports `httpx` for HTTP polling, but `httpx` was not listed in `requirements.txt`.

**Fix:** Added `httpx>=0.27.0` to `services/flight-service/requirements.txt`.

**File:** `services/flight-service/requirements.txt`

### 6. Integration test — `AttributeError: 'list' object has no attribute 'get'` (Medium)

**Root cause:** `test_event_chains.py` assumed `GET /flow/map` returns `{"zones": {...}}` (dict), but the endpoint returns `{"zones": [...]}` (list of dicts with `zone_id` key).

**Fix:** Normalize zones to dict via `{z["zone_id"]: z for z in zones_raw}` before accessing. Fixed in 3 test functions.

**File:** `tests/integration/test_event_chains.py`

---

## Dashboard Styling Improvements

### Navigation (HeaderBar)
- Increased nav item size from `text-xs` to `text-sm` with larger click targets
- Added backdrop blur and shadow to header for visual depth
- Improved active state: `shadow-inner` + `border border-blue-500/30`
- Better dropdown: rounded corners, `border-l-2` active indicator, animated chevron
- Responsive: weather strip hidden on small screens

### Global Styles (index.css)
- Added base heading contrast: `h1, h2, h3 → text-white font-semibold`
- Custom dark-theme scrollbar styling
- Form element dark-mode defaults with focus ring
- Reusable component classes: `.card`, `.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-sm`, `.section-label`
- Smooth animations: fade-in, slide-down, slide-right, pulse-glow

### Text Contrast (all pages)
- Bulk-upgraded ~92 instances of `text-gray-500` to `text-gray-400` across all pages
- Intentional muted text (e.g. strikethrough) preserved at `text-gray-500`
- Pages affected: FlightBoard, IncidentConsole, Scenarios, Debug, GroundOps, PassengerFlow, BaggageTracker, SimHistory, Settings

---

## Validation Results

| Check | Result |
|---|---|
| `ruff check` (Python lint) | ✅ All checks passed |
| `tsc --noEmit` (TypeScript) | ✅ No errors |
| `npm run build` (API Gateway) | ✅ Exit 0 |
| `vite build` (Dashboard) | ✅ 829 modules, built in 11s |
| Unit tests (507) | ✅ All passed |
| Integration test fix | ✅ zones dict normalization |
| Service health (all 7) | ✅ 200 OK |
| ADS-B endpoint | ✅ 200 OK (0 aircraft — OpenSky rate limit in Azores region) |
| Debug inject flight | ✅ Creates flight + 209 passengers + 246 baggage |
| Debug inject passengers | ✅ Injects 5 passengers at specified status |
| Debug inject baggage | ✅ Injects 3 bags at specified zone |
| Debug Cypher console | ✅ Returns query results |
| Debug entity inspector | ✅ Returns properties + relationships |

---

## Scripts Added

- `scripts/helper_test_debug_endpoints.sh` — comprehensive debug endpoint smoke test

---

## Notes

- **ADS-B rate limiting:** OpenSky free tier returns 429 frequently. The system handles this gracefully by keeping the last known state. KART's mid-Atlantic location means few aircraft are visible (~0–5 at any time). This is expected behavior.
- **Baggage tag uniqueness:** The previous approach of starting counters from 1 or 5B was fragile. The new timestamp-based approach avoids collisions but tags are no longer sequential within a single day — acceptable tradeoff for robustness.

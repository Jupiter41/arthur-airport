# Sprint: Freemium Datasets — ADS-B, OurAirports, BTS

**Date:** 2025-01  
**Scope:** Data source improvements, WorldMap UI, documentation updates

---

## Changes Made

### 1. ADS-B Display Fix (WorldMapPage.tsx)

**Problem:** ADS-B toggle was on ("ADS-B: 1993 real") but aircraft were not rendered on the map.

**Root cause:** The `adsb-symbols` Mapbox layer was created with `visibility: "none"` hardcoded in the image-onload callback. The useEffect that toggles visibility could run before the layer existed (race condition), or the initial state was simply wrong.

**Fix:** Used a `showAdsbRef` ref for closure-safe access and set initial visibility to `showAdsbRef.current ? "visible" : "none"`. Also added Leaflet fallback ADS-B rendering (orange markers) that was completely missing.

**Lesson:** When creating Mapbox layers inside async callbacks (image loading), always use refs for current state — closures capture stale values.

### 2. WorldMap UI Improvements

Added three new controls to the map header:
- **Routes toggle** — show/hide great-circle route arcs
- **Flight direction filter** — all / departures only / arrivals only
- **Map style selector** — satellite / dark / streets (Mapbox only)

ADS-B aircraft are visually differentiated: orange color, distinct from cyan (departures) and green (arrivals).

### 3. OpenSky → adsb.lol Migration (Documentation)

The codebase already used adsb.lol as the primary ADS-B source with OpenSky as fallback, but documentation and UI labels still referenced OpenSky as primary.

**Updated files:** README.md, QUICKSTART.md, MISC.md, ROADMAP.md, data/README.md, DATA_SOURCES.md, DataSourcesPage.tsx, dataSources.ts, flights.py docstring, adsb_synthetic.py docstring.

**Left unchanged:** Historical sprint reports (accurate records of what happened), code variable names (`OPENSKY_URL`, `OPENSKY_USERNAME` — still needed for fallback).

**Added to MISC.md:** adsb.lol vs Aviationstack comparison — they serve different purposes (positions vs schedules) and are complementary.

### 4. Paid Data Sources Evaluation

**Conclusion: Not needed** for a portfolio/teaching project. The free tier ($0) with adsb.lol, BTS, ASRS, OurAirports, IEM, and ADDS covers all core needs. Paid sources (Aviationstack $45/mo, FlightAware) would only matter for production use. No evaluation.md written.

### 5. OurAirports Added to Data Source Page

Added `ourairports` entry to DataSourcesPage SOURCE_DESCRIPTIONS and gateway dataSources.ts as an "infrastructure" type source (always active, offline fixture data).

### 6. BTS (US DOT) Referenced Everywhere

BTS was already specced in DATA_SOURCES.md with a full adapter blueprint. Added:
- BTS section to data/README.md with dataset descriptions and download info
- `bts_historical` entry to Currently Implemented Sources table in DATA_SOURCES.md
- License entry in data/README.md summary table
- Gateway and dashboard already had BTS entries from prior work

**Note:** The actual BTS adapter code (`bts_adapter.py`) is specced but not yet implemented — this is a future data science sprint task.

---

## Key Takeaways

1. **Mapbox layer creation in async callbacks** requires refs, not state variables, for correct initial values.
2. **Documentation drift** is real — code used adsb.lol for months while docs still said OpenSky. Regular doc audits help.
3. **"Infrastructure" data sources** (OurAirports) are different from runtime sources — they're offline fixtures, always active, no polling needed. The type system should reflect this.

# P1-1-5 — ADS-B Historical Track Calibration Plan

**Status:** Planned  
**Priority:** Low  
**Complexity:** High (data pipeline + statistical analysis)

---

## Goal

Use historical ADS-B tracks from OpenSky Network Zenodo monthly dumps to calibrate
the great-circle interpolation model used in the flight-service. The current model
assumes aircraft fly perfect great-circle arcs, but real tracks deviate significantly
due to:

- North Atlantic Track (NAT) system for westbound/eastbound transatlantic flights
- ATC-assigned routing via waypoints and airways
- Weather avoidance (convective cells, jet stream positioning)
- RVSM altitude constraints and step climbs

## Data Source

| Source | URL | Format |
|---|---|---|
| OpenSky Network Zenodo | https://zenodo.org/communities/opensky/ | Monthly CSV dumps (~10 GB/month compressed) |
| Fields needed | `time`, `icao24`, `callsign`, `lat`, `lon`, `baroaltitude`, `heading`, `velocity` | |

## Implementation Steps

### Step 1 — Download and prepare historical data

```bash
# Download one month of ADS-B data from Zenodo
# Filter to flights within 2000 km of KART coordinates
# Output: data/adsb-historical/filtered_tracks.parquet
```

Tooling: Python script `scripts/helper_adsb_historical_download.py`

### Step 2 — Route extraction

For each unique `(origin, destination)` pair:
1. Reconstruct the full track from ADS-B position reports
2. Compute the great-circle arc between origin and destination
3. At 100 evenly-spaced points along the great-circle, measure the cross-track
   deviation to the nearest ADS-B point
4. Store the average deviation profile per route region

Route regions:
- **NAT** (North Atlantic): KART ↔ LHR/CDG/AMS/FRA
- **Southbound**: KART ↔ NBO/JNB/ACC
- **Westbound**: KART ↔ JFK/BOS/MIA
- **Short-haul**: KART ↔ LIS/MAD/BCN

### Step 3 — Build correction model

For each route region, fit a per-fraction correction curve:
```python
# deviation_km = f(fraction, route_region)
# Where fraction ∈ [0, 1] is the proportion of the route completed
```

Expected corrections:
- NAT tracks: +50–150 km lateral deviation (waypoint routing)
- Short-haul: +5–20 km (mostly direct)
- Long-haul equatorial: +20–60 km

### Step 4 — Apply correction in geospatial.ts

Add a `correctedGreatCirclePoint()` function that applies the region-specific
correction factor per fraction:

```typescript
function correctedGreatCirclePoint(
  start: GeoPoint,
  end: GeoPoint,
  fraction: number,
  routeRegion: string,
): GeoPoint {
  const gc = greatCirclePoint(start, end, fraction);
  const correction = getCorrection(routeRegion, fraction);
  // Apply lateral offset perpendicular to the great-circle heading
  return offsetPerpendicularKm(gc, computeBearing(gc, end), correction.lateralKm);
}
```

### Step 5 — Validation

Compare corrected positions against a held-out month of ADS-B data.
Report mean and p95 cross-track deviation before/after correction.

## Dependencies

- Python 3.11 + pandas + pyarrow (for parquet processing)
- ~5 GB disk space for one month of filtered data
- Internet access to download from Zenodo

## Estimated Effort

This is a research task that spans multiple sessions:
- Data download and filtering: 1 session
- Route extraction and deviation measurement: 1 session
- Correction model fitting: 1 session
- Integration into geospatial.ts: 1 session
- Validation: 1 session

## Decision

Defer to a dedicated data science sprint. The current great-circle model is
acceptable for demonstration purposes. The track comparison feature (P1-1-4)
already shows live deviation when ADS-B is enabled, providing qualitative
validation without the full calibration pipeline.

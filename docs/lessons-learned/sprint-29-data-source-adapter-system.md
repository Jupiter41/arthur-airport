# Sprint 29 — Pluggable Data Source Adapter System

## Date: 2026-05-07

## Objective
Build a pluggable adapter system enabling runtime switching between simulation and real-world data sources, with a dedicated dashboard page for monitoring and management.

## Changes Made

### 1. World Map — Zoom on Plane (WorldMapPage.tsx)
- Increased `selectPlane()` fly-to zoom from 6 → 9 and pitch from 30° → 45°
- Duration increased from 1500ms → 1800ms for smoother animation
- Both Mapbox and Leaflet code paths updated consistently
- When a user searches for a plane and clicks it, the map now zooms in close enough to clearly see the individual aircraft icon and surrounding airspace

### 2. Data Sources Page (new)
- **File**: `dashboards/art-dashboard/src/pages/DataSources/DataSourcesPage.tsx`
- Full-featured page showing all data providers feeding the digital twin
- **Features**:
  - Summary statistics bar (total, active, degraded, unavailable, real-world count)
  - Per-source cards with status badges, current source info, and available alternatives
  - Runtime source switching for weather (simulated ↔ historical ↔ live)
  - Weather data comparison panel — fetches data from alternate source and shows field-by-field diff table with delta values
  - Expandable JSON details for each source
  - Collapsible integration guide with step-by-step instructions for adding new sources
  - Auto-refresh every 15 seconds
- **Route**: `/data-sources`
- **Navigation**: Added under Simulation dropdown menu in HeaderBar

### 3. Gateway Data Sources Endpoint (new)
- **File**: `services/api-gateway/src/dataSources.ts`
- `GET /api/v1/data-sources` aggregates source status from all services
- Queries: weather source config, ADS-B status, sim status, passenger flow, baggage flow
- Graceful degradation: unavailable services shown with status "unavailable"
- Registered in `services/api-gateway/src/index.ts`

### 4. Frontend API Layer
- **File**: `dashboards/art-dashboard/src/hooks/useApi.ts`
- Added `DataSourceStatus` and `DataSourcesResponse` TypeScript interfaces
- Added `dataSourcesApi` with `list()` and `switchWeatherSource()` methods

### 5. Architecture Documentation (new)
- **File**: `docs/architecture/DATA_SOURCES.md`
- Complete guide for the pluggable adapter system
- Architecture diagram showing adapter pattern flow
- Currently implemented sources table
- Step-by-step guide for adding new sources (with BTS passenger data as example)
- Runtime switching documentation
- Potential future sources catalog (FlightAware, Open-Meteo, BTS, Eurostat, FAA ASRS, etc.)

## Files Changed
| File | Change |
|------|--------|
| `dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx` | Zoom level 6→9, pitch 30→45 on plane search |
| `dashboards/art-dashboard/src/pages/DataSources/DataSourcesPage.tsx` | New page |
| `dashboards/art-dashboard/src/App.tsx` | Route + lazy import for DataSourcesPage |
| `dashboards/art-dashboard/src/components/HeaderBar.tsx` | Nav entry under Simulation |
| `dashboards/art-dashboard/src/hooks/useApi.ts` | DataSources API types + methods |
| `services/api-gateway/src/dataSources.ts` | New aggregate endpoint handler |
| `services/api-gateway/src/index.ts` | Register /data-sources route |
| `docs/architecture/DATA_SOURCES.md` | New architecture doc |

## Tests & Validation
- Dashboard `npm run build` — passes (DataSourcesPage bundle: 15.72 kB)
- Dashboard `tsc --noEmit` — passes (zero errors)
- Gateway `tsc` — passes (zero new errors)
- Python `ruff check services/` — all checks passed
- No regressions in existing pages or routes

## Design Decisions
1. **Gateway aggregation vs per-service polling**: Chose gateway-level aggregation so the frontend makes a single request for all source statuses, consistent with the existing `handleAggregate` pattern.
2. **Weather-only runtime switching**: Only weather service has full runtime source switching today. Other source buttons are disabled with a tooltip explaining the feature is not yet implemented. This avoids misleading users while showing the extensibility path.
3. **Comparison via temporary switch**: Weather comparison works by briefly switching to the alternate source, fetching a reading, then switching back. This is acceptable for a dev/ops dashboard but would need a dual-read pattern for production use.

## Future Work
- Implement `/source` endpoints for passenger-service and baggage-service
- Add BTS T-100 passenger data adapter
- Add NOAA ISD weather historical source as alternative to Iowa State Mesonet
- Side-by-side comparison without source switching (query alternate source in parallel)

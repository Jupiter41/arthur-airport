# Sprint — Gap 0.5: Better Dashboards

## Overview

Improving the React dashboard with sorting, exports, archive view, history timeline, and chart visualisations.

## Implementation Plan

### GAP-05-0: Plane favicon ✅

- Created SVG plane icon in `public/favicon.svg`
- Added `<link rel="icon">` to `index.html`

### GAP-05-1: Column sorting

- Create a `useSort` hook that manages sort column + direction
- Add clickable column headers with ▲/▼ indicators to FIDSPanel
- Apply sorting to both departures and arrivals tables
- Also add sorting to connection risk list and baggage loading panel

### GAP-05-2: Archive / past simulation runs

- Add a `SimDayRecord` Neo4j node type (day_number, date, summary metrics, status)
- Have sim-orchestrator persist day summaries at each day boundary
- Add `GET /api/v1/sim/history` endpoint returning past days
- Build an archive page in the dashboard accessible from nav

### GAP-05-3: Simulation history timeline

- Use weather history, incident events, and flight stats to build a timeline
- Create a scrollable timeline component showing events by sim time
- Render on a new `/history` route or as a panel on each page

### GAP-05-4: Better chart visualisations

- Install Recharts as chart library
- Add security queue depth line chart to PassengerFlow page
- Add weather timeline chart to FlightBoard bottom bar
- Add tooltips, zoom hints, and severity color coding

### GAP-05-5: Per-page CSV/JSON export

- Create a `downloadData` utility function
- Add export dropdown (CSV/JSON) to each page header
- Use current page data from Zustand stores

### GAP-05-6: Global simulation export

- Add export button in HeaderBar or SimControls
- Fetch from all endpoints in parallel and bundle into a single JSON archive

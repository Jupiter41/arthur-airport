# art-dashboard

**Framework:** React 18 + TypeScript · **Build tool:** Vite · **Port:** 5173

The operator frontend for Arthur International Airport digital twin. The dashboard is event-driven and consumes real-time updates from the API gateway.

## Dashboards

| Route         | Name                                                    | Spec                                                                             |
| ------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `/`           | Flight board (FIDS)                                     | [FLIGHT_BOARD.md](../../docs/dashboards/FLIGHT_BOARD.md)                         |
| `/baggage`    | Baggage tracker                                         | [BAGGAGE_TRACKER.md](../../docs/dashboards/BAGGAGE_TRACKER.md)                   |
| `/passengers` | Passenger flow                                          | [PASSENGER_FLOW.md](../../docs/dashboards/PASSENGER_FLOW.md)                     |
| `/incidents`  | Incident console                                        | [INCIDENT.md](../../docs/dashboards/INCIDENT.md)                                 |
| `/ground-ops` | Ground operations                                       | [GROUND_OPS.md](../../docs/dashboards/GROUND_OPS.md)                             |
| `/world`      | Geospatial world map                                    | [ROADMAP.md](../../ROADMAP.md)                                                   |
| `/history`    | Simulation history                                      | [TIMELINE.md](../../TIMELINE.md)                                                 |
| `/scenarios`  | Scenario lifecycle (run/create/edit/fork/delete custom) | [services/sim-orchestrator/README.md](../../services/sim-orchestrator/README.md) |
| `/settings`   | Runtime simulation controls                             | [services/sim-orchestrator/README.md](../../services/sim-orchestrator/README.md) |

## Delivery context

This frontend has incorporated roadmap and sprint work from:

- Gap 0.5 dashboard upgrades
- Sprint 11 scenario engine integration
- Sprint 12 scenario lifecycle UX (custom scenarios)
- Phase 6 geospatial world-map delivery

Implementation reports:

- [docs/lessons-learned/sprint-gap-05.md](../../docs/lessons-learned/sprint-gap-05.md)
- [docs/lessons-learned/sprint-11-scenario-engine.md](../../docs/lessons-learned/sprint-11-scenario-engine.md)
- [docs/lessons-learned/sprint-12-scenarios-page-lifecycle.md](../../docs/lessons-learned/sprint-12-scenarios-page-lifecycle.md)
- [docs/lessons-learned/phase-6-mapbox-cesium-implementation-report.md](../../docs/lessons-learned/phase-6-mapbox-cesium-implementation-report.md)

## Quick start

```bash
# Via Docker (recommended)
docker compose up dashboard

# Local dev
cd dashboards/art-dashboard
npm install
npm run dev
```

Open **http://localhost:5173**

The dashboard connects to the API gateway at `http://localhost:3000`. Make sure the full stack is running first (`docker compose up`).

## Tech stack

| Concern             | Library               |
| ------------------- | --------------------- |
| Framework           | React 18 + TypeScript |
| State               | Zustand               |
| Data fetching       | React Query           |
| Real-time           | Native WebSocket API  |
| Styling             | Tailwind CSS          |
| Charts              | Recharts              |
| Maps / SVG diagrams | D3 + custom SVG       |
| Build               | Vite                  |

## Status

- [x] Project scaffold (Vite + TS + Tailwind)
- [x] API client + WebSocket hook
- [x] Flight board (FIDS)
- [x] Baggage tracker
- [x] Passenger flow heatmap + forecast widgets
- [x] Incident dashboard + cascade visualizer
- [x] Ground ops schematic
- [x] Simulation controls panel
- [x] World map route with token fallback path
- [x] Scenarios page lifecycle for custom scenarios
- [x] History route and archive-oriented views

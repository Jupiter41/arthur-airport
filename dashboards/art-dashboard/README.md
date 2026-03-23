# art-dashboard

**Framework:** React 18 + TypeScript · **Build tool:** Vite · **Port:** 5173

The operator frontend for Arthur International Airport digital twin. Five dashboards, all driven by real-time WebSocket events from the API gateway.

## Dashboards

| Route | Name | Spec |
|---|---|---|
| `/` | Flight board (FIDS) | [FLIGHT_BOARD.md](../../docs/dashboards/FLIGHT_BOARD.md) |
| `/baggage` | Baggage tracker | [BAGGAGE_TRACKER.md](../../docs/dashboards/BAGGAGE_TRACKER.md) |
| `/passengers` | Passenger flow | [PASSENGER_FLOW.md](../../docs/dashboards/PASSENGER_FLOW.md) |
| `/incidents` | Incident console | [INCIDENT.md](../../docs/dashboards/INCIDENT.md) |
| `/ground-ops` | Ground operations | [GROUND_OPS.md](../../docs/dashboards/GROUND_OPS.md) |

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

| Concern | Library |
|---|---|
| Framework | React 18 + TypeScript |
| State | Zustand |
| Data fetching | React Query |
| Real-time | Native WebSocket API |
| Styling | Tailwind CSS |
| Charts | Recharts |
| Maps / SVG diagrams | D3 + custom SVG |
| Build | Vite |

## Status

- [ ] Project scaffold (Vite + TS + Tailwind)
- [ ] API client + WebSocket hook
- [ ] Flight board (FIDS)
- [ ] Baggage tracker
- [ ] Passenger flow heatmap
- [ ] Incident dashboard + cascade visualizer
- [ ] Ground ops schematic
- [ ] Sim controls panel

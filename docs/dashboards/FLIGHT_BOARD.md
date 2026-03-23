# Flight board dashboard — specification

**File:** `FLIGHT_BOARD.md`  
**App:** `art-dashboard` (React + TypeScript)  
**Route:** `/`  (default landing view)  
**Data sources:** `flight-service`, `weather-service`, `sim-orchestrator` via API gateway  
**Real-time:** WebSocket topics `flights`, `weather`

---

## 1. Purpose

The flight board is the primary operational view of Arthur International Airport. It replicates a real-world FIDS (Flight Information Display System) with operator-grade depth: live status for all 420 daily movements, runway and gate utilisation at a glance, weather strip, and simulation controls.

---

## 2. Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  KART  Arthur International Airport          SIM: Day 1 · 14:32 ▶  │  ← Header bar
│  ART   IMC · 2800m · 27028G42KT · BKN009    Speed: 60×  [⏸] [↺]  │
├──────────────────────────┬──────────────────────────────────────────┤
│  DEPARTURES (210)        │  ARRIVALS (210)                          │  ← Split FIDS
│  ┌──────────────────┐    │  ┌──────────────────┐                   │
│  │ AX412  B07  14:30│    │  │ BK201  C03  14:40│                   │
│  │ BOARDING  ████░░ │    │  │ ON TIME          │                   │
│  │ BK217  A12  14:45│    │  │ KV388  A09  15:00│                   │
│  │ DELAYED +22      │    │  │ APPROACH         │                   │
│  └──────────────────┘    │  └──────────────────┘                   │
├──────────────────────────┴──────────────────────────────────────────┤
│  RUNWAYS          GATES            WEATHER           STATS          │  ← Status bar
│  09L ████ LAND    42 total         IMC               Delayed: 12   │
│  09R ████ TKOF    38 occupied      ↓ since 11:00     Cancelled: 1  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component tree

```
<FlightBoardPage>
  <HeaderBar>
    <AirportIdentity />           — KART · ART · airport name
    <SimClock />                  — sim time + day, live-updating
    <WeatherStrip />              — category badge + METAR summary
    <SimControls />               — speed selector, pause, reset buttons
    <IncidentBadge />             — red badge if active incidents
  </HeaderBar>

  <FIDSPanel>
    <DepartureBoard>
      <FlightRow />               — one per departure, paginated
    </DepartureBoard>
    <ArrivalBoard>
      <FlightRow />               — one per arrival
    </ArrivalBoard>
  </FIDSPanel>

  <StatusBar>
    <RunwayStatus />              — per-runway utilisation + operation
    <GateUtilisation />           — occupied / total gauge per terminal
    <WeatherImpactSummary />      — capacity numbers
    <FlightStats />               — delayed, cancelled, airborne counts
  </StatusBar>

  <FlightDetailDrawer />          — slides in on row click
</FlightBoardPage>
```

---

## 4. Flight row component

Each row in the FIDS displays:

| Field | Source | Notes |
|---|---|---|
| Flight number | `flight.flight_number` | bold |
| Airline logo (text code) | `flight.airline_code` | 2-letter code pill |
| Destination / Origin | `flight.destination_iata` / `flight.origin_iata` | |
| Gate | `flight.gate_id` | highlighted if changed recently |
| Scheduled time | `flight.scheduled_time` | |
| Estimated time | `flight.estimated_time` | strikethrough + amber if delayed |
| Status badge | `flight.status` | colour-coded (see below) |
| Delay indicator | `flight.delay_minutes` | only shown if > 0 |
| Boarding progress bar | `passengers.boarded / pax_count` | only on boarding status |

### Status badge colours

| Status | Badge colour | Label |
|---|---|---|
| `scheduled` | gray | SCHEDULED |
| `boarding` | green | BOARDING |
| `departed` | blue | DEPARTED |
| `airborne` | blue | AIRBORNE |
| `approach` | teal | APPROACH |
| `landed` | teal | LANDED |
| `taxiing` | teal | TAXIING |
| `at_gate` | purple | AT GATE |
| `delayed` | amber | DELAYED +Nmin |
| `cancelled` | red | CANCELLED |
| `diverted` | red | DIVERTED |

### Row update animation

When a `FlightStatusChanged` WebSocket event arrives for a visible row, the row flashes the new status colour for 1.5 seconds, then settles. Gate changes additionally show a `→ NEW GATE` pill for 30 seconds.

---

## 5. Flight detail drawer

Clicking any flight row opens a right-side drawer (400px wide) showing:

- Full flight header (number, airline, aircraft type, registration)
- Status timeline (visual step track of all past statuses with timestamps)
- Gate assignment with reassignment history
- Runway slot
- Passengers: boarded / total / connections at risk
- Baggage: loaded / total / flagged count
- Active incidents affecting this flight
- Cascade effects triggered by this flight
- `[Hold flight]` / `[Release hold]` operator action buttons

---

## 6. FIDS panel behaviour

**Sorting:** default ascending by scheduled time; column header click re-sorts.

**Filtering:** status (multi-select), terminal (A/B/C), airline code (text), show delayed only toggle.

**Pagination:** 20 rows per page. Auto-advance every 10 real seconds when no filter active (auto-scroll mode mimicking a real FIDS). Pauses on hover.

---

## 7. Runway status component

```
09L  [████████░░]  LANDING   32 → 18 mvts/hr (IMC)   Queue: 3
09R  [██████░░░░]  TAKEOFF   32 → 16 mvts/hr (IMC)   Queue: 5
```

Bar fill shows utilisation vs capacity. Status badge: `OPEN` (green) / `RESTRICTED` (amber) / `CLOSED` / `INCIDENT` (red + pulse).

---

## 8. Weather strip

Compact bar updating instantly on `WeatherStateChanged`:

```
IMC  ·  2800m vis  ·  27028G42KT  ·  BKN009 OVC050  ·  +4°C  ·  Q1002
```

Category badge colours: `CAVOK` green · `VMC` teal · `IMC` amber · `LIFR` red with pulse.

Clicking opens a weather modal: raw METAR, TAF, 12-hour category history chart, and operational impact summary.

---

## 9. Simulation controls

Located in the header bar (operator role only):

| Control | Action |
|---|---|
| Speed selector | Dropdown 1×/10×/60×/600×/3600× → `PATCH /sim/speed` |
| Pause / Resume | `POST /sim/pause` or `POST /sim/resume` |
| Reset | `POST /sim/reset` — requires confirmation modal |
| Inject event | Opens incident injection modal (see `INCIDENT.md`) |

---

## 10. WebSocket integration

Subscriptions on mount: `flights`, `weather`, `incidents`

| Event type | Handler |
|---|---|
| `FlightStatusChanged` | Update row status, trigger flash animation |
| `FlightGateAssigned` | Update gate cell, show gate-change pill |
| `FlightCancelled` | Mark row cancelled, red highlight |
| `WeatherStateChanged` | Update weather strip + runway capacity |
| `IncidentAlert` | Increment badge, show toast |
| `SimClockTick` | Tick the sim clock display |

---

## 11. API calls on mount

| Endpoint | Purpose |
|---|---|
| `GET /airport` | Populate all counters |
| `GET /flights?limit=200` | Populate FIDS |
| `GET /weather/current` | Weather strip |
| `GET /runways` | Runway panel |

All state kept live via WebSocket after mount — no polling.

---

## 12. Key UX behaviours

- **Incident banner:** On `critical` `IncidentAlert`, a full-width red banner appears at top with incident title and protocol. Persists until dismissed or resolved.
- **Dark mode only:** Consistent with real FIDS aesthetics.
- **Monospace font** for times and codes; sans-serif for labels.
- **ARIA live regions** on all status changes for screen reader compatibility.

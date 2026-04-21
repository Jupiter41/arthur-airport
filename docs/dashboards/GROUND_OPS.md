# Ground operations dashboard — specification

**File:** `GROUND_OPS.md`  
**App:** `art-dashboard` (React + TypeScript)  
**Route:** `/ground-ops`  
**Data sources:** `flight-service`, `weather-service`, `incident-service` via API gateway  
**Real-time:** WebSocket topics `flights`, `weather`, `incidents`

> **See also:** [ROUTES.md](../architecture/ROUTES.md) (endpoint inventory) · [EVENT_BUS.md](../architecture/EVENT_BUS.md) (Kafka schemas) · [DATA_MODEL.md](../architecture/DATA_MODEL.md) (Neo4j graph) · [flight-service SPEC](../services/flight-service/SPEC.md) · [analysis-service](../../services/analysis-service/) (recommendations)

---

## 1. Purpose

The ground operations dashboard provides an air traffic control-style overview of the KART airfield: runway activity, gate occupancy across all three terminals, active weather constraints, ground stop status, and the holding stack. It is the highest-level spatial view in the system — showing where every active flight is at the current simulated moment.

---

## 2. Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Ground Operations — KART          SIM: Day 1 · 14:32   IMC ⚠      │
├───────────────────────────────────────────────────────────────────┬─┤
│                    AIRFIELD VIEW                                  │W│
│  ┌────────────────────────────────────────────────────────────┐  │E│
│  │  TERMINAL A          TERMINAL B          TERMINAL C        │  │A│
│  │  [A01][A02]...       [B01][B02]...       [C01][C02]...     │  │T│
│  │                                                            │  │H│
│  │  ═══════════════ RUNWAY 09L/27R ════════════════════       │  │E│
│  │  → AX412 (TKOF)   → BK201 (LAND)                          │  │R│
│  │                                                            │  │ │
│  │  ═══════════════ RUNWAY 09R/27L ════════════════════       │  │P│
│  │  → KV388 (LAND)   → ZT105 (TKOF)  → LM024 (queue)         │  │A│
│  └────────────────────────────────────────────────────────────┘  │N│
│                                                                   │E│
│  HOLDING STACK (4)     GROUND STOP    QUEUE                       │L│
│  AX508 · -18min        DEPARTURES     09L: 3 arr · 2 dep          │ │
│  ZN201 · -12min        SUSPENDED      09R: 0 arr · 5 dep          │ │
│  KV102 · -9min                                                    │ │
│  BK310 · -4min                                                    │ │
└───────────────────────────────────────────────────────────────────┴─┘
```

---

## 3. Component tree

```
<GroundOpsDashboardPage>
  <PageHeader>
    <AirportIdentity />
    <SimClock />
    <WeatherBadge />               — compact category + wind
    <IncidentBadge />
  </PageHeader>

  <MainView>
    <AirfieldSchematic>
      <TerminalBlock terminal="A" />
      <TerminalBlock terminal="B" />
      <TerminalBlock terminal="C" />
      <RunwayStrip runway="09L" />
      <RunwayStrip runway="09R" />
      <TaxiwayOverlay />
    </AirfieldSchematic>

    <WeatherSidePanel>
      <MetarDisplay />
      <RunwayImpactCard />
      <WindIndicator />           — compass rose with wind arrow
    </WeatherSidePanel>
  </MainView>

  <BottomBar>
    <HoldingStackPanel />
    <GroundStopPanel />
    <RunwayQueuePanel />
  </BottomBar>
</GroundOpsDashboardPage>
```

---

## 4. Airfield schematic

An SVG-based schematic of the KART airfield. It is a simplified top-down diagram — not geographically accurate, but operationally readable.

### Gate cells (terminal blocks)

Each terminal (A, B, C) is shown as a rectangular block with 14 gate cells arranged in a row. Each gate cell:

- Shows the gate ID (A01 etc.)
- Fill colour reflects gate status:
  - White: available
  - Blue (light): flight at_gate or boarding
  - Green: departing soon (within 30 sim-min)
  - Amber: delayed flight
  - Red: incident-affected
  - Gray: maintenance / closed
- Hovering a gate cell shows a tooltip: flight number, status, estimated departure/arrival

### Runway strips

Two horizontal runway strips in the lower portion of the schematic. Each runway strip:

- Shows the runway designation (09L/27R)
- Shows currently active movements as labelled arrows traversing the strip:
  - Rightward arrows (→) with flight number: landing approaches
  - Leftward arrows (←) with flight number: departing
- Runway strip background colour:
  - Green: open and active
  - Amber: restricted (IMC/reduced rate)
  - Red: incident / closed
  - Gray: idle

Aircraft icons (simple triangles) are animated along the runway strip as movements progress. Landing aircraft animate from right edge to mid-strip (touchdown zone) then slow to taxi. Departing aircraft animate from mid-strip to right edge (rotation).

### Holding stack visual

When arrivals are in the holding stack, small circling icons appear in the upper right of the schematic (above the terminal blocks), with altitude-stack labels (FL080, FL090, etc. — simulated) and flight numbers.

---

## 5. Runway strip component

Each runway strip shows:

| Element          | Description                                   |
| ---------------- | --------------------------------------------- |
| Runway ID        | `09L / 27R`                                   |
| Status badge     | `OPEN` / `RESTRICTED` / `CLOSED` / `INCIDENT` |
| Active movements | Animated flight arrows                        |
| Capacity display | `Current: 18/hr ← Max: 32/hr`                 |
| Queue indicator  | `Arr queue: 3 · Dep queue: 2`                 |
| ILS indicator    | `ILS CAT III` badge when active (LIFR)        |

When a runway incursion incident is active, the runway strip turns red with a `⚠ INCURSION` badge and the animated aircraft icons freeze.

---

## 6. Holding stack panel

Shows all arrivals currently in the simulated holding pattern:

| Field                  | Description                                                |
| ---------------------- | ---------------------------------------------------------- |
| Flight number          |                                                            |
| Entry time             | How long in holding (relative)                             |
| Fuel state             | Simulated: `NORMAL` / `MIN FUEL` (if holding > 30 sim-min) |
| Expected approach time | When the flight is next in the runway queue                |

Holding stack entries are ordered by entry time (earliest first = next to land). The `MIN FUEL` state triggers an amber highlight and a `PassengerAlert` (informational only — no real emergency in the simulation unless the operator injects one).

---

## 7. Ground stop panel

Displays the current departure ground stop status per runway.

| State        | Display                                                             |
| ------------ | ------------------------------------------------------------------- |
| No stop      | `NORMAL — Departures active` (green)                                |
| Stop active  | `⛔ GROUND STOP — Departures suspended` (red) with trigger incident |
| Partial stop | `⚠ REDUCED — Departure rate: N/hr` (amber)                          |

The panel also shows the estimated stop duration and affected departure count.

---

## 8. Runway queue panel

Compact view of the departure and arrival queues per runway:

```
09L  Arrivals: AX412 · BK201 · KV388 (+3 holding)
     Departures: ZT105 · LM024 · [5 more]

09R  Arrivals: [none]
     Departures: AX810 · BK507 · KV201 · [4 more]
```

Queued flights are listed in priority order. Clicking a flight number opens the flight detail drawer.

---

## 9. Weather side panel

A compact vertical panel on the right side of the airfield view:

- **Current category** — large coloured badge (`CAVOK` / `VMC` / `IMC` / `LIFR`)
- **METAR** — most recent raw METAR string in monospace
- **Wind compass** — animated compass rose showing wind direction and speed, with gust indicator
- **Runway impact** — `Arrival rate: 18/hr` / `Departure rate: 16/hr` / `Active runway: 09L (ILS)`
- **Trend arrow** — improving (↑ green) / stable (→ gray) / deteriorating (↓ red)

---

## 10. WebSocket integration

Subscriptions: `flights`, `weather`, `incidents`

| Event type                           | Handler                                            |
| ------------------------------------ | -------------------------------------------------- |
| `FlightStatusChanged`                | Update gate cell colour, update runway strip       |
| `FlightGateAssigned`                 | Update gate cell assignment                        |
| `FlightRunwayAssigned`               | Add/update movement on runway strip                |
| `WeatherStateChanged`                | Update side panel, runway strip colours + capacity |
| `IncidentCreated` (runway_incursion) | Freeze runway strip, show red overlay              |
| `IncidentCreated` (security_breach)  | Mark terminal blocks with locked overlay           |
| `IncidentStatusChanged` (resolved)   | Restore normal display                             |

---

## 11. API calls on mount

| Endpoint                                                         | Purpose                       |
| ---------------------------------------------------------------- | ----------------------------- |
| `GET /runways`                                                   | Runway status + queues        |
| `GET /gates`                                                     | All gate statuses             |
| `GET /flights?status=approach,taxiing,boarding,at_gate,departed` | Active airfield movements     |
| `GET /weather/current`                                           | Side panel                    |
| `GET /incidents?status=active`                                   | Active incidents for overlays |

---

## 12. Key UX behaviours

- **Zoom toggle:** The airfield schematic has two zoom levels — full airport view and terminal-focused view (one terminal at a time). Toggle via tab buttons above the schematic.
- **Night mode:** The schematic uses a dark tarmac background by default with bright runway lights and gate cell contrast — consistent with a real tower display aesthetic.
- **Incident area overlay:** When an incident affects a specific zone, a translucent red/amber polygon is drawn over that zone on the schematic, with a label showing the incident title.
- **Auto-reset pan:** If the operator has panned/zoomed the schematic, a `[Reset view]` button restores the default full-airport view.
- **Flight count badge:** The page tab shows the count of active airfield movements: `(12) Ground Ops — ART`.

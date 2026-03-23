# Passenger flow dashboard — specification

**File:** `PASSENGER_FLOW.md`  
**App:** `art-dashboard` (React + TypeScript)  
**Route:** `/passengers`  
**Data sources:** `passenger-service`, `flight-service` via API gateway  
**Real-time:** WebSocket topics `passengers`, `incidents`

---

## 1. Purpose

Provides a real-time view of passenger movement through every zone of KART — check-in halls, security checkpoints, airside concourses, gates, and baggage claim. Highlights bottlenecks, connection risk, and zone lockdowns during security incidents.

---

## 2. Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Passenger Flow                            ART  SIM: Day 1 · 14:32  │
├──────────────────────────────────────────────────────────────────────┤
│  IN AIRPORT: 4,218    SECURITY QUEUES    CONNECTIONS AT RISK: 7    │  ← KPI bar
│  AIRSIDE: 1,402       A: 34 pax  11min                             │
│  BOARDED: 743         B: 78 pax  22min   MISSED TODAY: 1           │
│                       C: 12 pax   4min                              │
├──────────────────────────────────────────────────────────────────────┤
│                     AIRPORT HEATMAP                                  │  ← Zone heatmap
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  [CHECK-IN A]  [SECURITY A]  [AIRSIDE A]   [GATES A01–A14]    │ │
│  │  [CHECK-IN B]  [SECURITY B]  [AIRSIDE B]   [GATES B01–B14]    │ │
│  │  [CHECK-IN C]  [SECURITY C]  [AIRSIDE C]   [GATES C01–C14]    │ │
│  │                              [CAROUSEL 1–6]                    │ │
│  └─────────────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────────────┤
│  CONNECTIONS AT RISK                 ZONE DETAIL (click zone above)  │
│  Sam Okonkwo   AX201+38min  →AX508  ┌────────────────────────────┐  │
│  Mia Pereira   KV102+31min  →BK410  │ Security-B                 │  │
│                                     │ 78 pax · 65% capacity      │  │
│                                     │ Wait: ~22 min              │  │
│                                     │ Lanes open: 3 of 5         │  │
│                                     └────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component tree

```
<PassengerFlowPage>
  <PageHeader />

  <KPIBar>
    <TotalInAirport />
    <SecurityQueueSummary />        — wait time per terminal
    <ConnectionRiskCounter />       — at-risk + missed
  </KPIBar>

  <HeatmapPanel>
    <AirportHeatmap>
      <ZoneCell />                  — one per zone, colour = load %
    </AirportHeatmap>
    <HeatmapLegend />
  </HeatmapPanel>

  <BottomPanel>
    <ConnectionAtRiskList>
      <ConnectionRiskRow />
    </ConnectionAtRiskList>
    <ZoneDetailPanel />             — shown when a zone is clicked
  </BottomPanel>

  <PassengerSearchBar />
  <PassengerDetailDrawer />
</PassengerFlowPage>
```

---

## 4. Airport heatmap component

A schematic grid representing all passenger zones at KART. Each zone is a coloured rectangle sized to reflect its capacity.

### Zone grid layout

The heatmap is organised in 4 columns (left to right: check-in → security → airside → gates) and 3 rows (terminals A, B, C). A fourth row below shows arrival carousels.

| Column | Zones |
|---|---|
| Check-in | check-in-A, check-in-B, check-in-C |
| Security | security-A, security-B, security-C |
| Airside | airside-A, airside-B, airside-C |
| Gates | gate-A01..A14, gate-B01..B14, gate-C01..C14 (grouped per terminal) |
| Arrivals | carousel-1 through carousel-6 |

Gate cells are smaller (14 per terminal) and sit in a sub-grid within the gates column. The cell for a gate-level zone is clickable and shows the specific gate number on hover.

### Zone colour scale

Heatmap colour represents `density / capacity` (load percentage):

| Load % | Colour |
|---|---|
| 0–25% | Light green |
| 26–50% | Green |
| 51–70% | Yellow-green |
| 71–85% | Amber |
| 86–95% | Orange |
| 96–100% | Red |
| Locked (incident) | Gray + lock icon overlay |
| Evacuating | Red pulse animation |

Colour transitions are smoothly animated (CSS transition 0.8s) rather than instant jumps, giving a natural "heat rising and falling" feel.

### Live update

On `PassengerStatusChanged` events, the affected zone's density counter updates and the cell colour interpolates to the new heat level.

### Zone click

Clicking a zone opens the `ZoneDetailPanel` (right side) showing:
- Zone name + capacity
- Current density + load percentage
- Estimated wait time (security zones only)
- Active incidents in this zone
- List of flights whose pax are concentrated here (top 5)
- If gate zone: the assigned flight + boarding status

---

## 5. Security queue summary

Three compact cards (one per terminal) in the KPI bar:

```
Terminal A    Terminal B    Terminal C
34 pax        78 pax        12 pax
~11 min       ~22 min       ~4 min
4 lanes       3 lanes       4 lanes
```

A warning badge appears on any terminal where wait time exceeds 20 simulated minutes.

When a `security_breach` incident locks a terminal, the card shows a `🔒 LOCKED` state in red.

---

## 6. Connection risk list

Sorted by urgency (most critical first — least time until departure).

Each row:

| Field | Description |
|---|---|
| Passenger name | Link to passenger detail |
| Inbound flight | `AX201 +38min delayed` |
| Connection flight | `→ AX508` |
| Time until connection departs | In simulated minutes |
| Risk level badge | `WATCH` (gray) / `AT RISK` (amber) / `MISSED` (red) |
| Baggage indicator | Number of checked bags (adds complexity to re-booking) |

The list updates in real time as delay values change. Passengers who miss their connection transition to `MISSED` (red) and remain in the list for 10 sim-minutes before auto-archiving.

---

## 7. Passenger search and detail

**Search bar:** accepts name (partial), PNR (exact 6-char), or flight number.

**Passenger detail drawer** (400px right panel):

- Name, nationality, PNR
- Current status badge + location zone
- Flight assignment + boarding status
- Seat number
- Connection info (if applicable) with risk level
- Baggage list with each item's status
- Full timeline (every status change with sim timestamp)
- Alerts received (gate change, connection risk notices)
- Special assistance flag (if set)

---

## 8. Incident overlays on heatmap

When incident events arrive via WebSocket, the heatmap responds visually:

| Incident type | Heatmap effect |
|---|---|
| `security_breach` (zone_lockdown) | Affected zone turns gray with lock icon; adjacent zones amber |
| `security_breach` (terminal_lockdown) | Entire terminal column turns gray; pulsing red border |
| `security_breach` (full_evacuation) | All zones pulse red; `EVACUATION IN PROGRESS` banner overlaid |
| `runway_incursion` | No direct heatmap effect (airside only) |
| `system_failure` | No heatmap effect (baggage system only) |

Incident overlay persists until `IncidentStatusChanged` (resolved) is received.

---

## 9. WebSocket integration

Subscriptions: `passengers`, `incidents`

| Event type | Handler |
|---|---|
| `PassengerStatusChanged` | Update zone density, refresh connection risk if relevant |
| `PassengerAlert` | Show notification toast if currently viewing that passenger |
| `IncidentCreated` | Apply heatmap incident overlay |
| `IncidentStatusChanged` (resolved) | Remove overlay, restore zones |

---

## 10. API calls on mount

| Endpoint | Purpose |
|---|---|
| `GET /flow/summary` | KPI bar counts |
| `GET /flow/heatmap` | Zone density data |
| `GET /connections/at-risk` | Connection risk list |
| `GET /security/queues` | Security card stats |

---

## 11. Key UX behaviours

- **Flow animation (optional):** Small animated dots travel between zone cells along the schematic paths, representing aggregate passenger movement. Rate proportional to throughput. Can be toggled off for performance.
- **Peak hour indicator:** A time-of-day strip below the KPI bar shows a 24-hour demand curve (bar chart of expected pax volume per hour), with the current simulated time marked. Peaks are shaded amber so operators can anticipate pressure.
- **Responsive grid:** Gate cells collapse to a single grouped cell per terminal on narrow viewports.

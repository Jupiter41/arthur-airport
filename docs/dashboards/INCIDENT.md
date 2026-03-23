# Incident & alert dashboard — specification

**File:** `INCIDENT.md`  
**App:** `art-dashboard` (React + TypeScript)  
**Route:** `/incidents`  
**Data sources:** `incident-service`, `flight-service`, `passenger-service`, `baggage-service` via API gateway  
**Real-time:** WebSocket topics `incidents`, `alerts`

---

## 1. Purpose

The incident dashboard is the safety and operations nerve centre of the KART digital twin. It displays active hazardous events, their severity, the full cascade tree of downstream effects, emergency protocol status, and provides the manual event injection interface. It also auto-generates downloadable incident reports upon resolution.

---

## 2. Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Incident Operations         ART · SIM: Day 1 · 14:32  [+ INJECT]  │
├───────────────────────┬─────────────────────────────────────────────┤
│  ACTIVE INCIDENTS (1) │  CASCADE VISUALIZER                        │
│  ┌─────────────────┐  │  runway_incursion (CRITICAL)               │
│  │ ● CRITICAL      │  │      ↓                                     │
│  │ Runway incursion│  │  holding_stack (HIGH) · 7 aircraft         │
│  │ 09L · 14:30Z    │  │      ↓                                     │
│  │ RUNWAY_STOP     │  │  departure_ground_stop (MED) · 4 dep       │
│  │ [4 min ago]     │  │      ↓                                     │
│  └─────────────────┘  │  gate_congestion (LOW) · 3 gates           │
│                       │                                             │
│                       │  PROTOCOLS ACTIVE                          │
│                       │  ● RUNWAY_STOP   ● BAGGAGE_HOLD            │
├───────────────────────┴─────────────────────────────────────────────┤
│  ALERT FEED                                                          │
│  14:34  CRITICAL  Runway 09L — 7 aircraft in holding pattern        │
│  14:30  CRITICAL  RUNWAY_STOP protocol activated — 09L incursion    │
├──────────────────────────────────────────────────────────────────────┤
│  RESOLVED TODAY (2)                              [Export all]       │
│  14:12  security_breach  RESOLVED  T+18min  Terminal A  [↓ Report]  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component tree

```
<IncidentDashboardPage>
  <PageHeader>
    <InjectEventButton />          — opens injection modal
  </PageHeader>

  <MainPanel>
    <ActiveIncidentList>
      <IncidentCard />             — one per active/contained incident
    </ActiveIncidentList>

    <RightPanel>
      <CascadeVisualizer />        — tree of selected incident
      <ProtocolStatusBar />        — active emergency protocol badges
    </RightPanel>
  </MainPanel>

  <AlertFeed />                    — scrolling live alert log

  <ResolvedIncidentList>
    <ResolvedIncidentRow />
    <DownloadReportButton />
  </ResolvedIncidentList>

  <InjectEventModal />
  <IncidentDetailDrawer />
</IncidentDashboardPage>
```

---

## 4. Incident card component

Cards sorted by severity descending, then by start time.

| Field | Display |
|---|---|
| Severity border | red (critical) · orange (high) · amber (medium) · gray (low) |
| Type icon | Symbolic icon per type |
| Title + location | `incident.title` · `incident.location` |
| Started at | Relative ("4 min ago") + absolute sim time |
| Protocol badge | Active protocol code |
| Status | `ACTIVE` (pulse) / `CONTAINED` (solid) |
| Cascade count | `↓ 3 cascades` |
| Actions | `[Contain]` `[Resolve]` |

`CRITICAL` cards have a slow red pulse border (2s period). Clicking selects the incident and loads the cascade visualizer.

---

## 5. Cascade visualizer

Interactive vertical tree of the selected incident. Each node:

```
┌──────────────────────────────────┐
│ [severity badge]  cascade_type   │
│ short description                │
│ Affected: N entities             │
└──────────────────────────────────┘
```

Node background colours match severity (red/orange/amber/gray/green for resolved). New child nodes animate in with a slide-up + arrow-draw effect on `IncidentCascaded` events.

A depth indicator shows `Depth: 3 / 5 max` — amber at depth 4, red at depth 5.

Clicking a node opens a side panel listing the specific affected entities for that cascade level.

---

## 6. Protocol status bar

Row of badges below the cascade visualizer. Each shows: protocol code, triggering incident, elapsed active time. Clicking opens a modal explaining procedure steps, affected systems, and resolution actions.

---

## 7. Alert feed

Reverse-chronological scrolling log of all `IncidentAlert` events. Format:

```
[sim_time]  [SEVERITY]  [short_message]
```

`CRITICAL` entries have a bold red left border. Auto-scrolls to latest unless user has manually scrolled up. Max 200 visible entries.

---

## 8. Event injection modal

Opened by `[+ INJECT]`. Form fields:

| Field | Options |
|---|---|
| Event type | runway_incursion, baggage_fire, security_breach, severe_weather, system_failure |
| Severity | low, medium, high, critical |
| Location | Dynamically populated per type (see below) |
| Description | Optional override |

Location options per type:

| Type | Locations |
|---|---|
| `runway_incursion` | runway-09L/09R/27R/27L |
| `baggage_fire` | make-up-{A/B/C}-{1–5} |
| `security_breach` | gate-{id}, terminal-{A/B/C}, airside-{A/B/C} |
| `severe_weather` | airport-wide |
| `system_failure` | conveyor-sorting, conveyor-induction-{A/B/C}, power-{A/B/C}, screening-unit-{1–6} |

After form completion, a **confirmation preview** shows expected immediate effects and cascade chain before submission — teaching the causal model:

```
Injecting: runway_incursion (CRITICAL) on runway-09L

Expected:
  → Runway 09L closed immediately
  → ~6 aircraft go-around / enter holding
  → RUNWAY_STOP protocol activates
  → ~18–34 min disruption

[Cancel]   [Confirm Inject]
```

---

## 9. Resolved incidents panel

Table of today's resolved incidents: sim time, type, status, duration, location, cascade count, `[↓ Report]` button.

The report modal fetches `GET /incidents/{id}/report` and displays a formatted summary: timeline, flights affected, total delay minutes, protocols activated, recommendations. Downloadable as Markdown.

---

## 10. WebSocket integration

Subscriptions: `incidents`, `alerts`

| Event type | Handler |
|---|---|
| `IncidentCreated` | Add card, animate in |
| `IncidentStatusChanged` | Update badge; if resolved: move to resolved panel |
| `IncidentCascaded` | Add child node to cascade tree |
| `IncidentAlert` | Append to feed |

On `critical` + `sound_alert: true`: viewport flashes red once (250ms), auto-dismiss toast appears (10s), nav icon pulses red if user is on another page.

---

## 11. API calls on mount

| Endpoint | Purpose |
|---|---|
| `GET /incidents?status=active,contained` | Active list |
| `GET /incidents?status=resolved` | Resolved panel |
| `GET /alerts?limit=100` | Initial feed |

---

## 12. Key UX behaviours

- **Sound mute toggle** in header: suppresses audio without hiding visual alerts.
- **Tab title counter:** `(2) Incident Operations — ART` when critical incidents are active.
- **Deep cascade warning:** Persistent amber banner when any incident reaches depth 4.
- **Export all:** Full JSON download of all incident records for the current simulated day.

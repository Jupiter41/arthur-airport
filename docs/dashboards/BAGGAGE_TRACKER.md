# Baggage tracking dashboard — specification

**File:** `BAGGAGE_TRACKER.md`  
**App:** `art-dashboard` (React + TypeScript)  
**Route:** `/baggage`  
**Data sources:** `baggage-service`, `flight-service` via API gateway  
**Real-time:** WebSocket topics `baggage`, `incidents`

---

## 1. Purpose

Gives ground handlers and operations staff a live view of the entire baggage handling system at KART: conveyor zone utilisation, item-by-item tracking, dangerous goods flags, system failure impact, and flight baggage loading progress.

---

## 2. Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Baggage Operations                        ART  SIM: Day 1 · 14:32  │
├────────────────────────────────┬────────────────────────────────────┤
│  CONVEYOR MAP                  │  ZONE STATS                        │
│                                │  ┌──────────────────────────────┐  │
│  [induction-A] ──► [screen-1]  │  │ Sorting matrix   59%  1,800/h│  │
│  [induction-B] ──► [screen-2]  │  │ Screening units  72%   OK    │  │
│      ↓               ↓        │  │ Induction-B      91%  ⚠ HIGH │  │
│  [sorting matrix] ──► [make-up]│  └──────────────────────────────┘  │
│  [arrival belts 1–6]           │  FLOW SUMMARY                      │
│                                │  In system:  1,842                 │
│                                │  Flagged:    3   Loaded: 891       │
├────────────────────────────────┴────────────────────────────────────┤
│  FLIGHT BAGGAGE LOADING PROGRESS                                     │
│  AX412  B07  [██████████░░░░░░]  124/186  67%   Dep: 15:30         │
│  BK217  A12  [████░░░░░░░░░░░░]   42/203  21%   Dep: 15:45 ⚠SLOW  │
├──────────────────────────────────────────────────────────────────────┤
│  FLAGGED ITEMS (3)                                                   │
│  Tag: 0074567890  DG Class 3  Flight BK217  Screening unit 4  PEND  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component tree

```
<BaggageTrackerPage>
  <PageHeader />

  <MainPanel>
    <ConveyorMap />               — SVG zone map with live item counts
    <ZoneStatsPanel>
      <ZoneStat />                — one row per zone with utilisation bar
    </ZoneStatsPanel>
    <FlowSummary />               — aggregate counts by status
  </MainPanel>

  <LoadingProgressPanel>
    <FlightBaggageRow />          — per-departure flight loading progress
  </LoadingProgressPanel>

  <FlaggedItemsPanel>
    <FlaggedBaggageRow />         — one per active flagged item
  </FlaggedItemsPanel>

  <BaggageSearchBar />            — search by tag or PNR
  <BaggageDetailDrawer />         — slides in on item click or search result
</BaggageTrackerPage>
```

---

## 4. Conveyor map component

An SVG-based schematic of the KART baggage handling system. Zones are drawn as labelled rectangles connected by directional arrows. Item counts float above each zone, updating in real time.

### Zone layout (schematic)

```
[induction-A] [induction-B] [induction-C]
       ↓             ↓             ↓
[screen-1] [screen-2] [screen-3] [screen-4] [screen-5] [screen-6]
                        ↓
                [sorting-matrix]
               ↙       ↓        ↘
     [make-up-A]   [make-up-B]  [make-up-C]
       (1–5)          (1–5)        (1–5)

[arrival-belt-1] [arrival-belt-2] ... [arrival-belt-6]
```

### Zone colour coding

| Utilisation | Colour |
|---|---|
| 0–60% | green |
| 61–80% | amber |
| 81–100% | red |
| Offline (incident) | gray + `⚠ OFFLINE` badge |

### Live updates

On `BaggageStatusChanged` events, the item count on the affected zone updates immediately. On system failure, the zone dims and shows an `⚠ OFFLINE` badge.

### Clickable zones

Clicking any zone opens a zone detail panel listing all items currently in that zone sorted by time-in-zone descending (oldest first — useful for detecting stuck items).

---

## 5. Flight baggage loading progress

All departing flights in the next 3 simulated hours, sorted by ETD.

| Field | Description |
|---|---|
| Flight number + gate | Link to flight detail |
| Progress bar | `loaded / total_baggage_items` |
| Percentage loaded | |
| Estimated departure | ETD |
| Warning indicator | `⚠ SLOW` if loading pace won't complete before T-15 min |

### Loading pace warning logic

```
remaining_items = total - loaded
time_remaining_min = (etd - sim_time) - 15
items_per_min = (sorting_throughput / 60) × flight_share
estimated_completion_min = remaining_items / items_per_min

if estimated_completion_min > time_remaining_min → show ⚠ SLOW
```

---

## 6. Flagged items panel

All items in `flagged` or `held_for_review` status:

| Field | Description |
|---|---|
| Baggage tag | 10-digit code |
| Flag reason | `dangerous_goods_detected` / `false_positive` |
| DG class | Class number + description if DG |
| Passenger + flight | Links |
| Current zone | Location in system |
| Review status | `PENDING` / `CLEARED` / `REJECTED` |

DG class 3 (flammable) items are highlighted red. New flagged items animate amber on appearance.

---

## 7. Baggage search

Accepts: 10-digit tag (exact), PNR (6-char), passenger name (partial), or flight number. Results populate the detail drawer.

---

## 8. Baggage detail drawer

- Tag + weight
- Passenger name / PNR
- Flight + status
- DG class badge if applicable
- Full scan history timeline (zone → status → timestamp per scan)
- Current location highlighted on the conveyor map

---

## 9. WebSocket integration

Subscriptions: `baggage`, `incidents`

| Event type | Handler |
|---|---|
| `BaggageStatusChanged` | Update zone count + loading panel |
| `BaggageFlagged` | Add to flagged panel, flash amber |
| `IncidentCreated` (system_failure) | Mark zone offline on map |
| `IncidentStatusChanged` (resolved) | Restore zone |

---

## 10. API calls on mount

| Endpoint | Purpose |
|---|---|
| `GET /baggage/flow/map` | Zone counts for conveyor map |
| `GET /baggage/flow/summary` | Aggregate stats |
| `GET /baggage/flagged` | Flagged panel |
| `GET /flights?direction=departure&status=boarding,scheduled` | Loading progress |

---

## 11. Key UX behaviours

- **System failure visual:** Affected zone dims on map; `⚠ SYSTEM FAILURE` banner identifies zone + elapsed offline time.
- **Baggage fire auto-highlight:** On `baggage_fire` incident, the affected make-up zone pulses red for 5 seconds before settling to offline state.
- **Throughput sparkline:** 30-sim-minute sparkline beside the sorting matrix stat confirms recovery after failures.

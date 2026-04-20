# Sprint 21 — UI Bugs, Day Transition, Baggage Fixes

## Status: IN PROGRESS

## Issues identified

### 1. Dropdown z-index overlap (HeaderBar)

- **Symptom**: Nav dropdown menus mix up with page content, hard to click
- **Root cause**: The dropdown has `z-50` but the `main` content area has `overflow-hidden`, potentially causing clipping+overlap issues. The header `<nav>` also needs proper stacking context.
- **Fix**: Add proper `relative z-50` to the header and ensure dropdowns use `z-[100]` or higher. Add `isolate` to header to create stacking context.

### 2. Passengers page colors

- **Symptom**: Colors could be more distinct and readable
- **Fix**: Improve heatColor palette for better contrast on dark backgrounds. Add more distinct color stops and better opacity handling.

### 3. Ground Ops terminal C icon only

- **Symptom**: Terminal C only shows an icon, no gate data
- **Root cause**: `TerminalBlock` renders gates via `gates.slice(0, 14)` — if Terminal C has fewer gates assigned or gate IDs don't match the terminal filter, it renders empty.
- **Fix**: Investigate gate data for terminal C and fix the terminal-detection logic.

### 4. Ground Vehicles display issues

- **Symptom**: All vehicle types show 100% busy except stairs. Numbers appear correct but layout is cramped.
- **Fix**: This may be a backend issue (all vehicles always dispatched) or a display issue. Investigate backend ground vehicle state management.

### 5. Incident page too crowded

- **Symptom**: Page mixes incidents, reports, LLM, what-ifs etc. all on one scroll
- **Fix**: Split into tabbed sections:
  - Tab 1: "Incidents" — Active incidents list, cascade tree, protocol bar, alert feed, resolved list
  - Tab 2: "Analysis" — Bottlenecks, recommendations, what-if panel
  - Tab 3: "AI Tools" — Anomaly panel, NL query, NL inject, narration, report generator

### 6. ML/Agent training page

- **Symptom**: No page exists to start RL training, view progress, etc.
- **Fix**: Add new route `/ml` with a dedicated MLTrainingPage that:
  - Shows current RL agent status (training/idle)
  - Start/stop training controls
  - Training progress (episode, reward, steps)
  - Model comparison table

### 7. Arrival baggage not emptying (332/332)

- **Symptom**: Arrival flights at gate show full baggage count, never decreasing
- **Root cause**: Flight-service `baggage_loaded` query counts `on_carousel` and `collected` statuses as "loaded". For arrivals, bags transition from `in_hold` → `on_carousel` → `collected`, all of which count as "loaded".
- **Fix**: For arrival flights, use different semantics:
  - `baggage_loaded` for arrivals should count `collected` bags only (successfully claimed)
  - Or introduce `baggage_claimed` / `baggage_delivered` field for arrivals
  - Simplest: change the Cypher query to differentiate by flight direction

### 8. Day 2 display stuck on Day 1

- **Symptom**: When simulation reaches Day 2, the UI still shows "Day 1" and all flights appear as SCHEDULED
- **Root cause (display)**: `updateFromTick` in simStore.ts never updates `day_number`. WebSocket handler in useWebSocket.ts ignores `day_of_sim` from tick payload.
- **Root cause (flights)**: Flight list endpoint is day-scoped by `sim_time.date()`. On day 2, it returns only Day 2 flights which are all newly seeded as SCHEDULED.
- **Fix**:
  1. Update `updateFromTick` to accept and set `day_number`
  2. Update WebSocket handler to pass `day_of_sim` from tick payload
  3. The flights being SCHEDULED on Day 2 is correct behavior — but the UI should clearly show "Day 2" so the user understands the context switch

## Implementation order

1. Day 2 display fix (backend data flow → frontend)
2. Arrival baggage semantics fix (backend Cypher)
3. Dropdown z-index fix (CSS only)
4. Passengers page colors (CSS only)
5. Ground Ops terminal C fix (investigate + fix)
6. Ground Vehicles display fix (investigate + fix)
7. Incident page tabs (React refactor)
8. ML Training page (new page)

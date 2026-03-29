# Sprint 8 — Lessons Learned

**Goal:** Build all 5 dashboards with real-time WebSocket data, simulation controls, and incident injection.

---

## 1. WebSocket handling

### Reconnection strategy

- Exponential backoff with a 30-second cap works well. The gateway sends a `snapshot` frame on connect which re-syncs state, so no explicit "catch-up" logic is needed on the client.
- The heartbeat timeout must be longer than the server's heartbeat interval (15s) to account for jitter. We used 20s on the client side.

### Event duplication

- React's StrictMode double-mounts components in dev, which opened two WebSocket connections. Solution: store the WebSocket ref and check `readyState` before creating a new connection. The `useRef` + `useEffect` cleanup pattern prevents duplicates.

### Topic subscription

- Subscribing to all 6 topics (`flights`, `passengers`, `baggage`, `weather`, `incidents`, `alerts`) on a single connection is simpler than per-page subscriptions. The volume is manageable because the gateway already filters by `event_type`.

---

## 2. State synchronization

### Zustand store design

- Normalized stores (keyed by entity ID) are essential for O(1) updates on WebSocket events. Using `Record<string, T>` instead of arrays eliminates the need to search for entities on every event.
- The `flashIds: Set<string>` pattern for row update animations works — add to set on event, remove after 1500ms timeout. The `Set` is replaced each time to trigger re-renders.

### REST hydration + WebSocket updates

- Initial data load via REST (`useEffect` on mount) populates the store, then WebSocket events patch it. This avoids a "blank screen" on page load while still being real-time.
- Race condition risk: a WebSocket event may arrive for an entity not yet in the store (flight created between REST call start and WS subscription). Current approach: silently ignore events for unknown entities. This is acceptable because the next REST call will pick them up.

### Store coupling

- Incident overlays on the baggage and passenger pages require reading from `incidentStore` in addition to the domain store. This cross-store dependency is handled via `useIncidentStore` in the page component — no store-to-store coupling.

---

## 3. Performance

### Large flight lists

- 420 flights × 2 FIDS panels = 840 rows total. Pagination to 20 rows per page keeps the DOM small. Memoizing the departure/arrival filter with `useMemo` prevents recalculation on every irrelevant state change.

### SVG rendering

- The conveyor map (18 zones), airfield schematic (terminals + runways), and passenger heatmap all use SVG. Performance is good because the element count stays under ~200 nodes. CSS transitions on `fill` and `opacity` are smoother than React re-renders for heat color changes.

### Heatmap transitions

- Using `transition-all duration-700` on zone cells gives a natural "heat rising/falling" effect. The 0.7s duration is a good balance between responsiveness and smoothness.

---

## 4. Animation complexity

### Flight row flash

- The flash animation uses Zustand state (`flashIds`) rather than CSS animation classes because the trigger is a WebSocket event, not a DOM event. The 1500ms timeout for clearing the flash is simple but effective.

### Runway aircraft movement

- SVG `<animateTransform>` provides smooth, performant aircraft movement on runway strips without React re-renders. Landing aircraft animate right-to-left, departures left-to-right.

### Holding stack orbiting

- Used SVG `<animateTransform type="rotate">` for circling indicators. Each aircraft has a slightly different duration (3s, 4s, etc.) to avoid synchronized movement, which looks more natural.

### Incident pulse

- Tailwind's `animate-pulse` on critical incident cards and the red banner is sufficient. No custom keyframes needed.

---

## 5. API inconsistencies discovered

### Response envelope variations

- Flight list returns `{ flights: [...], total: N }`, baggage map returns `{ zones: [...] }`, passenger heatmap returns `{ zones: [...] }`, but incident alerts may return `{ alerts: [...] }` or a flat array depending on whether the gateway wraps the response. Solution: defensive destructuring with fallback to array check.

### Null vs. missing fields

- Some services return `null` for optional fields, others omit them entirely. The TypeScript types use `| null` but the runtime code needs `??` operators for both cases.

### Weather event payload

- `WeatherStateChanged` payload uses `new_category` (the new state) rather than `category`. The store update handler must map both field names.

---

## 6. UX issues and improvements

### Dark theme

- The dark airport-operations aesthetic (gray-900 background, teal/blue accents) feels authentic. The contrast ratio for text is adequate for operational use.

### Information density

- The flight board is dense by design — real FIDS show as much as possible. The detail drawer provides depth without cluttering the main view.

### Incident injection workflow

- The preview step before injection is critical for teaching the causal model. Showing expected cascade effects helps operators understand the system's behavior.

### Responsive concerns

- The current layout assumes a wide monitor (≥1280px). The grid-based layouts would need significant restructuring for narrow viewports. Not a priority for a control-room application.

---

## 7. What I would redesign

### React Query for REST calls

- Currently using raw `fetch` in `useEffect`. React Query would add caching, automatic refetch on window focus, and better loading/error states. Skipped to keep the implementation simpler but would add in a production scenario.

### WebSocket message types

- The current dispatcher uses a large `if/else` chain on `event_type`. A registry pattern (`Map<string, (payload) => void>`) would be cleaner and more extensible.

### Component granularity

- The page files are large (300+ lines each) because they contain subcomponents. Extracting each subcomponent to its own file would improve maintainability but adds file overhead for a teaching project.

### Store middleware

- Zustand's `devtools` middleware would help debugging store updates in development. Not included to minimize dependencies.

### Testing

- No unit tests for stores or components in this sprint. The stores' reducer logic (update, upsert, flash) should be unit-tested. Component tests with MSW for API mocking would validate the full data flow.

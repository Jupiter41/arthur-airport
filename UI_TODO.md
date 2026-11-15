# UI / UX TODO

Updated: 2026-11-15. Status: proposed backlog; all items remain unimplemented.

Design rationale, source findings, proposed information architecture and workflow sketch: [Detailed UI/UX review](docs/dashboards/UI_UX_REVIEW.md).

## Goal and review limits

Make the airport easy to navigate and investigate: what needs attention, where it is happening, what is affected, which action is available, and whether it worked.

This backlog comes from a source-based review. The local preview could not be reached because of a socket/network restriction. Rendered layout, contrast, performance, responsive behavior and live workflows still need verification. Suspected scroll/layout issues are risks to reproduce, not confirmed browser failures.

## P0 — Navigation and immediate friction

- [ ] Replace the crowded global navigation with Operations, Planning and System workspaces, a labelled desktop sidebar and a labelled mobile/tablet drawer.
- [ ] Organize Operations into Overview, Flights, Airfield, Terminal, Incidents and Decisions. Place ground operations/ATC within Airfield and passengers/baggage/special assistance within Terminal.
- [ ] Organize Planning around Experiments and Performance. Validate whether the World map belongs here under the clearer name Network.
- [ ] Move simulation setup, data sources, model training, diagnostics and access into System.
- [ ] Keep shared-airport scenarios and isolated planning experiments explicitly distinguished; preserve existing routes as aliases during migration.
- [ ] Rename Cockpit to Overview and operational Accessibility to Special assistance. Retain readable navigation labels at smaller breakpoints.
- [ ] Simplify the header to page/scope context, simulated clock, speed, paused state and concise data health. Move export into the relevant page toolbar.
- [ ] Replace the persistent credential form with an account dialog and compact role/control indicator. Explain disabled actions locally.
- [ ] Move reset and detailed simulation controls into a dedicated panel; describe reset consequences in a focused confirmation.
- [ ] Keep the user's selected flight sort stable during live updates. Remove update-flash priority from the main sort; highlight changed cells without moving rows.
- [ ] Define consistent scroll ownership across routes; reproduce and fix potential planning-page clipping under the shell's hidden overflow.

## P0 — Coherent operational views and investigation

- [ ] Replace the 3D on/off switch with explicit Board / Map / 3D views where useful. Keep essential information and actions accessible in every representation.
- [ ] Default routine investigation to the most legible board or 2D schematic; retain 3D as a deliberate spatial view.
- [ ] Preserve terminal scope, selected entity and relevant filters across representation changes. Put shareable scope and entity IDs in the URL.
- [ ] Open incident details from Overview before decision history. Keep summary, affected entities, cascade, actions and related decisions together.
- [ ] Deliver one complete journey: Overview → terminal congestion → proposal → approval → execution → measured outcome.
- [ ] Preserve queued, executed and awaiting-measurement distinctions. Never imply execution from dispatch alone or causal impact from an unqualified observed change.
- [ ] Update `docs/dashboards/AIRPORT_3D.md` and `docs/dashboards/OPERATOR_COCKPIT.md` before implementing changes to their explicit default-on 3D and cockpit contracts.

## P1 — Overview

- [ ] Rebuild the first viewport around a Needs attention queue beside a readable airport schematic.
- [ ] Show location, problem, impact, simulated observation time and next action for each attention item. Use transparent priority rules.
- [ ] Add a compact contextual metric strip with definitions and filtered drill-down links, including delayed flights and terminal security waits.
- [ ] Show near-term schedule/capacity pressure and pending actions below the main attention area. Label observed trends and predictions accurately; do not invent forecasts.
- [ ] Give healthy conditions little visual weight. Keep unavailable/stale observations explicit rather than displaying healthy zeroes.
- [ ] Move teaching instructions to Help/Lab, remove the promotional 3D card, and keep detailed decision history in its dedicated workspace.

## P1 — Flights

- [ ] Use a full-width table by default with All / Departures / Arrivals controls; retain split-board mode as an option.
- [ ] Expose flight search, terminal/status filters and saved views such as Delayed and Departing soon.
- [ ] Keep scheduled time, estimated time, delay, gate and status in predictable columns. Put specialist columns behind configuration controls.
- [ ] Collapse secondary statistics/trends by default when they reduce the primary board's usable space.
- [ ] Use a nonmodal inspector for routine flight detail and a full-screen detail route on narrow screens.
- [ ] Store the selected flight ID rather than a copied flight object; derive current details from live data.
- [ ] Preserve URL, filters, sort, scroll and selection when returning from details.

## P1 — Terminal, baggage and airfield

- [ ] Build a terminal comparison board showing observed wait, queue count, capacity, trend and exceptions.
- [ ] Keep terminal selection visible and consistent across Board / Map / 3D.
- [ ] Emphasize baggage exceptions, delayed/misrouted items, conveyor failures and actual scan history.
- [ ] Distinguish aggregate representative bags/passengers from individually tracked records.
- [ ] Make the airfield schematic readable with runway identifiers, gates, selected aircraft, layers and a status legend.
- [ ] Preserve 3D camera presets and the inspector. Move rendering quality and lengthy modelling explanations into view settings/help.
- [ ] Retain concise visible disclosures for schematic geometry and simulated operational data; preserve existing reduced-motion support.

## P1 — Incidents and decisions

- [ ] Consolidate incident investigation with contextual recommendations, approvals and decision timelines.
- [ ] Move scenario injection into Lab/Simulation; distinguish read-only natural-language investigation from state-changing injection.
- [ ] Lead decision details with proposed action, expected effect, evidence quality, status and next step.
- [ ] Expand ranking formula, receipts, provenance and causal evidence on demand without dropping required uncertainty disclosures.
- [ ] Add server-side search across decision history. Keep current-page search explicitly labelled until this exists.
- [ ] Preserve read-only historical decision playback and make its recorded-history state unmistakable; do not imply full airport rewind.

## P1 — Visual system and interaction consistency

- [ ] Establish shared page headers, toolbars, tables, inspectors, buttons, filters, status badges and loading/error/empty states.
- [ ] Adopt neutral graphite surfaces with one blue/cyan interaction accent; reserve amber/red for meaningful severity and green for confirmed normal/completed states.
- [ ] Remove gradient branding, decorative glass blur/glow and hover elevation from static containers. Reduce unnecessary card wrappers.
- [ ] Replace emoji navigation with one consistent SVG icon set.
- [ ] Standardize spacing and approximately 6–8px control/panel radii.
- [ ] Start with 14px body/table text, 12–13px supporting labels, 16px section titles and 24px page titles; validate legibility in rendered views.
- [ ] Use tabular numerals for operational values and time, and monospace selectively for identifiers.
- [ ] Replace promotional slogans and repeated tiny uppercase labels with concrete operational information.
- [ ] Replace API/WS and REST-reconciliation jargon with concise data status, while retaining expandable technical details.
- [ ] Distinguish simulated observation time from wall-clock fetch age, including when the simulation is paused.

## P1 — Accessibility and responsive behavior

- [ ] Provide keyboard-accessible navigation disclosures with expanded state, visible focus and appropriate focus return/Escape behavior.
- [ ] Make flight detail access, sorting and filtering keyboard accessible; expose table sort state with `aria-sort`.
- [ ] Add a skip link and consistent drawer/dialog focus management.
- [ ] Provide text alongside status colors and textual access to map/3D entities. Avoid announcing every streaming update.
- [ ] Verify WCAG 2.2 AA contrast and target-size requirements; prefer comfortable 36–44px common controls where space permits.
- [ ] Verify every route at 1440×900, 1280×720, tablet and narrow phone widths, plus 200% browser zoom.
- [ ] Keep navigation and essential actions reachable; use horizontal scrolling for dense specialist tables where needed.
- [ ] Define whether mobile supports monitoring/triage or full operational parity, and validate the resulting scope.

## P2 — Planning and supporting tools

- [ ] Consolidate scenario library, builder, what-if and comparisons into Baseline → Changes → Run → Compare → Save.
- [ ] Keep baseline identity, units, run state and shared/isolated effects visible throughout experiments.
- [ ] Make investment analysis a deeper result view; explain specialist terms on demand.
- [ ] Group costs, carbon and operational history into clearly named Performance views.
- [ ] Add global entity search and a command palette as supplements to visible navigation.
- [ ] Add and validate light/dark theme support after navigation and hierarchy are established.

## Dependencies and architectural constraints

- [ ] Specify gateway/data contracts before adding global search, history-wide decision search, impact aggregates or forecasts not already exposed.
- [ ] Keep all frontend requests through the gateway and preserve the existing per-domain source-of-truth rules.
- [ ] Keep state-changing business behavior in its owning service with Kafka events; do not introduce frontend-only operational mutations.
- [ ] Keep generated operational data synthetic and explicitly distinguish lab fixtures from live simulation observations.

## Delivery order and acceptance

1. Shell, navigation, access, stable sorting, scroll ownership and keyboard basics.
2. One polished Overview-to-congestion-to-outcome journey and its reusable components.
3. Flights, baggage, airfield and incidents using the same interaction patterns.
4. Planning, supporting tools, theme and responsive refinements.

- [ ] Capture rendered baseline screenshots and reproduce source-identified layout risks before implementation.
- [ ] Run formative usability sessions with people unfamiliar with the app; record task completion, time, wrong turns and assistance needed.
- [ ] Test identifying the top issue, finding a delayed flight/gate, locating congestion, explaining proposal execution state, finding an outcome and creating an isolated experiment.
- [ ] Validate proposed targets: top issue identifiable within 10 seconds; known flight reachable within two interactions using search; selection/scope retained across views; no live-update sorting jumps; no unreachable route content at tested sizes.
- [ ] Validate that users distinguish queued, executed and measured outcomes and shared-airport actions from isolated experiments.

Accessibility references: [WCAG 2.2](https://www.w3.org/TR/WCAG22/) and [WAI disclosure navigation](https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/examples/disclosure-navigation/).

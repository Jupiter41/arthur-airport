# Airport dashboard UI/UX review

Date: 2026-11-15. Proposal only; no product code changed.

## Review scope and confidence

Reviewed the architecture, cockpit and 3D contracts, application shell, navigation, access controls, global styles, cockpit, flight board, passenger flow, spatial inspector, incident console, decision workspace, and selected planning/settings pages. Findings below distinguish code-confirmed behavior from design judgments and risks requiring rendered verification.

The local Vite preview started, but browser access timed out and a local HTTP check reported a socket-permission restriction. No rendered screenshots, live-data journeys, measured contrast, performance measurements, or user testing were available. This is a source-based expert review, not a completed visual/accessibility audit. Mobile layout and scroll findings are implementation risks until reproduced in a browser.

## Assessment

The interface exposes considerable domain depth, but asks the user to assemble that depth into a workflow. Its structure follows feature accumulation: flights, incidents, analysis, AI tools, planning, what-if, simulation, training, and debugging coexist in one application shell. The result is hard to learn and visually generic despite an unusually specific subject.

The most valuable redesign is to make operational investigation the organizing principle. A user should be able to answer: what needs attention, where is it happening, what is affected, which action is available, and did that action work?

Keep the simulation clock, explicit uncertainty, decision evidence, synthetic-data identity, and spatial representations. These are differentiators. Give each a clear place and an appropriate level of detail.

## Findings and proposed changes

| Priority | Evidence | UX consequence | Proposed change |
| --- | --- | --- | --- |
| P0 | `HeaderBar.tsx` has 20 destinations; Ops mixes ground operations, ATC, costs, carbon, assistance and World; Simulation mixes experiments, ML, sources, settings and debugging. | Categories are difficult to predict. Users must remember where features live. | Separate Operations, Planning, and System workspaces. Use visible text navigation within each. |
| P0 | `OperationalView.tsx` enables 3D unless `3d=off`; the spatial component replaces the domain page. | Passenger charts, baggage tools and traffic tables are hidden behind a rendering preference. Changing representation changes the available task tools. | Use Board / Map / 3D tabs with consistent scope, selection and essential actions. Default routine work to Board or a clear 2D map. |
| P0 | `FIDSPanel.tsx` prioritizes `flashIds` before the selected sort. | Updating rows can jump above the user's chosen order. Tracking or clicking a flight becomes less reliable. | Keep sorting stable. Mark changed cells and show an update count. Offer an explicitly chosen recent-updates view. |
| P0 | Cockpit incidents navigate to filtered decision history; incident actions and approvals also live in separate surfaces. | An incident investigation can lose the operational context while moving into history. | Open an incident detail workspace first, with impact, actions and linked decision history. Preserve the incident target throughout. |
| P1 | Header includes navigation, weather, incident status, API/WS health, clock, speed, pause, reset and export; `AccessBar.tsx` adds a persistent credential form for viewers. | Everyday navigation competes with session administration and simulator controls. | One compact status bar; account/control menu; a dedicated simulation control panel. Keep time, speed and paused state visible. |
| P1 | Cockpit contains indicators, schematic state, incidents, approvals, a 3D promotional link, decision workspace, and teaching runbook. | Several purposes compete on the landing page. Urgent work is one section among many. | Make Overview an attention queue plus airport context and near-term pressure. Move teaching instructions to Help/Lab and detailed history to its own workspace. |
| P1 | `index.css` gives cards rounded corners, shadows, blur and hover elevation; pages also use independent gray/slate styles. | Decorative panels flatten hierarchy, and separate visual dialects make the product feel assembled. | Shared flat surfaces, restrained borders, consistent typography, unified controls, fewer card wrappers. |
| P1 | Navigation uses emojis; labels disappear below the `lg` breakpoint. | Recognition depends on ambiguous symbols, with platform-dependent appearance. | Use one SVG icon set and retain readable labels through a drawer or sidebar. |
| P1 | Flight board has an unconditional two-column arrivals/departures layout and an expanded statistics area. | The available reading width is divided even when users need to investigate one set of flights. | Full-width board by default; All / Departures / Arrivals controls; optional split-board display mode; secondary trends collapsed. |
| P1 | Flight selection is a component-state `Flight` object rather than an entity ID in the URL. Spatial selection is also local state. | Details cannot be reliably bookmarked/shared; copied records risk lagging behind live store changes. | Put selected ID and scope in the URL and derive details from current data. Preserve selections across representations. |
| P1 | Decision search filters only the fetched page, explicitly labelled as such. | Users can miss an existing decision unless they manually paginate. | Add server-side search/filtering over history. Retain the honest label until supported. |
| P1 | Navigation disclosures lack `aria-expanded`/`aria-controls`; flight rows and sorting headers rely on pointer clicks. | Keyboard and assistive-technology users lack equivalent navigation and table actions. | Disclosure semantics, keyboard-accessible links/buttons, sort buttons with `aria-sort`, dialog focus management, visible focus. |
| P1 | `App.tsx` hides main overflow; `PlanningPage.tsx` lacks the height/scroll wrapper used on other pages. | Long planning content may become unreachable at shorter viewport heights. | Define one scroll ownership contract and test it across all routes and zoom levels. |
| P2 | Frequent 10–11px labels, uppercase tracking, long provenance paragraphs and internal terms such as owner receipts and REST reconciliation. | Important explanations are hard to scan; internal architecture leaks into operational tasks. | Readable type, concise status summaries, progressive disclosure for provenance and technical detail. |

P0 means address in the first redesign slice; it does not claim production safety severity.

## Proposed information architecture

Use a workspace selector above a roughly 224px desktop sidebar. On smaller screens, use a labelled navigation drawer. A command palette supplements visible navigation.

**Operations**

- Overview
- Flights
- Airfield — ground operations and ATC as local tabs
- Terminal — Passengers, Baggage, Special assistance as local tabs
- Incidents — Active, Needs approval, Resolved
- Decisions — lifecycle tracking and evidence

**Planning**

- Experiments — scenario library, builder, what-if and comparisons within one coherent workflow
- Performance — operational history, costs and carbon as clearly separated views
- Network — the current World map, if its main purpose supports planning; validate this placement with the intended user

**System**

- Simulation setup and control
- Data sources
- Model training
- Diagnostics
- Account/access

Do not treat scenario execution against the shared airport and isolated planning runs as equivalent. Use explicit badges and copy: “Shared airport” versus “Isolated experiment.” Group the tools while preserving their different effects. Keep existing routes as aliases during migration.

Rename Cockpit to Overview, Ops to Airfield where appropriate, World to Network, and the operational Accessibility page to Special assistance. Distinguish assistance operations from accessibility preferences for the application itself.

## Overview composition

The first viewport should present current simulated time and scope, actionable exceptions, and the airport context needed to understand them. The following is a structural sketch, not a rendered design:

```text
Workspace/sidebar | Overview   All terminals   Search   Sim time · speed · status
                  |------------------------------------------------------------
                  | Needs attention                         Airport schematic
                  | Priority · location · issue · impact     Runways and gates
                  | Open incident / review proposal          Terminal conditions
                  |------------------------------------------------------------
                  | Next 60 simulated minutes               Pending actions
                  | Departures · queue pressure · capacity   Approval / execution
```

Attention entries should say what is wrong, where, what is affected and the next action. Sort by severity, then a transparent domain rule such as deadline or affected flights. Do not invent an opaque aggregate airport-health score.

Use a compact strip for a few contextual metrics. Each should expose its definition and scope. Clicking delayed flights should open the board with the matching filter; clicking security wait should open the affected terminal. If near-term forecasts do not exist, show an observed trend and schedule-based view labelled accordingly.

Give healthy states little visual weight. Reserve strong emphasis for actual exceptions. Missing observations must remain visibly unknown; an empty incident list after a failed request must not become “All clear.”

## Core investigation workflow

Design and validate a complete Terminal B congestion journey:

1. Overview surfaces an actual queue threshold breach with terminal and simulated observation time.
2. Selecting it opens the passenger workspace with Terminal B already selected.
3. A persistent detail pane shows wait, open lanes, affected connections, relevant incidents and available proposals.
4. A proposal explains the proposed change, expected effect, evidence quality and required permissions. Use real backend estimates only.
5. Approval or submission produces a clear pending state. “Queued,” “Executed,” and “Awaiting measurement” remain separate states.
6. The outcome view distinguishes prediction, observed change and attributed change. Missing controls or measurements remain explicit.

This joins existing capabilities into one journey. It should not change ownership of business logic or introduce direct service calls.

## Page-specific direction

### Flights

Use a full-width operational table with visible search, terminal/status filters and saved views such as Delayed and Departing soon. Show scheduled and estimated times, delay, gate and status in predictable columns. Move specialist columns into configurable density/column controls.

Keep the flight drawer open without dimming the whole board for ordinary inspection. Reserve modal treatment for actions requiring focused input. On narrow screens, use a full-screen detail route. Preserve filter, scroll, sort and selection when returning.

### Terminal and baggage

Default to a terminal comparison board: observed wait, queue count, capacity, trend and exceptions. Clicking a zone reveals detail. Keep terminal scope visible in both Board and Map/3D modes.

Baggage should emphasize delayed/misrouted items, conveyor exceptions and scan history. The spatial rendering should locate the problem, while the inspector carries actual records. Keep aggregate representative bags distinct from individually tracked items.

### Airfield and 3D

Make the map useful at a glance: runway identifiers, gate labels, selected aircraft, meaningful status legend, and layers. Use a top-down schematic as the calm default where spatial reasoning helps.

Preserve 3D as a deliberate spatial view with camera presets, selection and an inspector. Move rendering quality and long motion/model explanations into a view-settings/help panel. Retain a concise visible “Schematic geometry; simulated operational data” disclosure. Extend the existing reduced-motion behavior rather than assuming it is absent.

### Incidents and decisions

Incident detail should combine summary, affected entities, cascade, available actions and decision history. Move scenario injection into Lab/Simulation. Separate natural-language investigation from state-changing injection; the current AI Tools grouping obscures that distinction.

Present a decision summary first: proposed action, expected effect, confidence/validation, status and next step. Put detailed ranking formula, receipts and causal evidence in expandable sections. Preserve the distinctions required by the decision contract.

### Planning

Guide users through Baseline → Changes → Run → Compare → Save. Show units, run state and baseline identity consistently. Investment analysis can be a deeper result view. Explain domain terms on demand instead of leading the page with implementation methods.

## Visual direction

Adopt a precise, quiet airport operations aesthetic: legible data tables, schematic airfield geometry, restrained surface layers and clear exception states.

- Use a neutral graphite application background, slightly lighter panels and one blue/cyan interaction accent. Use amber/red for severity and green for confirmed normal/completed states. Avoid assigning every feature a competing bright color.
- Remove gradient branding, decorative glow, glass blur and hover elevation from static containers. Use subtle background changes for actual interactive rows.
- Use 6–8px control/panel radii and a consistent spacing scale. Allow tables and section dividers to create structure without wrapping everything in cards.
- Starting typography: 14px body/table text, 12–13px supporting labels, 16px section titles, 24px page titles. Use tabular numerals for counts and time; monospace selectively for identifiers.
- One page title, one clear scope and a predictable toolbar per page. Replace repeated promotional headings with concrete operational information.
- Support dark and light themes after the structure works. Validate both; theme switching alone will not solve navigation.

## Time, freshness and control

Keep “Simulated” visible with clock, timezone, speed and paused state. Historical decision playback must carry its own persistent “Recorded history” treatment and remain read-only. Do not imply a full airport rewind when only decision stages replay.

Distinguish operational observation time from wall-clock fetch age. A paused simulation can have an old simulated timestamp and a healthy connection. Replace global API/WS jargon with a concise data-status summary and expandable per-domain freshness.

Move sign-in to an account dialog. Keep a compact role/control indicator with a clear way to request operator control. Explain disabled actions locally. Move reset to the simulation panel with explicit consequences and a dedicated confirmation rather than a transient two-click label beside Pause.

## Accessibility and responsive acceptance criteria

Use WCAG 2.2 AA as the baseline, with larger comfortable targets where possible. Verify normal text contrast at 4.5:1, large text at 3:1, and applicable non-text controls at 3:1. The AA minimum target criterion is 24×24 CSS pixels subject to its exceptions; prefer 36–44px controls for common actions.

Use keyboard-accessible disclosure navigation, visible focus, labelled sort/filter controls, proper table headers, drawer/dialog focus behavior and Escape handling. Add a skip link. Keep status text alongside color and offer textual access to map/3D entities. Avoid broadcasting every streaming update to screen readers.

Test at 1440×900, 1280×720, tablet width, and a narrow phone viewport, plus 200% browser zoom. Dense specialist tables may scroll horizontally, but primary navigation and essential actions must remain reachable. Define mobile as monitoring/triage first if full operational parity is out of scope.

References: [WCAG 2.2](https://www.w3.org/TR/WCAG22/) and [WAI disclosure navigation example](https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/examples/disclosure-navigation/). These support accessibility requirements; the product structure and visual recommendations above are project-specific design judgments.

## Delivery sequence

1. **Shell and immediate friction:** workspace/sidebar navigation, compact status header, account dialog, stable flight sorting, shared scroll ownership and keyboard basics. Preserve routes and domain behavior.
2. **One polished vertical slice:** Overview → Terminal congestion → proposal → approval → execution → outcome. Establish shared toolbar, table, inspector, severity and feedback patterns here.
3. **Extend the system:** flights, baggage, airfield and incidents; coherent Board/Map/3D behavior with shared selection and scope.
4. **Planning and supporting tools:** experiment workflow, results comparison, history, system tools and theme/responsive refinements.

Before changing defaults, update `AIRPORT_3D.md` and `OPERATOR_COCKPIT.md`: the existing default-on 3D and cockpit composition are explicit contracts. Do not silently implement a conflicting redesign.

Frontend-only work includes shell/layout, typography, stable sorting, disclosure semantics and much of URL state. API/data work is needed for global entity search, history-wide decision search, complete filtered deep links, some impact aggregates and forecasts where they are not already exposed. Specify those contracts before implementation.

## Validation plan

Recruit a small formative sample, for example five people unfamiliar with the app. Record baseline and redesigned task completion, time, wrong turns and assistance needed. This is usability feedback, not statistical validation.

Tasks: identify the most urgent issue; find a delayed flight and its gate; locate terminal congestion; inspect a proposal and explain whether it has executed; find its measured outcome; create an isolated experiment without affecting the shared airport.

Proposed design targets, to validate rather than report as achieved: identify the top issue within 10 seconds; reach a known flight within two interactions using search; maintain selection and scope across Board/Map/3D; no automatic flight reordering under a selected sort; no inaccessible route content at tested sizes; clear queued/executed/measured distinctions in task responses.

The redesign succeeds when users can carry an investigation to an outcome without reconstructing context across unrelated pages.

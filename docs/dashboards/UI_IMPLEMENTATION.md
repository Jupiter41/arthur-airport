# Dashboard workspace contract

Updated 2026-11-15. Supersedes earlier navigation, cockpit composition and default-on 3D requirements.

Operations has Overview, Flights, Airfield (ground/ATC), Terminal (passengers/baggage/special assistance), Incidents and Decisions. Planning contains isolated Experiments, Performance (history/costs/carbon) and Network. System contains shared-airport Simulation/Lab, sources, models, diagnostics and Help. Existing URLs remain valid. Mobile supports monitoring and triage with access to specialist tools through scrollable views.

The shell owns route scrolling. Pages use normal document flow inside the scrollable main region; map/table panes may own bounded local scrolling. All navigation retains text labels. Account credentials live in a focused dialog, with the controller lease renewal mounted independently of its visibility. Simulation time, UTC, speed and pause remain visible; wall-clock fetch age is separate.

Operational routes default to Board. `mode=board|map|3d` selects representation; legacy `3d=on|off` remains supported. `terminal`, `entity`, and domain filters survive representation changes. Map is a schematic top-down spatial presentation; 3D keeps camera presets. The domain board remains available beneath spatial views so actions and records remain accessible. Selected entities use URL IDs and current owner observations. Shared-airport mutations retain existing authorization and service ownership.

Overview prioritizes actual incidents, observed security waits >=20 minutes and conveyor utilisation >90 percent. It provides filtered drill-downs, runway/gate context, pending approvals and the next 60 simulated minutes of scheduled flights. This is schedule context, not a forecast. No synthetic health score or invented outcome is introduced. Teaching instructions move to Help.

Flight boards default to full width, allow arrivals/departures/all/split, preserve URL filters and sort, and never prioritize changed rows ahead of the selected sort. Details are nonmodal on desktop, with keyboard focus/return and a narrow-screen detail presentation. Known flight IDs can be fetched directly through the gateway.

Search uses gateway domain endpoints. The command palette distinguishes navigation, bounded flight/incident observations and baggage lookup; it must not imply an exhaustive search when results are bounded. Decision history supports `q` (max 200 characters) and `terminal` filters in analysis-service before pagination. Match description, IDs, action and target zone; terminal matching uses normalized exact terminal identity, not substring letter matching. Existing incident/status/bottleneck filters remain composable. Gateway relays these query parameters, with no domain logic added.

Experiments expose baseline, changes, run state, comparison and investment/audit views. Shared-airport scenario injection remains in Simulation/Lab with an explicit effect label. Historical decision replay stays read-only and does not rewind the airport.

Dark/light themes share semantic colors and controls. Keyboard focus, skip navigation, labelled sort/filter controls, reduced motion and text alternatives to maps are required. Validation must report actual checks; formative human testing and unavailable backend execution are never marked complete by inference.

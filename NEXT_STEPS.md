# Next steps — make the living twin visible

**Updated:** 2026-11-16
**Purpose:** Portfolio and teaching experience  
**Status:** Decision loop and 3D airport/passenger/baggage views implemented; ATC and decision-quality campaign remain next

The descriptive → predictive → prescriptive → action → outcome loop is now
visible through the cockpit and Decision Timeline. The user's next priority is
to make the simulated airport tangible in 3D. Do the visual/spatial work below
first; retain decision-quality validation as the following workstream.

## UI delivery and external acceptance

The UI implementation checklist is archived in [archive/UI_TODO.md](archive/UI_TODO.md).
Current timestamp, responsive, accessibility and planning evidence is in
[UI validation](docs/dashboards/UI_VALIDATION.md). Human usability sessions,
assistive-technology/full WCAG review and actual browser zoom remain explicit
acceptance tasks in [UI_ACCEPTANCE.md](docs/dashboards/UI_ACCEPTANCE.md).

## Priority 1: an explorable 3D airport

### 1. Airport scene and aircraft models

**Done — 2026-11-14.** `/airport-3d?view=airport` provides the 3D airport,
original aircraft and ground-vehicle models, live selection/inspection, orbit,
pan, zoom and camera presets. Reciprocal runway ends share physical strips.
Aircraft placement and depot parking slots are explicitly illustrative;
operational state and vehicle coordinates come from owner APIs. Build, adapter
tests and live aircraft/vehicle selection checks passed.

**Simulation-time motion — 2026-11-15.** Aircraft now follow the flight FSM
timeline (approach from ETA−20, rollout/taxi over owner taxi durations,
5-minute departure window, holding stack), vehicles travel their owner trip
segments, and queues/belts flow at observed rates. Motion pauses with the
source and follows its speed. Unit/build checks pass; live browser
verification is still pending.

All three deliveries, screenshots, live evidence and verification limits are
recorded in [3D validation](docs/validation/AIRPORT_3D.md).

Create a coherent 3D view of the fictional ART airport: terminals, gates,
aprons, taxiways and runways, with aircraft models and ground-service vehicles.
Support airport overview, orbit/zoom and selection of an aircraft or facility
to inspect its live state. Connect selected entities to existing specialist
pages and related decision timelines.

Start with one gate and one aircraft moving through its available operational
states, then expand the airport. Use reusable assets with documented licenses,
consistent scale and a shared coordinate system. Match aircraft variants to
the synthetic fleet where data supports it.

### 2. Passengers and security lanes in 3D

**Done — 2026-11-14.** `/airport-3d?view=passengers` provides terminal
cutaways, bounded queue figures, owner lane/frozen state and exact wait/count
metrics. Terminal switching and a live owner-confirmed change from eight to
four lanes were verified. Frozen queues and simulation-time pause behavior
have automated coverage; figures are labelled as aggregate representations.

Show terminal interiors or cutaway views with passengers, queue areas,
security checkpoints and open/closed lanes. Make congestion and processing
visible, with selectable queues showing depth, wait and lane capacity.
Opening a lane should become visible only after passenger-owner confirmation.
Build one terminal/checkpoint first, including its connection to the existing
security-lane decision story.

### 3. Baggage and conveyors in 3D

**Done — 2026-11-14.** `/airport-3d?view=baggage` provides terminal-scoped
conveyor networks, representative suitcase models, owner occupancy/status,
offline/degraded indicators, and actual item/scan inspection. A live synthetic
injection verified populated conveyors and real scan history. Offline movement,
terminal mapping and unavailable-data behavior are covered by tests.

Show baggage items moving through conveyor segments, screening, sorting and
loading areas. Highlight blocked/failed conveyors, utilisation and affected
bags; selecting an item or segment should expose its recorded state and route
where available. Start with one complete conveyor path and expand the network.

### 4. Air traffic control view

**Done — 2026-11-15.** `/atc` adds approach corridors, holding, data blocks, a
tower camera and a read-only traffic board backed by the owner runway queue
(`GET /runways/queue`: order, wake separation, ROT, capacity). No clearance
controls: the owner models none. Live browser verification pending.

Add an ATC-style view of simulated arrivals, departures, approach paths,
holding patterns, runway occupancy and taxi movements. Combine an airport/tower
camera with a readable traffic overlay and flight selection. Display runway
assignments, queues and clearances only where the simulation actually models
them. Any new clearance or separation behaviour requires a documented domain
contract and owner-side implementation before interactive controls are added.

### 5. Further spatial detail

Candidate extensions after the first four slices: ground handling and vehicle
dispatch, boarding bridges and boarding flows, incident/emergency overlays,
weather and visibility, and camera presets for terminal, apron and tower views.
Prioritize details that reveal operational state or explain a decision.

### Shared requirements and first 3D milestone

Audit available positions, routes, queue membership and owner events before
implementing each slice. Existing data drives the scene; missing spatial data
needs spec-first backend wiring. Label illustrative movement or aggregate crowd
representations explicitly instead of implying exact tracked positions.

Interpolate visual movement using simulation time; pause must stop it and speed
changes must remain synchronized. Domain state stays owned by services and is
rebuildable from Neo4j. Operator actions use existing authorized gateway/command
flows and owner receipts. Keep all scene data fictional.

Use instancing, levels of detail and bounded entity counts for crowds/bags;
provide quality settings, reduced motion and access to the existing 2D views.
Agree a target device and measurable frame-rate/loading budget before scaling.

**First milestone:** explore one gate/aircraft, one terminal security queue and
one conveyor path in 3D, select their live state, and watch an approved lane
change appear after its owner receipt. Expand to the full airport and ATC view
after this connected slice works.

## Priority 2: prove and improve decision quality

1. **Automate a validation campaign.** Collect at least 20 eligible security-lane
   outcomes across varied congestion levels. Export prediction error,
   attribution eligibility, control quality, failures and excluded runs.
   Keep missing/failed evidence visible and avoid selecting only good results.
2. **Improve the effect model from the evidence.** Investigate divergence,
   adjust the model, and evaluate changes on separate scenarios rather than
   the same cases used for tuning.
3. **Polish a five-minute teaching walkthrough.** Guide a visitor through
   detection, reasoning, approval, execution and outcome, including uncertainty
   and the link between the 3D scene and durable evidence.
4. **Add a second complete decision story.** Gate reassignment is the proposed
   next slice, reusing the timeline, owner receipts and honest outcome display.

G4's action-level accuracy gate requires at least 20 eligible samples and median
absolute relative error of at most 25%. The current security example has roughly
41% error; accuracy remains unvalidated. Observational attribution does not
establish randomized causality.

## Later: the simulation time machine

Distinguish viewing recorded history from restoring and rerunning the
simulation. A read-only recorded-decision cursor is already implemented; full
pause/scrub/replay needs coordinated snapshots and deterministic recovery
across services. The simulation clock alone does not provide that capability.

## Completed: decision-loop milestone

**An operator can follow one security-lane decision from detection to
owner-confirmed execution to an honestly measured outcome, without switching
pages.**

Completed on 2026-11-14. `/` is the operator cockpit; `/flights` retains the
flight board; `/decisions` provides durable history, deep links, reasoning,
approval actions and a read-only recorded-stage cursor. Actual owner receipts
and measured outcomes survive analysis-service restart.

The live synthetic teaching run retained a predicted wait change of -111.35 min,
observed change of -89.40 min and attributed change of -79.15 min with two
comparison terminals. This is observational evidence, not randomized causality.
Replay reports one eligible sample and 40.69% relative error: accuracy remains
**unvalidated**, below the 20-sample minimum and above the target error for this
individual example. No claim of passing the empirical G4 accuracy gate is made.

See [implementation contract](docs/dashboards/OPERATOR_COCKPIT.md),
[teaching runbook and validation](docs/validation/DECISION_LOOP.md),
[actual exported evidence](docs/validation/security-lane-teaching.json) and
[replay report](docs/validation/decision-loop-replay.json).

The previous Real LDT roadmap is preserved in
[`archive/ROADMAP_REAL_LDT.md`](archive/ROADMAP_REAL_LDT.md). Its accepted local
gap scopes are closed; the recorded follow-ups and empirical-validation limits
still apply.

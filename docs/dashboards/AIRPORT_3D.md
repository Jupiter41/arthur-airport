# Airport 3D — implementation contract

> 2026-11-15: Navigation, default views and workflow composition are superseded by [UI_IMPLEMENTATION.md](UI_IMPLEMENTATION.md). Domain and evidence contracts below remain in force.

Updated contract, 2026-11-14: `/ground-ops`, `/passengers` and `/baggage`
each provide a single 3D on/off switch, default on. Off selects the existing 2D
view at the same URL (`3d=off`). `/airport-3d` is a compatibility redirect to
the appropriate operations page and no longer appears as separate navigation.
Terminal selection remains a query parameter.

## Simulation-time motion (supersedes the correction below), 2026-11-15

The renderer has a visual clock but still runs no simulation of its own. Every pose is a
pure function of owner facts and simulation time:

- The clock extrapolates between `SimClockTick`s at the source speed multiplier, at most
  two wall-seconds past the last tick, stays monotonic, follows source resets and freezes
  at the last tick while the source is paused. Reduced motion steps once per tick.
- Aircraft use the flight state-machine windows: `approach` from ETA−20 min to touchdown at
  ETA on the assigned runway; `landed`/`taxiing` over the owner's `taxi_initial_minutes` /
  `taxi_total_minutes` from `actual_time`; `boarding`/`at_gate` on the stand; `departed`
  over the owner's 5-minute window, then 7 minutes of climb-out. `delayed` arrivals circle
  a holding stack. An aircraft whose runway, gate or time is missing is not placed.
- Vehicles follow their owner trip (`origin → target`, `dispatched_at → arrives_at`).
- Queue figures advance so a figure joining now reaches the lanes after the reported wait;
  bags cross each belt in `items ÷ throughput`. Frozen lanes and offline belts stop.

Approach distance, holding fix, taxi routes, take-off geometry, parking slots, queue shape
and belt layout are schematic and labelled as such.

## Air traffic control view (`/atc`), 2026-11-15

`/atc` follows the same 3D on/off pattern. 3D on shows the airfield plus approach
corridors, the holding fix and aircraft data blocks, with a tower camera preset. 3D off
shows the traffic board alone. The board is read-only and shows only modelled state:

- Runway strips: owner status, `current_use`, ILS, queue depths, and the aircraft
  occupying each strip (from the timeline phases above). It also shows the airport-wide
  runway-occupancy-time block (`runway_free_at`).
- Sequence: the owner's arrival and departure queues from `GET /runways/queue`, in owner
  priority order, with weight category and owner wake separation.
- Traffic: arrivals on approach (time to touchdown, spacing behind the previous
  arrival on the same runway), the holding stack, aircraft taxiing in and out, and
  departures boarding (with the FSM's 95 % boarded threshold).
- Capacity: weather category, ILS requirement, arrival/departure rates, current rate.

The flight owner models no clearances, no radar separation enforcement and no runway
crossings, so the view offers no clearance controls. Adding any of them requires a domain
contract and owner-side implementation first.

## Live projection correction (superseded 2026-11-15)

The 3D renderer consumes the same live twin data as 2D; it has no independent
clock, trajectory prediction, conveyor loops or crowd animation. Only new owner
observations change rendered operational state. Aircraft with reported X/Y
coordinates use them; parked flights without telemetry can be shown anchored
to their assigned gate and labelled accordingly. All other unlocated flights
remain inspectable in the entity list, with position unavailable, rather than
being flown along invented routes. Depot vehicles use reported coordinates
without invented parking offsets. Queue/bag figures represent actual aggregate
counts and stay static until observations change. No installed standby lanes
are invented.

Unsampled `SecurityQueueUpdated`, `BaggageZoneSnapshot` and
`GroundVehicleSnapshot` events refresh the existing canonical query/store data.
Partial security events never create fabricated zero counts for other terminals.
REST polling reconciles/reconnects and errors explicitly label stale data.
Domain simulation remains synthetic; real-world telemetry is not available.

This correction supersedes the illustrative animation, predicted aircraft
placement and depot/standby-lane descriptions below, retained as original scope.

## Scope and data ownership

Three.js renders original procedural aircraft, ground vehicles, terminals,
passenger figures, security portals, bags and conveyor structures. No external
models, map credentials or live aviation feeds are required. All data is fake.
This presentation adds no domain mutations or service-to-service communication.

Implementation status: all three scene slices complete, 2026-11-14. See
`docs/validation/AIRPORT_3D.md` for checks, live evidence and limitations.

Flights/gates/runways and ground vehicles read the existing Zustand stores,
seeded and reconciled via gateway REST. Passenger checkpoints and baggage zones
remain React Query-owned, polled every five seconds. Selected-zone baggage items
use the existing paginated list endpoint (bounded to 50), with detail/scan history
via the existing item endpoint. Network failures retain last successful data
with a stale/unavailable notice; empty results never become invented traffic.

The owner grid uses X east and Y south, 0–1000. Rendering maps it to X/Z with
origin at the centre. Gate/runway placements use supplied positions when present;
otherwise a labelled schematic layout is used. Buildings and paths are
illustrative architecture. Aircraft locations are illustrative placements derived
from flight status, gate/runway assignment and simulation timestamps; this is
not ground-position telemetry. Ground vehicles use their owner X/Y coordinates;
vehicles collocated at the depot are visually separated into illustrative
parking slots, while the inspector retains their exact owner coordinates.

Security uses committed queue counts, wait, lanes and frozen status. Figures
are bounded aggregate representatives, not tracked passenger identities. Display
the actual count separately and explain each figure's representation. At least
one standby portal is illustrative, not a claimed physical installed capacity.
No optimistic lane changes: only a later owner summary changes the scene. Link
to the existing decision page for authorized actions and their receipts.

Baggage flow uses actual zone IDs, occupancy, throughput and status. Pipeline
connections are an illustrative explanation of induction → screening → sorting
→ make-up, with separate arrival belts, not tracked trajectories. Representative
bags never imply exact item positions. Selecting an actual listed item shows
its recorded scan history; unobserved next destinations remain unknown. Offline
segments stop movement and show red, including with zero occupancy.

## Interaction and rendering

Provide orbit, pan, zoom, camera presets/reset, click selection and keyboard
accessible equivalent lists/inspectors. Terminal selection scopes passenger and
baggage detail. Quality presets cap pixel ratio and representative figure counts;
use instanced crowds/bags and shared geometry. Reduced motion freezes illustrative
animation. All automatic motion derives from simulation time; bounded visual
extrapolation between ticks stops on pause/disconnect and never changes domain
state. Camera movement remains available while paused.

Handle WebGL initialization/context failure with a readable fallback and links
to the 2D pages. Resize without stretching; dispose controls, GPU resources,
listeners and animation frames on unmount. Lazy-load the renderer route.

## Completion checks

1. Airport: selectable procedural aircraft, gates, runways and distinct ground
   vehicle models; live state, camera control, unavailable/empty states.
2. Passengers: terminal cutaway, actual open/frozen lane state, representative
   queue figures and exact metrics; link to decision evidence.
3. Baggage: all observed zones, connected explanatory belts, stopped offline
   segments, representative moving bags, real item/scan inspection.

Verify adapter/position/time/cap behavior and page interactions with tests;
run the dashboard production build and inspect all three scenes in the browser,
including mobile and a paused simulation. Record verification limits explicitly.
Target for the balanced preset: at most 600 crowd instances, 400 bag instances,
pixel ratio 1.5 and 30 FPS at 1280×720 on an integrated-GPU laptop. This is a
performance budget to measure, not a guarantee for every device.

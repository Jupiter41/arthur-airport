# Airport 3D implementation and verification

Completed 2026-11-14. The first three spatial priorities in `NEXT_STEPS.md` are
implemented at `/airport-3d`; air traffic control remains a separate next step.
The route is available from the main navigation and cockpit.

## Delivered views

| View | Implemented behavior | Evidence |
| --- | --- | --- |
| Airfield | Three terminals, two physical runways with reciprocal designators, gates/jetbridges, narrow/wide-body procedural jet variants, fuel/catering trucks, tugs, loaders and stairs; selection, state inspector, orbit/pan/zoom, overview/top/focus cameras | [Airport screenshot](airport-3d.jpg) |
| Passengers | Terminal cutaway, open/standby security portals, owner-confirmed open/frozen state, bounded instanced passenger figures, exact queue and wait metrics, terminal selector and decision-evidence link | [Passenger screenshot](passengers-3d.jpg) |
| Baggage | Terminal-specific induction/screening/make-up/reclaim zones and shared sorter, explanatory belt connections, suitcase handles/wheels, bounded instanced bags, normal/degraded/offline state, real item and scan-history inspection | [Baggage screenshot](baggage-3d.jpg) |

All model geometry is original procedural code under
`dashboards/art-dashboard/src/pages/Airport3D/`. No external models, textures,
map keys or aviation feeds are needed. Three.js is pinned to 0.182.0 with its
matching TypeScript definitions and lockfile.

## Live synthetic verification

Used the existing disposable Compose project `art-decision-validation`, cached
images and source mounts, after a Docker storage preflight. The normal project
was not reset and no volumes were deleted.

- Selected an actual boarding flight and focused its aircraft model; inspected
  aircraft type, gate, runway and delay. Unavailable registration is labelled.
- Selected a fuel truck and verified its owner grid coordinates and status.
  Owner-collocated depot vehicles are visibly separated into labelled,
  illustrative parking slots.
- Changed Terminal A from eight to four lanes through the passenger owner's
  existing command handler. Its execution receipt preceded the later UI
  observation of four portals and updated queue/wait metrics. Terminal B showed
  its own independent state. Restored Terminal A to eight afterward.
- Created one future synthetic departure and injected 100 dropped-off bags in
  the lab through existing debug APIs. Resumed briefly to obtain committed
  conveyor observations, then restored pause and speed. Selected induction-A,
  read the actual item list and inspected an actual induction scan timestamp.
  Existing synthetic bags also entered the pipeline; scene counts reflect the
  full observed queues rather than just the injected batch.
- Compared the rendered conveyor region across two full screenshots while
  paused: decoded pixels were unchanged. Automated tests separately cover
  simulation-time extrapolation, frozen crowds, stopped offline belts and
  moving normal belts.
- Inspected all three views in the browser with no console errors observed.
  At 390px width, the canvas resized to 350px and document scroll width matched
  the 390px viewport after fixing canvas intrinsic sizing and nav wrapping.
  The temporary viewport override was reset.

[Saved owner responses and scan evidence](airport-3d-live.json) contain no
credentials. The validation stack and preview server were stopped afterward;
volumes and synthetic evidence remain available.

## Checks and limits

- Dashboard: **60 tests passed across 12 files**, including 14 new 3D tests.
- TypeScript and Vite production build passed.
- `git diff --check` passed for the changed implementation/docs.
- Existing Vite deprecation, stale Browserslist and large-chunk warnings remain.

Observed approximately 27–28 FPS in this desktop browser at its default large
viewport. Low/balanced/high presets bound pixel ratio and aggregate instances;
the integrated-GPU 1280×720 performance budget is still a target, not a certified
device benchmark. Touch-device usability was checked through viewport emulation,
not physical-device testing. WebGL failure has an automated fallback test;
context-loss handling is implemented but was not forced on a physical GPU.

Architecture, aircraft placement, crowd positions, belt links and bag motion
are illustrative. They do not introduce passenger tracking, precise aircraft
ground telemetry or exact bag trajectories. Counts, lanes, failures, vehicle
coordinates and scan history come from existing owner APIs. No new domain
mutations or backend services were added. Authorized lane decisions remain in
the existing decision workspace with their owner receipts.

## Run locally

Start the backend with `python scripts/docker_storage.py up`. For frontend
development, install the locked dashboard dependencies with `npm ci`, then run
`npm run dev` from `dashboards/art-dashboard`. Open `/airport-3d` and select the
three perspectives. Docker dashboard rebuilds must use the storage guard:
`python scripts/docker_storage.py up dashboard`.

## Simulation-time motion (2026-11-15)

The scene previously showed only parked aircraft and stepped once per refetch.
It now reflects the owner state continuously in simulation time.

| Element | Driven by | Schematic part |
| --- | --- | --- |
| Arriving aircraft | `approach` window ETA−20 min → ETA on the assigned runway; `delayed` arrivals circle a stable holding stack | Approach distance compressed (vertical ×2), holding fix |
| Landing / taxi-in | `actual_time` + owner `taxi_initial_minutes` (rollout) and `taxi_total_minutes` (on stand); holds short if the owner has not confirmed the gate | Exit point and taxi route along the drawn apron lines |
| Departures | `departed` 5-min window from `actual_time`: pushback, taxi-out, roll, rotation; climb-out visible for 7 min after airborne | All geometry; the owner models only the 5-min duration |
| Ground vehicles | Owner trip `origin → target` between `dispatched_at` and `arrives_at` | Stand/depot parking slots |
| Security queue | Figures advance so a figure joining now reaches the lanes after the reported wait (Little's law); frozen lanes stop | Serpentine queue shape |
| Baggage | Bags cross each belt in the observed dwell time `items ÷ throughput`; offline/zero-throughput belts stop | Belt layout |

The visual clock (`simClock.ts`) extrapolates between sim ticks at the source
speed multiplier, never more than two wall-seconds ahead of the last tick,
stays monotonic across slightly late ticks, follows genuine source resets, and
freezes at the last tick when the source pauses. With reduced motion it steps
once per tick. `FlightStatusChanged` events stamp `actual_time` locally on
`landed`/`departed` so motion starts on the transition tick.

Owner-side, flight-service now exposes read-only coordinates, `actual_time`,
taxi durations and vehicle trip facts (see flight-service SPEC, "Spatial and
timing projection"). No domain behaviour changed.

Verification: flight-service unit tests (171 including 5 new), dashboard
`vitest run` 82 passed across 15 files (new `airport3dTimeline.test.ts`), and
`tsc -b && vite build` passed. Not yet verified against a live stack or in a
browser; the next live run should watch one arrival from approach to stand and
one departure through pushback at ×60 and while paused.

## Air traffic control view (2026-11-15)

`/atc` (navigation: Ops → ATC) has 3D on/off like the other operational views.

- **3D:** the airfield timeline above, plus glide-path and ground-track corridors for all four
  runway ends (marked 2/5/10/20 min to touchdown on the compressed approach scale; ends in
  use for landing highlighted), the holding ring when arrivals hold, data blocks
  (callsign · type · status · runway), and a tower camera preset (also on Ground Ops).
- **Board (also the 2D view):** capacity (weather, ILS requirement, rates, movements/60 min,
  ROT block). Physical runway strips show owner status/use, the aircraft in a runway phase,
  short final (≤ 2 min) and owner queue depths. Also on the board: the final approach sequence with
  time to touchdown and per-strip spacing, the holding stack, the owner runway sequence
  (`GET /api/v1/runways/queue`: priority order, weight category, wake separation, emergency),
  ground movements, and departures at gate against the FSM's 95 % boarded threshold.
- **No clearances:** the flight owner models none, so the view is read-only and says so.

Owner side: `RunwayQueue.snapshot()` is a non-mutating read of the heaps (lazy-removed
items skipped as the scheduler would). The endpoint is documented in the flight-service SPEC
and `ROUTES.md`; the gateway already proxies `/api/v1/runways/*`.

Checks: flight-service unit tests 172 passed (new snapshot test); dashboard 89 passed
across 16 files (new `airport3dAtc.test.tsx`); `tsc -b && vite build` passed. Not yet
exercised against a live stack or in a browser.

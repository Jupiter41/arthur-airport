# UI implementation validation

Date: 2026-11-16. Contract: [UI_IMPLEMENTATION.md](UI_IMPLEMENTATION.md).
Delivery checklist: [archived UI_TODO.md](../../archive/UI_TODO.md).
External acceptance still open: [UI_ACCEPTANCE.md](UI_ACCEPTANCE.md).

## Delivered and repaired

The workspace/navigation redesign from 2026-11-15 is retained. This close-out
adds per-record owner observation times to security rows, baggage zones and
incident summaries. Overview shows complete UTC dates separately from incident
start time; absent evidence remains unavailable. Event replacements retain
source times. Incident ages now use simulation time rather than wall time.

Live browser use exposed a cascade crash: relationship-only events were being
inserted as full incidents. Cascade facts now reconcile owner reads, and
creation facts normalize `incident_id` before status updates. Regression tests
cover the actual owner payload shapes.

The rendered accessibility review repaired associated form labels, named
increment/decrement controls, switch roles/states, minimum control dimensions,
focus visibility, hourly-slider keyboard access and proxy focus, text contrast
in both themes, chart legends/tooltips and fixed-dark 3D overlays. Planning tabs
and delta controls wrap at 320 CSS pixels. Screen-reader-only sliders are
positioned within their locally scrollable chart rather than overflowing the
page.

Actual experiment submission exposed a native constraint-validation failure:
an auto-estimated annual cost of €204,400 was invalid with `step=1000`.
CAPEX/OPEX now accept cents, with a regression covering non-round estimates.
P5–P95 labels describe simulated outcomes rather than calibrated confidence.

## Automated checks

- Dashboard: **106 tests across 23 files passed**; TypeScript and Vite production
  build passed. Existing optional map/chart/3D chunk-size, old Browserslist data
  and test-tool deprecation notices remain.
- Python: **23 focused tests passed** across observation times, passenger count
  projection, planning outcomes and decision history. Endpoint test model
  imports are isolated so incident models cannot contaminate analysis tests.
  FastAPI TestClient required execution outside the socket-restricted sandbox.
- `git diff --check` passed.

## Rendered route and accessibility checks

[Raw measurements](../validation/ui-browser-audit.json) contain **132 primary
route samples** and **8 Map/3D samples**. All 22 primary routes were visited at
each size below. The last measurements at each route/size are retained after
repairs.

| Viewport | Theme | Primary routes |
| --- | --- | --- |
| 1440×900 | Dark | 22 |
| 1280×720 | Light | 22 |
| 768×1024 | Light | 22 |
| 390×844 | Light | 22 |
| 720×450 | Light; equivalent reflow for 1440×900 at 200% | 22 |
| 320×844 | Light; narrow reflow | 22 |

Routes: `/`, `/flights`, `/ground-ops`, `/atc`, `/passengers`, `/baggage`,
`/accessibility`, `/incidents`, `/decisions`, `/planning`, `/whatif`, `/history`,
`/costs`, `/carbon`, `/world`, `/scenarios`, `/settings`, `/lab`, `/data-sources`,
`/ml`, `/debug`, `/help`.

The final sampled states have no document/main horizontal overflow, no measured
normal-text contrast failures and no unlabelled form inputs. The read-only DOM
check composites CSS text/background colors, uses 4.5:1 normal / 3:1 large text
thresholds, and inventories target dimensions and label associations. Common
buttons/selects are at least 36px high; delta controls are 36×36. Small inline
links and screen-reader-only inputs remain in the raw inventory: the former
need contextual inline/spacing assessment, and hourly inputs have visible,
labelled pointer proxies and keyboard focus. Canvas/image text and all manual
WCAG criteria are not certified by this check. Chart SVG text was given semantic
fills and tooltip/legend text was checked separately.

Map and 3D were exercised for ground operations, ATC, passengers and baggage at
768×1024. Terminal B and selected `airside-B` persisted through Board → Map →
Board → 3D, with textual inspection and operational records available. This is
interaction evidence, not a 3D frame-rate benchmark.

Keyboard flight search for loaded synthetic flight AF217 followed by Enter
opened its gate/delay details in two interactions. Escape preserved `q=AF217`
and returned focus to its inspection trigger. The account dialog also closed
with Escape and returned focus. Operator sign-in and the isolated experiment
form were exercised without injecting, approving or resetting the shared airport.

## Current planning backend verification

The existing stack initially used an older gateway without viewer auth and an
older planning image producing legacy accounting. A current compiled gateway
was run in a temporary existing image on port 3002; only the changed timestamp
owners and planning were rebuilt/recreated using the serial storage guard.
No second full stack or new Neo4j/Kafka data volumes were created.

[`verify_ui_planning.py`](../../scripts/verify_ui_planning.py) exercised the
current gateway → planning path: baseline → one Terminal B lane change → a
1-day/2-run synthetic job → completed status → KPI/baseline comparison →
investment → identical persisted reread. Seed `16112026`, `airport-v1` accounting
and frozen financial-rate version are in [actual API evidence](../validation/ui-planning.json).
The baseline was unchanged. The planning service was then restarted; the
scenario, results, investment and baseline reread identically using
`--verify-existing`.

The browser independently created **UI browser verification — isolated lane**
(`c6d7f043-905f-491c-bbde-70e3ce0102f5`), observed completion, compared results
and opened investment details. Screenshots: [planning](../validation/ui-planning.jpg),
[Overview](../validation/ui-overview.jpg), [phone flight inspection](../validation/ui-flight-phone.jpg).
Verification scenarios remain durable, named synthetic evidence; no existing
scenario or operational data was deleted.

Build storage was checked on the actual `/home/docker-data` filesystem. About
100.3 GiB was free before guarded builds; about 98 GiB remained afterward.
Builds were serial, logs bounded, and no volumes/images were pruned. The
existing stack otherwise remains a mixed-revision development stack: its old
analysis image did not serve decision history. The UI's explicit unavailable
state was checked, while current history filtering/lifecycle evidence was
verified by tests. Full live decision-loop deployment/validation is separate.

## Acceptance limits

Actual browser zoom shortcuts had no effect in the available in-app browser
(`innerWidth`, `innerHeight` and pixel ratio stayed unchanged). Equivalent
viewport reflow was checked; **actual 200% browser zoom remains unverified**.
Human formative sessions, time-to-find measurements, a screen-reader pass and
full manual WCAG 2.2 AA review remain open in [UI_ACCEPTANCE.md](UI_ACCEPTANCE.md).
No unfamiliar participant was simulated or reported as a human result. Current
screenshots are not a pre-redesign baseline. Primary route coverage does not
claim every expanded tab, dialog, error permutation or operator-only state.

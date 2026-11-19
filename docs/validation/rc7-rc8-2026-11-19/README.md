# RC7 / RC8 closure validation

Date: 2026-11-19 (Europe/Luxembourg). Implementation checkpoints: `f833de4`,
`37543f7`, `2e10906`, `11bbd69`; RC1 was committed separately as `0298ad5`.

**RC7, RC8 and the RC12 dependency are closed.** The broader review remains open.

## Scope

RC7's real seed-existence query now groups the legacy count explicitly, and the
passenger repository accepts the inbound `airborne` lifecycle transition.
Generators retain complete named manifests and transfer identities; owners alone
create entities, relationships and creation facts. Cold-start validation also
found a genuine tag collision between provisional arrival/departure ranges.
The baggage owner now allocates final unique 10-digit tags from its durable
sequence atomically with seed acceptance. Retries cannot reserve another range.

RC8/RC12 collection observations now persist in the passenger-owned
`PassengerBaggageObservation` before Kafka acknowledgement, including inputs
received before passenger creation. Inbox, observation, lifecycle-valid location
updates and observation facts commit together. An owner lock and a second inbox
check fence competing replicas. The arrival FSM reads that projection with a
simulation-time fence; volatile checkpoint collection sets are retired.
Carousel positioning requires `baggage_claim`. Startup alone bootstraps linked
live/archive arrival scans for missing/expired offsets, without reading mutable
baggage state in tick decisions. Passenger purge removes observations; bounded
orphan cleanup commits its own fact. BULK retains named per-bag collection and
carousel facts, and the passenger owner also accepts batch replay.

## Cold-start and boundary evidence

The separate `art-rc78-cold2` project started with fresh volumes. Cached images
provided dependencies; current Python service sources were mounted at
`/current-source`, with that directory ahead of `/app` on the import path.
No application workarounds, airport reset, volume pruning, or external reference
API inputs were used. The configurable workload was 60 movements/day at 600x,
then 60x for integration checks. This is a functional closure run, not a new
420-movement/day performance benchmark or a deployed-image certification.

[Cold-start and boundary snapshots](cold-start.json) record:

| Invariant at June 16, 00:39 simulated time | Result |
| --- | --- |
| Readiness | All 10 service endpoints returned 200 |
| June 15 / June 16 manifests | Both ready; all 76 owner batches accepted |
| Bags | 16,570; zero anonymous bags |
| Passengers | 19,110; zero flight-assignment cardinality violations |
| Airborne passengers on scheduled arrivals | Zero |
| Completed passenger / baggage transfers | 910 / 848 |
| Completed claim visits / visits shorter than 45 minutes | 4,157 / 2,437 |
| Owner checkpoints at paused clock | All three at 00:39 |

The June 16 manifest is already ready in the 23:58 snapshot, proving next-day
pre-seeding before midnight. The final snapshot proves acceptance across the
boundary. Early claim exits prove collection-triggered progress; the remaining
visits include passengers without checked bags and do not imply universal
sub-45-minute collection. Anonymous historical assignments are not fabricated.

## Verification gates

Final gate results are recorded alongside this report. The broad transaction
suite and the expanded observation suite overlap in six tests: their 44 and 12
passing checks represent **50 distinct live transaction regressions**.

- [Full live integration gate](integration.xml): 142 passed, zero skips.
- [Final readiness after restarts](final-readiness.json): all ten services returned 200.
- [Python unit results](unit-results.txt): 1,490 passed; eight existing warnings.
- [Broad Neo4j/Kafka transaction gate](domain-transactions.xml): 44 passed, no skips.
- [Expanded RC8/RC12 observation gate](observations.xml): 12 passed, no skips.
- [Ruff](lint.txt): required service/live-transaction scope passed.
- Gateway: [43 tests passed](gateway-tests.txt); [TypeScript build passed](gateway-build.txt).
- Dashboard: [115 tests passed](dashboard-tests.txt); [production build passed](dashboard-build.txt).

The expanded live gate uses independent owner processes and actual Neo4j/Kafka:

- Real consumer polling and synchronous ACK, then `os._exit(29)` before a tick;
  a fresh process still exits claim at 12:01 instead of waiting until 12:44.
- Duplicate Kafka replay, competing observation workers, partial transaction
  rollback, and collection before passenger creation.
- Snapshot recovery with no input replay, protecting progress after Kafka input
  retention or offset loss; source scan time remains authoritative.
- An actual BULK baggage planner, atomic status/scan/outbox commit, real broker
  publication, passenger ACK/process death, restart and claim exit.
- Old arrived-flight holds outside the FlightView window: startup recovery,
  another worker restart, and normal/BULK ticks through carousel and collection.
- Indexed age-based orphan cleanup protects observations attached to active
  passengers. RC1's archive/purge/scan-trail regressions also remain green.
- Two seed batches with the same provisional barcode receive distinct owner tags.

Stale fixtures were repaired to execute the documented contracts: worker and
boarding-query fixtures initialize FlightView; late bags enter via the atomic
arrival path; planning results include their existing `legacy` model version.
The optional local network-reference endpoint's documented 503 is asserted as
an unavailable response instead of skipped. No real reference data is fetched.

## Reproduction

From the repository root, use a new disposable Compose project and available
runtime images. The recorded source overlay maps each Python service directory
to `/current-source:ro`, sets `working_dir=/current-source`, and supplies
`PYTHONPATH=/current-source:/app`; the normal common/config mounts remain intact.
Recorded files: [source overlay](compose.override.yml), [isolated G1 configuration](g1.compose.yml).
The commands below use these files with an explicit repository root. The G1
configuration has no published ports.
Use the Docker storage guard for any required image builds.

```bash
export ARTHUR_REPO_ROOT="$PWD"
cp docs/validation/rc7-rc8-2026-11-19/compose.override.yml /tmp/rc78-compose.yml
cp docs/validation/rc7-rc8-2026-11-19/g1.compose.yml /tmp/rc78-g1.yml
# Full stack with a fresh project and the source overlay:
docker compose -p art-rc78-cold -f docker-compose.yml -f /tmp/rc78-compose.yml up -d --no-build
python -m scripts.validate_rc78 --report /tmp/rc78-cold-start.json
# The boundary probe pauses to capture converged checkpoints. Resume at 60x
# before integration tests that depend on clock-driven outcome measurement.
curl -X PATCH http://localhost:8006/api/v1/sim/speed -H 'Content-Type: application/json' -d '{"speed_multiplier":60}'
curl -X POST http://localhost:8006/api/v1/sim/resume
REQUIRE_LIVE_STACK=1 RC7_NEO4J_URI=bolt://localhost:7687 \
  COMPOSE_PROJECT_NAME=art-rc78-cold COMPOSE_FILE=docker-compose.yml:/tmp/rc78-compose.yml \
  python -m pytest tests/integration -q

# Separate port-isolated Neo4j/Kafka-only G1 project; never target the airport:
docker compose --project-directory "$PWD" -p art-rc78-g1 -f /tmp/rc78-g1.yml up -d neo4j kafka
docker compose --project-directory "$PWD" -p art-rc78-g1 -f /tmp/rc78-g1.yml run --rm --no-deps kafka-init
G1_DISPOSABLE_STACK=1 REQUIRE_LIVE_STACK=1 \
  COMPOSE_PROJECT_NAME=art-rc78-g1 COMPOSE_FILE=/tmp/rc78-g1.yml \
  python -m pytest tests/live_transactions -q
python -m pytest tests/unit -q
ruff check services tests/live_transactions scripts/validate_rc78.py
```

The initial discarded cold project exposed the tag collision; its volumes were
preserved. Earlier interrupted integration attempts included a paused-clock
harness error; the final gate runs with a normal running clock. Native gateway
tests require local loopback binding. Builds can use temporary output directories
when existing generated `dist` directories are not writable.

RC14 remains responsible for rollout and legacy-data disposition on the existing
airport. The validation projects are stopped after verification, preserving their
volumes. The overall data-flow review remains open for its other findings.

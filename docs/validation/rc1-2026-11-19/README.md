# RC1 closure — terminal lifecycle retention

Date: 2026-11-19 (Europe/Luxembourg). Baseline: `627eede` plus the RC1 working-tree changes.

**RC1 is closed.** Both remaining B5 dispositions have owner-defined lifecycle,
atomic facts, indexed age-based retention and independent-process restart evidence.
The overall data-flow review remains open for its other findings. This is checkout
validation, not certification of an existing deployment (RC14).

## Changes

- Passenger retention archives terminal `missed_connection` by its indexed
  `missed_connection_at`, alongside `missed_flight` and `departed_airport`.
- Consumed `FlightDiverted` and `FlightStatusChanged(diverted)` dispose only
  arrival `in_hold` bags as terminal `diverted`, zone `diverted-aircraft`.
  Status, sim-time scan, inbox and per-bag outbox facts commit together. Facts
  retain flight/passenger identity, including BULK. A locked owner transaction
  selects still-held bags before mutation, preventing duplicate re-stamping.
- Startup/hourly recovery uses the same path and the event-fed FlightView.
  The actual startup bootstrap includes old outstanding holds beyond its normal
  window. Recovery records observation time rather than inventing past scan times.
  Active arrivals stay live; local unloading and onward transfer are not fabricated.
- Diverted bags archive by their terminal scan age. Existing archive/purge logic
  preserves identity links, archives scan trails, removes derived live labels and
  emits lifecycle facts atomically. Archive after 24 sim-hours; purge 168 sim-hours
  after archival, with strict cutoffs. Diverted bags leave active aggregate counts
  and analysis action targets immediately.
- Service specs, lifecycle/event contracts and owner skills describe these rules.

## Verification

| Gate | Result | Evidence |
| --- | --- | --- |
| Full Python unit suite | 1,477 passed; 8 existing warnings | [unit results](unit-results.txt) |
| Independent-process real Neo4j lifecycle regressions | 2 passed, 0 skipped | [JUnit](live-transactions.xml), [results](live-results.txt) |
| Required service/live-transaction Ruff scope | Passed | [lint](lint.txt) |
| Whitespace/diff check | Passed | `git diff --check` |

The live tests use actual owner repositories with current sources mounted ahead
of cached runtime code, and shared current libraries. Every operation starts a
new worker container. They prove rollback leaves no partial status/scan/archive
or fact, restart recovery works on out-of-window diverted arrivals, duplicate
recovery is inert, age boundaries are strict, active/young entities remain live,
identity links survive archival, and purge deletes the bag's archived scans.
Outbox contents are inspected in Neo4j; broker delivery is outside this RC1 gate.
Unit regressions additionally cover both diversion input types, BULK facts,
late-seeded bags, failure/retry, and future/direction guards.

The only full-unit failure during development was an RC5 fixture assuming its
retention task was last. It now selects that task by name, retaining its behavior
assertion. Early live-test harness failures (Compose flag, overstrict bootstrap
assertion after disposition, and stale inbox fixtures on rerun) were corrected
before the recorded final green run. No application workarounds are used.

## Reproduction and environment

No Docker stack was running initially. A separate `art-rc1-validation` Neo4j-only
project used cached `neo4j:5`. No build, pruning or airport-volume reset occurred.
Cached Python images supply dependencies; the harness mounts each current owner
at `/g1-source` and resolves it before `/app`.

For the same isolated environment, create a temporary Compose override:

```yaml
services:
  passenger-service:
    image: art-ldt-g6-passenger-service:latest
  baggage-service:
    image: art-ldt-g6-baggage-service:latest
```

Use available cached images, or build the required owners through
`python scripts/docker_storage.py build passenger-service baggage-service`.
For alternative images, adjust the override. From the repository root:

```bash
docker compose -p art-rc1-validation up -d --no-build neo4j
G1_DISPOSABLE_STACK=1 COMPOSE_PROJECT_NAME=art-rc1-validation \
  COMPOSE_FILE="$PWD/docker-compose.yml:/tmp/rc1-compose.yml" \
  .venv/bin/pytest tests/live_transactions/test_rc1_retention.py -q
.venv/bin/pytest tests/unit -q
.venv/bin/ruff check services tests/live_transactions
git diff --check
docker compose -p art-rc1-validation down
```

The live fixture requires a disposable G1 graph, refuses non-G1 operational
entities, and resets G1 fixtures/runtime/outbox records between cases. Never
point it at an operational airport. The validation project was stopped after
verification; its volumes were preserved. No existing airport was deployed or
modified. Other RC8/RC12 recovery work and RC14 rollout gates remain open.

# Weekend checkpoint — 2026-11-13

G9 is still OPEN/PARTIAL. Do not mark it closed based on unit tests alone.

## Completed before this checkpoint

- G2 implemented and marked closed: shared airport accounting policy, airline
  expenses separate, live/planning full compensation liability aligned,
  airport-only investment benefit, legacy migration/labelling and dashboard/specs.
  Validation: 1,173 Python units, four local Neo4j/Kafka accounting/rate checks,
  dashboard production build and 40 dashboard tests passed.
- G12 closed by owner scope decision: no Kubernetes cluster available; initial
  target is local operation. Cluster certification is deferred, not claimed.
- G9 implementation in progress: durable unsampled security aggregates, public
  full-fleet graph snapshots/facts, atomic graph replacement, durable discovery
  identities/timers/outbox, startup checkpoint restoration for flight/passenger/
  baggage, replica-readable discovery endpoints and focused regressions.
- Latest full Python unit suite: **1,180 passed**, four existing warnings.
  Focused discovery/projection/startup tests: **36 passed** before the final
  fleet projection additions (covered by the subsequent full suite).
- Python service lint passed before the final small edits; rerun it.

## Remaining G9 work

1. Review the new projection_store and consumer integration for late owner facts,
   clock replay/rewind, empty/deleted entities, proposal-status refresh and
   competing evaluators. Check endpoint consistency and failure behaviour.
2. Finish the independent-process live G9 harness. No projection_worker.py or
   test_projection_recovery.py was created yet. The existing live worker gained
   a startup mode returning the recovered checkpoint and simulation time.
3. Use real Neo4j/Kafka to test actual passenger/flight/baggage producer snapshots
   reaching analysis in REALTIME and BULK; verify queues, lanes, fleet busy counts,
   baggage aggregates and deletion/reconciliation without sampled-event drift.
4. Exercise discovery failure after writes, abrupt exit before/after commit,
   restart after clock acceptance before evaluation, replay, competing workers,
   stable identities and retained outbox publication under broker failure.
5. Compare owner startup state with its committed checkpoint BEFORE any new tick:
   conveyor transit, vehicle travel/pending requests, turnaround tasks and security
   queues. Run the existing complete live transaction regression suite too.
6. Add the new live tests to the fail-closed CI gate (build analysis-service in
   that job if its new tests require it). Update EVENT_BUS/DATA_MODEL, owner specs
   and recovery skill notes for the final implementation. Baggage/flight startup
   documentation and the new fleet event need final consistency review.
7. Only after live checks pass, update both G9 roadmap rows and add validation
   evidence. Commit/push the finished G9 changes.

## Local validation setup

An isolated infrastructure-only project was created: art-g9-validation.
Override used separate Neo4j ports 27474/27687 and removed Kafka host ports.
It is disposable; normal project infrastructure was not changed.
The four service images were built before the latest small edits; rebuild or
mount current sources before testing. The G9 live tests have NOT been run.

Existing live suite invocation (on disposable infrastructure only):

```bash
G1_DISPOSABLE_STACK=1 REQUIRE_LIVE_STACK=1 python -m pytest tests/live_transactions -q --tb=short
```

Use COMPOSE_PROJECT_NAME and COMPOSE_FILE to select isolated infrastructure.
The existing live harness refuses foreign flight IDs; use its synthetic fixtures.
The full unit suite runs with `.venv/bin/python -m pytest tests/unit/ -q`.
Async thread shutdown hangs in this environment's restricted sandbox, so those
checks were run with elevated execution. Node is available under
`/home/chevallier/.nvm/versions/node/v24.13.0/bin`.

## Other remaining roadmap work

G4: shared what-if effect core. G7: training-job recovery and the remaining
planning input/checkpoint scope. G8: baseline/counterfactual attribution and
prediction calibration. Recheck the authoritative roadmap when resuming.

This checkpoint also saves the owner's previously staged article/presentation
and other workspace edits, as explicitly requested before shutdown.

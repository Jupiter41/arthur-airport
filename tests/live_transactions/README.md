# G1 live transaction gate

This suite requires **an empty, disposable Compose project with only Neo4j and
Kafka running**. Do not point it at a development simulation. It refuses foreign
flight data and resets its synthetic fixtures and owner runtime/outbox records
between cases. Missing infrastructure fails; strict CI forbids skipped checks.

```bash
docker compose build flight-service passenger-service baggage-service
docker compose up -d --wait neo4j kafka
docker compose run --rm --no-deps kafka-init
G1_DISPOSABLE_STACK=1 REQUIRE_LIVE_STACK=1 \
  python -m pytest tests/live_transactions -q --tb=short --junitxml=g1-transactions.xml
docker compose down -v
```

Use `COMPOSE_PROJECT_NAME` and `COMPOSE_FILE` to select an isolated project and
port overrides when another stack is already running. The test harness inherits
them for every independent owner process. Worker containers mount current owner
sources read-only alongside the normal shared-library/config mounts.

Coverage for flight, passenger and baggage owners:

- actual domain/outbox/checkpoint writes followed by rollback or abrupt process exit;
- process exit after commit, then a new worker replaying the same tick;
- competing independent tick and command processes;
- command mutation/receipt/fact rollback and redelivery;
- broker failure retention, then real Kafka delivery with stable IDs across an ack/delete gap;
- real Kafka input replay through owner dispatch and acknowledged consumer polling;
- flight gate assignment, turnaround, vehicle, fuel and BULK summary facts.

The separate `domain-transactions` CI job runs this suite. The existing
`full-stack` job continues to require every application service and all REST,
event-chain, financial, planning and resilience integration tests.

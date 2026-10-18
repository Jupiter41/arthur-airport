# cost-service — Skill file

Patterns, gotchas, and implementation notes for the cost-service.

---

## Architecture

The cost-service is a **passive financial observer**. It subscribes to domain events via Kafka
and computes costs/revenues without ever calling another service over HTTP or mutating domain
entities. Its ledger transaction owns `CostRecord`, `CarbonRecord`, `CostInbox`,
`CostRuntime` and `CostOutbox`. See the spec's durable event accounting contract.

```
flights.events  ──┐
incidents.events ─┤
baggage.events  ──┤──→  cost-service  ──→  CostRecord (Neo4j)
passengers.events ┤                   ──→  cost.events (Kafka)
sim.clock  ───────┘
```

---

## Key patterns

### Running totals

In-memory running totals (`_running_totals` dict in `cost_engine.py`) track cumulative costs,
revenues, and per-category breakdowns. On restart, `ledger.initialize()` restores
the durable runtime checkpoint, migrating pre-existing Neo4j records once.

```python
_running_totals = {
    "total_cost_eur": 0.0,
    "total_revenue_eur": 0.0,
    "net_eur": 0.0,
    "by_category": defaultdict(float),
    "eu261_exposure": 0.0,
    "last_updated": None,
}
```

### Dual-entry accounting

For fees that are both a cost to airlines and revenue to the airport (landing fees, passenger
fees), two CostRecords are created: one with `is_revenue=False` (cost) and one with
`is_revenue=True` (revenue). Both link to the same flight.

### Aircraft family classification

Aircraft types are classified into three families for cost calculations:
- **wide**: B77W, A333, A332, A359
- **regional**: DH8D, E195, AT75
- **narrow**: everything else

Used for: fuel burn rates, catering costs, cleaning costs, crew counts.

### Tick-based accumulation

Some costs are computed periodically from `SimClockTick` events:
- **Holding fuel**: every 5 sim-minutes — queries Neo4j for flights in `approach` status
- **Staffing**: once per sim-hour — estimates staff based on time of day (peak: 06–22)
- **Retail revenue**: every 10 sim-minutes — estimates airside pax from time of day

### Rate overrides

Synthetic defaults live only in `_common/data/cost_rates.json`, loaded through
`_common.financial_rates`. Effective rates and their content version live in
`CostRuntime.document`. `services/rates.py` validates a copy and commits updates
under the ledger lock together with `CostRatesUpdated` in the outbox. Never mutate
a shared rates dict or publish an update before commit. Each input reads its
rates inside its ledger transaction; fee/carbon facts retain `rates_version`.
GET and recommendations read committed rates. Planning snapshots them on first
claim and retains them through recovery/replay. Existing charges are preserved.

---

## Common gotchas

1. **structlog not logging** — This service uses `structlog`, not stdlib `logging`. All files
   must use `import structlog` / `structlog.get_logger()`. The sprint-38 crash was caused by
   mixing stdlib logger with structlog-style keyword arguments.

2. **sim_day extraction** — The `sim_day` value comes from `payload.day_of_sim` in
   `SimClockTick` events but may need to be extracted from the envelope for other event types.
   The consumer extracts it at dispatch time.

3. **Neo4j session management** — Financial input processing uses one managed
   transaction for the entire event. Flight/holding reads use its transaction,
   not nested sessions. Do not retain a session beyond that event or perform
   external network calls inside the transaction callback.

4. **Running totals vs Neo4j** — The in-memory totals are the hot path for `/summary`.
   `ledger.initialize()` restores the committed calculation checkpoint. Event
   processing publishes caches only after the ledger/inbox/outbox commit. Use
   `ledger.current_batch` in calculators to collect effects; do not write records
   or publish Kafka facts individually from the production event path.

---

## File layout

```
services/cost-service/
├── main.py                   # FastAPI app, lifespan, startup sequence
├── _logging.py               # structlog setup
├── _tracing.py               # OpenTelemetry (optional)
├── requirements.txt
├── Dockerfile
├── fixtures/
│   └── carbon_factors.json   # Carbon defaults; financial defaults are in _common/data/
├── db/
│   ├── neo4j.py              # Driver, CostRecord CRUD, relationship linking
│   └── queries.py            # Aggregation queries (P&L, hourly, ranking)
├── kafka/
│   ├── consumer.py           # Subscribes to 5 topics, dispatches to cost_engine
│   └── producer.py           # Emits CostRecorded events to cost.events
├── routers/
│   └── costs.py              # REST API (/summary, /pnl, /flight, /rates, etc.)
└── services/
    ├── cost_engine.py         # All cost/revenue calculators + event handlers
    └── recommendations.py     # Prescriptive financial recommendations
```

---

## Testing

Unit tests cover:
- All pure calculator functions (`compute_landing_fee`, `compute_eu261`, etc.)
- Aircraft family classification
- Running totals accumulation
- All 4 recommendation types with threshold boundaries
- Net-benefit calculations and schema validation

Test files: `tests/unit/test_cost_engine.py`, `tests/unit/test_cost_recommendations.py`

# analysis-service — execution contract

Port: 8007. Consumes domain facts, detects bottlenecks, projects interventions,
and proposes actions. It never writes another service's operational entities.

## Action lifecycle

All entry points (manual Apply, automatic rules, human approval) share a single
mapping to concrete commands. Supported mappings are `ReassignGate`, `HoldFlight`
on `flights.commands`, `OpenSecurityLane` on `passengers.commands`, and
`RedirectBaggage` on `baggage.commands`. Aggregate recommendations without the
required entity identifiers remain advisory; applying one returns 422.

Proposals transition `pending → approved → dispatched → executed|failed`, or
`pending → rejected`. Approval authorizes dispatch; it does not prove execution.
Only an owning service's `CommandExecuted` receipt marks an action applied.
`CommandRejected` records failure. Both receipts carry `command_id` and
`command_type` on the owner's existing facts topic and use its simulation clock.
An unavailable clock rejects submission. An unavailable broker retains a
durably queued dispatch; it never produces a successful-apply claim.

Consumers drain bursts in batches and analysis evaluates once using the latest
clock in each batch. Every domain fact and receipt is still processed. Owners
retain commands received before their first simulation clock until a validated
`SimClockTick` supplies that clock; `issued_at` cannot substitute for it.

Proposal IDs are also stable command IDs, so retries reuse the same identity.
Safety guarded actions always need the approval endpoint; manual Apply cannot
bypass that gate. Unsupported guarded actions can be reviewed/rejected but cannot
be executed. Expired recommendations cannot be submitted.

## Intelligence availability

The training API supports the implemented RL subprocess only. Requests for
forecast/anomaly training return 422 rather than manufacturing completed runs.
RL control requires a usable policy and concrete recommendations; policy output
alone never counts as an operational action. Forecast and planning heuristic
outputs must identify their actual source.

The default image supports PPO training without installing the optional
TensorBoard extras: when TensorBoard is absent, training uses console/evaluation logs.
Training limits CPU threads with `RL_THREADS` (default 1). A short synthetic
training smoke test proves artifact creation, reload and action inference; it
does not validate the policy's operational quality or the separate RL effects.

The pure approval queue is a cache rebuilt from Neo4j `ActionProposal` records.
Dispatch and receipts persist lifecycle state. Confirmed execution logs are
rebuilt from executed proposals. Missing receipts trigger retries after five
simulation minutes with the same command ID. Domain mutation/receipt atomicity,
measured-outcome recovery and remaining work are tracked in `ROADMAP_REAL_LDT.md`.

## Coordinated action proposals (Real LDT G7, 2026-10-18)

Neo4j is authoritative for proposal creation, approval/rejection, dispatch attempts
and owner receipts. An analysis-owned runtime lock serializes these short
transactions across replicas. Creation deduplicates active identical
bottleneck/action/parameter targets and submitted recommendation identities. Decisions read the committed status;
a stale cache cannot approve a rejected proposal or overwrite a confirmed receipt.

Each lifecycle write commits its audit facts and any concrete domain command in
`AnalysisOutbox` together. Dispatch status means a durable command is queued, not
broker delivery or successful execution. An independent publisher deletes an
entry only after broker confirmation. Delivery is at least once with stable event
and command IDs. An interrupted publisher or unavailable broker retains the work;
receipt timeout retries after five simulation minutes atomically advance the
attempt timestamp/count and reuse the proposal's command ID. Competing replicas
cannot schedule the same retry at the same clock value. Only a matching owner
topic/type receipt can finish a dispatched proposal; duplicate receipts do nothing.

Approval lists and confirmed logs read Neo4j on every request; the pure queue is
only a calculation cache. The last validated consumed simulation tick is persisted
in `AnalysisRuntime`, so proposal endpoints on another replica can use the same
clock source. Broker partition/offset fencing prevents an older clock owner from
overwriting a newer consumed tick after rebalance. Clock/config metadata never
substitutes wall time for simulation time. Other analysis projection consistency,
training recovery, simulation epochs and owner mutation/receipt atomicity remain
separate roadmap work. Legacy proposals are retained and indexed at startup.
Consumer offsets commit only after durable receipt/proposal processing succeeds; new groups replay
retained inputs from the earliest offset.


`SecurityQueueUpdated` is an unsampled aggregate on `passengers.events` with
`terminal`, `queue_depth`, `lanes_open`, `wait_minutes` and `at`. Passenger-service
publishes it on each normal tick (every 20 ticks in BULK mode). Analysis uses
these measured snapshots to detect and resolve observed congestion. It does
not invent forecast confidence from an observed wait. This also avoids trying
to reconstruct exact queue counts from sampled per-passenger events.

## Projection recovery and input contracts

Before starting its consumer, analysis reads flights, gates, current weather,
active incidents and the latest baggage aggregate from Neo4j. It reconciles
these projections every ten ticks. This read-only snapshot does not advance the
simulation clock; only `SimClockTick` does that. Domain facts update the cache
between reconciliations. Security and ground-vehicle recovery remain separate
roadmap work.

Weather facts use the producer's `new_category` and recommended arrival/departure
rates. Capacity is expressed relative to configured CAVOK rates. Baggage occupancy
uses unsampled `BaggageZoneSnapshot` facts, including in BULK mode; per-bag
`scan_zone` transitions cannot be summed into exact occupancy. What-if requests
require the simulation clock and must not substitute wall-clock time.

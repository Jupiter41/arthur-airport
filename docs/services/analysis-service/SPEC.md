# analysis-service — execution contract

Port: 8007. Consumes domain facts, detects bottlenecks, projects interventions,
and proposes actions. It never writes another service's operational entities.

## Action lifecycle

All entry points (manual Apply, automatic rules, human approval) share a single
mapping to concrete commands. Supported mappings are `ReassignGate`, `HoldFlight`
and `GroundDelayProgram` on `flights.commands`, `OpenSecurityLane` on
`passengers.commands`, `RedirectBaggage` on `baggage.commands`, and
`ContainIncident`/`ResolveIncident` on `incidents.commands`.
`rebook_passengers` remains advisory until a replacement itinerary can be
validated and persisted by the passenger owner. Aggregate recommendations without the
required entity identifiers remain advisory; applying one returns 422.
Previously dispatched rebooking proposals can be failed during reconciliation or
by a matching passenger-owner rejection. A legacy success receipt cannot certify
an itinerary change that was never implemented.

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
separate roadmap work (training recovery: see "Durable training runs"). Legacy
proposals are retained and indexed at startup.
Consumer offsets commit only after durable receipt/proposal processing succeeds; new groups replay
retained inputs from the earliest offset.


`SecurityQueueUpdated` is an unsampled aggregate on `passengers.events` with
`terminal`, `queue_depth`, `lanes_open`, `wait_minutes` and `at`. Passenger-service
persists it on `SecurityCheckpoint` and publishes it on every tick, including BULK. Analysis uses
these measured snapshots to detect and resolve observed congestion. It does
not invent forecast confidence from an observed wait. This also avoids trying
to reconstruct exact queue counts from sampled per-passenger events.

## Projection recovery and input contracts

Before starting its consumer and before each discovery evaluation, analysis reads
flights, gates, current weather, active incidents, the latest baggage aggregate,
security checkpoints, ground vehicles, connection clusters and cost totals from
Neo4j. Security counts/waits are owner snapshots, and vehicle utilisation counts
all non-available vehicles by identity. Sampled passenger/vehicle transitions do
not increment these authoritative aggregates. Replacing a projection clears
removed entities and does not advance the simulation clock.

`AnalysisRuntime {id: 'discovery'}` owns versioned discovery state: input graph,
clock offset, active bottlenecks, recommendations and baggage threshold timers.
The existing analysis transaction lock serializes evaluation across workers.
The last validated `SimClockTick` (including a rewind at a newer broker offset)
is the only clock source. Discovery state and detected/resolved/recommendation
facts commit atomically in `AnalysisOutbox`; caches become visible after commit.
Replaying an evaluated offset restores the committed identities rather than
discovering duplicates. Startup evaluates an accepted but interrupted tick before
consumption resumes. Other workers refresh the shared result after batches.

Graph inputs are each owner's latest committed data, not a historical global
snapshot at the analysis clock. Owner facts can arrive after that clock; later
evaluations reconcile them. Local ephemeral anomaly/narration windows are not
operational truth. Training recovery (G7) and calibration (G8) are described in
"Durable training runs" and "Outcome attribution and calibration" below.

Weather facts use the producer's `new_category` and recommended arrival/departure
rates. Capacity is expressed relative to configured CAVOK rates. Baggage occupancy
uses unsampled `BaggageZoneSnapshot` facts, including in BULK mode; per-bag
`scan_zone` transitions cannot be summed into exact occupancy. What-if requests
require the simulation clock and must not substitute wall-clock time.

## Observed action outcomes

After at least 30 simulation minutes, executed proposals can record observed
conditions. Due-time comparisons normalize offsets to UTC. Incident measurements
read the target's persisted status, including resolved incidents; an absent
target is unknown, not proof of resolution. Gate measurements compare the observed
gate with the requested `gate_id`. Security measurements use the terminal's
observed queue wait and lane count, with its observation timestamp; an unobserved
checkpoint is not measurable. Observations do not establish causal savings.

Outcome updates and `ActionOutcomeMeasured` facts commit together in the analysis
outbox. Duplicate measurements do nothing. Rebuilding the action log preserves
the stored outcome and measurement timestamp. The scheduler records actual elapsed
simulation minutes, which may exceed 30 after downtime or a bulk tick.


## Durable training runs (G7, A58)

`TrainingRun` nodes (unique `id`, indexed `status`) hold the complete run
document — model type, total timesteps, seed, artifact/checkpoint paths, actual
progress, `attempt_count`, `resumed_from_timesteps` — plus `lease_token` and
`lease_until`. Claims and fenced writes first lock `AnalysisRuntime {id:
'training'}`, so they serialize across replicas; at most one run holds a live
lease. Lease times use Neo4j `timestamp()` only as job metadata.

`POST /training/start` creates a `queued` run, claims it and launches
`train_rl.py` with `--seed`, `--checkpoint-dir` and `--checkpoint-freq`
(`TRAINING_CHECKPOINT_TIMESTEPS`, default `timesteps // 20`, at least 1000). The
trainer atomically replaces `latest.zip` + `checkpoint.json` (resume point) and
`progress.json` (actual timesteps) in `<TRAINING_ARTIFACTS_DIR>/checkpoints/<id>`.
The monitor persists progress every heartbeat, which also renews the lease
(`TRAINING_LEASE_SECONDS`, default 30).

A lifespan loop (`TRAINING_RECOVERY_POLL_SECONDS`, default 5) claims any `queued`
run or `running` run whose lease expired, increments `attempt_count` and relaunches
it with `--resume latest.zip`; PPO continues to the requested total with the same
seed and configuration. Resumed training is not bitwise identical to an
uninterrupted run (optimizer/rollout state after the checkpoint is recomputed).
Without a checkpoint, the attempt restarts from zero with the persisted seed.
Graceful shutdown releases the run to `queued`; `POST /training/stop` records
`stopped`, which is terminal. A worker whose lease was replaced terminates its
subprocess and can neither write progress, promote the policy nor finish the
run. The policy is promoted atomically only after a successful exit, a valid
archive and a successful ownership check. Compose mounts the `analysis-artifacts`
volume at `/app/artifacts`; `RL_MODEL_PATH` defaults to
`/app/artifacts/rl_policy.zip`.

## Outcome attribution and calibration (G8, A58)

On first dispatch, a proposal stores `baseline`: the targeted condition, untreated
comparable units (other observed checkpoints; other gate-less waiting flights;
other unresolved active incidents; at most 50) and the engine's prediction in the
outcome's units (security: wait reduction `wait / new_lane_count`; binary
actions: the stated confidence). Retries keep the original baseline.

At measurement the outcome's `attribution` compares the treated change with the
untreated change over the same window: difference-in-differences for security
waits, lift over the untreated control rate for gate/incident actions. The
untreated arm is the counterfactual. Security observations must be refreshed after
the baseline. Without a fresh untreated comparable unit the result is a labelled
`pre_post` observation with `calibration_eligible: false`. Attribution is
observational (`causal_claim: false`), not a randomised estimate.

`services.calibration` derives per action type, from eligible executed proposals:
`effect_ratio` (realised / predicted), `impact_factor`, `success_rate`,
`confidence_factor` and `brier_score`. Factors shrink towards 1.0 with five prior
pseudo-observations and are clamped to [0.25, 2.0]. Ranking multiplies
`impact_value` by `calibration_impact_factor` and confidence by
`calibration_confidence_factor` (capped at 1); `calibration_samples` reports the
evidence. With no eligible outcomes all factors are 1.0. The snapshot is rebuilt
from persisted proposals at startup, after each tick's measurement pass and on
`GET /calibration`.

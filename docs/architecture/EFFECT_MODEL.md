# Shared operational effect model (G4)

`_common.effects` owns a deterministic, minute-step projection and an
`apply(actions, state, horizon)` wrapper. The compact state contains terminal
queues/lanes/arrival rates, gate pools, selected flight targets, baggage targets
and incidents. Adapters never mutate live state. Planning retains flight
lifecycle and Monte Carlo scheduling, but delegates intervention decisions,
runway capacity and queue throughput to this library.

Executable actions require concrete identifiers. GDP applies the same hold to
each eligible departure; baggage redirection changes one bag's flight/status
and removes that bag from its conveyor. Rebooking and other advisory actions
return `no_effect_model` with zero benefit. No itinerary or fleet improvement is
invented. Planning `gate_swap` now moves a flight to an existing available gate,
rather than creating stands. `gdp_start` applies a uniform hold at its start;
`gdp_end` is an end marker; it suppresses a coincident start and cannot undo
committed holds. There is no staggered slot scheduler. Legacy
`cap_pct` maps to a uniform hold of `(1-cap_pct)*duration_minutes`; explicit
`hold_minutes` takes precedence. Disruptions still reduce runway capacity.

Parameters live in `config/airport.yaml:operations.effects`. G8's shrunk,
bounded [0.25, 2.0] factors adjust projected benefits, never physical inventory
or command semantics. Ranking and dispatch-time outcome predictions use the
same projection, horizon and calibration snapshot. The persisted baseline
contains the compact input, parameters, factors, prediction and model version
for reproducible out-of-sample replay. Outcome units remain observational.

New planning results, recommendations, proposals, what-if responses/logs and
PPO archives carry `effect_model_version`. Unversioned persisted records are
labelled `legacy` on read; they are not rerun. PPO embeds the version inside
the atomic archive; load and resume reject incompatible environments.

`scripts/replay_effects.py` reads exported proposal documents or the local
Neo4j proposal log and replays dispatch-time inputs against measured G8
outcomes. It reports each modelled action: fewer than 20 eligible distinct proposal
samples is `unvalidated`; otherwise median absolute relative error must be
<= 0.25. Zero observations use absolute error (zero predicted is exact).
Synthetic tests verify the job, but cannot certify operational accuracy.

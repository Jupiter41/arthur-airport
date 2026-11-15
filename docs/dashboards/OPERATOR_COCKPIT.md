# Operator cockpit and decision history

> 2026-11-15: Navigation, default views and workflow composition are superseded by [UI_IMPLEMENTATION.md](UI_IMPLEMENTATION.md). Domain and evidence contracts below remain in force.

Status: implementation contract, 2026-11-14.

The landing route `/` composes airport state, urgent incidents, approvals and
decision history. The flight board moves to `/flights`; specialist pages stay
available. Live flights/incidents/weather/clock remain Zustand-owned, seeded
and reconciled by REST. Analysis, passenger and baggage observations remain
React Query-owned. A failed fetch must show unavailable/stale data, never a
healthy zero. Maps are schematic, with labelled gate/runway/queue/conveyor state.

`GET /api/v1/analysis/decisions` reads durable analysis-owned `DecisionRecord`
and `ActionProposal` records. Parameters: `limit` (1–100, default 25), `offset`,
`bottleneck_id`, `incident_id`, `status`. `GET /decisions/{id}` retrieves one
timeline independently of list pagination. A timeline is identified by proposal
ID, or bottleneck ID before submission. Lifecycle steps retain their actual
simulation times; dispatch means queued in the transactional outbox. Only a
validated owning-service receipt establishes execution. Retries retain each
dispatch attempt. Rejection, command failure, advisory-only, awaiting receipt,
awaiting measurement and unmeasurable outcomes are distinct states.

Discovery commits a DecisionRecord with the original bottleneck, ranked
recommendations, input metrics and resolution time in the same transaction as
its facts. Proposal creation captures immutable detection/ranking context;
later ranking refreshes cannot rewrite the rationale for an earlier decision.
Lifecycle history and the full owner receipt commit inside the existing
proposal/outbox transaction. Legacy records expose missing evidence explicitly.
No guessed timestamp or reconstructed receipt is presented as original evidence.

The timeline explains score = impact × calibrated confidence ÷ cost using
stored numeric inputs, units and calibration samples. Operational ranking units
are synthetic passenger/disruption minutes, not euros. Financial signals remain
separate context. Outcome views distinguish prediction, observed treated change
and attributed change; missing controls/pre-post measurements are labelled.
Fewer than 20 eligible outcomes is unvalidated, never zero error.

`/decisions` offers searchable decision history and deep links. A read-only
event cursor replays the recorded decision stages; historical mode disables
mutations and never changes simulation time. Full cross-service state rewind
remains deferred as specified in NEXT_STEPS.md.

The security-lane teaching runbook/script uses only gateway APIs against a
disposable synthetic stack. It injects controlled queues with untreated terminal
comparators, submits a normal recommendation, waits for the owner receipt and
the simulation-clock outcome, then exports the actual durable timeline. It
must fail on missing receipt/outcome rather than manufacture stages. One run is
an example, not empirical validation. Demo fixtures used in UI tests remain
explicitly separate from live API data.

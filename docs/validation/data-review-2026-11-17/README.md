# Data-flow review: closure revalidation

Date: 2026-11-17 (Europe/Luxembourg). Reviewed checkout: `0ae109a`.

**Verdict: do not close the review. RC1, RC7 and RC8 are reopened; earlier fixes are retained.**
The earlier green unit/transaction checks did not exercise the real orchestrator
startup query or the new airborne transition through the passenger repository.
Both fail when the current code runs together. The existing airport was left
running and all ten readiness endpoints still returned 200 at the end. Owned
validation stacks were stopped; project volumes were preserved.

## Scope and evidence boundaries

- Inspected all RC1–RC11 and lower findings L1–L9, current sources, running
  containers, graph aggregates, owner checkpoints, actual Kafka traffic,
  authenticated WebSocket traffic, owner source-health APIs and the browser UI.
- `art-ldt-g6` is the existing airport. All ten readiness endpoints initially
  returned 200. Its four flight/passenger/baggage/orchestrator images predate
  RC7/RC8, although their shared-library bind mounts are current. This is a
  **mixed deployment**, not evidence that `0ae109a` works end to end.
- `art-data-review` is a separate full stack using cached runtime images, current
  flow-owner source mounts, separate ports/networks and fresh project volumes.
  No build bypassed the Docker storage guard. The unchanged checkout failed its
  first cold start. Two temporary corrections, documented below, were needed
  only in this disposable stack to investigate downstream behavior.
- `art-data-review-g1` is a separate infra-only project for independent-process
  transaction/crash/replay tests. It uses current repository code without the
  two temporary corrections.
- Application sources were **not fixed** during this audit. The API suite on the
  existing airport includes synthetic incident injection and an isolated
  pagination fixture; its results are not a clean performance baseline. Full
  interruption, financial, planning and proposal tests ran on the disposable
  stack. No airport data volumes were reset or pruned.

## Canonical root-cause tracking

The actionable backlog is [DATA_FLOW_REVIEW.md](../../../DATA_FLOW_REVIEW.md).
Reopened entries retain their completed work; these links identify what remains.

| Report finding | Tracked under |
|---|---|
| B1/B2: startup query and rejected airborne transition | [RC7 — reopened](../../../DATA_FLOW_REVIEW.md#rc7) |
| B3/B4/B8: durable collection, lifecycle guards and BULK contract | [RC12](../../../DATA_FLOW_REVIEW.md#rc12), with [RC8 — reopened](../../../DATA_FLOW_REVIEW.md#rc8) recovery |
| B5: terminal retention/disposition gaps | [RC1 — reopened](../../../DATA_FLOW_REVIEW.md#rc1) and [RC8 — reopened](../../../DATA_FLOW_REVIEW.md#rc8) |
| B6: effective settings mismatch | [RC13](../../../DATA_FLOW_REVIEW.md#rc13) |
| B7: mixed deployment | [RC14](../../../DATA_FLOW_REVIEW.md#rc14) |
| Missing startup coverage and stale integration/transaction fixtures | [RC15](../../../DATA_FLOW_REVIEW.md#rc15) |
| L2: unbounded poison-message retry | [RC16](../../../DATA_FLOW_REVIEW.md#rc16) |
| L3: financial clock sanity | [RC17](../../../DATA_FLOW_REVIEW.md#rc17) |
| L6: historical gateway replay as live | [RC18](../../../DATA_FLOW_REVIEW.md#rc18) |
| L7: weather/incident write–fact atomicity | [RC19](../../../DATA_FLOW_REVIEW.md#rc19) |
| L8: UTC offset normalization | [RC20](../../../DATA_FLOW_REVIEW.md#rc20) |

## Confirmed runtime/code findings

| ID | Priority | Finding and impact | Evidence / code |
|---|---|---|---|
| B1 | P1 | **Orchestrator cannot start.** `_day_already_seeded()` mixes `d.ready` and `count(f)` inside a CASE without an explicit grouping step. Neo4j raises `CypherSyntaxError` before the day manifest is generated. This also affects startup on existing graphs. | [startup failure](startup-failure.log); `services/sim-orchestrator/services/seeder.py:27–30` |
| B2 | P1 | **A valid inbound flight event permanently stalls passenger processing.** RC7 now requests `booked → airborne`, but `_VALID_STATUSES` excludes `airborne`. Both the event path and reconciliation reach the rejecting repository. The consumer repeatedly retries the same event; the passenger checkpoint stayed at 06:01 while the clock reached 08:05 (124 sim-min behind). Passenger and baggage seed requests remained pending. | [stall log](passenger-stall.log), [lag sample](isolated-kafka.json), [partial manifests](isolated-probe-2.json); `services/passenger-service/db/neo4j.py:257`, `kafka/consumer.py:1890` |
| B3 | P1 | **Collection facts can be acknowledged without durable collection progress.** The `collected` branch only adds a passenger ID to an in-memory set. A Kafka batch can commit without a clock tick, then a crash loses the set update. The arrival-claim decision has no corresponding replay/reconciliation of durable collected bags, so timeout remains the fallback. | [production-handler/database reproduction](carousel-reproduction.json): memory true, checkpoint false, checkpoint unchanged; passenger consumer `:2229`, shared consumer loop `:234` |
| B4 | P2 | **Known arrival bags move passengers to the carousel too early.** The `on_carousel` handler updates the passenger's zone without checking their status. A real repository write left a synthetic passenger `status=deplaning`, `zone=carousel-3`. This path becomes common once RC7 supplies passenger IDs. | [reproduction](carousel-reproduction.json); passenger consumer `:2197–2227` |
| B5 | P2 | **Terminal dispositions still leak into live history.** Passenger retention omits terminal `missed_connection`; 17 such passengers were older than the 24-sim-hour archive cutoff. Arrival baggage on diverted flights is neither recovered nor archived: 887 live in-hold bags were attached to diverted arrivals, with the oldest scheduled June 17 while the clock was June 22/23. | [passenger retention](retention-and-sizing.json), [diverted holds](terminal-arrival-holds.json); passenger retention `:23`, baggage recovery `:699–704`, baggage retention `HoldSweep` |
| B6 | P2 | **Settings report capacities different from the owners.** The settings endpoint/UI advertises lanes A/B/C = 4/3/4 and sorting = 1,800/h; the passenger owner reports 8/12/8 and baggage reports 5,400/h. The settings schema retains old hardcoded defaults instead of the airport configuration. An operator cannot treat these displayed settings as the actual model. | [same-run endpoint comparison](settings-consistency.json); orchestrator `services/settings.py:52–59` |
| B8 | P2 | **BULK mode loses the collection trigger entirely.** The baggage planner persists `on_carousel → collected` but suppresses the individual `BaggageStatusChanged` facts. Passenger-service ignores `BaggageStatusBatchChanged`, so it never learns the collection and falls back to the claim timeout. | [production-planner reproduction](bulk-collection-reproduction.json); baggage consumer `:512–542, 1114–1122`, passenger dispatch `:584–607` |
| B7 | P1 deployment | **RC7/RC8 are not deployed in the existing airport.** Source fingerprints differ in 13 Python files across the four relevant service images; shared files match the checkout. The graph contains no `SeedDay`/`SeedBatch`, still has phantom airborne arrivals and mostly anonymous local-arrival bags. The initial sample found 20,949 airborne passengers on scheduled inbound flights. | [deployed hashes](deployed-source.json), [initial graph](live-probe-1.json), [corrected aggregate probes](live-probe-2.json) |
| L2 | P1 | **Unbounded poison-message retry remains.** Manual-commit dispatch retries every 100 ms indefinitely, without quarantine/DLQ or a recoverable error policy. B2 reproduced this with valid generated traffic rather than a malicious message. | shared `kafka_runtime.py:223–235`, [stall log](passenger-stall.log); cost consumer has the same indefinite-retry pattern |
| L3 | P2 | **Financial inputs lack clock-relative sanity checking.** A `FlightStatusChanged` for an existing synthetic flight, stamped `2030-01-01T12:00:00Z`, was accepted and written to `CostInbox` while the simulation was in 2024. | [isolated reproduction](future-event-reproduction.json); cost ledger `:266–281` |
| L6 | P2 | **Gateway restart can replay historical facts as live.** It retains the fixed `api-gateway` group and committed offsets, then forwards events without an age fence. The RC9 delivery policy coalesces/drops categories, but does not distinguish replay from current observations. This was verified in source, not by disrupting the existing gateway. | `services/api-gateway/src/kafka.ts:68–70, 104–145` |
| L7 | P1/P2 | **Weather and incident state/fact commits are still separate.** Weather persists its state then directly publishes; incident lifecycle changes the graph then calls its publication callback. A failure between the steps can lose the fact, and replay may see an already-advanced state. TTR decrement and resolution also remain separate writes. | weather consumer `:362–381`; incident lifecycle `:220–223, 279–297`. Existing finding remains open; no destructive fault injection on the existing airport. |
| L8 | P2 | **Offset timestamps are stripped rather than normalized to UTC.** `FlightView._iso('2024-06-15T12:00:00+02:00')` returns noon, rather than 10:00 UTC. Aware datetime inputs are also made naive without UTC conversion. UTC/Z traffic masks the bug. | [reproduction](time-normalization.json); `_common/flight_view.py:45–54` |

Prior live claim records all measured exactly 45 minutes, consistent with the
legacy anonymous-bag defect. That legacy measurement cannot establish that
named-bag exits work correctly after deployment. In the final conditional
run at 22:24, 28,530 completed claim visits ranged from 1 minute upward; 15,713
were at least 45 minutes (which also includes passengers with no checked bag).
This demonstrates some collection-triggered exits, not universal correctness.
The conditional run also crossed 23:30 and midnight: by day 2 at 00:50,
both SeedDay markers were ready and all requests were accepted, including day
2's 1 flight, 135 passenger and 120 baggage batches
([boundary evidence](day-boundary-final.json)). No phantom airborne arrivals, stranded at-gate/arrived holds, unscreened departure
holds or passenger-flight cardinality violations were found in that final
conditional snapshot ([final graph](isolated-probe-final.json)). The downstream corrected run
did confirm named collection facts: all 491 sampled `collected` facts carried a
passenger ID ([event metadata](arrival-bag-event-metadata.json)).

## Positive results and remaining closure requirements

| Review item | Revalidation | Closure assessment |
|---|---|---|
| RC1 | Live/archive separation and bounded target queries exist; active checkpoints are much smaller than the original history-wide state. New terminal-retention omissions are confirmed. | **Reopened: B5 must be resolved.** |
| RC2 | Deployed snapshot: flight 1.87 MB, passenger 0.17 MB, baggage 0.22 MB. Removed unbounded induction/draw sets remain removed. | Supported for the measured workload; retain long-run size tracking. |
| RC3 | Outboxes sampled at 0/0/0/8 for flight/passenger/baggage/cost. Deployed average passenger tick ≈163 ms; baggage ≈80 ms. Live sample p95 tick-to-produce: passenger batch 0.444 s, baggage batch 0.171 s, flight status 0.322 s, cost 0.950 s. | The main throughput fix is supported; this is not an exactly-once guarantee. |
| RC4 | Event-fed views and boarding progress exist. Live sample observed 9,146 batch passenger transitions with no reconciliation reason. Back-pressure reported live baggage lag up to 5 min at the busy dawn. | Normal-run improvement supported; do not certify restart causality until the red recovery gate is repaired and rerun. |
| RC5 | Existing deployment's completed-day mean departure delays were 1.1–2.4 min; exact one-flight relationship checks found no violations. Existing flow tests pass. | Main departure-flow fix supported. B4/B6 and new arrival paths still need correction. |
| RC6 | Zero sampled departure hold bags lacked a screening scan; BHS demand checks pass in the unit suite. | Main screening/capacity fix supported; B6 prevents trusting the settings display. |
| RC7 | Current-code cold start fails (B1); new inbound transition stalls (B2). With temporary corrections, all 142 passenger, 128 baggage and 1 flight batches were accepted, and arrival bags had CARRIES links. | **Reopen. Temporary validation corrections are not a fix to main.** |
| RC8 | Hourly/startup bag recovery is present, but B2 blocks progress, B3 can lose collection progress, B5 leaves terminal holds live, and B8 suppresses collection inputs in BULK. | **Reopen.** |
| RC9 | A 45 s authenticated browser-equivalent stream received ≈10.9 domain messages/s and 18.6 KB/s, versus the original ≈450 messages/s. No raw passenger/baggage status firehose reached that client. Dashboard/gateway contract tests pass. | Main delivery-policy fix supported; L6 still needs a replay policy. |
| RC10 | ADS-B correctly reports disabled, with owner health and clock labels. Weather and other owner-backed source statuses were verified. Overview/passenger pages loaded live data in the browser. | Main source-health fix supported; B6 is a separate remaining truthfulness issue. |
| RC11 | Bounded catch-up and transient checkpoint retry remain. Deployed health is good, but B2 produces a permanent retry stall and review-wide interruption gates are not yet green. | Do not close the overall resilience requirement from unit results alone. |
| L1 / L4 / L5 | Random tick sampling is removed; analysis target queries/cache exclude hold history; inbox pruning is implemented. | Prior fixes supported in source and the corresponding tests. |
| L9 | Actual heap/page cache are 2 GiB/2 GiB; tx-log target is 256 MiB. Directory measured 4,567 MiB. Logs show 15-minute checkpoints, so uncheckpointed logs can exceed the retention target substantially. | Operational capacity caveat, not proof of a fresh leak. A storage target is not a hard cap. |

## Validation gates

- Python unit tests: **1,470 passed**, 8 existing warnings.
- Gateway: **43 passed**, TypeScript build passed.
- Dashboard: **115 passed in 25 files**, TypeScript/Vite build passed.
- Required service/live-transaction Ruff scope: passed. An additional exploratory
  lint over all `tests/` reports 18 existing test-style errors outside that CI
  scope; these are not reported as 18 runtime defects.
- Existing-stack API/route gate: **68 passed** (includes synthetic incidents and
  a namespaced pagination fixture).
- Current-code full cold start: **failed**; see B1. Downstream runs require the
  two disposable-only corrections in [startup-workaround.diff](startup-workaround.diff).
- Independent-process, real Neo4j/Kafka transaction gate: **34 passed, 2 failed**.
  The baggage mutation fixture never bootstraps its event-fed FlightView, and
  the replay fixture inserts an arrived bag directly in Neo4j then expects an
  immediate pipeline refresh despite the current refresh cadence. These tests
  must be brought into agreement with the owner/event contract before their
  gate can be used as closure evidence. See [results](live-transactions.xml).
- Initial full integration attempt: 80 passed, 59 failed, 4 teardown/setup errors.
  Many failures were cascading **harness effects**: testing began during the
  isolated passenger replacement and the harness had disabled normal restart
  policies. This attempt is preserved, not presented as 63 independent bugs.
- Complete repeat with normal restart policies and readiness gating: **139 passed,
  3 failed**, no skips or teardown errors. The remaining failures are the
  boarding-query fixture and two planning result-metadata expectations described
  below. See [repeat results](isolated-integration-repeat.xml). This run still
  uses the two application workarounds and is not a green gate for main.

Two planning lease-test expectations are stale: their synthetic expected result
omits `effect_model_version`, while `model.get_results()` deliberately supplies
`effect_model_version='legacy'`. The boarding-query integration fixture writes
flights directly to Neo4j but never loads the FlightView it now queries. These
are validation defects, not evidence that the corresponding transaction lost
data. Diagnostic reruns with only a bootstrapped test FlightView and updated
metadata expectations all returned zero ([diagnostics](fixture-diagnostics.json)).
Repository tests remain unchanged, so their mandatory gates remain red.

## Conditions for closing the review

1. Fix B1/B2 and add a genuinely cold full-stack startup regression that calls
   the real seed-existence query and real passenger repository.
2. Make baggage collection observations durable/rebuildable across acknowledgement
   and crash, including BULK; gate carousel positioning on the passenger's actual lifecycle.
3. Complete terminal disposition/retention, reconcile the settings contract,
   and resolve L2/L3/L6/L7/L8 with regression evidence or explicitly accepted,
   separately tracked exclusions. A remaining accepted risk is not “fixed.”
4. Repair the stale integration/live-transaction fixtures and rerun every
   required gate without application workarounds.
5. Deploy a coherent version to the existing airport; exercise daytime arrivals,
   transfers, collection, service outages/replay, 23:30 seeding and retention.
   Decide explicitly how historical anonymous bags will be handled: their real
   passenger assignment cannot be reconstructed from missing data.

Until these conditions hold, the review is **open**, even though the original
performance/firehose problems have improved materially.

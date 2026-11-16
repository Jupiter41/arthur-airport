# Data-flow & event-driven behaviour review

Review date: 2026-11-16 · Reviewed commit: `1e7b16d` (main, clean)
Reviewed stack: `art-ldt-g6-*` compose project. It had been running continuously for about 23 simulated days at 60× (sim day 23–24, 2024-07-07 → 07-08).

The question was why data sources and events feel **slow** and are **sometimes wrong**.
Every finding below was checked against the running system (Kafka offsets/latency, Neo4j
PROFILE / `SHOW TRANSACTIONS`, graph queries, checkpoint benchmarks) and traced to the code
that causes it. Findings are grouped by **root cause**, not by symptom, because several visible
problems share one cause.

---

## 0. TL;DR

Ten root causes explain nearly everything. The first four make things **slow**; RC4–RC8 make
data **wrong**; RC9–RC10 make the **UI and data-source pages** look slow and wrong.

| #    | Root cause | Main visible symptom | Severity |
| ---- | ---------- | -------------------- | -------- |
| RC1  | The live operational graph keeps all history, and per-tick queries scan it by status | baggage/passenger ticks take 1–2 s; Neo4j 81% CPU; 11 GB tx logs | 🔴 High |
| RC2  | Each owner rewrites its **whole in-memory state** as one JSON property **every tick**; the baggage one grows without bound (8.6 MB) | baggage-service at 100% CPU, processing about 0.45 ticks/s | 🔴 High |
| RC3  | The outbox drains in 100-row round trips, and every bag/passenger transition is published twice (per-entity + batch) | +0.5–1.3 s before an event reaches Kafka; 340 baggage msgs/s | 🟠 Medium |
| RC4  | The clock is open-loop with no back-pressure. Services read **other domains' live state from the shared Neo4j** instead of the event stream | passengers deplane/depart from a polling sweep, up to 64 sim-min late; causality broken | 🔴 High |
| RC5  | Passenger flow is a step function (whole flight checked in at T-120 and sent to security at T-45). Boarding isn't gated by flight state | 80% of departures delayed ≥30 min ("boarding_incomplete"); 11.5% of pax board **after** their flight left; no-show rate 0.08% instead of 3% | 🔴 High |
| RC6  | Baggage-system capacity (1,800 bags/h) is less than generated demand (peak 4,900/h), and the departure handler hides the deficit by teleporting bags | 27–37% of departing bags are "in_hold" **without ever being screened** | 🔴 High |
| RC7  | The seeder writes other domains' entities directly and leaves out cross-domain links | 0 of 39,975 arrival bags linked to a passenger, so every arrival pax leaves claim on the 45-min timeout; 33,651 pax "airborne" on flights that haven't left origin | 🟠 Medium |
| RC8  | One-shot event triggers with no reconciliation, and consumers start at `latest` | 39,969 arrival bags from 2024-06-29 stuck `in_hold` permanently | 🟠 Medium |
| RC9  | The gateway forwards the raw firehose to browsers, and the dashboard does no-op store writes per event | about 450 WS msgs/s per tab; ~280 useless React store updates/s | 🟠 Medium |
| RC10 | The gateway builds data-source health itself (hardcoded) instead of the adapters reporting it | ADS-B shown as `adsb.lol · active` while `ADSB_ENABLED=false` and 0 aircraft | 🟡 Low–Med |
| RC11 | History-wide query plans exhaust Neo4j's *shared* transaction memory; coalesced catch-up ticks grow with each failed retry; the clock pauses on any checkpoint error | passenger-service stuck 6 sim-h behind, then the whole sim auto-paused (found during deployment) | 🔴 High |

### Fixes applied (2026-11-16)

**Round 1** (commit `78a9975`):

| Change | Where | Addresses |
| ------ | ----- | --------- |
| `inducted_bag_ids` removed from the persisted checkpoint (kept as a per-tick copy, rebuilt from `Baggage.status`, so it's bounded to bags still on the belt). Legacy checkpoints still restore via a new `SnapshotCodec(retired_fields=…)` | `baggage-service/kafka/consumer.py`, `_common/checkpoint.py` | RC2 |
| `run_tick` decodes the stored checkpoint only when the in-memory `last_tick_sim_time` differs from the committed one | `_common/transaction_scope.py` | RC2 |
| Second `deepcopy(conveyor)` skipped inside `run_tick` (the candidate is already a disposable copy) | `baggage-service/kafka/consumer.py` | RC2 |
| Baggage by-status gauge every 60 ticks (`BAGGAGE_STATUS_GAUGE_INTERVAL_TICKS`). The passenger gauge reads the existing 15 s flow projection instead of querying inside the tick | baggage / passenger consumers, `passenger-service/services/flow_projection.py` | RC1 |
| Induction query starts from in-window departures in live states, with per-flight expansion (`CALL {}`): **2.6M → 46k db hits** | `baggage-service/db/neo4j.py` | RC1 |
| Reconciliation query pinned to per-passenger expansion (`CALL {}`): the old plan held about 1.5M rows in a hash join, **713 MiB → negligible** | `passenger-service/db/neo4j.py` | RC1 / RC11 |
| Coalesced clock gaps replayed as ≤5-min owner ticks (`catch_up_times`, `CATCH_UP_MAX_STEP_MIN`) | `_common/transaction_scope.py`, baggage / passenger consumers | RC11 |

**Round 2** (closing the three items left open by round 1):

| Change | Where | Addresses |
| ------ | ----- | --------- |
| Clock checkpoint retries `TransientError` / `ServiceUnavailable` / `SessionExpired` with 0.2 → 2 s backoff, and pauses only after the retries fail | `sim-orchestrator/services/runtime_state.py` | RC11 |
| Next-day seeding runs as a background task at 23:30. A new `on_day_start` clock callback waits for it at midnight only if it hasn't finished (it only can be late at very high speeds), and reseeds inline if it failed | `sim-orchestrator/services/clock.py`, `main.py` | RC11 |
| Neo4j heap 1G → 2G (transaction pool 0.7 → 1.4 GiB) and page cache 512M → 2G, both env-overridable (`NEO4J_HEAP_MAX`, `NEO4J_PAGECACHE`) | `docker-compose.yml`, `docs/infra/DOCKER.md` | RC1 / RC11 |
| Baggage `_prepare_tick` re-reads the full pipeline only after a checkpoint restore, plus every 60 ticks as a safety net. Event handlers already keep the conveyor in sync | `baggage-service/kafka/consumer.py`, `TickScope.restored` | RC1 |
| Passenger FSM reads bounded to rows the rule can act on: booked ≤ T-120, checked_in ≤ T-45, airside ≤ gate-open, and deplaning/customs/claim by their own due timestamps (`get_passengers_by_status(due_field=…)`, whitelisted fields) | `passenger-service/db/neo4j.py`, `kafka/consumer.py` | RC1 |
| Lean security-queue reconcile (3 columns, no Flight/Gate expansion) | `passenger-service` | RC1 |
| Connection check seeks the status index instead of label-scanning every passenger for `connection: true` (no index exists): **4.0M → 665 db hits, 1.5 s → 2 ms** (same result set, checked atomically) | `passenger-service/db/neo4j.py` | RC1 |
| Arrival bags on a carousel already mapped for their flight skip the per-bag flight read and write. The tick places later passengers | `passenger-service/kafka/consumer.py` | RC3 |
| Tick observability: `service_tick_processing_seconds` (the existing P6-3 profiler, now wired in) and a new `service_tick_phase_seconds{phase}` covering passenger FSM phases and event handlers | `_common/_profiler.py`, baggage / passenger consumers | – |

Unit suite: 1340 → **1352 passing**, with a test for each behaviour above.

**Measured live** on the `art-ldt-g6` stack at daytime load (≈44k baggage events per 2 min, the
same as the 08:00 peak), using the default 2G/2G Neo4j settings:

| Metric | Before | After |
| ------ | -----: | ----: |
| Baggage checkpoint size | 8.6 MB (growing) | 2.2 MB at peak / 0.17 MB at night, no longer grows with history |
| Baggage CPU | 99.96% | ≈30% |
| Passenger CPU | 85% | ≈22% |
| Neo4j CPU | 81–144% | **≈46%** |
| Passenger tick (avg) | 1,025 ms (budget 1,000 ms) | **319 ms** |
| Clock ticks processed by passenger / emitted (2 min) | 97 / 117 (coalescing, lag 3–7) | **120 / 116**, consumer lag 1 (the tick in flight) |
| BaggageStatusChanged tick→produce p50 / p95 | 2.92 / 4.03 s | **0.17 / 1.08 s** |
| PassengerStatusChanged tick→produce p50 / p95 | 2.83 / 4.84 s | **0.67 / 1.01 s** |
| Clock across 23:30 seeding | ~20 s stall (41 of 60 ticks that minute) | worst tick gap **1.19 s** |
| Passenger 6 sim-h backlog after the RC11 stall | never recovered (OOM loop) | replayed in bounded steps, 0 OOMs |

What's left after outbox delivery is the fixed 0.5–0.7 s produce→broker wait (RC3 outbox polling),
which wasn't in scope here. RC3 (outbox batching / single event granularity) and RC4–RC10 are
model and contract changes, still open as described below. Retention/archival of finished
entities (RC1) is also not done. With bounded queries it is no longer on the hot path, but it
still drives disk use and the cost of any unbounded read.

**Optional, needs your decision:** the services run the pure-Python Neo4j driver.
`neo4j-rust-ext==6.2.0.0` (official Neo4j package, matching the pinned `neo4j==6.2.0`) speeds up
record decoding, which is now the main per-row cost (~0.1 ms/row). It is not installed.

**New finding while measuring:** connecting passengers have no `connection_flight_id` property
(Neo4j reports the property key as unknown), so `get_connecting_passengers` never resolves the
onward flight. Connection-risk evaluation runs without connection times or gates. This is the same
family as RC7 (the seeder omits cross-domain links).

---

## 1. Method & live measurements

All probes were read-only against the running stack. Scripts ran inside the existing service
containers, using their own `confluent_kafka` / `neo4j` drivers and throw-away consumer groups
(`review-<uuid>`, `auto.offset.reset=latest`, no commits).

### 1.1 Topic throughput (30 s window)

| Topic | msgs/s | Share |
| ----- | -----: | ----- |
| `baggage.events` | **337.6** | 75% of all domain traffic (7.9 M messages retained) |
| `passengers.events` | 93.4 | 21% |
| `cost.events` | 8.5 | |
| `flights.events` | 5.5 | |
| `sim.clock` | 1.1 | 1 tick/s = 1 sim-min/s at 60× |
| `__consumer_offsets` | 102.3 | commit traffic from manual per-batch commits |

### 1.2 Clock-tick → event latency (60 s window, every topic)

`tick→produce` = envelope `produced_at` minus the `produced_at` of the SimClockTick with the same
`sim_time`. `produce→broker` = Kafka log timestamp minus envelope `produced_at`, i.e. time spent
waiting in the outbox.

| Event | n/min | tick→produce p50 / p95 / max | produce→broker p50 / max |
| ----- | ----: | ---------------------------- | ------------------------ |
| BaggageStatusChanged | 17,475 | **2.92 / 4.03 / 4.28 s** | **1.32 / 2.17 s** |
| PassengerStatusChanged | 4,133 | **2.83 / 4.84 / 5.71 s** | 0.78 / 3.53 s |
| SecurityQueueUpdated | 99 | 1.41 / 4.98 / 5.30 s | 0.73 / 1.08 s |
| CostRecorded | 251 | 0.72 / 1.40 / 1.54 s | 0.57 / 1.06 s |
| FlightStatusChanged | 114 | 0.22 / 0.32 / 0.34 s | 0.49 / 1.15 s |
| IncidentAlert | 3 | 0.09 s | 0.00 s (direct produce) |

**Reading:** flight-service keeps pace with the clock (≈0.25 s). Baggage and passenger
services run **3–5 ticks behind**. At 60× that is 3–5 simulated minutes, plus another
0.5–1.3 s in the outbox. A UI showing the clock at 11:31 is showing baggage state from about 11:27.

### 1.3 Resource saturation

| Container | CPU | Note |
| --------- | --: | ---- |
| baggage-service | **99.96%** | One Python event loop pinned to one core |
| passenger-service | 85% | |
| neo4j | 81% | page cache 512 MB vs 5.7 GB store; **11 GB** of transaction logs, a 270 MB segment rotated about every 30 s (≈9 MB/s) |

### 1.4 Where Neo4j time goes (40 s `SHOW TRANSACTIONS` sampling, 1,765 samples)

| Total time | Calls | Client | Query |
| ---------: | ----: | ------ | ----- |
| **25.1 s** | 18 | baggage | `MATCH (b:Baggage) USING INDEX … RETURN b.status, count(b)` (Prometheus gauge, every tick) |
| 15.7 s | 18 | baggage | `MATCH (b:Baggage {status:'dropped_off'})-[:LOADED_ON]->(f) …` (induction candidates, every tick) |
| 14.1 s | 25 | passenger | `MATCH (p:Passenger {status:$status})-[:ON_FLIGHT]->(f) …` |
| 11.6 s | 7 | baggage | `SET s.document = $document` on `BaggageOutboxSeq` (8.6 MB checkpoint write) |
| 11.5 s | 25 | passenger | `get_passengers_by_status(... flight_statuses ...)` |
| 9.8 s | 17 | baggage | `get_baggage_in_pipeline` (`_prepare_tick`, every tick) |
| 8.4 s | 8 | passenger | `MATCH (p:Passenger) … RETURN p.status, count(p)` (status-count gauge) |

In 40 s the baggage service completed only **18 ticks**, about 0.45 ticks/s against a 1 tick/s
clock. The remaining ticks are coalesced by `run_consumer_loop` ("keep only the latest tick").

---

## 2. Findings by root cause

### RC1 — Live graph = full history, and per-tick queries scan it 🔴

**Evidence**

- Graph contents: `ScanEvent` 7.88 M, `Baggage` 2.15 M (1.22 M `in_hold` + 0.91 M `collected`;
  about 16k actually in the system), `Passenger` 1.58 M (1.58 M `departed_airport`),
  `CostInbox` 345k, `CostRecord` 370k.
- `get_baggage_counts_by_status()` ([baggage-service/db/neo4j.py:593](services/baggage-service/db/neo4j.py:593))
  costs **2,146,757 db hits** per call (one per bag ever created), ~480 ms idle and 1.4 s
  under contention. It runs every tick (`gauge_interval = 1` outside BULK,
  [consumer.py:679](services/baggage-service/kafka/consumer.py:679)).
- The passenger equivalent `get_status_counts()` scans 1.58 M nodes (max 2.5 s observed) every 5 ticks.
- `get_dropped_off_baggage_for_departures()` ([db/neo4j.py:679](services/baggage-service/db/neo4j.py:679))
  has **no time window**. It returns all 7,430 dropped-off bags (≈113k db hits) every tick, and
  Python then drops everything more than 90 min out
  ([consumer.py:793](services/baggage-service/kafka/consumer.py:793)).
- Neo4j page cache is 512 MB for a 5.7 GB store, so full-index scans miss the cache.

**Root cause.** Nothing ever leaves the operational graph. Finished entities (`in_hold` bags on
arrived flights, `collected`, `departed_airport` passengers, every `ScanEvent`, every inbox
marker) stay in the same label and status indexes the hot path queries. The design assumes
"Neo4j = current state" (CLAUDE.md rule 3), but the graph is in practice an append-only history
store. Per-tick cost therefore grows **linearly with simulated days**, and that is why the system
"gets slower" the longer it runs.

**Fix direction**

1. Add a lifecycle/retention step. Move finished entities to an archive label (`:BaggageArchive`,
   `:PassengerArchive`) or delete them once they are N sim-hours past their flight, and stream the
   history to analysis (a Kafka topic or Parquet) if needed.
2. Never compute gauges with `count()` over a label. Keep counters incrementally from the
   transitions the tick already computes (`plan.status_changes`), or run the query once a minute.
3. Bound `get_dropped_off_baggage_for_departures` by `f.estimated_time <= $now + 90 min`
   (the `Flight(scheduled_time)` index already exists).
4. Prune `*Inbox` nodes older than the Kafka retention (168 h). Past that, no redelivery can
   arrive, so dedup markers are dead weight.

---

### RC2 — Whole-state checkpoint serialized, copied and rewritten every tick 🔴

**Evidence** (benchmark inside the baggage container against the live checkpoint)

| Checkpoint | Size | read | decode | deepcopy | encode |
| ---------- | ---: | ---: | -----: | -------: | -----: |
| `BaggageOutboxSeq` | **8.64 MB** (6.9 MB 20 min earlier) | 125 ms | 125 ms | 120 ms | 236 ms |
| `FlightRuntime` | 1.0 MB (`turnaround_plans` 1.0 MB) | – | – | – | – |
| `PassengerRuntime` | 0.51 MB (0.18 MB 25 min earlier) | 73 ms | 3 ms | 3 ms | 9 ms |

- 5.8 MB of the baggage checkpoint is `inducted_bag_ids`: **144,588 IDs**, never pruned. Entries
  are only added ([consumer.py:584](services/baggage-service/kafka/consumer.py:584),
  [:672](services/baggage-service/kafka/consumer.py:672)). The set is only cleared on a cold
  rebuild, which never runs once a checkpoint exists
  ([consumer.py:105-109](services/baggage-service/kafka/consumer.py:105)).
- Per tick, `run_tick()` ([_common/transaction_scope.py:84](services/_common/transaction_scope.py:84)):
  1. reads the checkpoint inside the tx,
  2. deep-copies every codec field,
  3. **decodes the stored document again over the copy**, even though the in-memory state is
     already identical,
  4. `_advance_tick` deep-copies the conveyor a second time as a rollback snapshot
     ([consumer.py:646](services/baggage-service/kafka/consumer.py:646)),
  5. encodes everything back,
  6. writes ~8.6 MB as one property.

  That is about 600 ms of pure CPU per tick, plus ≈9 MB/s of Neo4j transaction log.
- `_prepare_tick` also re-queries the whole pipeline (`get_baggage_in_pipeline`) every tick.

**Root cause.** The A41 "per-tick atomicity" design snapshots **everything** the consumer
holds, including caches that can be derived from Neo4j (`inducted_bag_ids` duplicates
`Baggage.status`; dropped-off bags are found by status anyway). It does that synchronously on
the single event loop. Cost scales with state size, not with the size of the tick's change.

**Fix direction**

- Drop `inducted_bag_ids` from the checkpoint. The persisted `status` is the guard. Or bound it to
  bags whose flight hasn't departed.
- Only restore from the stored document when the in-memory `last_tick_sim_time` doesn't match the
  stored one (first tick after a restart or a lost transaction). In steady state, skip the decode.
- Store the conveyor as a compact per-zone list of IDs, or rebuild it from `Baggage.current_zone`,
  instead of a pickled-style object graph. Write it every N ticks, not every tick. Owner facts are
  already idempotent through stable event IDs.
- Replace the second `deepcopy(conveyor)` with the candidate copy `run_tick` already makes.

---

### RC3 — Outbox delivery and duplicated publication 🟠

**Evidence**

- `publish_pending()` ([_common/outbox.py:146](services/_common/outbox.py:146)) runs this loop:
  read up to 100 rows ordered by `(revision, position)`, produce them, **block until the broker
  acks** (`publish_confirmed_batch` polls until all callbacks fire), then delete them in a separate
  session. Each loop is three Neo4j round trips plus an `acks=all` round trip. When the outbox is
  empty it sleeps `poll_interval_s=1.0` before looking again.
- One baggage tick stages 600–700 facts, which takes ≥7 loops to drain. The live `BaggageOutbox`
  backlog oscillated between **1,047 and 1,735 rows**, giving 1.3 s median / 2.2 s max outbox delay.
- Every bag transition is emitted **twice**: as a per-bag `BaggageStatusChanged` and inside
  `BaggageStatusBatchChanged` ([consumer.py:534-541](services/baggage-service/kafka/consumer.py:534)).
  Passengers do the same (`PassengerStatusChanged` + `PassengerStatusBatchChanged`). No backend
  service consumes the batch events. Only the dashboard uses them, as an "invalidate" hint.
- The per-bag stream (17.5k/min) goes to consumers that drop almost all of it:
  - `passenger-service` only handles `on_carousel` and `collected` (about a third).
  - `cost-service` subscribes to `baggage.events` and `passengers.events`, Pydantic-validates
    every message, and uses none of it.
  - The dashboard turns each one into a no-op store write (RC9).

**Root cause.** The outbox treats delivery as a polling, ack-per-batch job, with a fixed small
batch and an idle sleep. Event design never decided *which* granularity is the contract, so both
granularities are published to everyone.

**Fix direction**

- Raise the batch to about 1,000, pipeline produce with `linger.ms`, and delete IDs in the same
  call as the next read.
- Wake the outbox loop with an `asyncio.Event` set after each tick commit, instead of a 1 s sleep.
- Pick **one** contract per domain. Keep per-entity facts for transitions others actually react to
  (`on_carousel`, `collected`, `in_hold`, `flagged`). Move pipeline-internal hops
  (`inducted → screening → sorting → loaded`) to the batch/audit topic, or drop them.
- Remove `baggage.events` / `passengers.events` from cost-service's subscription. Filter by
  `event_type` before JSON-schema validation.

---

### RC4 — Open-loop clock + cross-domain reads of the shared graph ⇒ causality violations 🔴

**Evidence**

- In a 150 s window, **749 of 1,566 `departed_airport` transitions** (48%) were produced by the
  reconciliation sweep (`reconciliation_reason = "persisted_flight_state"`), not by the
  `FlightStatusChanged(departed)` handler. They arrived **1–64 sim-min after the departure**
  (median 7) and 7.5 s later in real time. Earlier, 262 of 627 `airborne → deplaning` transitions
  were also reconciliation-driven.
- Several services read Neo4j labels owned by another service:

  | Reader | Reads |
  | ------ | ----- |
  | flight-service | `Passenger` ×5 (`get_boarded_percentage` decides departure), `Baggage` ×3 |
  | passenger-service | `Flight` ×4 (every FSM query joins `f.status`) |
  | baggage-service | `Flight` ×4, `Passenger` ×8 |
  | sim-orchestrator | writes `Flight`, `Passenger`, `Baggage` directly |

**Root cause.** Two mechanisms combine.

1. **The clock never waits.** [`run_clock_loop`](services/sim-orchestrator/services/clock.py:199)
   emits on a fixed wall-clock cadence. A consumer that can't keep up (RC1/RC2) silently processes
   coalesced ticks (`delta_minutes` 2–3) and lags 3–5 sim-min. Nothing measures or bounds that lag:
   no watermark, no back-pressure, no "slowest owner" gate.
2. **Each service reads other domains' *current* graph state instead of the events it has
   consumed so far.** A lagging passenger tick at sim T−3 queries `Flight.status` as written by
   flight-service at T, which is ahead of the passenger consumer's position in `flights.events`.
   Results:
   - reconciliation "steals" transitions before their event arrives, and stamps them with the
     lagging tick's sim time, which can be *before* the flight event that caused them;
   - the event handler then finds no eligible passengers;
   - flight-service decides departure from Passenger nodes that are 3–5 sim-min stale.

   CLAUDE.md rule 1 forbids direct HTTP between services. Direct reads of another owner's Neo4j
   nodes are the same coupling through a different channel.

**Fix direction**

- Each consumer should make decisions only from the events it has consumed (its own projection),
  or from its own nodes. Example: passenger-service keeps a `flight_id → status` projection from
  `flights.events`. Flight-service gets boarding progress from a `BoardingProgress` /
  `PassengerStatusBatchChanged` event, not by counting Passenger nodes.
- Add a **tick watermark**: each owner publishes `TickProcessed(sim_time)`, and the orchestrator
  holds the next tick while the slowest owner is more than K ticks behind (or reports it as a
  first-class metric). That turns silent coarsening into visible back-pressure.
- Keep reconciliation as a restart-recovery path only (e.g. first N ticks after boot, or
  hourly). Never let it race the primary event path.

---

### RC5 — Passenger flow model produces impossible timelines 🔴

**Evidence** (graph, departures of 2024-07-07)

- Departure delay distribution: 0 min ×22, 1–14 ×16, 15–29 ×34, **30–59 ×113, 60+ ×31**.
  `delay_reason`: `boarding_incomplete` ×358 (avg 34.8 min), against 13 CTOT and 10 crew.
- Per-flight timelines (minutes relative to scheduled departure):

  | Flight | delay | security entry p50 / p95 | airside p95 | at_gate p95 | boarded p95 |
  | ------ | ----: | ------------------------ | ----------: | ----------: | ----------: |
  | KL187 | 88 | −45 / −45 | +66 | +130 | +131 |
  | AF328 | 90 | −44 / −42 | +131 | +136 | +137 |
  | BA815 | 30 | −44 / −43 | +42 | +47 | +49 |

  The whole flight enters security in the same minute.
- Of 33,904 passengers on 195 departed flights:
  - **3,903 (11.5%) boarded after their flight's `actual_time`**;
  - 1,615 cleared security after departure;
  - 3,592 reached the gate after departure.
- Effective no-show share: **0.08%** (max 1.6%), against `noshow_rate = 0.03`.

**Root cause**

1. **Step-function release.** `_advance_booked_to_checkin`
   ([consumer.py:1082](services/passenger-service/kafka/consumer.py:1082)) checks in a flight's
   *entire* cohort in the first tick after T-120. `_advance_checkin_to_security`
   ([consumer.py:1178](services/passenger-service/kafka/consumer.py:1178)) sends the entire cohort
   to security at T-45, capped only by a global 80 pax/min. Security drains at
   `lanes × 180 pax/h` (≈12 pax/min per terminal), so every flight dumps 150–260 pax into a queue
   that clears 12/min. The passenger SPEC contradicts itself: §3 specifies a
   `Beta(3,2)` show-up distribution over `[T-180, T-45]`, while the §2 transition table says
   "Batched — all pax on flight move together". The code follows the table.
2. **Boarding isn't gated by the aircraft.** `_advance_boarding` explicitly bulk-boards everyone
   still `at_gate` when the flight is already `departed / airborne / taxiing`
   ([consumer.py:1525-1527](services/passenger-service/kafka/consumer.py:1525)).
   `FORWARD_FLIGHT_STATUSES` keeps moving airside passengers to the gate of a departed flight.
   There is no `missed_flight` outcome, so passengers board an aircraft that has left, and the
   reconciliation sweep later moves them to `departed_airport` (RC4).
3. **The 95% departure threshold depends on RC4 and RC5.** Flight-service departs when
   `boarded / total ≥ 0.95` ([state_machine.py:152](services/flight-service/services/state_machine.py:152)),
   read from Passenger nodes. With queues from (1), the 95% is rarely reached by T-0, so most
   flights fall through to the 30/60/90-min "grace" rules.
4. **The no-show draw runs on a partial cohort.** It fires once per flight, on the first tick any
   passenger of that flight is `at_gate` and boarding is eligible, and it samples only
   `pax_group`: the handful already at the gate. Then it marks the flight as drawn
   ([consumer.py:1487-1522](services/passenger-service/kafka/consumer.py:1487)).

**Fix direction**

- Implement the §3 arrival distribution: give each passenger a show-up time drawn at seed time,
  and let check-in and security transitions fire per passenger. Fix the contradictory SPEC row
  first (rule 6).
- On `FlightStatusChanged(departed)`, move non-boarded passengers to `missed_flight` (or
  `rebooking`). Don't board them afterwards.
- Draw no-shows over the full booked cohort at check-in close, not over whoever is at the gate.
- Make flight-service's boarding gate use a passenger-owned `BoardingProgress` fact (see RC4).

---

### RC6 — Baggage system under-dimensioned; deficit masked by teleport-to-hold 🔴

**Evidence**

- Departing bags whose trail contains a `loaded` scan / never had a `screening` scan:

  | Day | bags | % loaded | % **never screened** |
  | --- | ---: | -------: | -------------------: |
  | 2024-07-05 | 54,628 | 64.5% | 29.0% |
  | 2024-07-06 | 52,394 | 64.3% | 27.4% |
  | 2024-07-07 | 51,374 | 51.0% | 36.9% |

- Live stream (90 s, partly during an induction-A outage): `in_hold` transitions came from
  `loaded` 2,797, `inducted` 2,005, `screening` 430, `sorting` 210.
- Demand vs capacity. Departing bags per hour on 2024-07-07 peak at **4,906 (08h)** and
  4,624 (17h). Capacity from `ZONE_THROUGHPUT`
  ([conveyor.py:61](services/baggage-service/services/conveyor.py:61)) is
  induction 3×600 = 1,800/h, screening 6×300 = 1,800/h, sorting 1,800/h. Peak demand is
  **≈2.7× capacity**, and even the 18-hour operating average (~2,860/h) is above it.
- Live projection: `induction-A` 4,304 items, `induction-B` 2,911, `induction-C` 1,923, all at
  100% utilisation.

**Root cause.** Two specs were never sized against each other:

- `SIMULATION.md` uses Poisson λ = 1.2 bags/pax (about 52k bags/day);
- baggage `SPEC.md §3` sets throughputs that clear at most 1,800/h.

On top of that, induction only starts at T-90, and baggage-service itself runs at ~0.45 ticks/s
(RC2). The backlog is structural. It stays invisible because `_apply_departure_in_hold`
([consumer.py:1005](services/baggage-service/kafka/consumer.py:1005)) moves **every** bag still in
`dropped_off / inducted / screening / sorting` to `in_hold` when the flight departs, as a
documented "fast-track". Unscreened bags are reported as loaded, the `flight_baggage_not_loaded`
cascade fires only sometimes, and the KPIs look fine.

**Fix direction**

- Re-dimension. Either λ ≈ 0.7–0.9 checked bags/pax (closer to real-world averages) or about
  2.5× throughput (more induction points and screening units). Encode the check
  "peak hourly bags ≤ 0.85 × min-stage capacity" as a seed-time assertion or test.
- Replace the teleport with an honest outcome. Bags not `loaded` at departure become
  `short_shipped` / `offloaded`, emit `BaggageMissedFlight`, and never pass through
  `in_hold` unscreened. Count them as a KPI.

---

### RC7 — Seeder writes other domains' data, without links or events 🟠

**Evidence**

- Arrival bags on 2024-07-07: **39,975, of which 0** have `(:Passenger)-[:CARRIES]->(b)`.
- Arrival passengers' time in `baggage_claim`: p10 = 45, p50 = 46, p90 = 51 min, so all
  **33,335** left on the 45-min timeout. `PassengerRuntime.baggage_collected` is empty (len 0).
- **33,651 passengers are `airborne` on flights whose status is `scheduled`**: arrivals seeded at
  23:30 for the next day, before their flights departed origin. The data-source panel reports
  `airborne: 34,665`.

**Root cause.** `seed_day()` ([sim-orchestrator/services/seeder.py:35](services/sim-orchestrator/services/seeder.py:35))
generates arrival passengers (`generate_passengers(..., initial_status="airborne")`) and arrival
baggage (`generate_arrival_baggage`, by pax count × λ) **independently**, and writes both straight
into Neo4j. Bags have no passenger, so `_on_baggage_status_changed` in passenger-service
(`if new_status == "collected" and passenger_id`,
[consumer.py:2172](services/passenger-service/kafka/consumer.py:2172)) never matches. The
event-driven exit from baggage claim (SPEC: "BaggageStatusChanged (collected) OR timeout") can
never fire. The initial status hard-codes `airborne` regardless of the flight lifecycle. Seeding
emits only `FlightScheduleSeeded`: about 75k Passenger/Baggage creations per day happen without
events (rule 4).

**Fix direction**

- Generate arrival bags from the arrival passengers (one call, shared RNG) and create `CARRIES`.
- Seed arrival passengers as `booked` (or `expected`), and set `airborne` when the flight leaves
  `scheduled` (from `FlightStatusChanged`).
- Longer term, let the owning services create their own entities by consuming
  `FlightScheduleSeeded` (+ a `PassengerManifestSeeded` fact), instead of the orchestrator writing
  their labels.

---

### RC8 — One-shot triggers with no reconciliation; consumers start at `latest` 🟠

**Evidence**

- **39,969 arrival bags from 2024-06-29** are still `in_hold` on flights with status `arrived`.
  Every other day has 100% `collected`.
- Baggage arrival offload happens only in `_on_flight_status_changed` when
  `new_status == "at_gate" and previous_status in ("taxiing", "landed")`
  ([consumer.py:957](services/baggage-service/kafka/consumer.py:957)).
- `rebuild_from_neo4j` / `_prepare_tick` only restore bags in pipeline states. `in_hold` bags of
  arrived flights are never revisited.
- Every Python consumer is created with `"auto.offset.reset": "latest"`.

**Root cause.** Domain transitions that depend on another domain's event have no recovery path
when that event is missed: service down while it was produced, a new or expired consumer group
(`offsets.retention.minutes=10080`), or a handler that raised and got skipped. Passenger-service
grew a reconciliation sweep (which then caused RC4). Baggage-service has none. One bad day
therefore stays wrong forever, and it inflates RC1's history (these bags count as "in system").

**Fix direction.** Give each cross-domain trigger an idempotent catch-up driven by *consumed*
state, e.g. "arrival flights in my `flight_status` projection that are ≥ at_gate and still have
bags `in_hold`". Run it at startup and hourly. Use `auto.offset.reset=earliest` for owner groups.
The durable inboxes already make replays safe.

---

### RC9 — UI receives the firehose and re-renders for nothing 🟠

**Evidence**

- Gateway counters since start: `baggage` **1,110,763** and `passengers` 920,716 events
  forwarded, against 6,307 clock ticks, i.e. about 175 baggage events per tick per tab.
- [`fanOut`](services/api-gateway/src/websocket.ts:80) forwards every event of every subscribed
  topic. Throttling only applies in BULK mode. Each message is `JSON.parse`d, re-`stringify`d and
  sent. Any client whose `bufferedAmount` exceeds 256 KB is `terminate()`d, so a slow tab
  disconnects, reconnects and loses events.
- Dashboard handlers ([useWebSocket.ts](dashboards/art-dashboard/src/hooks/useWebSocket.ts)):
  - `BaggageStatusChanged` calls `useBaggageStore.updateZone(scanZone, {})`. That builds a **new
    `zones` array** (spread of an empty patch) and notifies every subscriber, about 280 times/s,
    with no change.
  - `PassengerStatusChanged` is an explicit no-op.
  - Each `FlightStatusChanged` invalidates `flights`, `gates` and `runways`, i.e. three REST
    refetches. `/api/v1/flights` averages 290 ms on flight-service.

**Root cause.** The gateway relays domain-internal events as a UI protocol. Since the UI already
takes aggregates from REST and the `*Snapshot` / `*BatchChanged` events, ~95% of WS traffic has
no consumer.

**Fix direction**

- Add a server-side allow-list per WS topic (snapshots, batch hints, alerts, flight status) and
  coalesce per ~1 s.
- Remove the `updateZone(…, {})` call, or make it return the same state when the patch is empty.
- Debounce `reconcileLiveQueries` by key over ~1–2 s instead of a microtask.

---

### RC10 — Data-source status is fabricated at the gateway 🟡

**Evidence** (`GET /api/v1/data-sources`)

- ADS-B: `current_source: "adsb.lol", status: "active"`, with `aircraft_count: 0` and
  `last_update: null`. The container has **`ADSB_ENABLED=false`**.
- Weather: `status: "active"`, `last_updated` = the HTTP request time. The weather state itself is
  `2024-07-07T21:00Z` while the clock is `2024-07-08T09:54`.
- Passengers: `total_passengers: 0`, with `zone_counts` that are actually status counts over all
  history (`departed_airport: 1,578,851`).
- Simulated flights: `last_updated` is a sim time while the others are wall-clock times.

**Root cause.** [`handleDataSources`](services/api-gateway/src/dataSources.ts:39) hardcodes
`status: "active"` and `last_updated: new Date()` whenever the upstream HTTP call succeeds, and
equates "the `/adsb-states` response has a `metadata` key" with "ADS-B active". The
`DataSourceAdapter` protocol ([_common/data_sources.py](services/_common/data_sources.py)) has
no `enabled`, `last_ingest_at`, `last_error` or `record_count` fields, so no service *can* report
real freshness.

**Fix direction.** Extend the adapter protocol with
`enabled / last_ingest_at (wall) / last_observation_at (sim) / last_error / items`, expose it from
each owner's `/source` endpoint, and have the gateway derive `active | stale | disabled | error`
from it. Label every timestamp's clock (sim vs wall).

---

### RC11 — Lag turns into a permanent stall: planner traps + coalesced catch-up + clock auto-pause 🔴 (found while deploying the fixes)

**Evidence.** At 08:27 (real time) the sim **paused itself**: `Clock checkpoint failed;
simulation paused`, caused by `Neo.TransientError.General.MemoryPoolOutOfMemoryError`. By then
passenger-service was **6 sim-hours behind** (checkpoint at 16:54 against a clock at 22:44), and
every one of its tick attempts failed with the same error: *"allocation of an extra 2.0 MiB would
use more than the limit 716.8 MiB"*. `SHOW TRANSACTIONS` showed one passenger transaction at
**713 MiB**, running `get_reconciliation_candidates`.

**Root cause (a chain).**

1. *Planner trap (RC1 again).* The reconciliation query was written to "bound reads by indexed
   passenger states", but the cost planner chose a `NodeHashJoin` from the **Flight** side. Every
   historical departure is in status `arrived`, so the join expanded about 1.5M passengers into
   memory. The baggage induction query had the same trap (2.6M db hits for 0 rows). As history
   grows, this kind of plan eventually exceeds `dbms.memory.transaction.total.max` (70% of a 1 GB
   heap), and that limit is **shared by every transaction in the database**.
2. *Coalesced catch-up.* A lagging consumer sees only the latest SimClockTick and applies the whole
   gap (here ~350 min) as one owner tick in one transaction. Each failed retry adds more lag, so
   the transaction keeps growing and never fits again: L2's infinite retry turns into a permanent
   stall.
3. *Shared pool → clock pause.* While passenger's transaction holds the pool, the orchestrator's
   tiny clock checkpoint gets `MemoryPoolOutOfMemoryError`. `run_clock_loop`
   ([clock.py](services/sim-orchestrator/services/clock.py)) responds to **any** checkpoint error
   with `pause()`, with no retry for transient errors. The whole airport stops until someone
   resumes it.

**Fixed:** both queries pinned with `CALL {}` subqueries, and catch-up split into ≤5-min ticks.
After redeploy, passenger replayed the 6-hour backlog with zero OOMs, and the sim was resumed via
`POST /api/v1/sim/resume`. In round 2 the clock checkpoint gained a transient-error retry, the
transaction pool was doubled (2G heap), and `seed_day` moved off the tick path (it had cost 19 of
60 ticks at 23:30).

---

## 3. Lower-severity findings

| # | Finding | Evidence / location | Why it matters |
| - | ------- | ------------------- | -------------- |
| L1 | `PassengerStatusChanged` is **randomly** sampled at 2% during *every* tick, REALTIME included (`set_tick_batch_mode(True)` each tick). Reconciliation events are never sampled | [passenger-service/kafka/producer.py:22,50](services/passenger-service/kafka/producer.py:50) | The per-passenger stream is non-deterministic across replays and dominated by reconciliation artefacts (766 of 1,336 sampled events). Any consumer counting it is biased |
| L2 | Poison messages block a consumer forever: `run_consumer_loop(manual_commit=True)` retries a failing dispatch every 100 ms without limit. Cost-service does the same every 1 s | [_common/kafka_runtime.py:219](services/_common/kafka_runtime.py:219), [cost-service/kafka/consumer.py:136](services/cost-service/kafka/consumer.py:136) | One bad payload freezes a whole domain. There's no DLQ or skip-after-N |
| L3 | No sim-time sanity check on inputs: cost-service accepted and inboxed two events with `sim_time = 2026-01-01T12:00:00Z` (18 months ahead of the clock) | `CostInbox` ids `266c7026…`, `83591c45…` | Test or foreign traffic on the live bus is accepted silently |
| L4 | analysis-service rebuild loads every bag not `delivered/collected` (≈1.22 M `in_hold`) into `baggage_targets`. The dict grows per event and is deep-copied for every what-if | [analysis-service/db/neo4j.py:172](services/analysis-service/db/neo4j.py:172), [whatif.py:129](services/analysis-service/services/whatif.py:129) | Memory and what-if latency grow with history (RC1) |
| L5 | Inbox markers (`CostInbox` 345k, one per SimClockTick, plus a `FinancialEventProcessed` fact per tick) are never pruned | `cost-service` ledger | Unbounded growth, Kafka noise |
| L6 | Gateway uses a fixed consumer group `api-gateway` with committed offsets: after a restart it replays the backlog to clients as if live. Stale group `api-gateway-ui-verification` sits about 450k messages behind | [api-gateway/src/kafka.ts:70](services/api-gateway/src/kafka.ts:70) | Bursts of stale events into the UI after a restart. A live relay should use a per-instance group at `latest`, or no group |
| L7 | Weather and incident events are produced directly, not through the outbox, so a DB write and its event aren't atomic. In `tick_ttr` the TTR update and the resolve are separate writes | [weather-service/kafka/producer.py](services/weather-service/kafka/producer.py), [incident-service/services/lifecycle.py:291](services/incident-service/services/lifecycle.py:291) | Self-healing in practice (observed a transient `active, ttr_remaining=0`), but breaks the "every state change ⇒ event" guarantee under crash |
| L8 | Mixed timestamp conventions: weather uses `…Z` (aware), most owners use naive ISO. The gateway mixes wall and sim clocks in one field | weather `/current`, data-sources payload | A recurring source of UI-side "wrong time" bugs (cf. commit `d77f0eb`) |
| L9 | Neo4j sizing: 512 MB page cache vs 5.7 GB store, 1 GB heap; tx-log retention `"2 days 2G"` while 11 GB is retained | neo4j container config | Amplifies RC1/RC2. Worth fixing only after them |

---

## 4. How the root causes chain together

```
RC1 history in hot indexes ─┐
                            ├─► baggage/passenger tick > 1 s ─► coalesced ticks, 3-5 sim-min lag ─┐
RC2 8.6 MB checkpoint/tick ─┘                                                                     │
RC3 outbox round-trips + double publish ─► +0.5-1.3 s per event, 340 msg/s firehose ─► RC9 UI     │
                                                                                                  ▼
RC4 cross-domain live-graph reads + open-loop clock ─► reconciliation races events, stale boarding %
RC5 step-function pax release ─► security waves ─► <95 % boarded ─► "boarding_incomplete" delays,
                                                   pax board departed aircraft
RC6 bags demand 2.7× BHS capacity ─► backlog ─► teleport to hold (unscreened "loaded" bags)
RC7 seeder w/o links ─► arrival "collected" never fires, phantom "airborne" pax
RC8 no catch-up path ─► one missed event = permanently wrong entities (feeds RC1)
RC10 fabricated source health ─► "active" sources that are disabled/stale
```

## 5. Suggested order of work

1. **RC2 quick wins** (~1 day): drop `inducted_bag_ids` from the checkpoint, skip the redundant
   restore/decode, remove the double deepcopy. Expected: baggage tick drops from ~1.5 s to a few
   hundred ms, and lag drops to under 1 tick.
2. **RC1 quick wins**: stop per-tick `count()` gauges, add a time window to the dropped-off
   query. Then add archival/retention of finished entities and inbox pruning.
3. **RC6 + RC5 model fixes** (spec first): size bag volume against BHS capacity; implement the
   Beta show-up curve; add `missed_flight` / `short_shipped` outcomes and remove the teleports.
4. **RC4**: replace cross-domain graph reads with event-fed projections; add a tick watermark
   metric, then back-pressure.
5. **RC7/RC8**: link arrival bags to passengers; add owner-side catch-up sweeps; switch owner
   groups to `earliest`.
6. **RC3/RC9/RC10**: outbox batching and wake-up, one event granularity per domain, WS allow-list
   and coalescing, adapter-reported source health.

## 6. Reproducing the measurements

- Topic rates: `kafka-run-class kafka.tools.GetOffsetShell --time -1` twice, 30 s apart.
- Latency: a throw-away consumer on all topics. Map `sim_time → SimClockTick.produced_at`, then
  compare each event's `produced_at` with the Kafka message timestamp.
- Hot queries: sample `SHOW TRANSACTIONS YIELD clientAddress, currentQuery, elapsedTime` every
  20 ms for 40 s and aggregate by client IP and query prefix.
- Checkpoint cost: inside the owner container, read `s.document`, then time `codec.restore`,
  `deepcopy` of `codec.fields`, and `codec.dump`.
- Correctness: the Cypher in each finding, run against the live graph (all read-only).

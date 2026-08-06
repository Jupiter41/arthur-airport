# Roadmap to a Real Living Digital Twin (LDT)

> Principal-architect / product-CTO review of the Arthur International Airport digital twin, and a
> pragmatic transformation plan to evolve it from a **facade of an LDT** into an **operational LDT**
> with a closed descriptive → predictive → prescriptive → actionable loop.
>
> Scope reviewed: whole repo (~44k LOC Python across 9 services, ~28k LOC React/TS, Neo4j + Kafka +
> observability, 178 markdown docs). File/line references are as-observed at review time; treat them
> as pointers, not guarantees after refactors land.

---

## 0. Framing — this is not "just a dashboard"

The most important correction to the usual framing: this platform already *reaches for* the full
analytics ladder. `AUTONOMOUS_OPS.md` documents four autonomy modes, 14 operational actions, an RL
agent, and an LLM layer. `analysis-service`, `cost-service`, and `planning-service` exist
specifically as intelligence/action layers.

The real problem is subtler and more dangerous than "add prediction": **the intelligence and action
layers are largely theatrical, and the loop never closes.** Concretely:

- The event bus is **facts-only by design** (`EVENT_BUS.md §1`: "Events are facts, not commands").
  There is **no command channel**. When the autonomous engine "applies" an action,
  `analysis-service/services/autonomous.py` only marks it `applied` and emits an event — **nothing
  consumes that to mutate flight/pax/baggage state.** The corrective loop is open.
- The UI "Apply" button on recommendations (`IncidentConsole/RecommendationFeed.tsx:99-125`) is a
  **fake** — it runs a what-if projection and `// silently ignore — projection-only`.
- The RL agent ships **no model** (`rl_policy.zip` absent) so `predict_action` returns a no-op; the
  forecast-training endpoint is a **stub that instantly reports "completed"**; planning's LightGBM
  models are decorative (the heuristic fallback is the real path, and the training data has the
  label equal to a feature).
- `flightsApi.hold/release` and `incidentsApi.contain/resolve` **exist but are wired to no UI**.

So the transformation is not primarily "build AI." Most AI plumbing exists. It is: **close the loop,
make the numbers trustworthy, and unify the duplicated concepts into one twin.** That is a more
tractable — and more valuable — program than a rewrite.

---

## 1. Architecture Assessment

### 1.1 Pattern & topology (as-built)

Event-driven microservices, graph DB as source of truth, Kafka backbone, thin Node gateway, React
SPA. The intended contracts (`OVERVIEW.md`, `EVENT_BUS.md`, `DATA_MODEL.md`) are genuinely good and
mostly honored.

```
                          React SPA (dashboards/art-dashboard, ~28k LOC, 18 routes)
                          Zustand stores (WS-fed)  +  TanStack Query (REST-polled)  <- DUAL state, hand-synced
                                    | REST + WS
              +---------------------v----------------------+
              |  api-gateway (Node/Express/ws :3000)        |  auth = STUB (dev backdoor, hardcoded JWT secret)
              |  proxy - aggregate - rate-limit - WS fan-out|  ZERO tests
              +--+-----------------------------------+------+
        HTTP proxy (allowed exception)          Kafka consume (read-only)
   +-------+-------+-------+-------+-------+-------+-------+-------+
   v       v       v       v       v       v       v       v     v
 flight   pax   baggage weather incident simOrch analysis cost planning
 :8001   :8002  :8003   :8004   :8005   :8006   :8007   :8008  :8009
   |       |       |       |       |       |       |       |      +- NO Kafka/Neo4j; in-memory globals; offline MC+DCF
   |       |       |       |       |       |       |       +-------- consumes 5 topics; NO idempotency; dual-entry $$
   |       |       |       |       |       |       +---------------- consumes; emits "applied" events NOBODY executes
   +-------+-------+-------+-------+-------+-------+
   each = a vertical slice re-implementing the SAME transport layer
   (Neo4j driver, Kafka producer/consumer, envelope, sim-clock parse, logging/tracing/profiler = 6-7 identical copies)
                                    |
                    +---------------v----------------+     +-----------------------------+
                    |  Kafka (10 topics, facts-only) |     | Neo4j (single source truth) |
                    |  NO *.commands topic <- blocker|     | (planning-svc bypasses it)  |
                    +---------------+----------------+     +-----------------------------+
                                    |
                    Prometheus + Grafana + Loki + Jaeger (profiled; cost/planning /metrics NOT scraped)
```

### 1.2 Strengths (keep these)

- **Contract-first discipline is real and rare.** The spec docs (`EVENT_BUS.md`, `DATA_MODEL.md`,
  `SIMULATION.md`) are high quality: common event envelope, domain-scoped topics, DLQ convention,
  idempotency-by-`event_id`, schema-evolution rules. A solid backbone to build on.
- **Clean async boundaries.** The "no service-to-service HTTP" rule is actually respected (verified
  in the gateway and services). Domain decoupling is genuine.
- **Config-driven airport identity.** `config/airport.yaml` + `HOW_TO_CREATE_AIRPORT.md` +
  `scripts/helper_validate_airport_config.py` is a strong Open/Closed foundation (partial — see §3).
- **`_common/` and `_template/` exist** — the team already recognized the DRY problem and built the
  shared library. It is under-adopted, but the intent and the seams are there.
- **Deployment maturity beyond a portfolio toy:** Kustomize-based `k8s/` (base + infrastructure +
  services), CI with lint/unit/integration/docker/e2e stages, load tests (`tests/load/*.js`), a
  data-source adapter system for sim-vs-real.

### 1.3 Weaknesses (the load-bearing problems)

1. **No command/action channel — the loop is open.** Facts-only Kafka means recommendations can
   never become actions within the current bus. #1 blocker to an operational LDT (see §4.3, §6).
2. **Transport logic is duplicated 6–7× and fused with domain logic.** Every `db/neo4j.py`
   (`init/close/get_driver/check/wait/create_constraints`) is byte-identical across 6 services;
   every Kafka producer rebuilds the same envelope dict; every `kafka/consumer.py` re-implements the
   run-loop, `_validate_envelope`, `_dispatch`, and the `sim_time = datetime.fromisoformat(...)` line
   (verbatim at flight:349, pax:437, baggage:257, weather:635, incident:328). `_logging.py` /
   `_tracing.py` / `_profiler.py` are md5-identical in all 7 locations. Meanwhile `_common/events.py`
   and `_common/infra.py` — which solve exactly this — are imported by **nobody**.
3. **God-module consumers.** Each `kafka/consumer.py` fuses transport + global mutable state + the
   domain pipeline. `flight-service/kafka/consumer.py` is 1,457 LOC; `passenger-service` is 1,670 LOC
   running a 12-step `_on_clock_tick`; `analysis/consumer._on_tick` and
   `cost_engine.on_flight_status_changed` (~180 lines) are the same anti-pattern. Domain rules cannot
   be unit-tested without Kafka + Neo4j (DIP violation).
4. **`sim-orchestrator` is a 10-concern monolith** (clock authority + static seeding + schedule gen +
   pax gen + baggage gen + BTS calibration + scenario engine + injection + multi-airport network/GDP
   + snapshot/restore). Both a producer and a consumer; owns unrelated lifecycles.
5. **No canonical domain model.** Business rules are copy-pasted and *divergent*: `WIDE_BODY_TYPES`
   has 4 types in `cost_engine.py:27` but 6 in `carbon_tracker.py:32` (a B748 is billed "narrow" but
   emits as "wide"); EU261/fee constants live in both `_common/finance_constants.py` and
   `cost_rates.json`; peak hours `[7,8,9,17,18,19]` are hardcoded in 4 files; walking speed
   `84.0 m/min` in 3. There are **two recommendation engines** (cost vs analysis) and **three
   action-effect simulators** (planning MC, analysis what-if, RL env) modeling the same 14 actions.
6. **Trust defects in the intelligence layer.** planning-service: adding a runway has **zero
   throughput effect** (`simulation.py:392-396` no-op branch + `RUNWAY_CAPACITY` capped at 2), and
   `missed_connections`/`max_cascade_depth` are **structurally always 0** yet `benefit_extractor.py:88`
   monetizes missed-connections into NPV for an €800M decision. Worse than missing — confidently wrong.
7. **Persistence & money integrity.** planning-service keeps scenarios/audit in module-global dicts
   (`scenarios/model.py:111`) despite the docstring claiming Neo4j — violates architecture rule #3 and
   returns 404 under multi-worker. cost-service has **no idempotency** in its consumer *and* uses
   dual-entry records, so Kafka redelivery **double-counts revenue and cost**.
8. **Security is a stub that's dangerous by default.** `auth.ts:16` accepts **any credentials when
   `NODE_ENV !== "production"`**; `JWT_SECRET` defaults to `"art-digital-twin-dev"`; every token is
   `role:"operator"` (no RBAC). Fine for a demo, fatal the moment this touches anything operational.

### 1.4 Accidental vs essential complexity

- **Essential:** Kafka + Neo4j + cascade modeling + simulation clock. Justified by the domain.
- **Accidental:** the dual frontend state system (Zustand-via-WS *and* TanStack-Query-via-REST,
  reconciled by ad-hoc `useEffect` copies); three what-if engines; two recommendation engines; the
  6× copied transport layer; the doc sprawl (178 md files, 80 sprint logs, 5 overlapping roadmaps, a
  *nested* `docs/old/lessons-learned/`, committed Azurite artifacts `AzuriteConfig` and
  `__azurite_db_table__.json` that are not even part of the stack).

---

## 2. Duplicate Logic (prioritized)

| # | Duplication | Where | Why it happened | Business impact | Consolidation |
|---|---|---|---|---|---|
| D1 | **Transport layer** (Neo4j driver, Kafka prod/cons, envelope, sim-clock parse) | 6 × `db/neo4j.py`; 6–8 × `kafka/producer.py`+`consumer.py`; `_logging/_tracing/_profiler` ×7 | Services scaffolded by copy before `_common` matured; `_common.events`/`infra` never back-adopted | Every bus/DB change = 6+ edits; drift already happening | **HIGH.** Promote to `_common`: `neo4j_client`, `kafka_runtime` (loop+validate+dispatch+sim-clock), `EventEnvelope` producer path, `_logging/_tracing/_profiler`. Delete copies. |
| D2 | **Financial constants** | `_common/finance_constants.py` vs `cost-service/fixtures/cost_rates.json` vs `planning-service/adapters/simulation.py:15` | Live engine wanted editable JSON; planning wanted static constants | Rate changes silently diverge; planning appraises against stale numbers | **HIGH.** One source: JSON authoritative, `finance_constants` loads/validates; planning imports same loader. |
| D3 | **`WIDE_BODY_TYPES` / `_aircraft_family`** | `cost_engine.py:27` (4) vs `carbon_tracker.py:32` (6) | Copy-paste, edited independently | **Wrong money & wrong CO₂** for B748/A380 | **HIGH, low effort.** Canonical aircraft registry in `_common`/config. |
| D4 | **Recommendation engines (×2)** | `analysis/services/recommender.py` + `cost/services/recommendations.py` | Cost team built its own rather than emit facts for analysis to reason over | Two inconsistent "brains"; UI queries both with nested try/catch (`AutonomousPanel.tsx:71-107`) | **MEDIUM.** cost-service emits *signals*; a single recommender ranks. |
| D5 | **What-if / action-effect simulators (×3)** | `analysis/whatif.py` · `planning/engine/simulation.py` · `analysis/rl/env._apply_action` | Each subsystem needed "what would this action do?" and built its own | Three divergent answers for the same 14 actions; RL trains against a toy that doesn't match reality | **HIGH (strategic).** One simulation/effect engine as a library, reused everywhere. |
| D6 | **Operational constants** (peak hours ×4, walking 84 m/min ×3, apron speed ×2, weather thresholds ×2, cascade-depth logic ×2) | see §1.3(5) | Local convenience | Tuning an airport = grep-and-hope | **MEDIUM.** Externalize to `airport.yaml`, load via `_common`. |
| D7 | **Frontend normalization / dual state** | `normalizeWeatherResponse` (`useApi.ts:25-71`) duplicated in `weatherStore.updateFromEvent`; duplicate query keys; 909-line `useApi.ts`; 4565-line `destinationCoordinates.ts` | Server payload shapes inconsistent; WS + REST both feed same domains | Fragile sync bugs, payload-shape whack-a-mole | **MEDIUM.** Fix payloads server-side; one state source per domain. |
| D8 | **Dead duplicated models** | `baggage-service/models/{domain,events}.py` (unimported; re-declares `EventEnvelope`); `flight models/domain.py` missing `diverted` though FSM emits it | Left behind during refactors | Confusion, false sense of typing | **LOW effort.** Delete or wire to `_common.events`. |

---

## 3. SOLID Review

**Single Responsibility — the dominant violation.**
- Every `kafka/consumer.py` is a god-module (transport + state + domain pipeline). Worst:
  `passenger-service` (6 domains — FSM, security, LightGBM, PRM/SLA, connections, BTS ingest — in one
  1,670-LOC file), `sim-orchestrator` (10 concerns), `flight-service` (1,457 LOC with a stochastic
  noise model embedded).
- `routers/planning.py` (837 lines) runs business logic across "7 phases" inside a controller with
  ~40 function-local imports.
- **Fix:** extract pure domain services (already partly done — `state_machine.py`, `runway_queue.py`,
  `cascade.py` are clean); make the consumer a thin adapter calling
  `DomainService.handle(event, clock) -> [Effect]`.

**Open/Closed — partial.** Adding an airport works via `config/*.yaml`, but adding one *fully* still
requires editing in-service JSON fixtures (`sim-orchestrator/fixtures/*`, `cost-service/fixtures/*`)
and hardcoded Python (`finance_constants.py`, the constants in §D6). Adding a *new operational action*
requires touching all three effect simulators (D5). Adding a *new decision rule* means editing the
hand-coded `recommender.py` switch. **Fix:** externalize rules to config/a rule engine; single effect
engine; action registry.

**Liskov — mostly N/A** (little inheritance), but the `DataSourceAdapter` protocol has adapters that
lie: `opensky` returns `[]`, planning's provider-named adapters call no live APIs. Substitutability is
nominal, not behavioral.

**Interface Segregation.** The gateway's `/api/v1/airport` aggregate and the 909-line `useApi.ts` are
fat client contracts. `health.ts` `SERVICE_KEYS` omits cost/planning/analysis — the health interface
under-reports reality.

**Dependency Inversion — systematically violated.** Domain logic depends *directly* on Neo4j + Kafka
+ FastAPI globals. `cost_engine._write_and_emit` couples every handler to both stores;
`analysis._on_tick` runs the domain pipeline inside the Kafka adapter; module-global mutable
singletons (`_state`, `_running_totals`, `active_bottlenecks`) are everywhere and routers reach into
consumer privates (`routers/flights.py:197` → `kafka.consumer._state`; `routers/costs.py:199` →
`from kafka.consumer import set_rates`). **This is why the codebase is hard to test** (integration
tests need the full stack; the idempotency "unit test" re-implements the validator rather than
exercising real consumers). **Fix:** ports & adapters (§4.1).

---

## 4. Target Architecture (evolution, not rewrite)

The *macro* architecture (event-driven microservices + graph + gateway) is right. The fixes are
**internal to services** plus **two new seams** (command bus, approval workflow). No re-platforming.

### 4.1 Per-service: Hexagonal / Clean core

Refactor each service into three layers, reusing the modules that are *already clean*:

```
service/
  domain/      <- pure: FSM, rules, calculations (already exists: state_machine.py, cascade.py, runway_queue.py)
               <- returns Effects (events/commands/db-writes) as data, no I/O
  application/ <- handle(event, clock_state) -> [Effect]; orchestration only
  adapters/    <- neo4j_repo, kafka_in, kafka_out, http (thin; import from _common)
```

`_common` becomes the enforced runtime (promote the dead code): `neo4j_client`, `kafka_runtime`
(loop + `_validate_envelope` + dispatch + sim-clock state), `EventEnvelope` (all producers route
through it), `_logging/_tracing/_profiler`, `IdempotencyTracker` (mandatory for **all** consumers,
not 3 of 7). **Business justification:** transport changes become one edit; domain logic becomes
unit-testable without containers; new services scaffold correctly from a fixed `_template`.

### 4.2 Digital Twin Core (canonical model + rule engine)

Today there is no single twin — each service owns a slice and duplicates constants. Establish:
- **Canonical domain model** in `_common` (or a `twin-core` package): `Flight`, `Gate`, `Runway`,
  `Passenger`, `Baggage`, `Incident`, `Aircraft` (with the *one* wide-body classification), plus
  value objects for the constants in D3/D6. Neo4j stays the persisted projection; the model is the
  shared vocabulary.
- **Externalized rule/parameter set** sourced from `airport.yaml`/`config/`: peak hours, walking
  speeds, capacity tables, cost/carbon factors, SLA targets, cascade rules. Finishes Open/Closed — a
  new airport or scenario is config, not code.

### 4.3 Action Layer — the missing seam (highest business value)

Introduce **commands** alongside facts, without breaking the facts-only philosophy for domain events:

```
Recommendation (analysis)                        Approval Queue (new)
      |  emits ActionProposed (fact)      human -- approves -->  ActionApproved (fact)
      v                                                              |
  operator UI  -- manual "Apply" (real) ---------------------> *.commands topic (NEW)
                                                                     |  e.g. flights.commands: {HoldFlight, ReassignGate}
                                                          +----------v-----------+
                                                          | owning service        |  validates, executes,
                                                          | command handler (new) |  then emits the usual FACT event
                                                          +----------+-----------+
                                                                     v  FlightStatusChanged (unchanged)
```

- `{domain}.commands` topics (`flights.commands`, `passengers.commands`, …), owned/consumed only by
  the domain that owns the entity. Commands are validated intents; the resulting **state change still
  emits the existing fact event** — so the whole existing consumer graph and audit trail keep working.
- An **Approval workflow** service (or module in analysis): proposals → queue → human approve/reject →
  command. This is exactly what `AUTONOMOUS_OPS.md` already promises ("GDP always requires human
  approval") but the UI never delivers. `SAFETY_GUARDED_ACTIONS` becomes real.
- **This single seam turns L4 (display-only recommendations) into L5 (actionable ops)** and closes
  the autonomous loop. It also makes `record_outcome` (currently dead) meaningful — you can measure
  predicted-vs-actual, which the Planning Audit tab already wants to do.

### 4.4 Intelligence Layer — one engine, trustworthy numbers

- **Unify the three what-if simulators (D5)** into one `simulation-core` library: a pure
  `apply(actions, state, horizon) -> projected_state`. planning-service (Monte Carlo wrapper),
  analysis what-if (single-shot), and the RL env all call it. Biggest correctness win — one place to
  fix, one place to validate.
- **Fix the trust bugs before adding models:** runway-count capacity scaling (`simulation.py:392`),
  increment `missed_connections`/cascade depth (or stop monetizing them), remove fabricated
  RL/forecast progress. A prescriptive engine on wrong numbers is a liability.
- **Single recommender** consuming signals (including cost signals) with a real ranking
  (impact × confidence ÷ cost), not confidence-only sort.
- Keep the genuinely-working pieces: IsolationForest anomaly detection, the slot MILP (PuLP/CBC), the
  DCF math, the LLM narration layer (note: it is Mistral/OpenAI-compatible, **not** Claude — a
  candidate for upgrade given the AI-application context).

### 4.5 Data Platform

Neo4j stays the write model / projection. Add a lightweight **historical store** for the intelligence
layer (planning already reads CSVs; formalize a time-series/Parquet lake for training + audit) so the
twin has memory. planning-service must **stop using in-memory globals** and persist to Neo4j (or
Postgres) — a rule-#3 violation and a multi-worker correctness bug today.

**Patterns recommended / rejected:**
- ✅ Hexagonal per service (testability), **command bus** (close the loop), **rule/parameter
  externalization** (Open/Closed), an **approval workflow engine** (a small state machine, not
  Temporal-scale).
- ✅ **CQRS-lite** naturally emerges (writes via commands → facts; reads via Neo4j projections). Do
  not over-formalize it.
- ❌ **Event sourcing** — not justified; Kafka + Neo4j projections already give replay/audit. Adding
  an event store is architecture-astronautics here.
- ❌ SpacetimeDB (ADR-005) — leave as a documented option; do not act on it.

---

## 5. Simplification Opportunities (be aggressive)

1. **Collapse the dual frontend state.** *Complex because* every overlapping domain lives in both
   Zustand (WS) and TanStack Query (REST), reconciled by `useEffect` copies
   (`IncidentConsolePage.tsx:54-64`, etc.). *Simplify:* one source per domain — WS-driven store as
   truth, Query only for non-realtime (planning, history). *Benefit:* kills a class of sync bugs,
   shrinks `useApi.ts` (909 lines).
2. **Delete duplicated transport by promoting `_common`.** Removes thousands of copy-paste lines and
   6× drift risk. *Benefit:* faster, safer changes; onboarding drops from "learn 6 copies" to "learn 1."
3. **Split `sim-orchestrator`.** Extract at minimum a `clock` service (or module) from the
   seeding/scenario/network/snapshot concerns. *Benefit:* the clock is safety-critical (all services
   depend on it) and should not share a deploy with a scenario test-engine.
4. **Retire the doc sprawl.** 178 md files, 80 sprint logs, 5 overlapping roadmaps, nested
   `docs/old/lessons-learned/`, ~18 root docs. Move `lessons-learned/` and `old/` out of the working
   tree (archive branch/wiki); keep a single `docs/architecture/` + `ROADMAP.md` + `README.md`. Delete
   committed `AzuriteConfig` / `__azurite_db_table__.json` (not part of the stack) and gitignore
   caches. *Benefit:* the docs stop lying (CHANGELOG stops at Sprint 10 while sprints reach 52; the
   service map omits planning-service; `analysis.events` isn't in the topic catalogue).
5. **Delete dead/fake code that implies capability it doesn't have.** The no-op RL path, the
   forecast-training stub that reports "completed", the never-wired `/perf` profiler,
   `_apply_overrides()` (weather, defined-never-called), dead `db/neo4j.py` query helpers in analysis,
   dead model files in baggage. *Benefit:* the codebase stops advertising features that don't work —
   critical for trust in an ops tool.
6. **One recommender, one what-if engine** (§4.4/D5). *Benefit:* one behavior to reason about and
   validate.

---

## 6. Dashboard → Operational Capability Transformation

Current reality: live-ops surfaces are **L1–L2**; there is real **L3** (anomaly detection, at-risk
connections, demand forecast, counterfactual); **L4** prescriptive output exists but is **almost
entirely display-only**; genuine **L5** exists only for *simulation control* and *incident injection*
(a test affordance) plus a backend autonomy toggle whose actions bypass the UI and execute nothing.

Levels: L1 viz · L2 monitoring/alerts · L3 prediction · L4 prescriptive · L5 autonomous/actionable.

| Capability | Now | Descriptive | Predictive | Prescriptive | Actionable (target) |
|---|---|---|---|---|---|
| **Flight ops** (FlightBoard) | L2 | delays, runway throughput | ETA/CTOT already modeled | "reassign gate B07→C12 saves N min" | **Wire `hold/release` + `reassign` → `flights.commands`** (endpoints exist, no UI) |
| **Passenger congestion** | L3 | zone heatmap, queue depth | LightGBM 90-min forecast (real) | "open lane 4 / redirect check-in" | Propose→approve→`passengers.commands: open_security_lane` |
| **Connections** | L3 | at-risk list | MCT breach prediction (real) | "hold connecting flight AX / fast-track pax" | `hold_connecting_flight` command + notify |
| **Baggage** | L2 | conveyor map | (add) make-up backlog forecast | "reroute to belt 3 / expedite loading" | `baggage.commands: redirect_baggage` |
| **Incidents** | L2→L5 uneven | cascade tree | cascade projection | protocol recommendation | **Wire `contain/resolve` (exist, no UI)**; make "Apply" real |
| **Cost / EU261** | L4 display | live P&L | EU261 exposure trend | financial recs w/ payback | Link recs to the operational command that realizes the saving |
| **Autonomy** | L5 backend, no effect | action log | confidence scores | ranked actions | **Approval queue UI + command execution** so "applied" actually applies |

The pattern the LDT vision asks for — *"Congestion in 45 min → open gate X → auto-execute after
approval"* — is **90% built**: forecast (real), recommendation (real), the `open_security_lane` action
(defined). What is missing is the last 10%: the command topic, the execution handler, and the approval
UI (§4.3). That is the single highest-leverage product move in this repo.

---

## 7. Refactoring Roadmap

### Phase 0 — Stabilization (weeks 0–3) ✅ COMPLETE
**Objectives:** stop the bleeding; make numbers and money trustworthy; kill fake signals.
- ✅ Fix cost-service idempotency + double-counting (`kafka/consumer.py` add `IdempotencyTracker`; dedup
  dual-entry). *Affected:* `cost-service/kafka/consumer.py`, `cost_engine.py`. *(A1)*
- ✅ Fix planning trust bugs: runway capacity scaling (`simulation.py:392`),
  `missed_connections`/cascade increments or stop monetizing them (`benefit_extractor.py:88`). *(A2)*
- ✅ Reconcile `WIDE_BODY_TYPES` (D3); single finance source (D2). *(A3)*
- ✅ CI gaps: cost/planning deps missing from `unit-tests`; remove `|| true` on integration; add gateway
  tests; scrape cost/planning `/metrics`. *(A4)*
- ✅ Delete committed Azurite artifacts; gitignore caches; archive doc sprawl. *(A4)*
- **Complexity:** LOW–MED. **Deps:** none. **Value:** HIGH — cannot make decisions on a system that
  double-counts money and monetizes always-zero metrics.

### Phase 1 — Architecture Foundation (weeks 2–8, overlaps P0) ✅ PARTIAL
**Objectives:** kill duplication; invert dependencies; make domain logic testable.
- ✅ Promote to `_common` and delete copies: `neo4j_client`, `kafka_runtime`, `EventEnvelope` producer
  path, `_logging/_tracing/_profiler`; make `IdempotencyTracker` mandatory. Fix `_template`. *(A5 — pilot: flight-service)*
- ✅ Refactor consumers into thin adapters over pure `application.handle()` (start with flight + pax). *(A6 — partial: pure decisions extracted, full handle() inversion deferred)*
- Externalize D6 constants to `config/airport.yaml`.
- *Affected:* all `services/*/db|kafka`, `_common/*`, `_template/*`. **Complexity:** MED–HIGH.
  **Deps:** none (mechanical). **Value:** HIGH — every later change gets cheaper; unit tests become
  possible.

### Phase 2 — Digital Twin Core (weeks 6–12)
**Objectives:** one canonical model + one effect engine.
- Canonical entities + value objects in `twin-core`/`_common` (§4.2).
- **Unify the 3 what-if simulators (D5)** into `simulation-core`; rewire planning MC, analysis
  what-if, RL env. **Complexity:** HIGH. **Deps:** P1. **Value:** HIGH — correctness + coherence.
- Persist planning scenarios/audit to Neo4j (fix rule-#3 violation).

### Phase 3 — Intelligence Platform (weeks 10–16)
**Objectives:** one trustworthy recommender; real forecasting where claimed.
- Single recommender consuming cost/analysis signals with impact×confidence÷cost ranking.
- Either make RL/forecast real (train on the new historical store + `simulation-core` env) **or**
  remove the stubs and stop advertising them. **Complexity:** MED–HIGH. **Deps:** P2.
  **Value:** MED–HIGH.

### Phase 4 — Action Platform (weeks 14–22) ✅ PARTIAL
**Objectives:** close the loop — commands + approvals.
- ✅ Add `flights.commands` topic + command handler in flight-service (emit existing facts on success). *(A7 — flights only; other domains pending)*
- ✅ Approval-workflow service/module; wire `SAFETY_GUARDED_ACTIONS`. *(A9)*
- ✅ UI: real "Apply", approval queue, wire `hold/release` + `contain/resolve`. *Affected:* gateway
  (command routes), flight-service (handler), `analysis/autonomous.py` (emit commands), dashboard. *(A8, A9)*
  **Complexity:** MED (small per service, cross-cutting). **Deps:** P0–P3. **Value:** HIGH — this is
  the LDT.
- ✅ Harden auth (kill dev backdoor, real secret, RBAC) — prerequisite for real action execution. *(A10)*
- ✅ `passengers.commands` + passenger-service `OpenSecurityLane` handler.
- ✅ `baggage.commands` + baggage-service `RedirectBaggage` handler (Neo4j redirect + conveyor eviction + `BaggageStatusChanged` fact).
- `incidents.commands` and full-fleet command coverage deferred (no unsatisfied roadmap item).

---

## 8. Prioritization Framework

| Initiative | Business Value | Effort | Tech Risk | Priority | Reason |
|---|---|---|---|---|---|
| Fix cost double-counting + idempotency | HIGH | LOW | LOW | **P0** | Financial data corruptible on Kafka redelivery |
| Fix planning trust bugs (runway no-op, zero-metrics-into-NPV) | HIGH | LOW | LOW | **P0** | €800M decisions on confidently-wrong numbers |
| Reconcile WIDE_BODY/finance constants (D2/D3) | HIGH | LOW | LOW | **P0** | Wrong money & CO₂; one-source fix |
| CI/observability gaps (deps, `\|\| true`, gateway tests, cost/planning scrape) | MED | LOW | LOW | **P0** | Cheap; unblocks safe iteration |
| Command bus + approval workflow (close the loop) | **HIGHEST** | MED | MED | **P1** | Turns the whole L4 surface into L5; the actual LDT |
| Promote `_common`, delete transport copies | HIGH | MED | LOW | **P1** | Makes every later change cheaper; enables testing |
| Wire existing unwired actions (hold/release, contain/resolve, real "Apply") | HIGH | LOW | LOW | **P1** | Endpoints already exist; near-free L5 wins |
| Consumer → hexagonal (flight, pax first) | HIGH | HIGH | MED | **P2** | Testability + SRP for the god-modules |
| Unify 3 what-if simulators → simulation-core | HIGH | HIGH | MED | **P2** | Correctness + coherence for intelligence/RL |
| Persist planning state to Neo4j | MED | MED | LOW | **P2** | Fixes rule-#3 + multi-worker 404s |
| Split sim-orchestrator (extract clock) | MED | MED | MED | **P3** | Isolate safety-critical clock |
| Single recommender + real ranking | MED | MED | LOW | **P3** | One brain instead of two |
| Auth hardening + RBAC | HIGH (gates P4) | MED | LOW | **P3** | Required before real action execution |
| Remove/real-ify RL + forecast stubs | MED | HIGH | MED | **P3** | Stop advertising non-working AI |
| Doc consolidation + delete stray artifacts | MED | LOW | LOW | **P0-side** | Docs currently mislead |

---

## 9. Executive Summary

### Current state
A genuinely well-specified, event-driven airport digital twin with real depth — good Kafka/Neo4j
contracts, a config-driven airport, k8s deployment, real anomaly detection, a real slot MILP, real DCF
math, and a broad dashboard. But its **intelligence and action layers are largely a facade**:
recommendations are display-only, the "Apply" button is fake, the autonomous engine emits actions
nothing executes, RL and forecasting are stubs, and several planning numbers are confidently wrong.
Under the hood, the same transport layer is copy-pasted 6–7× and fused with domain logic, and core
operational concepts are duplicated and divergent across services.

### Future state
An **operational LDT** where the descriptive→predictive→prescriptive loop actually closes: a forecast
triggers a ranked recommendation, an operator (or the guarded autonomy engine) approves it, a
**command** executes against the owning service, the resulting fact flows through the existing bus, and
predicted-vs-actual outcome is measured and fed back. Internally: pure, testable domain cores behind
thin adapters; one canonical model and one simulation engine; parameters externalized so a new airport
or scenario is config, not code.

### The 5 biggest blockers
1. **No command/action channel** — the bus is facts-only, so no recommendation can ever become an
   action; the loop is structurally open.
2. **Transport duplicated 6–7× and fused with domain logic** — domain rules can't be tested, and every
   change touches everything (DIP violation, god-module consumers, `sim-orchestrator` monolith).
3. **No canonical domain model** — divergent constants and *three* action-effect simulators + *two*
   recommenders mean there is no single "twin," just correlated slices.
4. **Untrustworthy intelligence** — fake RL/forecast progress and monetized always-zero metrics; you
   can't run prescriptive ops on numbers that are wrong or theatrical.
5. **State/money/security fragility** — planning in-memory globals (rule-#3 violation, multi-worker
   404), cost double-counting on redelivery, and an auth stub that accepts any credentials off-prod.

### First 10 actions (exact sequence)
1. ✅ **DONE** — Add `IdempotencyTracker` to the cost-service consumer and eliminate dual-entry
   double-counting; add a test that redelivers a message and asserts no double-mutation.
   *(See Execution Log → A1.)*
2. ✅ **DONE** — Fix planning fidelity bugs: runway-count → capacity scaling (`simulation.py:392`),
   and either increment `missed_connections`/cascade depth or remove them from
   `benefit_extractor.py:88` NPV. *(See Execution Log → A2.)*
3. ✅ **DONE** — Collapse `WIDE_BODY_TYPES`/`_aircraft_family` and the finance constants to a single
   source (JSON authoritative, `finance_constants` + planning both load it). *(See Execution Log → A3.)*
4. ✅ **DONE** — Fix CI: add cost/planning deps to `unit-tests`, drop `|| true` on integration, add
   gateway tests, scrape cost/planning `/metrics`; delete `AzuriteConfig`/`__azurite_db_table__.json`,
   archive `docs/old` + `lessons-learned`. *(See Execution Log → A4.)*
5. ✅ **DONE** — Promote `neo4j_client`, `kafka_runtime`, `EventEnvelope`, `_logging/_tracing/_profiler`
   into `_common`; delete the copies from one pilot service (flight) end-to-end to prove the pattern.
   *(See Execution Log → A5.)*
6. ✅ **DONE (partial — see note)** — Refactor `flight-service` consumer into
   `adapters → application.handle() → pure domain`; land real unit tests for the FSM without
   containers. *(See Execution Log → A6.)*
7. ✅ **DONE** — Introduce `flights.commands` + a command handler in flight-service that executes
   `HoldFlight`/`ReassignGate` and emits the existing `FlightStatusChanged`/`FlightGateAssigned` fact.
   *(See Execution Log → A7.)*
8. ✅ **DONE** — Wire the already-existing UI actions: `flightsApi.hold/release` in FlightDetailDrawer,
   `incidentsApi.contain/resolve` in Incident Console, and make `RecommendationFeed`'s "Apply" a real
   server action (records + emits `AutonomousActionApplied`; concrete-command emission on
   `flights.commands` lands with A9's approval queue). *(See Execution Log → A8.)*
9. ✅ **DONE** — Build the approval-queue module + UI, and make `analysis/autonomous.py` emit
   `ActionProposed`/commands through it (activating `SAFETY_GUARDED_ACTIONS` and `record_outcome`).
   *(See Execution Log → A9.)*
10. ✅ **DONE** — Harden gateway auth (remove the dev backdoor, require a real `JWT_SECRET`, add
    operator/approver roles) so command execution is gated by identity. *(See Execution Log → A10.)*

Do 1–4 immediately (a two-to-three-week stabilization that removes correctness and money defects),
then treat 5–10 as the backbone of the LDT transformation. The macro-architecture is sound — the work
is closing the loop, unifying the concepts, and making the numbers honest, not rewriting.

---

## Execution Log

Records what was actually implemented and **how it was validated**. Only items with real,
reproducible test evidence are marked done. Anything that could not be validated in the current
environment (no full Kafka + Neo4j container stack available) is called out explicitly.

### A1 — cost-service idempotency + no double-mutation on redelivery ✅

**Status:** Done and validated (unit).

**Changes**
- `services/cost-service/kafka/consumer.py`
  - Imported `IdempotencyTracker` from `_common.idempotency`; added a module-level
    `_idempotency = IdempotencyTracker()` and a `reset_idempotency()` test helper.
  - Extracted the dispatch logic out of the poll loop into a testable
    `async def process_envelope(envelope) -> bool`. It checks `_idempotency.is_duplicate(event_id)`
    **before any dispatch**, so a redelivered `event_id` is dropped ahead of every cost/revenue
    state mutation. Returns `False` when a message is skipped as a duplicate, `True` otherwise.
  - `run_consumer()` now decodes → `mark_message()` → `await process_envelope(...)`; behaviour on
    the happy path is unchanged.
- `tests/unit/test_cost_consumer_idempotency.py` (new)
  - Drives the **real** consumer dispatch (`process_envelope`) with only the I/O boundary
    (Neo4j writes, Kafka emit) stubbed via monkeypatch — unlike the pre-existing
    `test_idempotency.py`, which tested the tracker in isolation and re-implemented the validator.
  - `test_redelivery_does_not_double_count`: same `event_id` twice → totals + Neo4j write count
    move exactly once; second call returns `False`.
  - `test_distinct_event_ids_both_processed`: control — two ids double the totals.
  - `test_empty_event_id_is_not_deduplicated`: empty ids are never collapsed.

**Validation**
- `pytest tests/unit` → **752 passed** (749 prior baseline + 3 new); full cost suite
  (`test_cost_engine`, `test_cost_p1_p2`, `test_cost_recommendations`, `test_idempotency`) still green.
- Mutation check: temporarily disabling the guard makes `test_redelivery_does_not_double_count` fail
  (`processed_second` becomes `True` and totals double) — confirming the test has teeth.

**Honest scope note — "dual-entry"**
The bug the roadmap flags (§1.3 / §7) is that *Kafka redelivery* double-counts revenue and cost
because there was no idempotency; that is now fixed and verified. The separate, first-delivery
modelling question — landing/passenger/gate fees each booked as **both** an airport cost and an
equal airport revenue (net-zero on the airport P&L) — is an intentional-looking accounting choice
with wide blast radius (dashboards, `by_category` cost signals, `recommendations.py` daily history).
Reworking the airport P&L model is deferred to the finance-model cleanup (A3 territory) and is **not**
claimed done here, since it cannot be validated without the dashboard + full stack.

### A2 — planning fidelity: runway-count capacity scaling + honest NPV ✅

**Status:** Done and validated (unit).

**Changes**
- `services/planning-service/engine/simulation.py` (`_tick`)
  - Replaced the no-op branch (`max_dep = max_dep` / `max_arr = max_arr`) with real
    runway-count scaling. Capacity now scales linearly by usable runways against the 2-runway
    baseline the per-category rates are calibrated for: good-visibility categories use every
    physical runway (adding/closing a runway moves throughput); low-visibility categories
    (`cap["runways"] < 2`) stay weather-bound and never scale *up* past the category limit.
  - Before: `runway_count` had **zero** effect on throughput — a "close a runway" scenario
    showed no impact, and a "new runway" scenario showed no benefit.
- `services/planning-service/finance/benefit_extractor.py`
  - Stopped monetizing `missed_connections` into the NPV. The simulation has no
    connecting-passenger / MCT model, so `missed_connections` is structurally always 0
    (declared + reported but never incremented). `missed_annual` is now held at `0.0` and
    excluded from `total_annual_benefit`; the field is kept for schema compatibility with a
    comment. (An always-zero — hence meaningless — line was previously presented as a real,
    quantified benefit in an eight-figure decision.)
- `tests/unit/test_planning_fidelity.py` (new, 4 tests)
  - `test_fewer_runways_reduce_throughput`: closing a runway (2→1) in CAVOK increases avg delay.
  - `test_capacity_is_monotonic_in_runways`: 1→2→3 runways never worsens avg delay.
  - `test_missed_connections_not_monetized`: a 100/day fake `missed_connections` delta moves
    neither the missed line nor the total.
  - `test_real_benefits_still_counted`: EU261 + delay + revenue improvements still flow through.

**Validation**
- `pytest tests/unit` → **756 passed** (752 prior + 4 new).
- Mutation check: reverting *both* fixes fails 3 of the 4 new tests — the runway test's delays
  collapse to equal, and `missed_connections_avoided_annual` jumps back to **€5,201,250** (proving
  the monetization was live and the assertions have teeth).

**Honest scope note — cascade depth & upward runway scaling**
`max_cascade_depth`/`cascade_depth` are also never incremented, but they are *not* monetized
(reported KPI only), so per the roadmap's "or remove them from NPV" they need no NPV change; a
real cascade model is deferred. Runway scaling *above* the 2-runway baseline is linear off the
category rate — modelling diminishing returns / independent-runway separation for 3+ runways is a
capacity-model enhancement, not a bug fix, and is left for later.

### A3 — single source of truth: aircraft body-class + finance constants ✅

**Status:** Done and validated (unit).

**What was actually wrong.** Two separate duplications:
- **Aircraft body-class had drifted.** `WIDE_BODY_TYPES` was copied into cost-service,
  carbon-tracking, planning-service and four flight-service modules — and the copies disagreed:
  cost-service listed `A359` but not `B748`/`A380`; planning/flight listed `B748`/`A380` but not
  `A359`; carbon-tracking listed the union. Net effect: a `B748` was wide-body for gate assignment
  but narrow-body for ground-handling cost, and an `A359` was wide for cost but narrow for gates and
  turnaround buffers — the twin disagreed with itself about the same tail.
- **Finance constants** were already half-consolidated: planning imports from
  `_common.finance_constants`, and the cost-service `cost_rates.json` fee values already matched it —
  but nothing *guarded* against them drifting apart again.

**Changes**
- `services/_common/aircraft_reference.json` (new) — canonical body-class lists (JSON authoritative):
  `wide_body_types` = the full union `[A332, A333, A359, A380, B748, B77W]`; `regional_types`.
- `services/_common/aircraft.py` (new) — loads the JSON once and exposes `WIDE_BODY_TYPES`,
  `REGIONAL_TYPES` (frozensets) and `aircraft_family(type) -> "wide"|"regional"|"narrow"`.
- Deleted the private copies and imported the shared symbols in:
  - cost-service: `services/cost_engine.py`, `services/carbon_tracker.py`
    (`_aircraft_family` now re-exported from `_common.aircraft`).
  - flight-service: `services/gate_resolver.py`, `services/turnaround.py`,
    `services/turnaround_plan.py`; removed a **dead** copy in `services/state_machine.py`
    (defined, never used). Updated the `SKILL.md` snippet to import rather than redefine.
  - planning-service: removed the dead `WIDE_BODY_TYPES` in `engine/simulation.py` (only its
    `SEAT_MAP` was used); already imports finance constants from `_common.finance_constants`.
- `tests/unit/test_aircraft_single_source.py` (new, 5 tests)
  - canonical set equals the full union; `aircraft_family` classifies `A359`/`A380`/`B748` as wide.
  - **identity** checks: flight-service and cost-service `WIDE_BODY_TYPES` are the *same object* as
    `_common.aircraft.WIDE_BODY_TYPES` (a redefined literal would be equal-but-distinct — and
    historically divergent), plus an explicit `"A359" in gate.WIDE_BODY_TYPES`.
  - finance drift guard: `cost_rates.json` `airport_fees` equal the `finance_constants` values.

**Validation**
- `pytest tests/unit` → **761 passed** (756 prior + 5 new).
- Mutation check: re-introducing the old private set (`{B77W, A333, A332, B748, A380}`, missing
  `A359`) in `gate_resolver.py` fails `test_flight_service_uses_the_canonical_set` with exactly the
  pre-A3 drift (`A359` absent); restoring the import returns the suite to green. The guard has teeth.

**Honest scope note.** The finance half was largely a no-op (values already agreed) — the real,
behaviour-changing fix was unifying the aircraft sets; the new test now *locks* both against future
drift. `MTOW`/seat/crew-count tables in `cost_rates.json` remain service-local domain data (not
shared constants) and were intentionally left in place.

### A4 — CI correctness + repo hygiene ✅

**Status:** Done and validated (each piece checked locally where possible).

**Changes**
- `.github/workflows/ci.yml`
  - `unit-tests`: now installs `cost-service` and `planning-service` requirements. Previously
    neither was installed — any cost/planning unit test that needed a real dependency would have
    errored in CI (they pass locally only because the dev venv has everything).
  - `integration-tests`: **dropped the `|| true`** that was swallowing every failure, and added
    `requests` to the install (every integration module does `import requests` at top). The suite is
    now honest: a real integration failure fails the job. When the app stack isn't up, each module's
    `pytestmark = skipif(not _service_reachable())` skips it — so the job stays green without hiding
    anything.
  - New `gateway-tests` job: `npm ci` + `npm test` for the api-gateway.
- `services/api-gateway` — first tests for the gateway:
  - `src/auth.test.ts` (9 tests) covering `handleToken` (400 on missing `client_id`; issues a
    verifiable JWT), `authMiddleware` (401 on missing token, 401 on wrong-secret token, `next()` on a
    valid token), and `verifyTokenFromRequest` (header token, `?token=` query token for WS upgrades,
    rejects malformed). Uses the **built-in `node:test` runner + `ts-node`** — no new npm
    dependency, so `package-lock.json` is untouched and CI's `npm ci` stays valid. (vitest was tried
    first but its fresh dependency resolution collided with the gateway's pre-existing OpenTelemetry
    peer-dep graph and broke `npm ci`; node:test avoids that entirely.)
  - `package.json`: added `"test": "node --require ts-node/register --test $(find src -name '*.test.ts')"`.
  - `tsconfig.json`: excluded `src/**/*.test.ts` from the build so tests never ship in `dist/`
    (ts-node still type-checks them at test time).
- `infra/prometheus/prometheus.yml` — added scrape jobs for `cost-service:8008` and
  `planning-service:8009` (both expose `/metrics` via `prometheus_fastapi_instrumentator` but were
  never scraped).
- Repo hygiene:
  - `git rm` the stray Azure Storage emulator artifacts `AzuriteConfig` and
    `__azurite_db_table__.json` (nothing in the stack is Azure — these were committed by accident),
    and added them plus `__blobstorage__/`, `__queuestorage__/`, `.azurite/` to `.gitignore`.
  - `git mv docs/old → archive/docs-old` with a new `archive/README.md`. `docs/old/` (20+ stale
    bring-up sprint notes + a stale *nested* `lessons-learned/`) had **zero** inbound references.

**Validation**
- YAML: `ci.yml` and `prometheus.yml` parse; asserted prometheus now lists `cost-service` +
  `planning-service`, `ci.yml` installs both requirements, contains no `|| true` on integration, and
  defines `gateway-tests`.
- Gateway: `npm test` → **9 passed / 0 failed**; `tsc --noEmit` clean; a throwaway `tsc` build
  confirmed no `*.test.js` leaks into `dist/`.
- Integration honesty: installed `requests` locally and ran `pytest tests/integration` with the stack
  **down** → **96 skipped, exit 0** (proves removing `|| true` won't turn CI red when the stack is
  absent, while still failing on a genuine error).
- `pytest tests/unit` → **761 passed** (unchanged).

**Honest scope note — what "archive lessons-learned" did *not* touch.**
The roadmap line reads "archive `docs/old` + `lessons-learned`", but the **top-level**
`docs/lessons-learned/` is an *active, heavily-referenced* directory (README, CONTRIBUTING,
PROMPT.md, `infra/README`, `scripts/README`, dashboard README, several roadmaps, and two test files
link into it; PROMPT.md instructs writing new lessons there). Archiving it would break dozens of
links and the documented workflow. The genuine sprawl was the *nested* `docs/old/lessons-learned/`
(old duplicates), which moved as part of `docs/old`. The active dir was deliberately left in place —
matching the roadmap's own framing (§Duplicate Logic calls out the *nested* copy specifically).
Two CI jobs still can't be exercised in-session (`docker-build`, `e2e-smoke-test`) as they need
Docker; they were left structurally unchanged and only reasoned about, not run.

### A5 — Promote transport layer into `_common` (flight = pilot) ✅

**Status:** Done and validated for the pilot service (flight-service). The four shared modules now
live in `_common` and flight-service imports them; its local copies are deleted.

**What was promoted (new files under `services/_common/`)**
- `_logging.py`, `_tracing.py`, `_profiler.py` — copied byte-for-byte from flight-service (the
  canonical originals), with only internal imports/doc examples rewritten to the `_common._*` path
  (e.g. `_logging.py` now does `from _common._tracing import get_trace_context`).
- `neo4j_client.py` — the generic async-driver lifecycle: `init_driver(...)` (all params default to
  the shared `NEO4J_*` env vars, so a bare `await init_driver()` reproduces prior behaviour),
  `get_driver()`, `close_driver()`, `check_connectivity()`. One `_driver` holder per process.
- `kafka_runtime.py` — the generic producer lifecycle + **the standard event-envelope contract**:
  `init_producer(name)` (acks=all, retries=3), `close_producer()`, `build_envelope(...)` (builds
  `event_id`/`event_type`/`schema_version`/`produced_at`/`sim_time`/`producer`/`payload` and injects
  OTel `trace_id`/`span_id` when present), and `produce_event(...)`.

**Flight-service converted to delegate (copies deleted)**
- Deleted `services/flight-service/{_logging,_tracing,_profiler}.py` (`git rm`).
  `main.py` now imports `from _common._logging import setup_logging`, `_common._tracing`
  (`init_tracing`/`shutdown_tracing`), `_common._profiler` (`get_perf_stats`).
- `db/neo4j.py`: driver lifecycle (`init_neo4j`/`close_neo4j`/`get_driver`/`check_neo4j` + the
  `wait_for_neo4j` cleanup) now delegates to `_common.neo4j_client`; the local `_driver` global is
  gone. The CONSTRAINTS/INDEXES and ~20 domain query functions stay local (service-specific).
- `kafka/producer.py`: `init_kafka_producer`/`close_kafka_producer`/`_produce_event` are now thin
  wrappers over `_common.kafka_runtime`; the inline envelope-building, `_delivery_report`, and the
  now-unused `json`/`uuid4`/`timezone` imports were removed. The flight-domain `emit_*` helpers and
  `check_kafka`/`wait_for_kafka` stay local. The file no longer contains `event_id` anywhere — the
  envelope contract lives entirely in `_common`.

**Test updated for the new envelope location**
- `tests/unit/test_event_chain_contracts.py`: the two "producer must include `event_id`/`sim_time`"
  contract tests were source-grep checks against each producer file. Added `_effective_envelope_source()`
  which, when a producer delegates (`kafka_runtime` in its source), concatenates
  `_common/kafka_runtime.py` so the contract is enforced wherever the fields are built. The other four
  services (still inline) are unaffected.

**Validation**
- `pytest tests/unit` → **761 passed** (was 1 failed on the stale envelope-grep assertion before the
  test update; green after).
- Import-smoke: `kafka.producer` and `db.neo4j` import cleanly with `_common` on path; asserted
  delegation identity (`producer.kafka_runtime is _common.kafka_runtime`,
  `db.neo4j.neo4j_client is _common.neo4j_client`) and that `build_envelope(...)` emits all seven
  required envelope keys.
- Mutation test (proves teeth): stripping `event_id` from `_common/kafka_runtime.py` makes the
  flight-service envelope assertion **fail** (flight's own `producer.py` has zero `event_id`
  references), and it passes again on restore — confirming the concatenation path is what carries the
  contract, not a leftover string.
- Grep-verified: no stale `from _logging/_tracing/_profiler` (local-path) imports remain in
  flight-service; the three local files are gone.

**Honest scope note.** This is the **pilot only**. The other nine producing/consuming services still
hold their own local `db/neo4j.py`, `kafka/producer.py`, and `_logging/_tracing/_profiler` copies —
the drift risk the roadmap flags (D1) is *reduced but not eliminated* until they are migrated the same
way. Nothing here was exercised against a live Neo4j/Kafka stack (none available in-session): the
delegation is proven by import-smoke, identity assertions, and the unit suite, not by a running
broker. `EventEnvelope` was promoted as the `build_envelope`/`produce_event` **producer path** (which
is what flight uses); the consumer-side validate/dispatch and sim-clock parse remain per-service and
are follow-on work when the remaining services migrate.

### A6 — Flight-service application layer + container-free decision tests ✅ (partial)

**Status:** Done for the pure/testable seam; the full `handle()` decouple is explicitly *partial*
(see the honest scope note) because it can't be integration-validated in-session.

**What the layers already were.** The *pure domain* was already isolated: `services/state_machine.py`
is a no-I/O 11-state FSM (`evaluate_transition`/`can_transition`), and it already had 56 unit tests in
`tests/unit/test_flight_state_machine.py`. The *adapter* is `kafka/consumer.py` (the Kafka loop,
envelope validate, dispatch, Neo4j reads/writes, event emits, WebSocket broadcast, in-memory state).
What was missing was a named **application** layer: the FSM-adjacent business rules were inlined inside
the 1,450-line consumer, tangled with I/O, and therefore only reachable through a live stack.

**Change — new pure `application` layer (`services/flight-service/application/`)**
- `application/decisions.py` — three decision functions extracted *verbatim* (behaviour-preserving)
  from `_process_flight`/`_execute_transition`, now pure (no I/O, no `_state`, no RNG):
  - `suppress_transition_for_turnaround(new_status, direction, *, deplaning_done, ready_for_boarding)`
    — the turnaround gate (arrival can't `arrived` before deplaning; departure can't `boarding`
    before ready).
  - `resolve_delay_reason(base_reason, *, is_held, hold_reason, runway_incident, gate_incident)` —
    the delayed-state reason priority (hold > runway incident > gate incident > existing >
    `operational`).
  - `boarding_delay_update(current_status, direction, scheduled, sim_time, boarded_pct, current_delay,
    current_reason)` — the incomplete-boarding delay accumulation, preserving noise-model reasons.
- `kafka/consumer.py` (the adapter) now *gathers inputs and delegates the decision* to these three,
  then performs the effects. The three inline blocks were replaced with calls; net behaviour
  unchanged.

**Change — real tests without containers**
- `tests/unit/test_flight_decisions.py` (26 tests) drives the three functions directly with plain
  values — no Neo4j/Kafka/state, no mocking. Covers turnaround gating (both directions + non-gated
  transitions + `None` status), reason priority (all five branches + missing-hold-reason default),
  and boarding delay (wrong-state/arrival/missing/unparseable/pre-schedule/complete no-ops, delay
  math, no-bump-when-not-greater, noise-reason preservation, datetime input).

**Validation**
- `pytest tests/unit` → **787 passed** (761 prior + 26 new; the 56 existing FSM tests unchanged).
- `python -m py_compile kafka/consumer.py` clean; import-smoke confirms the consumer imports
  `application.decisions`.
- Behaviour-preservation reasoning verified: all flight time fields are generated from the *naive*
  `sim_time` (validated at `consumer.py:349`, which strips tzinfo) via `.isoformat()`, so the pure
  parser's tz-strip is a no-op vs. the original inline `datetime.fromisoformat` — no comparison
  divergence.
- Mutation tests (prove teeth): (1) forcing turnaround gate to `False`, (2) widening the boarding
  0.95 threshold, and (3) dropping the runway-incident branch each made exactly the corresponding
  test **fail**; all restored green.

**Honest scope note — why "partial".** The literal roadmap item asks for a full
`adapters → application.handle() → pure domain` rewrite, i.e. a single pure `handle()` that returns a
*decision object* (target status + the list of facts/effects to apply) with the adapter reduced to a
dumb executor. That full inversion of a 1,450-line consumer touches deeply I/O-interleaved paths
(async Neo4j reads mid-decision: `get_open_runway`, `get_boarded_percentage`, `ensure_gate_assigned`;
stateful RNG noise draws that mutate `_state`; turnaround-plan creation/vehicle dispatch). Rewriting
that blind is only safe if proven by integration tests against a live Neo4j+Kafka stack — which is
**not available in-session**, so a full rewrite could not be honestly validated and was deliberately
not attempted. What was done instead is the safe, fully-validatable slice: the *named* application
layer now exists, the genuinely-pure decisions are extracted out of the adapter and unit-tested
without containers, and the pure domain (FSM) was already isolated. The remaining I/O-orchestration
in `_process_flight`/`_execute_transition` (runway/gate acquisition, noise draws, turnaround/vehicle
side effects) stays in the adapter and is the follow-on for when a live stack can validate the full
`handle()` inversion.

### A7 — `flights.commands` command channel + flight-service handler ✅

**Status:** Done and validated on the consumer (flight-service) side, which is A7's scope. Producers
(gateway UI actions, analysis approvals) are wired in A8/A9.

**Why a command topic.** Everything else on the bus is a *fact* ("this happened"). Operator/agent
*intent* ("hold this flight") had nowhere to go except the REST hold endpoint — which other services
can't see, and which bypasses the "cross-domain comms are async via Kafka" rule. `flights.commands`
is the single, auditable intent channel: gateway + analysis publish, **flight-service is the sole
consumer and authority**, and executing a command emits the *existing* facts on `flights.events`
(`FlightStatusChanged` for a hold, `FlightGateAssigned` for a reassignment). Downstream services keep
consuming only facts.

**Spec first (`docs/architecture/EVENT_BUS.md`)**
- Added `flights.commands` to the topic catalogue (§2, producers api-gateway + analysis-service, sole
  consumer flight-service, 1h retention) and the partition table (§3, 6 partitions keyed on
  `flight_id`, group `flight-svc`).
- New §4.8b documents the **command envelope** (keyed on `command_type`, not `event_type`;
  `command_id` for idempotency; `issued_by`/`issued_at` audit metadata; commands carry no sim time —
  the executor stamps facts with the current `sim.clock`), the two supported commands
  (`HoldFlight`, `ReassignGate`) with payloads and effects, and the rejection semantics.

**Pure application layer (`services/flight-service/application/commands.py`)**
- Typed commands `HoldFlight(flight_id, reason, duration_min)` and `ReassignGate(flight_id, gate_id)`.
- `parse_command(command_type, payload) -> (command | None, error | None)` — pure validation: unknown
  type, non-dict payload, missing/empty fields, non-positive/non-numeric/`bool` duration all rejected
  with a reason; accepts the legacy `expected_duration_minutes` key and numeric-string durations.
- `validate_hold_precondition(status)` — the holdable-status rule (`boarding`/`scheduled`/`approach`),
  mirroring the REST endpoint so both paths agree.

**Adapter wiring (`kafka/consumer.py`)**
- Subscribes to `flights.commands`. `_dispatch` routes any envelope carrying `command_type` to the new
  `_handle_command`, before the fact path (which needs `event_type`/`sim_time`).
- `_handle_command`: dedupes on `command_id` (same `IdempotencyTracker` as facts → at-least-once
  redelivery executes once), parses/validates, requires a known `sim_time`, loads the flight, enforces
  preconditions, then executes via the existing `hold_flight(...)` (already emits `FlightStatusChanged`)
  or the new `reassign_gate(...)`. Every outcome increments `flight_commands_total{command_type,outcome}`.
- `reassign_gate(flight_id, gate_id, sim_time)`: re-links `ASSIGNED_TO` via the existing
  `assign_flight_to_gate`, refuses to double-book an occupied gate (`is_gate_occupied` excluding self),
  emits the existing `FlightGateAssigned` fact (`reason="reassignment"`), and broadcasts to WS.
- New Prometheus counter `flight_commands_total` added to `metrics.py` and the metric contract
  allowlist.

**Validation**
- `pytest tests/unit` → **808 passed** (787 prior + 21 new command tests); metric-contract test green
  after registering the new counter.
- `tests/unit/test_flight_commands.py` (21 tests) covers HoldFlight parsing (valid, legacy field,
  numeric-string, missing/empty flight_id/reason/duration, zero/negative/bool/non-numeric duration),
  ReassignGate parsing, envelope-level rejections (unknown type, None type, non-dict/list payload),
  and the holdable-status precondition (exact set + all non-holdable statuses rejected).
- `python -m py_compile kafka/consumer.py metrics.py application/commands.py` clean; import-smoke of
  the command module confirms real parse behaviour.
- Mutation tests (prove teeth): (1) accepting unknown `command_type`, (2) allowing non-positive
  duration, (3) widening the holdable set each made exactly the matching test **fail**; all restored
  green.

**Honest scope note.** The `_handle_command`/`reassign_gate` *adapter* path (Kafka consume →
Neo4j write → fact emit) is verified by compile + import-smoke and reasoned about, but **not executed
against a live Neo4j/Kafka stack** (none in-session). The pure parse/validate/precondition logic — the
part with real branching — is fully unit-tested. Idempotency is wired through the same tracker the
existing fact path uses (itself covered elsewhere), but end-to-end redelivery-executes-once was not
run against a broker. Producers on `flights.commands` are intentionally out of scope here (A8 wires the
gateway/UI, A9 wires analysis/approval) — this task delivers the topic contract + the authoritative
consumer.

---

### A8 — Wire the already-existing UI actions (close the manual loop) ✅

**Status:** Done and validated on the frontend (type-check + build + vitest) and on the new backend
apply logic (unit + mutation). The three previously-dead action affordances now hit real endpoints.

**The defect (roadmap §0).** Three real capabilities were built but not reachable from the UI:
`flightsApi.hold/release` and `incidentsApi.contain/resolve` existed in the API client but were wired
to no component, and the recommendation **"Apply" button was a fake** — it ran a what-if projection
and `// silently ignore — projection-only`, mutating nothing. The descriptive→actionable loop was open
at the last mile: the human could see the recommendation but not act on it.

**1. Flight hold/release (`FlightBoard/FlightDetailDrawer.tsx`).** Added an "Operator Actions" section
with a `FlightActions` component. It shows **Hold** (reason dropdown + duration input) only when the
flight is in a holdable status (`scheduled`/`boarding`/`approach`) and **Release** only when `delayed`
— mirroring the flight-service REST guards (`routers/flights.py:154,182`) so the surfaced button is the
one the backend will actually accept. On success it invalidates the `["flights"]` query so the board
reflects the new state. These calls go through the **existing** gateway `/api/v1/flights` proxy → real
Neo4j mutation + `FlightStatusChanged` fact; no gateway change required.

**2. Incident contain/resolve (`IncidentConsole/IncidentActions.tsx`, wired into `IncidentConsolePage`).**
New `IncidentActions` bar on the selected incident: **Contain** while `active`, **Resolve** while
`active`/`contained`, invalidating `["incidents"]` on success. Also fixed the client methods
(`incidentsApi.contain/resolve`) to send a JSON body (`{note}`) — the incident-service endpoints take a
`ContainRequest`/`ResolveRequest`, so the old bodyless POST would have failed to bind; the wiring is now
functional, not just present.

**3. Real "Apply" (`IncidentConsole/RecommendationFeed.tsx` + analysis-service).** Replaced the fake
what-if call with a real `POST /api/v1/analysis/recommendations/{id}/apply`. New pure function
`services/autonomous.py::apply_recommendation(recs, id, sim_time, initiated_by)` finds the recommendation,
marks it applied, records a tagged entry in the action log, and **registers the bottleneck cooldown** so
the autonomous engine won't immediately re-action it; the router emits a real `AutonomousActionApplied`
event on `analysis.events` (best-effort — a broker outage cannot lose the already-recorded in-memory
apply). The button now invalidates `["analysis","recommendations"]` and surfaces errors instead of
swallowing them.

**Validation**
- Frontend: `tsc -b` clean (exit 0); `vitest run` → **43 passed**; type-check covers the new
  components and the changed client signatures.
- Backend: `pytest tests/unit` → **816 passed** (808 prior + 8 new apply tests). `py_compile` of
  `services/autonomous.py` + `routers/analysis.py` clean.
- `tests/unit/test_analysis_apply.py` (8 tests): applies a known recommendation (marks applied, tags
  `initiated_by`, stamps `applied_at`, carries parameters), overrides initiator, rejects unknown id,
  rejects already-applied, rejects double-apply, registers the cooldown, appends to the action log.
- Mutation test (prove teeth): weakening the guard `rec is None or rec.applied` → `rec is None` made
  exactly the two double-apply tests **fail**; restored green.

**Honest scope note.** The operator "Apply" issues a **real, recorded, event-producing** server action
(replacing the discarded projection) — but it emits an `AutonomousActionApplied` *fact* on
`analysis.events`, it does **not** yet publish a concrete `HoldFlight`/`ReassignGate` command on
`flights.commands`. That is deliberate and honest: the current recommendations carry only *aggregate*
parameters (e.g. `alternate_terminal: "B"`, `hold_minutes: 10`), not a concrete `flight_id`/`gate_id`,
so synthesising a real flight command would require fabricating a target. Resolving a recommendation to a
concrete command, gating it, and forwarding approved intents to `flights.commands` is exactly A9's
approval-queue work — `apply_recommendation` is the seam A9 extends (hence the `initiated_by` tag and the
cooldown already in place). The two direct actions (hold/release, contain/resolve) *do* close a real loop
end-to-end via existing REST→Neo4j→fact paths. As with A5–A7, the HTTP→service round-trips were not
exercised against a live container stack in-session (no Kafka/Neo4j); the pure apply logic — the part
with real branching — is fully unit-tested, and the frontend wiring is type-checked and built.
`analysis.events` event types (incl. `AutonomousActionApplied`) are not catalogued in `EVENT_BUS.md`
today, so no spec entry was churned; adding `initiated_by`/`parameters` to that payload is additive.

### A9 — Approval queue: activate the safety guards and close the autonomous loop ✅

**Status:** Done and validated on the pure decision logic (unit + mutation) and the frontend
(type-check + build + vitest). The Kafka emission and HTTP round-trips are reasoned about but not run
against a live broker in-session (no Kafka/Neo4j stack), consistent with A5–A8.

**The defect (roadmap §0).** The autonomous engine did two dishonest things: it **silently dropped**
safety-guarded actions (`ground_delay_program`, `rebook_passengers` were listed in
`SAFETY_GUARDED_ACTIONS` but nothing ever surfaced them — the guard was decorative), and confident
actions were applied with **no audit trail** and **no route to a real command**. `record_outcome`
existed but was never fed a proposal record. There was no human-in-the-loop path at all.

**1. Pure approval-queue module (`analysis-service/services/approval_queue.py`, new, no I/O).**
A `Proposal` dataclass with an explicit lifecycle (`pending → approved → executed`, or
`pending → rejected`) and four pure functions that are the testable core:
- `classify(action_type, confidence, *, safety_guarded, blocked, threshold)` → `AUTO`/`HUMAN`/`BLOCK`/
  `SKIP`. Blocked beats everything; **safety-guarded always → HUMAN regardless of confidence** (this is
  what "activating `SAFETY_GUARDED_ACTIONS`" means — surfaced, not dropped); else confident → AUTO,
  low-confidence → SKIP.
- `propose(...)` (pending if `requires_human`, else auto-approved), `approve`/`reject`/`mark_executed`
  enforcing legal transitions (illegal ones return `None`), `take_unemitted()` (emit each `ActionProposed`
  exactly once), and `to_flight_command(action_type, parameters)` — the **honest mapping**: returns a real
  `HoldFlight`/`ReassignGate` command *only* when a concrete `flight_id` (+ `gate_id`/positive integer
  duration) is present, else `None`. `bool` durations are rejected (int subclass trap).

**2. Engine routing (`services/autonomous.py::evaluate_and_apply`).** Every candidate now goes through
`approval_queue.classify`: `BLOCK`/`SKIP` → dropped (as before); `HUMAN` → enqueued **pending** for the
dashboard and the bottleneck put on cooldown so it isn't re-proposed every cycle while awaiting a
decision (the action is **not** applied); `AUTO` → applied as before **plus** an auto-approved+executed
`Proposal` is recorded for a unified audit trail. New `record_proposal_execution(proposal, sim_time,
decided_by)` writes an `appr-`-tagged action-log entry in the same shape as an auto/operator apply, so the
existing `record_outcome` can fill in the measured outcome 30 min later — the seam is now fed.

**3. HTTP surface (`routers/analysis.py`).** `GET /api/v1/analysis/approvals` (pending by default,
`?all=true` for history); `POST /approvals/{id}/approve` — transitions pending→approved, records the audit
entry, and if `to_flight_command` yields a concrete command **publishes it on `flights.commands`** (A7
envelope) else emits the `AutonomousActionApplied` fact, then marks executed; `POST /approvals/{id}/reject`.

**4. Kafka wiring.** `kafka/producer.py`: `emit_action_proposed` (fact on `analysis.events`) and
`emit_flight_command` (A7 command envelope on `flights.commands`, keyed on `flight_id`, no `sim_time` —
flight-service stamps the fact). `kafka/consumer.py`: after each autonomous evaluation cycle,
`approval_queue.take_unemitted()` → `emit_action_proposed` for each, so proposals reach the dashboard.

**5. UI (`IncidentConsole/ApprovalQueue.tsx`, wired into the Analysis tab).** A polling (5 s) queue that
renders pending proposals with **Approve**/**Reject** buttons hitting the new endpoints and invalidating
the approvals + autonomous-log queries. `approvalsApi` (`approvals`/`approveProposal`/`rejectProposal`)
and an `Approval` type added to `hooks/useApi.ts`. The queue renders nothing when empty.

**Validation**
- Backend: `pytest tests/` (venv interpreter, has neo4j/confluent) → **853 passed, 96 skipped**
  (816 prior + 37 new). `py_compile` of `approval_queue.py`, `autonomous.py`, `producer.py`,
  `consumer.py`, `routers/analysis.py` clean.
- `tests/unit/test_approval_queue.py` (30 tests): classify verdicts incl. the at-threshold boundary and
  blocked-beats-guarded precedence; propose pending vs auto; approve/reject/mark_executed legal +
  illegal transitions; `take_unemitted` exactly-once; every `to_flight_command` branch (concrete map,
  missing target, zero/bool duration, unmapped action).
- `tests/unit/test_analysis_autonomous_routing.py` (7 tests): confident-unguarded auto-applies **and**
  leaves an executed proposal; below-threshold and blocked drop with no proposal; safety-guarded is
  proposed-not-applied and registers cooldown (not re-proposed within the window);
  `record_proposal_execution` audit shape + parameter defaulting.
- Mutation tests (prove teeth): (a) `confidence >= threshold` → `>` made `test_at_threshold_is_auto`
  **fail**; (b) removing the `if safety_guarded: return HUMAN` branch made **3** tests fail across both
  files (classify + both engine-routing guard tests). Both restored green.
- Frontend: `tsc -b` clean; `vitest run` → **43 passed**.

**Spec.** Catalogued the previously-undocumented `analysis.events` topic in `EVENT_BUS.md` (both tables)
and added §4.8c documenting its event types, the `ActionProposed` schema, and the approve→command path.

**Honest scope note.** The pure decision core (classify, transitions, command mapping, engine routing,
audit recording) is fully unit-tested and mutation-checked — this is where all the real branching lives.
The Kafka producers/consumer and the three HTTP endpoints are exercised only by `py_compile` and type
inspection, not against a live broker/DB (no container stack in-session), same caveat as A5–A8. The
`to_flight_command` mapping is deliberately conservative: aggregate/terminal-level proposals (no concrete
`flight_id`) map to **no** command and are recorded as facts only — approving them is a real audited
action but does not fabricate a flight target. Concrete `HoldFlight`/`ReassignGate` commands are formed
and forwarded only when a proposal genuinely carries a flight id and the required parameters.

### A10 — Harden gateway auth: kill the backdoor, require real secrets, add RBAC ✅

**Status:** Done and validated (unit + behavioral). The gateway is now fail-closed in production and
gates the highest-privilege command path (approvals) by identity.

**The defect (roadmap §1.3 #8).** `auth.ts` was "dangerous by default": (a) `NODE_ENV !== "production"`
made `handleToken` **accept any credentials** — the `secret` was never checked unless prod; (b)
`JWT_SECRET` silently defaulted to `"art-digital-twin-dev"`, so a prod deploy that forgot to set it
minted tokens anyone could forge; (c) **every** token was hardcoded `role: "operator"` — no RBAC, so the
A9 approval path had no identity gate. Fine for a demo, unsafe the moment it touches anything operational.

**1. No backdoor — real credential validation (`auth.ts::handleToken`).** Removed the `isDev` "accept
anything" branch entirely. Credentials are now validated against a **client registry** for every request,
in dev and prod alike. The secret is compared with `crypto.timingSafeEqual` (length-guarded, constant-time
for equal-length inputs). Unknown client ids and wrong secrets return an identical `401` (no client
enumeration).

**2. Client registry + fail-closed config.** `AUTH_CLIENTS` (JSON:
`{"<id>":{"secret":"...","role":"operator|approver"}}`) is parsed and shape-validated at load; malformed
entries are dropped with a warning. In **non-production** a single built-in dev client
(`dashboard`/`art-dev-secret`/`approver`) keeps `docker compose up` working. In **production** there is
**no** built-in credential. `isSecureConfig()` refuses to operate when `NODE_ENV=production` and either
`JWT_SECRET` is left at the dev default **or** no clients are configured; in that state `handleToken`,
`authMiddleware`, and `verifyTokenFromRequest` all **fail closed** (503 / false) rather than issue or
accept forgeable tokens. The gateway logs loudly but does not crash (a config typo serves 503s, it doesn't
take the deployment down).

**3. RBAC — operator/approver roles.** Tokens now carry the client's role (`viewer < operator < approver`
by `ROLE_RANK`). New `requireRole(minRole)` middleware admits any role of rank ≥ the required one and
returns `403` otherwise. Wired in `index.ts`: the A9 approval command path
(`POST /api/v1/analysis/approvals/:id/{approve,reject}`) requires **`approver`**, while `GET` on the queue
stays at normal auth so an operator can see what is pending. The gate sits before the proxy, so an
unauthorized approval never reaches the analysis-service.

**Validation**
- `npx tsc --noEmit` clean (gateway); dashboard unaffected (still `dashboard`/`art-dev-secret`, now
  resolving to the `approver` role, so every existing UI action keeps working).
- `npm test` (node:test) → **17 passed** (was 9). New/updated coverage: no-secret request rejected
  (backdoor gone), wrong secret rejected, unknown client rejected, valid credentials issue a
  role-carrying JWT; full `requireRole` matrix (equal/higher rank admitted, lower/absent/unknown role →
  403).
- Behavioral fail-closed check (run with real env): `NODE_ENV=production` + dev-default `JWT_SECRET` →
  `handleToken` **503** and `verifyTokenFromRequest` **false**; `NODE_ENV=production` + strong `JWT_SECRET`
  + `AUTH_CLIENTS` → **200**; dev → **200**. This exercises the security-critical branch that unit tests
  (loaded once, non-prod) cannot.

**Spec/infra.** `docker-compose.yml` gateway env now documents that `JWT_SECRET`/`AUTH_CLIENTS` are
dev-only defaults and that production fails closed without real values.

**Honest scope note.** The credential/RBAC decision logic is fully unit-tested and the prod fail-closed
path is behaviorally verified against real env vars. What is *not* exercised in-session: the end-to-end
403 through the live Express stack + proxy to a running analysis-service (no container stack), same
caveat as A5–A9 — the middleware itself is unit-tested in isolation and mounted in `index.ts`. The dev
client is deliberately `approver` so the single-console demo keeps full function; a real multi-user
deployment would define distinct `operator`/`approver` clients in `AUTH_CLIENTS`. Role is asserted at the
gateway (the trust boundary); upstream services still trust the gateway, unchanged.

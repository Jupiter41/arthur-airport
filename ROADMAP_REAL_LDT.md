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

### Phase 0 — Stabilization (weeks 0–3)
**Objectives:** stop the bleeding; make numbers and money trustworthy; kill fake signals.
- Fix cost-service idempotency + double-counting (`kafka/consumer.py` add `IdempotencyTracker`; dedup
  dual-entry). *Affected:* `cost-service/kafka/consumer.py`, `cost_engine.py`.
- Fix planning trust bugs: runway capacity scaling (`simulation.py:392`),
  `missed_connections`/cascade increments or stop monetizing them (`benefit_extractor.py:88`).
- Reconcile `WIDE_BODY_TYPES` (D3); single finance source (D2).
- CI gaps: cost/planning deps missing from `unit-tests`; remove `|| true` on integration; add gateway
  tests; scrape cost/planning `/metrics`.
- Delete committed Azurite artifacts; gitignore caches; archive doc sprawl.
- **Complexity:** LOW–MED. **Deps:** none. **Value:** HIGH — cannot make decisions on a system that
  double-counts money and monetizes always-zero metrics.

### Phase 1 — Architecture Foundation (weeks 2–8, overlaps P0)
**Objectives:** kill duplication; invert dependencies; make domain logic testable.
- Promote to `_common` and delete copies: `neo4j_client`, `kafka_runtime`, `EventEnvelope` producer
  path, `_logging/_tracing/_profiler`; make `IdempotencyTracker` mandatory. Fix `_template`.
- Refactor consumers into thin adapters over pure `application.handle()` (start with flight + pax).
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

### Phase 4 — Action Platform (weeks 14–22)
**Objectives:** close the loop — commands + approvals.
- Add `{domain}.commands` topics + command handlers in owning services (emit existing facts on success).
- Approval-workflow service/module; wire `SAFETY_GUARDED_ACTIONS`.
- UI: real "Apply", approval queue, wire `hold/release` + `contain/resolve`. *Affected:* gateway
  (command routes), each domain service (handler), `analysis/autonomous.py` (emit commands), dashboard.
  **Complexity:** MED (small per service, cross-cutting). **Deps:** P0–P3. **Value:** HIGH — this is
  the LDT.
- Harden auth (kill dev backdoor, real secret, RBAC) — prerequisite for real action execution.

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
1. Add `IdempotencyTracker` to the cost-service consumer and eliminate dual-entry double-counting; add
   a test that redelivers a message and asserts no double-mutation.
2. Fix planning fidelity bugs: runway-count → capacity scaling (`simulation.py:392`), and either
   increment `missed_connections`/cascade depth or remove them from `benefit_extractor.py:88` NPV.
3. Collapse `WIDE_BODY_TYPES`/`_aircraft_family` and the finance constants to a single source (JSON
   authoritative, `finance_constants` + planning both load it).
4. Fix CI: add cost/planning deps to `unit-tests`, drop `|| true` on integration, add gateway tests,
   scrape cost/planning `/metrics`; delete `AzuriteConfig`/`__azurite_db_table__.json`, archive
   `docs/old` + `lessons-learned`.
5. Promote `neo4j_client`, `kafka_runtime`, `EventEnvelope`, `_logging/_tracing/_profiler` into
   `_common`; delete the copies from one pilot service (flight) end-to-end to prove the pattern.
6. Refactor `flight-service` consumer into `adapters → application.handle() → pure domain`; land real
   unit tests for the FSM without containers.
7. Introduce `flights.commands` + a command handler in flight-service that executes
   `HoldFlight`/`ReassignGate` and emits the existing `FlightStatusChanged` fact.
8. Wire the already-existing UI actions: `flightsApi.hold/release` in FlightDetailDrawer,
   `incidentsApi.contain/resolve` in Incident Console, and make `RecommendationFeed`'s "Apply" issue a
   real command.
9. Build the approval-queue service/module + UI, and make `analysis/autonomous.py` emit
   `ActionProposed`/commands through it (activating `SAFETY_GUARDED_ACTIONS` and `record_outcome`).
10. Harden gateway auth (remove the dev backdoor, require a real `JWT_SECRET`, add operator/approver
    roles) so command execution is gated by identity.

Do 1–4 immediately (a two-to-three-week stabilization that removes correctness and money defects),
then treat 5–10 as the backbone of the LDT transformation. The macro-architecture is sound — the work
is closing the loop, unifying the concepts, and making the numbers honest, not rewriting.

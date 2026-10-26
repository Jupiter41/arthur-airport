# Roadmap to a Real Living Digital Twin (LDT)

> **Current verification: 2026-10-17.** The architecture review in §§0–9 and
> execution entries A1–A10 are historical observations, not a blanket claim that
> the LDT is complete. A11–A14 record this continuation; §10 is the current gap
> register. In particular, the old “applied” behavior in A8/A9 was an audit fact,
> not domain execution. It has been replaced by command dispatch plus owner
> receipts. Full Kafka/Neo4j runtime validation is still outstanding.

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

### Phase 0 — Stabilization (weeks 0–3) ⚠ PARTIAL (see §10)
**Objectives:** stop the bleeding; make numbers and money trustworthy; kill fake signals.
- ✅ Fix cost-service idempotency + double-counting (`kafka/consumer.py` add `IdempotencyTracker`; dedup
  dual-entry). *Affected:* `cost-service/kafka/consumer.py`, `cost_engine.py`. *(A1)*
- ✅ Fix planning trust bugs: runway capacity scaling (`simulation.py:392`),
  `missed_connections`/cascade increments or stop monetizing them (`benefit_extractor.py:88`). *(A2)*
- ✅ Reconcile `WIDE_BODY_TYPES` (D3) and financial rate sources (D2). A22 adds one shared loader, durable effective rates and frozen planning snapshots beyond A3's equality guards. **G2 remains partial:** mixed accounting perspectives still require migration. *(A3/A22, §10 G2)*
- ✅ CI gaps: cost/planning deps missing from `unit-tests`; remove `|| true` on integration; add gateway
  tests; scrape cost/planning `/metrics`. *(A4)*
- ✅ Delete committed Azurite artifacts; gitignore caches; archive doc sprawl. *(A4)*
- **Complexity:** LOW–MED. **Deps:** none. **Value:** HIGH — cannot make decisions on a system that
  double-counts money and monetizes always-zero metrics.

### Phase 1 — Architecture Foundation (weeks 2–8, overlaps P0) ✅ PARTIAL
**Objectives:** kill duplication; invert dependencies; make domain logic testable.
- ⚠ Pilot only — promote to `_common` and delete copies: `neo4j_client`, `kafka_runtime`, `EventEnvelope` producer
  path, `_logging/_tracing/_profiler`; make `IdempotencyTracker` mandatory. Fix `_template`. *(A5 — pilot: flight-service)*
- ⚠ Partial — refactor consumers into thin adapters over pure `application.handle()` (start with flight + pax). *(A6 — partial: pure decisions extracted, full handle() inversion deferred)*
- ✅ Externalize D6 constants to `config/airport.yaml`.
- *Affected:* all `services/*/db|kafka`, `_common/*`, `_template/*`. **Complexity:** MED–HIGH.
  **Deps:** none (mechanical). **Value:** HIGH — every later change gets cheaper; unit tests become
  possible.

### Phase 2 — Digital Twin Core (weeks 6–12)
**Objectives:** one canonical model + one effect engine.
- Canonical entities + value objects in `twin-core`/`_common` (§4.2).
- **Unify the 3 what-if simulators (D5)** into `simulation-core`; rewire planning MC, analysis
  what-if, RL env. **Complexity:** HIGH. **Deps:** P1. **Value:** HIGH — correctness + coherence.
- ✅ Persist planning scenarios/results/audit to Neo4j with a durable lifecycle outbox. *(A12; repository-boundary tests, live DB validation pending)*

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
- ✅ `incidents.commands` + incident-service `ContainIncident`/`ResolveIncident` handler (emits the existing `IncidentStatusChanged` fact + durable receipt; live-validated). *(A28)*
- ⚠ Concrete GDP/rebooking execution, recommender-proposed incident actions and remaining action coverage are still open. Unsupported/aggregate actions are advisory and cannot claim execution. *(A11, §10 G6)*

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

**Historical scope:** this process-local guard was not crash-safe. A20 (§16)
replaces it with an atomic durable financial inbox/ledger/checkpoint/outbox and
real rollback, competing-worker, process-exit and Kafka replay validation. The
former empty-ID behavior is replaced by stable broker-position identity.

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

**Superseded for financial rates by A22:** the common table/loader now owns the
defaults, live effective rates persist in Neo4j, and planning freezes them on claim.
The shared MTOW table replaces planning's seat-based weight approximation.

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

### A8 — Wire the already-existing UI actions (historical; execution corrected by A11) ⚠

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

### A9 — Approval queue (historical; execution corrected by A11) ⚠

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


### A11 — Commands now require owner confirmation; live congestion reaches the loop ✅

**Implemented (2026-10-17).** Manual Apply, automatic rules, RL-selected concrete
recommendations and human approval share `_common.commands.action_command` and
`analysis/services/action_execution.py`. Mappings cover concrete flight holds,
gate reassignment, security lane counts and baggage flight redirection. Terminal
labels and the existing outbound-flight/hold-duration fields are normalized.
Unsupported targets return 422 / remain advisory. Expired recommendations are
rejected. A pending command is not marked applied, including after approval.

Proposals follow `pending → approved → dispatched → executed|failed`, or rejection.
Neo4j `ActionProposal` records rebuild the cache and confirmed execution log.
Publishing waits for broker acknowledgement off the event loop. Failures retain
an approved retryable proposal; every retry uses the proposal ID as command ID.
Missing receipts are retried after five simulation minutes. Owning services emit
`CommandExecuted` / `CommandRejected` and reload saved Neo4j `CommandReceipt`
records before redelivery. Only an owner-topic receipt marks execution, updates
the recommendation and increments the action metric. The UI displays advisory,
pending, dispatched, executed and failed states separately.

Additional defects found while driving the real owners:
- Security lane commands previously changed only memory. They now save
  `SecurityCheckpoint`, emit `SecurityLanesChanged` and restore overrides.
- Analysis expected terminal/forecast fields absent from real passenger events.
  Passenger-service now publishes unsampled `SecurityQueueUpdated` aggregates.
  Analysis detects and resolves **observed** congestion without inventing a
  forecast confidence score; per-passenger event sampling cannot corrupt these
  aggregate queue counts.
- Manual holds previously vanished on restart and replaced existing delay totals.
  Hold metadata is committed with the delayed Flight, the cache rebuilds from
  Neo4j, delay increments preserve prior delay, and failed writes do not create
  a memory-only hold. Release clears cache only after a successful DB update.
- Gate assignment matched the new gate after deleting the old relationship.
  It now resolves/locks/checks the target first and returns a real success flag;
  rejected assignments cannot emit `FlightGateAssigned` or a success receipt.
- Connection-cluster queries used nonexistent `flight_id`, `flight_type`,
  `is_connecting` and `passenger_id` graph properties. They now use the documented
  IDs, direction and `connection_flight_id`. Actual flight direction/gate fields
  are accepted by the analysis projection.

**Validation:** real handler tests stub only DB/Kafka/metrics and unrelated ML
training boundaries. They cover accepted/rejected flight commands, receipt
redelivery after a new cache, lane persistence/rebuild, failed hold writes,
cumulative delay and rejected gate assignment. Lifecycle tests cover correct
owner-topic routing, early/duplicate/rejected receipts, unavailable broker,
stable retry IDs and unsupported actions. Measured queue snapshots detect and
resolve a real observed bottleneck. See A14 for final suite totals.

**Boundary:** domain mutations, their receipts and Kafka facts are not one atomic
transaction. A crash between them remains a correctness gap (G1); no exactly-once
claim is made. Multi-replica analysis proposal coordination is not implemented.

### A12 — Durable planning records, outbox and reproducible financial comparisons ✅

**Implemented.** `planning-service/db/store.py` replaces worker-local scenario,
result and audit stores with constrained Neo4j documents. Reads always consult
Neo4j. No silent memory fallback exists. Async routes offload synchronous driver
work to threads; the Monte Carlo worker durably writes seed, status and progress.
Pending/running deletion is rejected. Result persistence precedes completed
status; failed result writes produce failed scenarios. Completed deletion also
removes results. Counterfactual children and comparison/audit reads use the same
store. Service counts use total matches instead of the first 20 rows.

Every planning write commits a `PlanningEvent` outbox record in the same
transaction. A background publisher sends `planning.events`, retains failed
messages and acknowledges only confirmed delivery. Retries preserve event IDs.
Readiness checks Neo4j and Kafka; Compose now explicitly supplies planning's DB
and broker settings and creates planning/command topics.

The resolved random seed is persisted **before** date sampling and reused for
both comparison arms. Negative annual benefits now reach DCF unchanged (they were
silently clamped to zero). Audit accuracy compares measured predictions only,
rather than treating unmeasured recommendations as zero savings. Scenario
serialization now also preserves `weather_date`.

**Validation:** repository-injection tests cover full configuration roundtrips,
independent reads, durable progress, deletion, no-memory fallback, atomic
record/outbox writes, failed broker retry identity, like-for-like audit accuracy,
runner seed/progress/results, negative benefits and failed result storage.
These were repository-boundary tests, **not a live Neo4j restart test**. At A12,
interrupted jobs retained progress without automatic recovery. A21 now replaces
that execution limitation with durable leases, recovery and live fencing tests.

### A13 — Honest training availability and demand features ✅

**Implemented.** Analysis training rejects forecast/anomaly/unknown requests
instead of manufacturing completed runs. RL requires a usable policy before its
mode can be enabled. Policy selection must resolve to the same guarded concrete
recommendation path as other control modes. Training uses the current Python
interpreter, unique artifact paths, drains stdout while the process runs, labels
progress estimates, and reports completion only after a successful process exit
and a new model archive. Successful artifacts replace the canonical policy
atomically; stopping/shutdown reaps the training process. The UI disables the
unimplemented training choices and labels estimated progress.

Planning demand training aggregates route/calendar-month observations and builds
history exclusively from **earlier months**, never the current target. Labels
use actual days in each month; statute miles convert with 1.609344. Training
requires at least ten lagged observations and chronological validation.

**Validation:** synthetic CSV tests prove current/future months cannot enter the
historical feature and a single month cannot train itself. Training tests reject
fake run types, reject a zero-exit job without an artifact, and verify successful
archive promotion. No actual PPO/LightGBM training or forecast calibration is
claimed from these tests. Shared simulation effects and calibrated intelligence
remain open (G4/G8).

### A14 — Validation, documentation and completion-claim reconciliation ✅

Architecture overview now includes planning-service, correct speed conversions,
actual authentication and the existing REST/WS behavior. Graph/event/service
contracts describe the new records and lifecycle. Gateway health inventory now
includes cost and planning. A portable Node test runner replaces the committed
Unix `find` substitution so `npm test` works on Windows and Linux. Command metric catalogues include passenger/baggage
counters. Four pre-existing flight import-order lint failures were corrected.
`PLANNING.md`, `AUTONOMOUS_OPS.md` and related roadmaps point to the audit below.

**Final validation on the exact staged tree**, exported to a separate directory
without the unrelated working-tree edits. Node dependencies were installed there
using the committed lockfiles (`npm ci --no-audit --no-fund`).

| Command / scope | Result |
|---|---|
| `python -m pytest tests/unit -q --tb=short` | **936 passed**, no skips; 14 deprecation warnings for existing job-metadata `utcnow` calls. Local interpreter: Python 3.14.3; CI still targets 3.11. |
| Gateway: `npm test` | **17 passed**, portable discovery, no broker required. |
| Gateway: `npm run build` | TypeScript build passed. |
| Dashboard: `npm test` | **43 passed** across 8 files. |
| Dashboard: `npm run build` | TypeScript + Vite build passed; existing bundle-size/Browserslist warnings remain. |
| `python -m ruff check` on all nine services plus the new common modules | Passed. |
| `docker compose config --quiet` | Passed on the isolated staged Compose file. |
| `git diff --cached --check` | Passed. |

Tests requiring local sockets/temp-file operations ran outside the restricted
Windows sandbox after sandbox denials; they did not require a live broker or DB.
No full-stack test is counted as passed: Docker Desktop's engine pipe is absent.
Neo4j queries/transactions, live restart behavior and Kafka crash windows remain
explicit deployment-validation work (G1/G12).

Existing unrelated Raspberry Pi deployment/access-control changes were preserved
and excluded from this continuation's commit. The isolated tree contains 936 tests;
the additional eight uncommitted Pi/checkpoint tests are intentionally not part of
that committed-suite count.

## 10. Current gap register — checked against code and completed plan claims

**The roadmap is not complete.** Historical checkmarks describe delivered slices;
they do not prove the intended behavior across the whole digital twin. This audit
cross-checked this roadmap, `PLANNING.md`, `AUTONOMOUS_OPS.md`, `ROADMAP_USECASE.md`,
capacity-planning roadmap 4 and stabilization roadmap 5 against their code paths.

| ID / priority | Remaining gap and evidence | What completion actually requires |
|---|---|---|
| G1 / P0 — partial | Flight/passenger/baggage domain writes, receipt writes and fact delivery remain separate. A20 makes cost/carbon records, relationships, checkpoint, durable input IDs and financial outbox atomic; offsets follow processing. Financial rollback/competing-worker/process-exit/Kafka-replay tests exercise Neo4j/Kafka. A24 adds atomic analysis proposal decisions/attempts, lifecycle facts and command outbox entries. | Extend transactional domain/outbox/inbox boundaries to the remaining owners and receipts. Financial Kafka delivery remains at least once with stable event IDs, not exactly once; simulation epochs and legacy repair are separate work. |
| G2 / P0–P1 — partial | A22 replaces independently editable constants/fixtures with one shared default loader, cost-owned durable/versioned effective rates, atomic validated updates and frozen planning rate snapshots. First-delivery fee cost+revenue accounting remains mixed; planning still includes a 30% landing-cost assumption and 30% compensation claim assumption. | Agree airport/airline accounting perspective and migrate affected projections/calculation models. Rate unification alone does not close G2 or all of Phase 0. |
| G3 / P1 — partial | A27 deletes all 28 local `_logging`/`_tracing`/`_profiler` copies (9 services + `_template`); every service and the template now import them from `_common`. Still duplicated: 8× `db/neo4j.py` and 8× `kafka/producer.py`+`consumer.py` (D1 remainder); `_common` does not own the consumer loops. A6 extracted decisions, not a complete `application.handle()` flow; passenger orchestration is still in its consumer. | Promote `neo4j_client`/`kafka_runtime` consumer loop to `_common` and delete the remaining transport copies; invert flight/passenger application orchestration with real adapter tests. |
| G4 / P1 | Planning simulation, analysis what-if and RL environment still contain separate action-effect models. Canonical aircraft classification exists, not a canonical entity/effect core. | One calibrated effect library with shared contracts, used by all three, plus historical validation. Phase 2 remains partial. |
| G5 / P1 — partial | A25 replaces the confidence-only sort with impact × confidence ÷ cost over a common synthetic impact/cost scale (`analysis/services/ranking.py`), unit- and mutation-tested. Cost and analysis still have **separate recommenders**, and the impact/cost weights are heuristic, not calibrated (G8). | Emit cost signals into the one ranking path and calibrate the impact/cost scale against measured outcomes (needs G8); retire the second (cost-service) recommender. |
| G6 / P1 — partial | A28 adds the `incidents.commands` channel (owner execution + durable receipts, live-validated). A29 maps `contain_incident`/`resolve_incident` in `_common.commands.action_command`, so an **approved proposal now dispatches on `incidents.commands` and is confirmed by the owner receipt through the same approval machinery as flights/passengers/baggage** (live-validated propose→execute→confirm). A30 adds `ActionType.RESOLVE_INCIDENT`/`CONTAIN_INCIDENT` (both safety-guarded → human approval) and a `_recs_active_incident` recommendation that carries the `incident_id`, so the loop now **originates** executable incident recommendations too (live-confirmed: the endpoint serves an `executable` `resolve_incident` rec with a concrete id). A31 makes the gate-conflict `REASSIGN_GATE` recommendation concrete — it resolves a specific waiting flight + a specific free gate (via new `get_free_gate_ids_by_terminal`) so it carries `flight_id`+`gate_id` and maps to the existing `flights.commands: ReassignGate` (falls back to the aggregate advisory rec when no concrete pair is resolvable). Still open: GDP and rebooking lack concrete owner handlers, and the taxi/baggage proposals still often lack entity IDs. | Implement/validate the remaining concrete actions and their target selection; retain advisory UI until then. A8/A9/A28–A31 do not imply full-fleet autonomous control. |
| G7 / P1 — partial | A21 gives planning a durable pending queue, renewable leases, stale-worker fencing, automatic expired-job recovery and atomic result/completion publication. An attempt restarts from its persisted seed/config. A24 serializes analysis proposal creation, approval/rejection, retry attempts and receipts in Neo4j, with an independent acknowledged command/audit outbox. Training-job recovery is separate. | Retain analysis decision/retry and planning fencing/crash/concurrency tests; extend interruption recovery to training and other job types. Full analysis discovery/projection ownership remains G9. A22 freezes financial rate inputs; schedule/weather/model snapshots and partial Monte Carlo checkpoint resume remain separate work. |
| G8 / P1 | Automatic outcomes after 30 sim-minutes remain planned work, now labelled as such in `PLANNING.md`. Analysis `record_outcome` has no automatic caller; planning outcomes are manual REST input. Synthetic delay labels and heuristic uncertainty bands are not calibrated predictions. | Simulation-clock outcome measurement with baseline/counterfactual attribution and persisted evidence; validated training/history before financial savings claims. |
| G9 / P1 | Flight/gate/weather/incident projections rehydrate from Neo4j and reconcile every ten ticks (A15). Baggage aggregates are durable and unsampled, including BULK mode. A17 fixes owner scan-zone recovery, dangerous-goods/routing metadata and arrived-bag queues. A18 restores incident identities for flight restrictions, passenger freezes and conveyor failures. Analysis security/vehicle projections, transit progress and complete owner/vehicle recovery remain partial; aggregate publication retains the G1 crash window. | Complete graph-based projection rebuild and unsampled domain snapshots with actual producer→consumer contract tests, including BULK mode. |
| G10 / P2 | Zustand/WS and React Query/REST still overlap. Original “dashboards never poll” wording contradicted `useApi` and planning pages. | Choose a source of truth per domain and remove hand-synchronized duplicate state. Overview now describes current behavior honestly. |
| G11 / P2 | Provider-labelled adapters, historical data files and some plan examples conflict with the project-level fake-data-only contract. Operational/reference modes are not consistently labelled. | Reconcile the data policy in specs/config/UI; keep tests and generated operational data synthetic. This continuation imported no external data. |
| G12 / P2 — partial | A17–A24 validate local Compose, all-service readiness, full restart, command replay and browser checks. Run 39153728540 passes all jobs and 121 live tests, including analysis proposal contention/rollback/outbox/crash recovery, durable rates, ledger recovery and planning worker fencing. A26 adds the missing `cost-service`/`planning-service` k8s manifests and the gateway's cost/planning service URLs (`kustomize build` + offline validation; no live apply — cluster RBAC denies it here). Sustained load and the remaining owners' crash/replica behavior remain unproved. | Retain the strict full-stack CI gate and validate the remaining load/crash/replica behavior on a cluster. Functional integration success is not complete fidelity or deployment certification. |

**Corrected completion claims:** A8/A9 now send executable commands and wait for
owner receipts; security commands persist and publish facts; planning records are
durable; training stubs no longer claim success; negative investment benefits and
demand target leakage are fixed. Remaining rows above stay open rather than being
silently checked off. Existing historical logs are retained for traceability.


## 11. A15 — Whole-service recheck (2026-10-17)

**Disposition: keep this roadmap active. Do not archive it as completed.**
The user's all-service check found additional real defects despite passing
unit suites. G1–G12 are still completion conditions; this section records the
verified corrections without converting them into blanket certification.

- Passenger forecast REST used fixed 5-flight/500-passenger inputs and CAVOK
  weather. It now reads each future schedule window and the real simulated
  context. Neighbour congestion no longer always maps to false for the target.
  Closed/frozen lanes no longer predict zero wait. Each point identifies the
  actual LightGBM/fallback source. Uncalibrated confidence is explicitly null.
- Queue-model validation previously fit all rows and then evaluated the last
  20% of those same rows. Training now uses strictly earlier timestamps only.
  Atomic parquet/model replacement retains previous data on failures; a
  no-artifact retrain no longer claims success. A real LightGBM synthetic model
  was trained, saved, reloaded and used for inference in the regression suite.
- Analysis read `category` instead of the weather producer's `new_category`,
  leaving category/capacity stale. It now consumes recommended rates and new
  category; weather persists those rates for restart recovery.
- Analysis now reads the operational graph at startup and reconciles flights,
  gates, weather, incidents and baggage aggregates every ten ticks. Gate totals
  come from actual nodes after recovery. Baggage owner snapshots replace
  occupancy counts without replay inflation, including with per-bag BULK
  suppression. What-if requires simulation time instead of wall-clock fallback.
- Gateway readiness now requires all nine upstream `/ready` endpoints.
  Topic creation fails instead of claiming success after an error. Config
  mounts missing from overriding Compose volume lists are restored; default
  ADS-B fetching is disabled for the synthetic operational stack.
- Previous GitHub CI failed on an unpinned Ruff upgrade (0.17.1 expanded its
  default checks). CI now pins the locally validated version and declares the
  existing E4/E7/E9/F baseline explicitly. Integration CI now builds/starts the
  complete Compose stack, requires every service ready, runs every integration
  module and fails on skips. Dashboard tests are included.

A live regression test now exercises a persisted approved proposal through
analysis dispatch, Kafka, the passenger owner mutation, durable receipt and
analysis execution confirmation, then restarts the owner and replays the command
identity. This test is **added but not counted as passed without a live stack**.
It runs only against a disposable synthetic stack and restores lane capacity.

### Service verification matrix

| Service/capability | Evidence and remaining limit |
|---|---|
| flight-service | FSM/gate/runway/hold/receipt unit coverage passes; live restart/crash atomicity still unproved. |
| passenger-service / prediction | Queue/connection/spatial units and actual synthetic LightGBM artifact test pass; forecasts are conditional estimates, not calibrated operational probability. |
| baggage-service | Conveyor/screening/command units and actual aggregate producer→analysis contract pass; complete owner pipeline recovery remains open. |
| weather-service | FSM/capacity/METAR units and actual transition producer→analysis contract pass. |
| incident-service | Cascade/lifecycle/protocol units pass; full-fleet incident command integration is not implemented. |
| sim-orchestrator | Clock/schedule/scenario/speed units pass; full-stack execution needs a working engine. |
| analysis / recommendations | Routing/approval/owner confirmation and projection units pass; many action types remain advisory, G4/G5/G6/G8 remain open. |
| cost-service | Cost/revenue/calculator units pass; transactional dedup and the accounting/rate-source gaps G1/G2 remain open. |
| planning-service | Engine/finance/storage/outbox/demand-history units pass; jobs do not automatically resume and model uncertainty remains heuristic. |
| gateway / dashboard | Gateway regression tests and both builds checked below; browser/full-stack certification remains pending. |

### Validation evidence

Docker Desktop was started for this check but its backend crashed while opening
the local `dockerInference` socket (`Le système ne peut pas accéder au fichier`).
The strict readiness probe returned failure for all nine services and gateway.
No live result is claimed from that failure. The new strict CI gate will supply
deployment evidence when it completes on a functioning Docker host.

The exact staged tree was exported outside the working checkout, excluding
the unrelated Raspberry Pi/access-control edits. Dependencies were installed
from the committed lockfiles (`npm ci`). Local Python was 3.14.3; CI targets 3.11.

| Check | Result |
|---|---|
| Python unit suite | **948 passed**, no skips; 14 existing job-metadata deprecation warnings. Includes real LightGBM synthetic training/reload. |
| Gateway tests | **22 passed**, no skips. |
| Dashboard tests | **43 passed**, 8 files. |
| Gateway and dashboard builds | Passed; dashboard retains existing bundle-size/Browserslist warnings. |
| All nine Python services + common modules + validation scripts: Ruff | Passed with the committed explicit baseline. |
| Isolated `docker compose config --quiet` | Passed. |
| `git diff --cached --check` | Passed. |
| Strict live readiness on this machine | **Failed**: no service reachable after Docker backend startup crash. |
| Full live integration, restarts and broker redelivery | **Not yet validated**. Added to strict GitHub full-stack gate. |

The roadmap remains active because passing units/builds does not close G1–G12.
No roadmap file has been moved into the old-roadmap folder.


## 12. A16 — Verify actual training and policy inputs (2026-10-17)

The default analysis image omits optional TensorBoard extras, but PPO training
unconditionally enabled TensorBoard logging. Training now detects that optional
dependency and continues without it; CPU threads default to one. A real short
PPO run (1,024 steps) now saves an archive that is reloaded for action inference.
The policy observation includes actual `approach`/`taxiing` statuses, observed
security waits and the active bottleneck count instead of dropping those inputs.
What-if gate utilisation now uses the recovered graph gate count.

Planning delay training had a second leakage bug: `historical_otp` directly
encoded the current synthetic target. It now uses an explicit fixed prior and
identifies synthetic labels. Statute-mile conversion is corrected here too.
Training requires both outcomes in the training arm. Undefined holdout AUC is
null rather than NaN, preserving JSON validity. Synthetic model output is labelled
`lgbm_synthetic`, with calibration explicitly false in model/training metadata.
These fixes do not turn generated labels or the RL toy environment into validated
operational intelligence; G4/G8 remain open.

The live replay regression was strengthened to observe a **new owning-service
Kafka receipt** after replay. An unchanged old Neo4j receipt alone is insufficient
proof that replay was processed. The observer pins broker offsets before send.

**Isolated-tree validation:** **953 Python tests passed**, no skips, including
actual LightGBM queue/delay training and actual PPO training/reload/inference.
Both Node builds and their 22 gateway / 43 dashboard tests remain as checked in
A15; no frontend/gateway code changed in A16. Ruff passes for changed services.
CI now installs the CPU-only Torch build before the domain requirements.

GitHub run `39016849378` for `625ee09` passed Linux Python units, lint, gateway
tests and both builds, built all Compose images, and reached the strict live
readiness/integration stage. Its final deployment result is recorded separately
when available; reaching that stage is not a full-stack pass.


## 13. A17 — Local full-stack validation and recovery corrections (2026-10-17)

### Findings and corrections

GitHub runs `39016849378` and `39017397993` reached readiness for all nine
services and gateway, then reported **93 passed / 5 failed** live tests. Two
failures were obsolete test contracts: baggage `/flow/map` returns the specified
zone list, and passenger security is exposed by `/flow/summary`, not the removed
`/passengers/security/status` path. Those checks now assert the actual contracts.

The other failures exposed real latency under the default 60x simulation:

- Baggage performed hundreds of sequential status/scan writes before consuming
  incidents. Induction and flight-wide arrival/departure changes now persist in
  batches, preserving per-bag scan history and facts. Independent conveyor bag
  writes use bounded concurrency while each bag's transitions stay ordered.
  Departed bags are removed from the conveyor instead of advancing again later.
- Analysis/passenger consumers drain larger event bursts. Analysis evaluates the
  latest clock once per batch while processing every fact/receipt. Passenger and
  baggage commands arriving before the first clock are retained until a valid
  `SimClockTick`, rather than logged and discarded for lacking a clock. This is
  not a transactional Kafka inbox: the broader G1 crash window remains open.
- These services now stop/await their consumer task before closing its producer
  and Neo4j driver. Clock rewind releases the analysis baggage timestamp guard;
  naive/aware legacy timestamps are compared in UTC.

Checking the assertions behind the previous restart pass found another real
recovery error: writes used `last_scan_zone` while the baggage loader read only
`current_zone`. Recovery now reads the written field, restores arrived queues,
and preserves tag, dangerous-goods, passenger and terminal-routing metadata.
Repeated rebuilding does not duplicate queues. This closes that specific defect,
not the remaining transit/incident/vehicle recovery work in G9.

Browser inspection then exposed an independent broken What-If Replay page:
Report posted the wrong keys, KPI nodes used the wrong discriminator/shape, and
replay rows used `scenario_id` where responses contain `id`. The page and typed
API now use the real contracts and render nested KPI distributions. Gate
interventions send `delta`, matching the engine. Completed parent scenarios are
distinguished from replay children in list summaries.

Replay creation previously dropped demand multiplier, route changes and weather
date, and shared mutable infrastructure with its parent. It now copies the full
parent configuration, retains its persisted seed/disruption, resets only job
metadata and requested decisions, and requires a completed parent (409 otherwise).
That completion requirement is an explicit contract correction documented in the
planning spec. Live tests exercise both replay and report creation and verify
preserved inputs and completed results.

`PLANNING.md` no longer describes the unimplemented automatic 30-minute outcome
loop as delivered. `ROADMAP_USECASE.md` qualifies the counterfactual graph: it is
constructed from configured decisions/results, not measured causal event history.

### Actual local evidence

Docker Desktop is now working. Validation used an isolated export of the intended
Git tree, excluding unrelated Raspberry Pi/access-control edits, under Compose
project **`art-ldt-validation`** with its own volumes. The disposable project was
reset and started from empty volumes at the default 60x speed. All service images,
gateway and dashboard built. Container Python is 3.11; host tests used 3.14.3.

| Check | Result |
|---|---|
| Strict readiness | All nine services and gateway return 200 from `/ready`. |
| Python unit suite | **962 passed**, no skips, including actual LightGBM/PPO artifact tests and new burst/recovery/replay regressions; 18 deprecation/undefined-AUC warnings. |
| Complete live integration suite | **100 passed**, no skips, final run **112.55 s**. An earlier clean-start run also passed all 100 tests. |
| Live LDT behavior | Real forecast source/clock, isolated operational what-if, approved proposal recovery → Kafka owner execution → durable receipt → analysis confirmation, owner restart and fresh receipt on duplicate replay all pass. |
| Live planning behavior | Actual synthetic Monte Carlo/financial computation, unchanged persisted results after planning restart, configuration-preserving replay/report and real graph/row shapes pass. |
| Restart coverage | Full Compose restart now requires readiness of all nine services and gateway; individual owner restarts also pass. Restart subprocess failures are no longer ignored. |
| Incident propagation | Power failure requires all mapped zones offline; sorting failure and resolution/restore checks pass locally. |
| Dashboard tests/build | **44 passed**, 9 files; TypeScript/Vite build passes. Existing bundle-size/Browserslist warnings remain. |
| Gateway | Unchanged in A17; **22 tests** and build validated in A15. |
| Browser | Flight/passenger pages show live API/WS data. What-If Report produces five completed children and displays parent/replay KPI values without a crash. |
| Ruff / diff whitespace | Changed services, scripts and tests pass the declared baseline; staged whitespace check passes. |

The local stack remains available at `http://localhost:5173`. The browser report
is a functional check, not evidence of calibrated benefit: identical results are
valid when the chosen intervention does not affect that synthetic scenario.

### Completion decision

**Keep this roadmap active.** Local functional checks now pass, but G1–G12 still
include material unfinished behavior: transactional delivery/dedup, unified rates
and effect/ranking models, unsupported actions, interrupted-job recovery,
automatic attributed outcomes, complete projections and deployment/load work.
Neither these test passes nor older plan checkmarks justify saying every planned
capability is implemented or archiving the roadmap into an old-roadmap folder.


## 14. A18 — Preserve incident ownership across cascades and recovery (2026-10-17)

After A17's local pass, GitHub run `39037216847` passed all Python/Node unit,
lint and build jobs, built the stack and reached all-service readiness. The live
gate then failed with **36 passed / 1 failed**, stopping at the power-A chain.
The remaining integration tests did not run in that CI attempt.

The captured facts explain a further correctness defect: baggage set all three
power-A zones offline at 13:41:17.145, then restored them at 13:41:17.530 when a
short-lived cascade child resolved. The parent power failure, assigned a
101-minute repair time, was still active. Location matching alone was allowing
an unrelated child to release its parent's restriction.

Owners now preserve restriction identity:

- Baggage tracks `system_failure` IDs, ignores unrelated child resolutions and
  keeps overlapping zones offline until every affecting failure resolves. It
  rebuilds active/contained failures from Neo4j on startup.
- Passenger security tracks breach IDs per terminal. Unrelated child resolution
  and resolution of only one overlapping breach cannot unfreeze security. Queue
  recovery also restores active/contained breach ownership.
- Flight restrictions retain incident IDs through containment and restart.
  Only resolution removes that incident's restriction. Weather has a separate
  restriction set, so improvement in weather cannot reopen a runway still
  blocked by an incident, and incident resolution cannot remove a weather block.

Regressions exercise the actual incident producer payload for the failing
parent/child sequence, overlapping failures/breaches, containment, weather
isolation and all three owner recovery paths. The existing static location-map
check now targets the map declaration rather than an earlier reference.

The live conveyor-chain fixture uses **10x only during those three assertions**
and restores the prior speed afterwards. The shortest random repair is ten
simulation minutes; at 60x it can legitimately expire before the 30-second
propagation assertion budget. Controlled lifetimes keep that assertion valid.
The timeout and all-zone assertions remain unchanged. The rest of the local
stack runs at its default speed. This does not establish a sustained-load SLO.

**Validation:** **971 Python unit tests passed**, no skips, 18 existing warnings;
Ruff passes for changed services/tests. The rebuilt local stack passes
**all 100 live integration tests** with no skips in **115.93 s**, including
all-service readiness, full restart, planning/replay and command confirmation.
Dashboard/gateway checks remain as recorded in A17; their code is unchanged here.

The roadmap remains active under the completion conditions in §10/§13.


## 15. A19 — Command scheduling and clock-dependent restart readiness (2026-10-18)

GitHub run `39038375527` passed the unit/lint/build jobs and all-service
readiness, then stopped at **49 passed / 1 failed** in the live gate. The owner
receipt for the recovered approval did not arrive within 90 seconds; the cleanup
command also timed out. The passenger logs subsequently show the original lane
change executing. The fact/tick workload was delaying command consumption, rather
than a receipt being sufficient proof of timely control.

Passenger commands now use a dedicated Kafka consumer in the same service
process. The command loop remains serial but can run while the fact/tick loop
awaits database I/O. It waits for a real simulation clock, retries transient
handler failures and commits offsets only after receipt handling. A new group
starts at earliest offsets; persisted receipts make historical redelivery safe
without repeating completed operations. Both loops shut down before adapters
close. Broker delivery still lacks a transactional outbox, and the G1 domain
write/receipt crash window remains open.

The resumed local stack also exposed a separate restart defect: `/flights`
silently removed its current-day filter before the first clock, returning all
seven seeded days (2,940 flights) instead of the current 420. The flight list now
returns 503 until a clock is available, and readiness includes this condition.
This is an explicit contract correction in the flight spec. A paused simulation
must emit a tick or resume before a restarted flight service becomes ready.

Regressions cover command execution while a tick is blocked on I/O, waiting for
clock/retrying before offset commit, and refusing an unbounded current-day query
before the clock. The live restart assertions and time budgets are retained.

**Local validation:** **974 unit tests passed**, no skips, 18 existing warnings;
Ruff passes for both changed services and regression files. The isolated Compose
stack passes **all 100 live integration tests**, no skips, in **160.93 s**,
including all-service readiness, command confirmation/replay and full restart.
Staged runtime/test files match the tested export. Dashboard and gateway source
are unchanged from the A17/A18 validation; unrelated local work is excluded.

**Remote validation:** GitHub run [39108523313](https://github.com/Jupiter41/arthur-airport/actions/runs/39108523313)
passes on runtime commit `20da5150a6673f4829d60ae6ee7fb85b2402444a`: all lint,
unit, Node build/test and full-stack jobs succeed. All nine services plus the
gateway pass readiness; **100 live tests pass**, no skips, one existing warning,
in **290.84 s** on the clean CI stack. This includes the formerly failing
incident chain, command confirmation/replay and restart checks. CI also passes
**974 Python units**, **44 dashboard tests** and **22 gateway tests**.
The subsequent guide/validation-record update changes documentation only.

The roadmap remains active: these corrections do not close §10 G1–G12.

### Follow-up documentation audit

The warning at the top of `AUTONOMOUS_OPS.md` had left misleading claims in the
body. The guide now distinguishes the five action types with concrete mappings
from the nine advisory types, documents required target IDs and the owner-receipt
lifecycle, and stops calling skipped candidates a durable decision log. It
corrects RL from LightGBM/history replay to the actual synthetic-environment PPO
training path. The NL incident endpoint parses parameters only; it does not inject
them. Mode/score wording now reflects the actual gates without implying calibrated
safety or savings. `PLANNING.md` calls P5–P95 a sampled-model range rather than an
operational confidence guarantee. G8's register now reflects the already-corrected
manual-outcome documentation. These are corrected claims, not newly implemented
action handlers or calibrated intelligence.


## 16. A20 — Atomic cost/carbon event accounting (2026-10-18)

**Delivered portion of G1:** cost-service no longer marks input IDs seen before
processing or commits one charge at a time. Each supported event runs in a
managed Neo4j transaction with a locked `CostRuntime` checkpoint. It commits
cost/carbon records and relationships, `CostInbox`, checkpoint and `CostOutbox`
together. The checkpoint also retains gate starts, the dated staffing hour,
current-day summaries, EU261 exposure and seven previous days of summary history.
Non-clock facts without an explicit day derive it from the simulation clock,
including late prior-day facts, rather than silently using day 1.

Calculators collect effects in a task-local batch. Running caches become visible
only after commit; retries after an ambiguous commit restore the committed
snapshot rather than charging twice. Independent workers serialize financial
calculation against the checkpoint and durable inbox. Existing ledger records
initialize that checkpoint without deleting or rewriting their charges.

The Kafka consumer retries failed processing before later messages, starts a new
group at earliest retained offsets and commits fetched offsets only after the
whole batch is safe. Missing IDs use broker topic/partition/offset identity;
direct calls require a nonempty ID and validated envelope. The outbox publishes
existing financial/carbon facts plus `FinancialEventProcessed`, retaining stable
event IDs until broker confirmation. Startup/shutdown now restores the checkpoint
and waits for financial consumer/outbox tasks before closing adapters.

**Validation:** twelve focused unit cases replace A1's three process-local tests.
They cover partial-write rollback, ambiguous commit acknowledgement, durable
dedup/cache repair, gate/staffing checkpoint reload, migration/EU261 exposure,
late-day attribution, outbox retention and commit ordering/unfinished shutdown.
The full Python unit suite passes **983 tests**, no skips, 18 existing warnings.
Ruff passes for cost-service and the new tests.

Six live checks use actual Neo4j and Kafka on the isolated Compose stack. They
inject failure after ledger writes and after outbox/inbox writes, proving the
transaction rolls back; run independent competing worker processes; abruptly
exit after a committed boarding event then recover its gate window; inject a
publish failure and demonstrate actual duplicate broker delivery with the same
event ID after the acknowledgement/deletion gap. Fresh Kafka duplicates after a
real cost-service restart must reach committed consumer offsets while ledger
counts remain unchanged. These are additional checks, not weakened older tests.
All **106 live integration tests pass**, no skips, in **183.18 s**, including
all-service readiness and existing full restart/planning/command checks. The
final new-group offset setting and type annotations are followed by a rebuilt
image and rerun of all twelve unit/six live financial regressions. GitHub run
[39111013228](https://github.com/Jupiter41/arthur-airport/actions/runs/39111013228)
passes all jobs on `919faf35bab59b59a1e315bb1c270d2f2bc6b478`: **983 units** and
**106 live tests**, no skips, live duration **215.78 s**; Node lint/build and
44 dashboard/22 gateway tests also pass.

**Remaining limits:** this closes the cost-service transaction/dedup portion,
not all of G1. Flight/passenger/baggage writes, receipts and fact publication
still need atomic boundaries. Outbox delivery is at least once, not exactly
once. Legacy lost/duplicate charges are not retrospectively repaired; old
in-memory gate windows cannot be recovered by migration. Simulation rewinds with
new IDs need an epoch policy. Per-process caches are not a coherent distributed
read cache. Accounting perspective/rate unification (G2), calibrated financial
effects/outcomes and the other §10 gaps remain open. Keep this roadmap active.


## 17. A21 — Durable planning execution and recovery (2026-10-18)

**Delivered planning portion of G7:** persisted pending scenarios now form the
job queue. Routers/templates/replay/report no longer schedule an independent
FastAPI background execution. A lifespan worker claims work before computing,
using a Neo4j lock, renewable lease and unique fencing token. Claim commits the
actual seed and increments `attempt_count`. An existing unexpired owner excludes
competing workers; expired/legacy interrupted runs can be claimed automatically.

Recovered attempts restart both Monte Carlo phases using the persisted seed and
complete configuration, with attempt progress reset. They do not merge partial
aggregates from different attempts. Heartbeats use Neo4j wall time solely as
scheduling metadata; simulated days/seeds remain the engine inputs. Checks
between simulated days stop interrupted/stale computation. Every progress write
checks ownership; result, completed status and both outbox facts commit together.
An expired/replaced worker cannot overwrite progress, results or failure state.
Graceful shutdown releases its job to pending; abrupt exit leaves a recoverable
lease. Readiness now includes the worker task.

Public scenario/summary/status data includes `attempt_count`; replay children
start their own attempt count. Job timestamps use UTC metadata, and the status
endpoint handles legacy naive timestamps and stops elapsed duration at completion.
`PLANNING.md` no longer describes lost in-memory records as current behavior.
The planning skill now documents the durable worker and labels its unimplemented
outcome measurer as planned G8 work.

**Validation so far:** seven new lease/runner units and two elapsed-time cases
join the preserved persistence tests. **992 Python units pass**, no skips, four
remaining warnings (audit timestamp, LightGBM/sklearn). All five new live job
checks pass against Neo4j: independent competing processes; stale token rejection;
atomic completion rollback/retry; heartbeats beyond the original expiry; abrupt
process exit followed by automatic service recovery using seed 0 and attempt 2.
The complete isolated Compose gate passes **all 111 live tests**, no skips, in
**218.50 s**, with all nine services and gateway ready. This retains the existing
financial, prediction, command, planning/replay and full-restart assertions.
Staged runtime/tests match the tested export. GitHub run
[39112359217](https://github.com/Jupiter41/arthur-airport/actions/runs/39112359217)
passes all jobs on final runtime commit `26ff913972441dd8230677ffa168ed17b3ca7f6a`:
**992 Python units**, **111 live tests** (no skips, **287.72 s**), all-service
readiness, Python lint, Node builds, **44 dashboard tests** and **22 gateway
tests**. CI's two unit warnings are the existing ML warnings; its one live warning
is pytest's existing class-fixture deprecation. The planning commit also passes
its independent run `39112175576`. Subsequent changes update documentation only.

A follow-up audit corrected `FinancialEventProcessed.sim_day` for late prior-day
facts: it now matches the records' billing day, rather than the currently selected
summary day. The existing late-fact regression now checks both records and the
outbox payload; all twelve ledger regressions pass after this correction.

The documentation follow-up also removes an old `seed or random_value` example
that discarded seed 0, and describes the actual nullable/meaningfulness-flag IRR
response. A12's historical no-recovery note now points to this delivered worker.

**Remaining G7 scope:** analysis proposal ownership across replicas and training
job interruption recovery are not delivered here. One scenario runs per worker;
there is no partial Monte Carlo checkpoint resume. Persisting a seed/config does
not freeze changing input files or model versions. The job/financial regressions
do not certify sustained load or every service's replica behavior. Keep the
roadmap active under the remaining §10 completion conditions.


## 18. A22 — Shared, durable financial rates and planning snapshots (2026-10-18)

**Delivered rate portion of G2 and rate-input portion of G7:** one synthetic
reference table now lives at `services/_common/data/cost_rates.json`.
`_common.financial_rates` loads defaults and supplies shared carrier resolution;
`finance_constants` derives compatibility exports from that file. There is no
second editable cost fixture. Planning landing calculations use the shared MTOW
table rather than estimating weight from seat count.

Cost-service persists effective rates and their SHA-256 content identity in its
existing Neo4j runtime checkpoint. Financial inputs and rate updates serialize on
the same lock. PATCH validates a detached candidate before saving; unknown nested
keys, negative/non-finite amounts and booleans used as money are rejected without
partial updates. Concurrent workers do not lose each other's changes. The rate
table and `CostRatesUpdated` outbox fact commit together. GET/recommendations read
the committed table; financial/carbon records and facts retain `rates_version`.
Restart preserves overrides, and optional fuel refreshes use the same durable
update path. Existing charges are not retroactively repriced. Rate-event time is
the last consumed simulation clock, or the fixed synthetic epoch before a tick.

A first planning job claim reads the cost-owned graph snapshot, or shared defaults
before cost initialization. It persists the full table and content version before
computing. Both baseline/scenario phases and benefit extraction use that snapshot,
including carrier fee overrides, compensation tiers and delay valuation. Expired
job recovery and replay children retain the original table; new independent jobs
select current committed rates. Results expose the content version. No operational
writes or service-to-service HTTP calls are added.

**Audit/correctness corrections:** invalid PATCH previously mutated earlier valid
fields before raising on a later invalid field. This is now all-or-nothing. The
full live gate also caught missing Kafka routing for the new rate event; a stable
`financial-rates` key and direct broker-publication regression cover that path.

**Local validation:** **1,007 Python units pass**, with four existing warnings,
and affected-service/shared-rate Ruff checks pass. **All 112 live integration tests
pass**, no skips, in **277.37 s**, on the isolated `art-ldt-validation` Compose
stack. All nine services plus gateway pass readiness. The new real Neo4j/Kafka
case checks independent concurrent rate writers, confirmed broker delivery,
persistence across restart, invalid REST patch rollback, and a recovered planning
job completing with its original rate snapshot/version after live rates change.
Fifteen new unit cases cover validation/rollback/version identity, rate-event
routing, shared fee/MTOW use, benefit assumptions and recovered input stability;
existing replay tests additionally check snapshot copy independence. The final
optional fuel guard rejects NaN/infinity (39 focused cases pass after this small
follow-up), and the cost image is rebuilt with all-service readiness rechecked.
All staged runtime/tests match the tested isolated tree. GitHub run
[39149495301](https://github.com/Jupiter41/arthur-airport/actions/runs/39149495301)
passes every job on `a9588748c767cf40991fbadea797937b852fbdb5`: **1,007 units**,
**112 live tests** (no skips, **302.29 s**), Python lint, Node builds and gateway
tests. CI's two unit warnings and one live warning are existing ML/pytest notices.

**Still open:** airport/airline perspective and mixed P&L migration (G2); separate
planning/live compensation claim assumptions and action models (G4); schedule,
weather and model input snapshots, analysis ownership/training recovery and partial
Monte Carlo resume (G7); all other §10 gaps. This does not certify calibrated
financial benefits or complete the digital twin. Keep this roadmap active.
Legacy in-memory overrides cannot be recovered on upgrade, and historical planning
jobs without a rate snapshot cannot retrospectively recover their original inputs.
Rate selection is at processing/claim time; historical event-time tariff tables
for late inputs are not reconstructed by this slice.


## 19. A23 — Recover daily financial projections from the ledger (2026-10-18)

**Browser-discovered correction to the A20 checkpoint:** the local rate editor
saved a temporary passenger fee, retained it after a page reload and restored the
original value successfully. The surrounding live dashboard nevertheless displayed
zero cost/revenue while day-one Neo4j P&L contained €19,786,995.27 in charges.
This was a backend projection defect, not proof that the ledger had no data.

The old retention rule used the largest billing day to drop older summaries,
including the currently selected day after future/rewind inputs. Returning to an
evicted day created an empty/partial aggregate instead of rebuilding its existing
charges. Startup now rebuilds the selected day's financial/carbon aggregates from
the authoritative records, repairing older incomplete checkpoints. Event processing
restores any missing affected day before writing that event's records, so existing
and new effects are counted exactly once. Retention pins the selected day and keeps
seven other summaries. The full ledger is never deleted by cache eviction.

Three new transaction tests cover selected-day return, legacy damaged-checkpoint
restart and late input after eviction, including financial/carbon totals and the
eight-summary bound. A real Neo4j regression selects a distant day, returns to day
one and compares the rebuilt cache with independently aggregated records. This
does not define simulation epochs or reverse/re-deduplicate new business events.

**Local validation:** **1,010 Python units pass** (four existing warnings),
Ruff checks pass, and **all 113 live tests pass**, no skips, in **288.54 s**.
All nine services and gateway pass readiness. Staged recovery code/tests match the
isolated tested tree. The browser displays the recovered cost/revenue totals and
eight categories, replacing its false empty-state message. Proof: `local-cost-recovery-a23.png` in the task
validation artifact directory; no frontend source was changed.


**Final CI validation for A23:** run
[39150644982](https://github.com/Jupiter41/arthur-airport/actions/runs/39150644982)
passes **every job** on runtime commit
`0770d9896ffab1b4205f7d13fb6621cd9d2526cb`: **1,010 Python units**,
**113 live tests** (no skips, **342.02 s**), all-service readiness,
Python lint, Node builds, **44 dashboard tests** and **22 gateway tests**.
The two CI unit warnings and one live warning are the existing ML/pytest notices.
Its `full-stack-validation` artifact is saved locally under `ci-0770d98`.
After the live tests, the local readiness-only gate again passes all nine services
and the gateway. The subsequent commit updates documentation only; runtime/tests
remain the exact source validated by this run. The roadmap remains active for the
remaining §10 gaps and is not moved into the old-roadmap archive.


## 20. A24 — Coordinate analysis proposals and durable command delivery (2026-10-18)

**Delivered G7 proposal portion and G1 analysis-action portion:** authoritative
Neo4j transactions serialize creation, human decisions, retry attempts and owner
receipts across independent analysis workers. Active identical bottleneck/action/
parameter targets and submitted recommendation identities deduplicate creation.
Versioned caches cannot overwrite newer committed decisions. Approval/rejection
and confirmed-log endpoints read committed graph data on every request.

Proposal changes, lifecycle facts and canonical domain commands commit together
in an analysis-owned outbox. Broker failure or process exit retains the pending
work. Publication is at least once with stable envelopes/event IDs; all attempts
use the same command ID. A five-simulation-minute receipt timeout schedules at
most one retry for the shared clock value. Only a matching owner topic/type
receipt confirms execution; dispatched means durably queued. No Kafka publication
occurs inside Neo4j transaction callbacks. Legacy proposals migrate in place.

The last validated consumed clock is shared in Neo4j for REST decisions on any
replica. Broker offsets fence stale clock writers after reassignment. Consumer
offsets commit after durable handling/evaluation; new groups replay retained
inputs. The outbox worker is independent of simulation ticks and included in
readiness, so a committed command can recover while the clock is paused.

**Local validation:** all **1,022 Python units pass**, with four existing warnings,
and affected-service Ruff passes. The all-service readiness gate passes all nine
services plus gateway, and **all 121 live integration tests pass**, no skips, in
**335.96 s**. Real Neo4j/Kafka cases cover partial transaction rollback (both
proposal and outbox), independent worker creation/approval/rejection/retry
contention, broker failure/acknowledged-publication gaps and process exit after
command commit followed by owner-confirmed recovery.

Final adapter review also found a receipt arriving after the caller's cache read
but before dispatch: the adapter now reports an already-confirmed database result
without scheduling another command. A unit regression covers the stale caller;
the rebuilt final image passes all **eight analysis live cases** in **57.11 s**,
including a fresh worker resolving that race. Staged runtime/tests match the
isolated tested tree. Final CI evidence is recorded below.

**Still open:** recommendation/bottleneck discovery and full projections are not
a shared replicated analysis engine (G9); training recovery, other planning input
snapshots and partial Monte Carlo resume remain G7. Owner mutation/receipt/outbox
atomicity remains G1. Epochs, calibrated outcomes/ranking/action effects, mixed
accounting and the other §10 gaps remain active. This is not completion of every
service's intended digital-twin behavior; keep this roadmap out of the archive.


**Follow-up plan/implementation audit:** `services/analysis-service/services/training_manager.py` still owns
process-local `runs`, `active_run` and a subprocess handle, without a shared
training-job recovery store. `services/analysis-service/services/recommender.py` still sorts largely by
`confidence_score`, while cost has its own recommendation generator. The current
`k8s/services` tree still lacks cost/planning service manifests. These concrete
checks confirm the remaining G7/G5/G12 entries; the A24 proposal tests do not close
them.


**Final CI validation for A24:** run
[39153728540](https://github.com/Jupiter41/arthur-airport/actions/runs/39153728540)
passes **every job** on runtime commit
`4998bd6dde3a0fe87bd20d7a48cb61eacc3dc74e`: **1,022 Python units**, **121 live
tests** (no skips, **350.26 s**), Python lint, Node builds, **44 dashboard tests**
and **22 gateway tests**. All nine services plus gateway pass readiness. The two
unit warnings and one live warning are the existing ML/pytest notices. The
`full-stack-validation` artifact is saved locally under `ci-4998bd6`. Final local
post-test readiness also passes every service. This subsequent commit updates
only roadmap evidence; runtime/tests remain those validated in CI. The §10 gaps
above remain open, so the roadmap stays active rather than moving to the archive.


## 21. A25 — Impact/cost ranking for the recommender (2026-10-26)

**Delivered ranking portion of G5.** The analysis recommender ranked
interventions by `confidence_score` alone (`recommender.py:69`), so a
high-confidence trivial action (an announcement) could outrank a high-impact one
(saving 40 missed connections). A new pure module
`analysis-service/services/ranking.py` derives, for every recommendation, a
benefit and a cost on a **common synthetic scale** — passenger-minutes saved vs.
"disruption-minutes" — from the recommendation's own `parameters` and the owning
bottleneck's `metrics`/`affected_entity_count`, then computes

    priority_score = impact_value * confidence_score / cost_value

`generate_recommendations` now scores each recommendation and sorts by
`priority_score` (un-applied first, then applied), rather than confidence. Three
fields (`impact_value`, `cost_value`, `priority_score`) were added to the
`Recommendation` model and the dashboard's `AnalysisRecommendation` type — all
additive and defaulted, so no existing consumer breaks. Cost is floored
(`COST_FLOOR = 5.0`) so a "free" action never scores as infinitely good, and
`bool` values are rejected where a passenger/flight count is expected (int-subclass
trap, matching the convention established in A9's `to_flight_command`).

**Validation**
- `.venv` (Python 3.12) `pytest tests/unit` → **1,013 passed**; the 14 failures
  are pre-existing and solely missing optional ML deps locally (`joblib`, `torch`)
  — identical set before and after this change, so no regression. CI installs
  those deps.
- `tests/unit/test_analysis_ranking.py` (new, 5 tests): cost floor, field
  population + exact `impact * confidence / cost` identity, impact scaling with
  `passengers_saved`, `bool`-count rejection, and the headline case —
  a 0.70-confidence 40-connection hold outranks a 0.99-confidence announcement.
- `test_analysis_recommender.py`: the old `test_recs_sorted_by_confidence` (an
  invariant the new sort no longer guarantees) was replaced by
  `test_recs_sorted_by_priority_score`, asserting monotone `priority_score`
  ordering and strictly positive scores.
- Mutation checks (prove teeth): (1) collapsing `priority_score` to
  `confidence_score` fails the field-identity and override tests; (2) reverting the
  sort key to `confidence_score` fails `test_recs_sorted_by_priority_score`
  (confirming confidence-order ≠ score-order on that fixture). Both restored green.
- Ruff clean on all changed Python; dashboard `tsc -b` clean; `npm test` → **44
  passed**.

**Honest scope note.** This closes only the **ranking** half of G5. The impact/cost
weights are heuristic and **not calibrated** against measured outcomes (G8) — they
exist to make magnitude and cost matter, not to assert true benefit. Analysis and
cost-service still run **separate** recommenders; emitting cost-service signals into
this one ranking path, and calibrating the scale, remain open G5 work. Nothing here
was run against a live stack; the logic is pure and fully unit-tested.


## 22. A26 — Kubernetes manifests for cost and planning (2026-10-26)

**Delivered manifest portion of G12.** `k8s/services/` had deployment+service
manifests for seven domain services plus gateway and dashboard, but **not** for
`cost-service` (8008) or `planning-service` (8009) — the exact gap the A24
follow-up audit flagged, meaning a Kustomize deploy silently omitted both.

- New `k8s/services/cost-service.yaml` and `planning-service.yaml`, mirroring the
  existing service pattern (shared-config/shared-secrets `envFrom`, `/ready`
  readiness + `/health` liveness probes on the correct port, OTel service name).
  Both are **single-replica by design** — cost-service owns a durable Neo4j
  checkpoint (A20) and planning a lease-based Monte Carlo worker (A21), so extra
  replicas would only add contention; this matches analysis/incident/weather/sim,
  which also carry no HPA. Planning gets a heavier resource envelope (Monte Carlo +
  LightGBM + PuLP/CBC): 512Mi/1.5Gi vs. cost's 256Mi/512Mi.
- Added both to `k8s/services/kustomization.yaml`.
- Added `COST_SERVICE_URL`/`PLANNING_SERVICE_URL` to the api-gateway manifest —
  without them the gateway `proxy.ts` would fall back to its in-code defaults, but
  making them explicit matches every other service URL already declared there.

**Validation**
- `kustomize build k8s/` succeeds; the two services appear in the rendered output.
- YAML parses; the manifests are structurally identical to the nine known-good
  service manifests. `gateway proxy.ts` confirmed to read both env var names.
- **No live apply:** the kubeconfig on this machine points at a cluster whose RBAC
  denies this user `get` on `deployments`/`services` in the namespace, so
  `kubectl apply --dry-run=client` cannot complete (it does a server GET). The
  server did resolve every Kind/GVK, including the two new resources. Applying to a
  real cluster and validating load/crash/replica behavior remains open G12 work.


## 23. A27 — Consolidate logging/tracing/profiler into `_common` (2026-10-26)

**Delivered the transport-utility portion of G3.** A5 promoted `_logging`,
`_tracing` and `_profiler` into `_common` but converted only flight-service; the
other eight services and `_template` kept byte-identical local copies — the exact
**28 tracked files** §10 G3 counted. They were identical to `_common`'s except for
docstring example import paths, so they were pure drift risk: a change to one of
the three concerns needed nine edits.

**Change**
- Rewired every `from _logging/_tracing/_profiler import …` in the eight remaining
  services' `main.py` and `kafka/producer.py` (13 files) to `from _common._… import
  …`, matching flight-service's A5 form.
- `git rm` all 28 local copies (`_logging` ×10, `_tracing` ×9, `_profiler` ×7 across
  the eight services + `_template`). Only `services/_common/{_logging,_tracing,
  _profiler}.py` remain.

**Validation**
- `pytest tests/unit` → **1,022 passed** (the full CI count, once `joblib`/`lightgbm`
  are present locally); the 5 residual failures are `torch`/heavier-ML-env only and
  predate this change. Before installing those deps the suite was 1,013 passed / 14
  dep-failures both before *and* after the change — i.e. zero regression.
- Ruff clean across all nine services.
- Container-layout import-smoke (cwd = service dir, `_common` resolvable as the
  `/app/_common` mount is): **all nine** services `import main` cleanly, and the
  emitted log line now reads `"logger": "_common._tracing"`, proving the `_common`
  module is the one in use. (passenger-service needed `joblib` first — same
  pre-existing dep gap as the unit skips, not an import-wiring failure.)
- Symbol check: `setup_logging`, `init_tracing`, `shutdown_tracing`,
  `get_trace_context`, `get_perf_stats`, `tick_timer`, `update_speed` all resolve
  from `_common`. No remaining `from _logging/_tracing/_profiler import` anywhere
  outside `_common`; no doc/Dockerfile references to the deleted copies.

**Live validation (added during A28's stack bring-up).** The isolated `art-ldt-g6`
Compose stack — built from the tree *including* this change — brought **all nine
Python services + gateway to `/ready`**, and 65 existing live REST/cost integration
tests pass against it (`test_rest_endpoints.py`, `test_cost_endpoints.py`). So the
nine rewired services genuinely boot and serve under real Kafka/Neo4j with `_common`
as the only owner of these modules — stronger than A5's import-smoke bar.

**Honest scope note.** Two limits remain: (1)
the D1 transport remainder — 8× `db/neo4j.py` and 8× `kafka/producer.py`+`consumer.py`
are still duplicated, and `_common` still does not own the consumer loop, so G3 stays
partial; (2) `_common` reaches containers via a read-only **volume mount** (as it has
since A5), not baked into images, so the k8s manifests added in A26 would need the
mount (or an image `COPY`) before those pods could start — a pre-existing latent gap
this change extends from one service to nine, called out here because k8s remains
unvalidated under G12.


## 24. A28 — `incidents.commands` channel (2026-10-26)

**Delivered the incidents portion of G6.** Incident contain/resolve existed only
as REST actions (A8 wired the UI buttons); there was no command channel, so the
async bus couldn't carry incident intent the way it does flights/passengers/baggage
(A7/A11). `incidents.commands` closes that: incident-service is the sole consumer
and authority, executes `ContainIncident`/`ResolveIncident` via the **existing**
`lifecycle.contain_incident`/`resolve_incident` (so the usual `IncidentStatusChanged`
fact still flows), and emits a durable `CommandExecuted`/`CommandRejected` receipt on
`incidents.events` keyed on `command_id`.

**Change**
- Spec first: `EVENT_BUS.md` — `incidents.commands` in both catalogue tables (§2/§3,
  3 partitions keyed on `incident_id`, group `inc-svc`) and new §4.8f documenting the
  two commands, effects, rejection semantics, and the receipt.
- Pure `incident-service/application/commands.py`: typed `ContainIncident`/
  `ResolveIncident`, `parse_command`, and `validate_contain_precondition`/
  `validate_resolve_precondition` mirroring `lifecycle.VALID_TRANSITIONS` (contain only
  from `active`; resolve from `active`/`contained`; already-`resolved` is an idempotent
  success, not an error).
- Adapter: consumer subscribes to `incidents.commands`; `_dispatch` routes any
  `command_type` envelope to `_handle_command`, which uses the shared
  `_common.commands.CommandReceipts` lifecycle (process cache + persisted
  `CommandReceipt`) to dedupe, execute via `_execute_command`, persist and re-emit the
  receipt. New `incident_commands_total{command_type,outcome}` counter (added to the
  metric-contract allowlist).
- Infra: `docker-compose.yml` kafka-init now creates `incidents.commands:3:1`.

**Validation**
- Unit: `tests/unit/test_incident_commands.py` (13) — parse valid/invalid, envelope
  rejections, and the contain/resolve preconditions. Full suite **1,035 passed** (1,022
  + 13), same 5 `torch`/ML-env residuals; ruff clean on incident-service.
- **Live (isolated `art-ldt-g6` Compose stack, all nine services + gateway ready):**
  `tests/integration/test_incident_commands.py` (2) pass against real Kafka + Neo4j.
  It injects a real incident, publishes `ContainIncident` on `incidents.commands`
  (observer pinned to `incidents.events` watermarks before publishing), and asserts a
  `CommandExecuted` receipt **and** the incident transitioning to `contained`; a repeat
  with the same `command_id` re-emits the receipt with no second mutation; a command
  for a missing incident yields `CommandRejected`. This run also live-validated A27
  (all nine services boot with `_common` imports) and A26's gateway env.

**Honest scope note.** This delivers the **owner-side** channel + receipts, like A7 did
for flights before producers were wired. The analysis recommender does **not** yet
*propose* contain/resolve (no `_common.commands.action_command` mapping, no analysis
producer), so the channel is publishable by an operator/agent but not auto-proposed by
the autonomy loop — wiring that (and the other concrete action handlers) is the
remaining G6 work. Receipt delivery is at-least-once with a stable `command_id`, not
exactly-once; the owner mutation + receipt + fact are not one atomic transaction (the
G1 crash window applies here too).


## 25. A29 — Incident actions execute through the autonomy loop (2026-10-26)

**Extends G6 from an owner channel to a closed propose→execute→confirm loop.** A28
gave incident-service a command channel, but nothing on the analysis side could
*target* it: `_common.commands.action_command` mapped flight/passenger/baggage
actions only, so an approved incident proposal had no command to dispatch. A29 adds
the incident mapping — and because the A24 dispatch/outbox/receipt machinery is
already generic over `intent.topic` (it publishes to whatever topic the intent names
and matches receipts on `intent.topic.replace(".commands", ".events")`, and analysis
already consumes `incidents.events`), that one mapping is the whole change.

**Change**
- `_common/commands.py`: `action_command("contain_incident"|"resolve_incident", {...})`
  → `CommandIntent("incidents.commands", "ContainIncident"|"ResolveIncident",
  {incident_id, note?}, incident_id)` when a concrete `incident_id` is present; `None`
  otherwise (conservative, like every other mapping).

**Validation**
- Unit: `tests/unit/test_command_receipts.py` +4 — both action types map to the right
  topic/command/key/payload, note is optional, and a missing/empty `incident_id`
  yields no command. Full suite **1,039 passed** (same 5 ML-env residuals); ruff clean.
- **Live (isolated `art-ldt-g6` stack):**
  `test_incident_commands.py::test_approved_incident_proposal_executes_through_the_autonomy_loop`
  passes — inject a real incident, seed an **approved** `resolve_incident`
  `ActionProposal` in Neo4j, restart analysis-service (recovers the proposal *and*
  loads the new mapping from the read-only `_common` mount); analysis dispatches on
  `incidents.commands`, incident-service resolves the incident and emits
  `CommandExecuted`, and analysis marks the proposal `executed`. All three incident
  live tests pass together.

**Honest scope note.** This makes incident actions *executable when proposed*, reusing
the existing approval/dispatch/receipt path — it does **not** add a recommender that
*generates* contain/resolve recommendations with a concrete `incident_id` (that needs
new `ActionType`s, a `_recs_active_incident` option, and the `ACTIVE_INCIDENT`
bottleneck to carry the id). So the autonomy loop can now *carry out* an approved
incident action end-to-end, but won't *originate* one until that recommender work
lands. Same at-least-once / non-atomic (G1) caveats as A28.


## 26. A30 — Recommender originates executable incident actions (2026-10-26)

**Completes the incident autonomy loop's origination half (G6).** A28 gave the
owner channel, A29 made approved incident proposals execute; A30 lets the analysis
*recommender* generate them. The `ACTIVE_INCIDENT` bottleneck already carried
`incident_id` (`detectors.py:471`), so the recommender had the concrete target to
hand — it just never produced a resolve/contain recommendation.

**Change**
- `models/domain.py`: `ActionType.CONTAIN_INCIDENT` / `RESOLVE_INCIDENT`. (Safe to
  add: the RL action space is a fixed `NUM_ACTIONS=7` with its own name list, not the
  enum; `SAFETY_GUARDED_ACTIONS`/`blocked_actions` are explicit sets.)
- `autonomous.py`: both added to `SAFETY_GUARDED_ACTIONS` — resolving/containing an
  incident always routes to **human approval**, never auto-executes (the GDP rule).
- `recommender.py` `_recs_active_incident`: emits a `RESOLVE_INCIDENT` recommendation
  carrying `{incident_id, incident_type, location}` when the bottleneck has an
  `incident_id`, so (unlike the aggregate mitigations beside it) it maps to a real
  `incidents.commands: ResolveIncident` via A29's `action_command`.
- `ranking.py`: an incident-resolution case so the new rec gets a real
  impact/cost score rather than ranking last.

**Validation**
- Unit: `test_analysis_recommender.py` +2 — the rec is produced with the id and is
  executable (`action_command(...) is not None`), and is **absent** when the
  bottleneck has no `incident_id`. Full suite **1,041 passed** (same 5 ML-env
  residuals); ruff clean; approval/routing suites still green (safety-guarded → HUMAN).
- **Live (rebuilt analysis-service on `art-ldt-g6`):** injected a `runway_incursion`;
  `GET /api/v1/analysis/recommendations` then served a `resolve_incident` rec with a
  concrete `incident_id`, `executable: true`, `execution_status: "available"`,
  `priority_score 0.8`. This is a **manual** confirmation, not a committed test — an
  emergent-recommendation assertion is timing/sim-state dependent and would be flaky
  in CI, which is why the *deterministic* execution half is the committed live test
  (A29) and generation is covered deterministically by the unit tests.

**Honest scope note.** The incident loop can now originate → (human-approve) →
dispatch → execute → confirm. `contain_incident` is wired through the same machinery
but the recommender currently emits `resolve_incident` only (containment is a partial
mitigation; resolution is the terminal action worth surfacing). The *other* advertised
actions (GDP, rebooking, gate/taxi/baggage with concrete ids) remain the open G6 work.
Incident resolution is safety-guarded, so nothing here auto-executes without approval.


## 27. A31 — Concrete, executable gate reassignment recommendations (2026-10-26)

**Extends G6 to flight gates.** The gate-conflict recommender emitted a
`REASSIGN_GATE` rec with only `{original_terminal, alternate_terminal}` — no
`flight_id`/`gate_id`, so `action_command` returned `None` and it was advisory. The
`flights.commands: ReassignGate` **executor already exists** (A7/A11); the rec just
never named a target.

**Change**
- `state.py`: `get_free_gate_ids_by_terminal()` returns concrete free gate IDs per
  terminal (graph-loaded only; `{}` otherwise — no gate identities known yet). Reuses
  the same occupied/closed filter as the existing count helper.
- `recommender.py` `_recs_gate_conflict`: when a waiting flight (`get_flights_needing_gate`)
  and a free gate in the best alternate terminal both exist, emit a `REASSIGN_GATE`
  rec carrying `flight_id`+`gate_id` (→ executable). Falls back to the previous
  aggregate advisory rec when no concrete pair is resolvable.

**Validation**
- Unit: `test_analysis_recommender.py` +2 — a graph-loaded state with free Terminal-B
  gates and a landed gate-less flight yields a concrete, `executable` reassignment
  (`action_command(...) is not None`, carries the resolved `flight_id`/`gate_id`);
  with no graph, the rec stays aggregate/advisory (`executable is False`). Full suite
  **1,043 passed** (same 5 ML-env residuals); ruff clean.
- Execution path (`flights.commands ReassignGate`) is already live-validated
  (A11/event-chain suite), so A31's novel surface — concrete rec *generation* — is the
  part under test here, covered deterministically by the unit tests. No new live test:
  forcing a live `GATE_UTILISATION` bottleneck **and** a gate-less waiting flight
  concurrently is sim-state dependent and would be flaky (same reasoning as A30).

**Honest scope note.** `REASSIGN_GATE` is **not** safety-guarded (a routine, reversible
op), so a confident concrete reassignment *can* be auto-applied by the autonomy engine,
unlike incident resolution. Target selection is deliberately simple (first waiting
flight, first free gate in the least-congested alternate) — a real optimiser would weigh
walk distance, aircraft/gate compatibility and turnaround; that is left as future work.
DELAY_TAXI/baggage proposals and GDP/rebooking remain the open G6 items.


### Sprint-54 holistic live validation (A25–A31)

The full changeset (A25, A27, A28, A29, A30, A31) was validated **together on a
real stack**, not just per-slice:

- **Unit:** `pytest tests/unit` → **1,043 passed** (the 5 residual failures are
  `torch`/heavier-ML-env only and predate this sprint — the same set before and
  after every change). Ruff clean across all nine services.
- **Live:** isolated `art-ldt-g6` Compose stack, all nine services + gateway at
  `/ready`. `pytest tests/integration` → **119 passed** on the first full run; the
  only 1 failure + 4 errors were restart-interference from the new
  `test_incident_commands` proposal test (it restarts analysis-service immediately
  before `test_ldt_execution`), **not** a code regression — the stack stayed healthy
  and every test passed in isolation. The test was hardened to tolerate reset-during-
  restart and to leave analysis ready for the next module; re-running the two
  interfering modules in collection order then passed **7/7** in 37 s. So the
  effective live result is **all green**. 65 live REST/cost tests and the incident
  command loop were also exercised against this stack earlier in the sprint.

This is functional validation on a synthetic stack, not sustained-load or
deployment certification; the §10 gaps remain the authority on what is still open.

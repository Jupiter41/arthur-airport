# Repository audit for paper evidence

This report replaces the earlier informal draft. It is intentionally conservative: claims below are limited to what can be validated from the repository itself (file inventory, architecture docs, service structure, and commit history). Where the repository does not provide direct evidence, the wording says so explicitly.

## 1) Verified repository facts

The following numbers were verified from the current repository state.

- Commit history: 90 commits in `git rev-list --count HEAD`
- Service directories: 10 top-level directories under `services/` (API gateway, analysis-service, baggage-service, cost-service, flight-service, incident-service, passenger-service, planning-service, sim-orchestrator, weather-service)
- Service files: 109 files under `services/` in the current tree
- Service specifications: 9 `SPEC.md` files under `docs/services/`
- Cross-cutting skill files: 7 files under `docs/skills/`
- Architecture documents: 8 files under `docs/architecture/`
- Project-level operation docs: 2 agent-facing files (`AGENTS.md`, `CLAUDE.md`)
- Tracking/roadmap/audit-like files: no clear, repo-wide evidence of a formal sprint or audit ledger; the repository contains roadmap-related documents, but the project does not expose a verifiable “N sprints” or “M audit phases” structure in the working tree

These counts support the claim that the project is structured as a multi-service digital twin with explicit design and operations artifacts. They do not, by themselves, prove a particular research narrative; they show the repository has the material structure necessary for such a narrative.

## 2) What the repository does and does not show

### 2.1 Service structure is real and deliberate

The repository contains multiple service directories under `services/`, including:

- `api-gateway`
- `baggage-service`
- `cost-service`
- `flight-service`
- `incident-service`
- `passenger-service`
- `planning-service`
- `sim-orchestrator`
- `weather-service`
- `analysis-service`

The presence of a dedicated `api-gateway`, `planning-service`, and `sim-orchestrator` is consistent with a service-oriented architecture. The repo also contains service-specific `SKILL.md` files and a specification layer under `docs/services/`, reinforcing that the system was designed as a structured collection of domains rather than a single app.

### 2.2 Documentation density is high

The repository includes a layered documentation structure:

- `docs/architecture/` contains the system architecture and core rules
- `docs/skills/` contains cross-cutting operational guidance
- `docs/services/` contains service specs
- `AGENTS.md` and `CLAUDE.md` provide project instructions for automation and agent workflows

This is evidence of a specification-first workflow. The documentation density is real and can be counted. It supports the interpretation that the project was engineered deliberately, but it does not prove an exact research methodology or a publication-grade process by itself.

### 2.3 No direct evidence of a formal sprint ledger

The repo contains roadmap and planning files, but no clear, systematic count of sprint iterations or milestone phases is present. The repository does not expose a machine-readable artifact such as:

- a sprint log with numbered phases,
- a milestone table with dates and issue counts,
- or a formal audit file enumerating “N stages of refinement.”

As a result, any claim that the project had “X sprints” or “Y audit rounds” is not verifiable from the repository alone. The correct phrasing in a paper is: “No formal sprint ledger is present in the repo; the evidence is instead based on commit history and domain evolution.”

## 3) Evidence from the commit history

The git history is useful as a trajectory signal, but it should not be overinterpreted as narrative evidence without checking the actual file changes.

### 3.1 Feature-oriented commits are present

The repository contains commits whose messages use domain-oriented labels such as:

- `feature: planning service & dashboard, not fully tested yet`
- `feature: better planning + doc`
- `feature: planning cost model & app robustness`
- `phase 1 roadmap use case - carbon, disability planning`

This supports the general claim that the project grew through feature additions in specific domains. However, commit messages are only intent markers; they are not proof of the exact files changed or the impact breadth without checking the corresponding diff.

### 3.2 Refactor and stabilization commits are present

The history also includes refactor and repair commits such as:

- `big refactor of pages into subfiles + better comparison & BTS data + capacity planning`
- `fix: a lot of bugs for data sources + refactor + better comparison & cost`
- `refactor: big refactor of new pages + better error handling + common components`
- `better docker`
- `fix: D6`

These commits show iterative adjustment and improvement after initial implementation. That is consistent with a progressive, revision-heavy development process. It is not, on its own, proof of a specific “before/after” narrative beyond the repository’s revision history.

### 3.3 The project timeline is progressive, but not formally classified in the repo

The history suggests a staged evolution from initial scaffolding and UI/data work to planning, cost modeling, operational hardening, and documentation. This is a valid interpretation of the commit sequence, but the repo itself does not encode a formal “layer-by-layer maturity model” with metadata or labels. The progression is visible in the timeline, not in an explicit artifact.

## 4) Evidence for “new features added don't touch other services”

This claim is not supported for the five refactor commits audited below. The actual diffs show broad cross-service and cross-layer changes.

### What the repo supports

The structure of the codebase is service-aligned: different service folders correspond to different domains. That is an architectural property, but it does not imply that refactors remained local.

### What the audited diffs show

The following five commits were checked with `git diff <hash>^ <hash> --stat`:

- `23bea42`: 94 files changed, including shared infrastructure, API gateway, four domain services, dashboard, architecture docs, and tests.
- `8536eab`: 88 files changed, primarily a dashboard-wide restructuring, but also changes in cost, incident, passenger, planning, and simulation services.
- `10536f1`: 55 files changed, including dashboard, analysis, gateway, cost, passenger, planning, tests, and Docker configuration.
- `4d8e4b4`: 41 files changed, including dashboard-wide refactoring plus cost and passenger services.
- `22c5c18`: 45 files changed, including dashboard, architecture docs, cost service, passenger service, sim orchestrator, and tests.

Therefore, the audited evidence contradicts a categorical “new features do not touch other services” claim. A defensible paper statement is narrower: the project has service-aligned boundaries, while major refactors demonstrably crossed those boundaries.

### Specification and data-model check

The five diffs were also checked for explicit contract and persistence-model changes:

| Commit    | Event-bus/topic definitions                                                                                                                                       | Kafka implementation                                                                                     | Neo4j model                                                                                                                            | Service spec                                                                                          |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `23bea42` | **Yes**: `docs/architecture/EVENT_BUS.md` adds `flights.commands`, `passengers.commands`, `baggage.commands`, and `analysis.events`, with command/event contracts | **Yes**: adds shared `services/_common/kafka_runtime.py` and modifies multiple Kafka consumers/producers | **Implementation changes** in shared Neo4j runtime and baggage/flight Neo4j modules; no `DATA_MODEL.md` change in this commit          | No `SPEC.md` change found                                                                             |
| `8536eab` | No architecture event-bus document change found                                                                                                                   | **Yes**: incident and passenger Kafka consumers changed                                                  | **Yes, implementation only**: cost and incident Neo4j modules changed; no `DATA_MODEL.md` change                                       | No `SPEC.md` change found                                                                             |
| `10536f1` | No `EVENT_BUS.md` or `DATA_MODEL.md` change found                                                                                                                 | **Yes**: analysis and passenger Kafka consumers changed                                                  | No Neo4j model file matched in the diff                                                                                                | No `SPEC.md` change found                                                                             |
| `4d8e4b4` | No architecture event-bus document change found                                                                                                                   | **Yes**: passenger Kafka consumer changed                                                                | No Neo4j model file matched in the diff                                                                                                | No `SPEC.md` change found                                                                             |
| `22c5c18` | **Yes**: `EVENT_BUS.md` adds `cost.events` and `CostRecorded`                                                                                                     | **Yes**: cost Kafka consumer/producer changed                                                            | **Yes**: `DATA_MODEL.md` adds `CostRecord`, four relationships, a uniqueness constraint, and two indexes; cost Neo4j code also changed | **Yes**: `docs/services/cost-service/SPEC.md` was rewritten into an implemented service specification |

Thus, the answer to “did any modify event-bus definitions, Kafka schemas, or Neo4j models?” is **yes**. The strongest direct specification changes are in `23bea42` and `22c5c18`; `22c5c18` is the clearest schema/model evolution because it changes all three documentation surfaces: event bus, data model, and service specification.

### Exact diff classification

The following classifications are based on `git diff --unified=0`, so the quoted lines are the actual changed lines.

#### `23bea42`

`DATA_MODEL.md`: no changed lines. The event-bus changes are:

- **ADDITION**: `+| \`flights.commands\` | api-gateway, analysis-service | flight-service | 1h |`
- **ADDITION**: `+| \`passengers.commands\` | api-gateway, analysis-service | passenger-service | 1h |`
- **ADDITION**: `+| \`baggage.commands\` | api-gateway, analysis-service | baggage-service | 1h |`
- **MODIFICATION**: `-| \`cost.events\` | cost-service | api-gateway | 7 days |`followed by`+| \`cost.events\` | cost-service | api-gateway | 7 days |`. The topic semantics are unchanged; this is a table-row replacement/formatting change.
- **ADDITION**: `+| \`analysis.events\` | analysis-service | api-gateway | 7 days |`
- **ADDITION**: `+| \`flights.commands\` | 6 | \`flight_id\` | \`flight-svc\` |`
- **ADDITION**: `+| \`passengers.commands\` | 3 | \`terminal\` | \`pax-svc\` |`
- **ADDITION**: `+| \`baggage.commands\` | 6 | \`bag_id\` | \`bag-svc\` |`
- **MODIFICATION**: `-| \`cost.events\` | 3 | \`cost_record_id\` | \`gateway\` |`followed by`+| \`cost.events\` | 3 | \`cost_record_id\` | \`gateway\` |`. Again, no semantic change is visible.
- **ADDITION**: `+| \`analysis.events\` | 1 | entity id / — | \`gateway\` |`
- **ADDITION**: `+### 4.8b \`flights.commands\` — operator/agent command input`
- **ADDITION**: `+### 4.8c \`analysis.events\` — analysis-service facts`
- **ADDITION**: `+### 4.8d \`passengers.commands\` — passenger-service command input`
- **ADDITION**: `+### 4.8e \`baggage.commands\` — baggage-service command input`

The added sections define new command/event shapes, including the exact new event types `BottleneckDetected`, `BottleneckResolved`, `RecommendationGenerated`, `ActionProposed`, `AutonomousActionApplied`, `AnomalyDetected`, and `NarrationGenerated`. No pre-existing event type is removed or reshaped in this documentation diff.

#### `22c5c18`

`DATA_MODEL.md` contains additions only:

- **ADDITION**: `+### \`CostRecord\``
- **ADDITION**: `+| \`id\` | String (UUID) | unique |`
- **ADDITION**: `+| \`category\` | Enum | \`landing_fee\`, \`gate_fee\`, \`passenger_fee\`, \`eu261_compensation\`, \`crew_overtime\`, \`holding_fuel\`, \`ground_handling\`, \`incident_direct\`, \`incident_response\`, \`staffing\`, \`retail_revenue\`, \`slot_revenue\` |`
- **ADDITION**: `+| \`amount_eur\` | Float | cost or revenue amount (always positive) |`
- **ADDITION**: `+| \`currency\` | String | \"EUR\" |`
- **ADDITION**: `+| \`sim_time\` | String (ISO) | when the cost was incurred |`
- **ADDITION**: `+| \`sim_day\` | Integer | day number in simulation |`
- **ADDITION**: `+| \`description\` | String | human-readable label |`
- **ADDITION**: `+| \`is_revenue\` | Boolean | true for revenue records |`
- **ADDITION**: `+| \`FOR_FLIGHT\` | CostRecord → Flight | — | cost linked to a specific flight |`
- **ADDITION**: `+| \`FOR_TERMINAL\` | CostRecord → Terminal | — | cost linked to a terminal |`
- **ADDITION**: `+| \`CAUSED_BY\` | CostRecord → Incident | — | cost caused by an incident |`
- **ADDITION**: `+| \`FOR_DAY\` | CostRecord → Airport | \`day: Integer\` | daily cost rollup |`
- **ADDITION**: `+CREATE CONSTRAINT cost_record_id IF NOT EXISTS FOR (c:CostRecord) REQUIRE c.id IS UNIQUE;`
- **ADDITION**: `+CREATE INDEX cost_record_category IF NOT EXISTS FOR (c:CostRecord) ON (c.category);`
- **ADDITION**: `+CREATE INDEX cost_record_sim_day IF NOT EXISTS FOR (c:CostRecord) ON (c.sim_day);`

`EVENT_BUS.md` contains both modifications and additions:

- **MODIFICATION**: `-| \`flights.events\` ... passenger-service, baggage-service, incident-service, api-gateway |`becomes`+| \`flights.events\` ... passenger-service, baggage-service, incident-service, cost-service, api-gateway |`; `cost-service` is added as a consumer.
- **MODIFICATION**: `-| \`passengers.events\` ... \`incident-svc\`, \`gateway\` |`becomes`+| \`passengers.events\` ... incident-service, cost-service, api-gateway |`; consumer names and the consumer set change.
- **MODIFICATION**: `-| \`baggage.events\` ... api-gateway |`becomes`+| \`baggage.events\` ... cost-service, api-gateway |`; `cost-service` is added as a consumer.
- **MODIFICATION**: `-| \`incidents.events\` ... baggage-service, api-gateway |`becomes`+| \`incidents.events\` ... baggage-service, cost-service, api-gateway |`; `cost-service` is added as a consumer.
- **ADDITION**: `+| \`cost.events\` | cost-service | api-gateway | 7 days |`
- **MODIFICATION**: the corresponding partition-table rows for `flights.events`, `passengers.events`, `baggage.events`, and `incidents.events` add `cost-svc` or replace the earlier consumer labels.
- **ADDITION**: `+| \`cost.events\` | 3 | \`cost_record_id\`| \`gateway\` |`
- **ADDITION**: `+### CostRecorded`
- **ADDITION**: `+Topic: \`cost.events\``
- **ADDITION**: `+Producer: cost-service`
- **ADDITION**: `+Triggered: whenever a CostRecord is written to Neo4j`
- **ADDITION**: the new `CostRecorded` JSON envelope, including `event_type`, `schema_version`, `cost_record_id`, `category`, `amount_eur`, `is_revenue`, `flight_id`, `incident_id`, `description`, `sim_time`, and `sim_day`.

### Existing-consumer compatibility

The diffs do **not** show a pre-existing event type being renamed or its payload shape being changed. Existing consumers continued to dispatch the existing event types (`SimClockTick`, `FlightStatusChanged`, `FlightCancelled`, `IncidentCreated`, and `IncidentStatusChanged`) using the same payload fields.

There were, however, implementation changes around those consumers:

- In `23bea42`, baggage-service adds a new `baggage.commands` subscription and a separate `command_type` path; its existing fact-event validation/dispatch path remains present. Analysis-service adds `ActionProposed` emission. Cost-service extracts its existing dispatch into `process_envelope` and adds idempotency/health tracking, but retains the same existing event cases and topics.
- In `22c5c18`, cost-service’s existing `TOPICS` list remains `sim.clock`, `flights.events`, `incidents.events`, `baggage.events`, and `passengers.events`; the code adds consumer-health instrumentation, not a new read shape. The newly documented `cost.events` topic is produced by cost-service and consumed by the gateway, not consumed by the pre-existing domain consumers.

Therefore, the precise conclusion is: **existing consumers were not left literally unmodified, but they retained compatibility with the pre-existing topic/event contracts; the commits added new consumers/command paths and a new cost-event contract without requiring old consumers to parse a changed payload shape.**

## 5) Evidence for progressive fidelity

The repository does show a pattern of increasing capability and maturity.

A conservative interpretation is:

1. The repo begins with foundational work (UI/data setup, refactors, cleanup).
2. It adds domain features such as planning and cost logic.
3. It adds robustness, error handling, and operational improvements.
4. It adds architecture and documentation layers that make the system easier to reason about.
5. It culminates in publication-oriented artifacts and documentation.

This is a valid narrative for progressive fidelity. The strength of the evidence is moderate: it is visible in the file structure and git history, but not formally encoded as a measurement model. The repo does not provide a quantitative measure of fidelity by date or by service layer.

## 6) Before/after revision evidence

The commit history clearly supports iterative revision, but the repo does not preserve a formal before/after benchmark table.

The evidence is indirect but real:

- Refactor commits exist after earlier implementation work.
- Repair and stabilization commits follow feature introductions.
- Infrastructure and documentation improvements (for example, Docker and roadmap notes) arrive later in the timeline.

This is consistent with a project that evolved in rounds of implementation, error correction, and consolidation. The paper can state that the project shows iterative revision cycles; it should not claim a formal quantitative before/after experimental setup unless such data is present in the repository.

## 7) Architecture and service-layer readout

The repository’s architecture docs indicate an explicit system model:

- `docs/architecture/OVERVIEW.md`
- `docs/architecture/DATA_MODEL.md`
- `docs/architecture/EVENT_BUS.md`
- `docs/architecture/SIMULATION.md`
- `docs/architecture/DATA_SOURCES.md`
- `docs/architecture/ROUTES.md`
- `docs/architecture/ARCHITECTURE_DIAGRAM.md`

These files establish that the project separates architecture, data modeling, event flow, simulation logic, and data-source boundaries. That is strong evidence for a disciplined engineering approach. It does not, however, provide a fully quantitative measure of the number of layer transitions or service-level rework events.

## 8) Compact summary for the paper

A defensible summary is:

- The repository is a multi-service digital twin with explicit architecture, service specs, and operational guidance.
- It contains clear evidence of feature growth and iterative refinement through commit history.
- The project shows progressive maturity in both capability and documentation.
- The repository provides firm structural evidence for service-oriented and specification-first engineering.
- The repo does not provide a formal, machine-readable sprint log or a quantitative before/after experiment ledger, so those claims should be expressed cautiously or omitted.

## 9) Minimal evidence list for citation

The most relevant repo evidence to cite is:

- `git rev-list --count HEAD` → 90 commits
- `find services -mindepth 1 -maxdepth 1 -type d` → 10 service directories
- `find services -type f | wc -l` → 109 service files
- `find docs -type f -name 'SPEC.md'` → 9 specification files
- `find docs/skills -type f` → 7 cross-cutting skill files
- `find docs/architecture -type f` → 8 architecture files
- `AGENTS.md` and `CLAUDE.md` are present
- commit messages such as `feature: planning service & dashboard, not fully tested yet`, `feature: planning cost model & app robustness`, and `better docker` indicate progressive domain expansion and stabilization

This is the strongest evidence available without inventing claims that the repo does not support.

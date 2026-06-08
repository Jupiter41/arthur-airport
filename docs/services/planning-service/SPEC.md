# planning-service — specification

**Language:** Python 3.11+
**Framework:** FastAPI
**Port:** 8008
**Responsibility:** Runs isolated multi-scenario, multi-horizon capacity planning
simulations independent of the live operational twin. Provides infrastructure
investment analysis, Monte Carlo uncertainty quantification, demand forecasting,
and a decision audit trail. Never writes to live operational Neo4j nodes or
produces Kafka events.

---

## 1. Domain responsibilities

- Manage `PlanningScenario`, `PlanningResult`, and `RecommendationLog` entities
  (see §2 for storage model)
- Run isolated in-memory planning simulations (no live Kafka, no operational Neo4j writes)
- Expose scenario CRUD, run, and comparison REST endpoints
- Train and serve demand and delay prediction ML models
- Compute NPV/IRR investment analysis from scenario results
- Log recommendation outcomes and measure prediction accuracy
- Expose planning results to the api-gateway for the `/planning` dashboard

---

## 2. Data model

> **Storage decision (lesson 019, 2026-05-29):** scenarios, results, and
> recommendation logs live in **process-local in-memory dictionaries**, not
> Neo4j. Planning is a simulation tool whose outputs are ephemeral by design —
> they describe hypothetical futures, not operational state. Restart wipes the
> store; clients must re-create scenarios they want to keep. If durability is
> ever needed (audit-grade comparisons across deploys), the storage layer
> behind `scenarios/model.py` is the single seam to migrate.

The schemas below describe the **logical record shape** returned by the API
and stored in memory; the Neo4j labels remain reserved for a future
persistence implementation but are not currently written.

### `PlanningScenario`

| Property                | Type                 | Description                                                                             |
| ----------------------- | -------------------- | --------------------------------------------------------------------------------------- |
| `id`                    | String (UUID)        | Unique                                                                                  |
| `name`                  | String               | Human-readable scenario name                                                            |
| `description`           | String               |                                                                                         |
| `status`                | Enum                 | `pending` · `running` · `completed` · `failed`                                          |
| `horizon`               | Enum                 | `day` · `week` · `month` · `year` · `10year`                                            |
| `monte_carlo_runs`      | Integer              | Number of stochastic iterations                                                         |
| `random_seed`           | Integer \| null      | null = random                                                                           |
| `infrastructure_config` | String (JSON)        | Serialised `InfrastructureConfig`                                                       |
| `demand_source`         | Enum                 | `simulation` · `bts` · `eurocontrol`                                                    |
| `weather_source`        | Enum                 | `simulation` · `mesonet` · `historical_date`                                            |
| `demand_multiplier`     | Float                | Linear demand scaling (1.0 = baseline)                                                  |
| `new_routes`            | List[Object] (JSON)  | Additive routes (destination, daily_flights, aircraft_type, distance_km?, load_factor?) |
| `capex_eur`             | Float                | Upfront investment cost                                                                 |
| `opex_delta_eur`        | Float                | Annual operating cost change                                                            |
| `years_horizon`         | Integer              | NPV calculation horizon                                                                 |
| `discount_rate`         | Float                | WACC (default 0.07)                                                                     |
| `created_at`            | String (ISO)         |                                                                                         |
| `started_at`            | String (ISO) \| null |                                                                                         |
| `completed_at`          | String (ISO) \| null |                                                                                         |
| `error`                 | String \| null       | Error message if failed                                                                 |

### `PlanningResult`

One node per scenario, created on completion.

| Property                   | Type          | Description                              |
| -------------------------- | ------------- | ---------------------------------------- |
| `id`                       | String (UUID) |                                          |
| `scenario_id`              | String        | FK to PlanningScenario                   |
| `baseline_id`              | String        | FK to baseline PlanningScenario          |
| `kpis`                     | String (JSON) | Serialised `KPIDistribution` per metric  |
| `delta`                    | String (JSON) | KPI deltas vs baseline                   |
| `financials`               | String (JSON) | `InvestmentResult`                       |
| `annual_benefit_breakdown` | String (JSON) | Benefit by category                      |
| `model_versions`           | String (JSON) | demand_model + delay_model versions used |
| `run_duration_seconds`     | Float         | Wall-clock time for all MC runs          |
| `computed_at`              | String (ISO)  |                                          |

### `RecommendationLog`

| Property                    | Type                 | Description                                                            |
| --------------------------- | -------------------- | ---------------------------------------------------------------------- |
| `id`                        | String (UUID)        |                                                                        |
| `type`                      | Enum                 | `operational` · `planning`                                             |
| `recommendation_text`       | String               | Human-readable action description                                      |
| `category`                  | String               | `security_lane` · `gate_reassign` · `hold_flight` · `gdp` · `carousel` |
| `predicted_saving_eur`      | Float                |                                                                        |
| `predicted_cost_eur`        | Float                |                                                                        |
| `net_predicted_benefit_eur` | Float                |                                                                        |
| `confidence`                | Float                | 0.0–1.0                                                                |
| `was_applied`               | Boolean              |                                                                        |
| `applied_at`                | String (ISO) \| null |                                                                        |
| `measurement_sim_time`      | String (ISO) \| null | When outcome was measured                                              |
| `actual_saving_eur`         | Float \| null        | Measured 30 sim-min after application                                  |
| `prediction_error_eur`      | Float \| null        | predicted - actual                                                     |
| `sim_day`                   | Integer              |                                                                        |
| `model_version`             | String               |                                                                        |

**Relationships:**

Reserved for the future Neo4j-backed implementation (see §2 storage note):

```cypher
(PlanningResult)-[:FOR_SCENARIO]->(PlanningScenario)
(PlanningResult)-[:VS_BASELINE]->(PlanningScenario)
(RecommendationLog)-[:RECOMMENDED_FOR]->(Flight | Terminal | Incident)
```

**Constraints (planned, not currently enforced):**

```cypher
CREATE CONSTRAINT planning_scenario_id IF NOT EXISTS
  FOR (s:PlanningScenario) REQUIRE s.id IS UNIQUE;
CREATE CONSTRAINT planning_result_id IF NOT EXISTS
  FOR (r:PlanningResult) REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT recommendation_log_id IF NOT EXISTS
  FOR (r:RecommendationLog) REQUIRE r.id IS UNIQUE;
CREATE INDEX planning_scenario_status IF NOT EXISTS
  FOR (s:PlanningScenario) ON (s.status);
```

---

## 3. REST API

Base path: `/api/v1/planning`
All responses: `application/json`
Authentication: `Authorization: Bearer <token>` (same stub JWT as other services)

---

### Scenarios

#### `POST /scenarios`

Create and queue a new planning scenario.

Request body:

```json
{
  "name": "Add gate B15 to Terminal B",
  "description": "Evaluate impact over a peak week",
  "horizon": "week",
  "monte_carlo_runs": 100,
  "random_seed": 42,
  "infrastructure": {
    "gates_per_terminal": { "A": 14, "B": 15, "C": 14 }
  },
  "demand_source": "bts",
  "weather_source": "mesonet",
  "capex_eur": 8000000,
  "opex_delta_eur": 120000,
  "years_horizon": 25,
  "discount_rate": 0.07
}
```

Response `201`:

```json
{
  "scenario_id": "uuid",
  "status": "pending",
  "estimated_duration_seconds": 45
}
```

The scenario runs asynchronously as a background task. Poll `/scenarios/{id}/status`
or subscribe to `GET /scenarios/{id}/stream` (SSE) for progress.

---

#### `GET /scenarios`

List all scenarios.

Query parameters: `status`, `horizon`, `limit` (default 20), `offset`

Response `200`:

```json
{
  "total": 8,
  "scenarios": [
    {
      "id": "uuid",
      "name": "Add gate B15",
      "status": "completed",
      "horizon": "week",
      "monte_carlo_runs": 100,
      "created_at": "2024-06-15T10:00:00Z",
      "completed_at": "2024-06-15T10:01:23Z"
    }
  ]
}
```

---

#### `GET /scenarios/{id}`

Full scenario detail including configuration.

---

#### `GET /scenarios/{id}/status`

Lightweight status poll for running scenarios.

Response `200`:

```json
{
  "scenario_id": "uuid",
  "status": "running",
  "progress_pct": 43,
  "runs_completed": 43,
  "runs_total": 100,
  "elapsed_seconds": 19,
  "estimated_remaining_seconds": 25
}
```

---

#### `GET /scenarios/{id}/stream`

Server-Sent Events stream for real-time progress.

```
data: {"event": "progress", "runs_completed": 10, "progress_pct": 10}
data: {"event": "progress", "runs_completed": 50, "progress_pct": 50}
data: {"event": "completed", "result_id": "uuid"}
```

---

#### `DELETE /scenarios/{id}`

Delete a scenario and its results.

---

### Results

#### `GET /scenarios/{id}/results`

Full planning results for a completed scenario.

Response `200`:

```json
{
  "scenario_id": "uuid",
  "scenario_name": "Add gate B15 to Terminal B",
  "baseline_id": "uuid",
  "status": "completed",
  "kpis": {
    "avg_delay_minutes": {
      "mean": 8.2,
      "std": 2.1,
      "p5": 4.8,
      "p25": 6.9,
      "p50": 8.1,
      "p75": 9.6,
      "p95": 12.4
    },
    "missed_connections": {
      "mean": 3.4,
      "std": 1.2,
      "p5": 1.0,
      "p50": 3.0,
      "p95": 6.0
    },
    "gate_utilisation_pct": {
      "mean": 71.2,
      "std": 4.8,
      "p5": 63.1,
      "p50": 71.0,
      "p95": 80.1
    },
    "on_time_rate": {
      "mean": 0.847,
      "std": 0.032,
      "p5": 0.789,
      "p50": 0.851,
      "p95": 0.898
    },
    "eu261_liability_eur": {
      "mean": 28400,
      "std": 9200,
      "p5": 12000,
      "p50": 27000,
      "p95": 47000
    }
  },
  "delta_vs_baseline": {
    "avg_delay_minutes": { "mean": -3.1, "pct_change": -27.4 },
    "missed_connections": { "mean": -2.8, "pct_change": -45.2 },
    "eu261_liability_eur": { "mean": -18600, "pct_change": -39.6 }
  },
  "financials": {
    "capex_eur": 8000000,
    "annual_benefit_eur": 1240000,
    "annual_opex_eur": 120000,
    "net_annual_eur": 1120000,
    "npv_eur": 7840000,
    "irr_pct": 14.2,
    "payback_years": 7.1,
    "recommendation": "invest"
  },
  "annual_benefit_breakdown": {
    "eu261_avoided": 679000,
    "delay_cost_avoided": 391000,
    "missed_connections_avoided": 170000
  },
  "run_duration_seconds": 83,
  "computed_at": "2024-06-15T10:01:23Z"
}
```

---

#### `POST /scenarios/compare`

Compare two or more completed scenarios side-by-side.

Request body:

```json
{
  "scenario_ids": ["uuid-a", "uuid-b", "uuid-c"],
  "kpis": ["avg_delay_minutes", "eu261_liability_eur", "npv_eur"]
}
```

Response `200`:

```json
{
  "comparison": [
    {
      "scenario_id": "uuid-a",
      "name": "Baseline",
      "kpis": { "avg_delay_minutes": 11.3, "eu261_liability_eur": 47000 },
      "financials": { "npv_eur": 0, "recommendation": "baseline" }
    },
    {
      "scenario_id": "uuid-b",
      "name": "Add gate B15",
      "kpis": { "avg_delay_minutes": 8.2, "eu261_liability_eur": 28400 },
      "financials": { "npv_eur": 7840000, "recommendation": "invest" }
    },
    {
      "scenario_id": "uuid-c",
      "name": "Add 2 security lanes",
      "kpis": { "avg_delay_minutes": 9.8, "eu261_liability_eur": 31200 },
      "financials": { "npv_eur": 2100000, "recommendation": "invest" }
    }
  ],
  "recommended": "uuid-b"
}
```

---

### Preset scenario generators

#### `POST /scenarios/presets/add-gate`

```json
{ "terminal": "B", "additional_gates": 1, "wide_body_capable": true }
```

#### `POST /scenarios/presets/add-runway`

```json
{ "runway_id": "09C", "ils_capable": true, "length_m": 3200 }
```

#### `POST /scenarios/presets/add-route`

```json
{ "destination_iata": "DXB", "daily_flights": 2, "aircraft_type": "B77W" }
```

#### `POST /scenarios/presets/security-lanes`

```json
{ "lanes_delta": { "A": 1, "B": 1 } }
```

#### `POST /scenarios/presets/weather-stress`

```json
{ "weather_date": "2024-01-15", "horizon": "day", "monte_carlo_runs": 200 }
```

Each preset automatically fills in capex, opex, and years_horizon from the
cost rate table and returns the created scenario_id immediately.

---

### Counterfactual delay analysis (1B)

Replay an existing scenario with operator interventions to measure their causal
impact on KPIs. Both the baseline and the scenario re-runs apply the same
interventions and synthetic disruption so deltas isolate the decision change.

#### `POST /scenarios/{id}/replay`

```json
{
  "interventions": [
    {
      "action": "gdp_start",
      "sim_minute": 60,
      "duration_minutes": 120,
      "params": { "cap_pct": 0.6 }
    },
    {
      "action": "open_security_lanes",
      "sim_minute": 90,
      "duration_minutes": 180,
      "params": { "delta": 2 }
    }
  ],
  "disruption": {
    "sim_minute": 60,
    "duration_minutes": 120,
    "capacity_pct": 0.5
  },
  "label": "earlier-gdp"
}
```

`action` ∈ {`gdp_start`, `gdp_end`, `open_security_lanes`, `gate_swap`}. Returns the
new child scenario id; poll its status endpoint for progress.

#### `POST /scenarios/{id}/counterfactual-report`

```json
{
  "base_interventions": [
    {
      "action": "gdp_start",
      "sim_minute": 60,
      "duration_minutes": 120,
      "params": { "cap_pct": 0.6 }
    }
  ],
  "disruption": {
    "sim_minute": 60,
    "duration_minutes": 120,
    "capacity_pct": 0.5
  },
  "shifts": [-30, -15, 0, 15, 30],
  "intervention_index": 0
}
```

Spawns one replay per shift, varying the timing of the indexed intervention.
Returns `{ children: [{ scenario_id, shift_minutes, applied_sim_minute, label }] }`.

#### `GET /scenarios/{id}/causal-graph`

Returns a JSON DAG with `nodes` (scenario, disruption, intervention, kpi) and
`edges` (`triggers`, `responds_to`, `affects`). Used by the dashboard "What-If"
panel.

#### `GET /scenarios/{id}/replays`

Returns the list of all child replay scenarios spawned from a parent, with their
status and (if completed) results — used to render the comparison view.

---

### Slot allocation & coordination (2B)

Allocate slot requests to available capacity using different strategies.
Extends planning-service with ILP-based optimisation via PuLP.

#### `POST /slots/allocate`

```json
{
  "requests": [
    {
      "id": "s1",
      "airline": "BA",
      "requested_hour": 8,
      "priority": 3,
      "direction": "departure"
    },
    {
      "id": "s2",
      "airline": "LH",
      "requested_hour": 8,
      "priority": 1,
      "direction": "departure"
    }
  ],
  "strategy": "optimised",
  "hourly_capacity": 60
}
```

`strategy` ∈ {`fcfs`, `priority_weighted`, `optimised`}. Returns allocation
results with displacement per request, total displacement, and hourly
demand/capacity breakdown.

#### `POST /slots/compress`

```json
{
  "schedule": [
    {
      "flight_number": "BA123",
      "airline_code": "BA",
      "scheduled_departure": "2026-06-15T08:30:00"
    }
  ],
  "hourly_capacity": 60,
  "shift_limit_minutes": 15
}
```

Identifies flights shiftable ±N minutes to smooth demand peaks. Returns
compression opportunities with suggested shifts and throughput gains.

#### `POST /slots/compare`

Runs all three strategies (FCFS, priority-weighted, ILP-optimised) on the same
input and returns side-by-side total displacement, max displacement, and
identifies the best strategy.

---

### Network resilience & hub dependency (2D)

Analyse route network concentration and simulate airline disruptions.
Uses BTS T-100 data for real route statistics and a gravity model for
diversification recommendations.

#### `GET /network/dependency`

Returns hub dependency scoring: Herfindahl-Hirschman Index, concentration
rating (`low`/`moderate`/`high`/`very_high`), top airline shares, effective
number of airlines.

#### `POST /network/disruption`

```json
{ "airline": "B6", "reduction_pct": 100 }
```

Simulates the impact of an airline reducing/ceasing operations. Returns lost
daily departures, passengers, exclusive routes lost, residual gate utilisation,
revenue impact, and the resulting HHI change.

#### `POST /network/diversify`

```json
{ "target_hhi": 0.15, "max_recommendations": 10 }
```

Recommends new routes to reduce hub concentration using a gravity model
(`demand ∝ pop_origin × pop_dest / distance²`). Returns candidate destinations
ranked by estimated demand, with recommended frequency and aircraft type.

---

### Demand model

#### `GET /demand/forecast`

Predict daily passenger demand for a route in a given month.

Query parameters: `origin`, `destination`, `month` (1–12)

Response `200`:

```json
{
  "origin": "ART",
  "destination": "LHR",
  "month": 7,
  "predicted_daily_pax": 412,
  "confidence_interval": [318, 506],
  "model_trained": true,
  "data_source": "bts_t100",
  "feature_importance": {
    "historical_avg_pax": 0.41,
    "month": 0.22,
    "distance_km": 0.17,
    "population_dest": 0.12,
    "other": 0.08
  }
}
```

#### `GET /demand/growth`

Project demand growth under different scenarios.

Query parameters: `base_year_pax`, `years`, `scenario` (low/base/high)

Response `200`:

```json
{
  "base_year_pax": 18000000,
  "projections": [
    { "year": 2025, "low": 18320000, "base": 18612000, "high": 18864000 },
    { "year": 2026, "low": 18646000, "base": 19252000, "high": 19751000 },
    { "year": 2030, "low": 20118000, "base": 22418000, "high": 24312000 }
  ],
  "saturation_year": {
    "low": null,
    "base": 2031,
    "high": 2029
  },
  "source": "eurocontrol_statfor_2024"
}
```

---

### Investment analysis

#### `POST /investment/npv`

Standalone NPV/IRR calculator — usable independently of a full scenario run.

Request body:

```json
{
  "capex_eur": 8000000,
  "annual_benefit_eur": 1240000,
  "annual_opex_eur": 120000,
  "years_horizon": 25,
  "discount_rate": 0.07
}
```

Response `200`:

```json
{
  "npv_eur": 7840000,
  "irr_pct": 14.2,
  "payback_years": 7.1,
  "net_annual_eur": 1120000,
  "cumulative_cash_flows": [-8000000, -6880000, -5760000, "..."],
  "recommendation": "invest"
}
```

#### `GET /investment/sensitivity`

NPV sensitivity table across demand growth scenarios.

Response `200`:

```json
{
  "scenario_id": "uuid",
  "sensitivity": {
    "demand_growth": {
      "low  (1.8%)": {
        "npv_eur": 3200000,
        "irr_pct": 9.8,
        "recommendation": "marginal"
      },
      "base (3.4%)": {
        "npv_eur": 7840000,
        "irr_pct": 14.2,
        "recommendation": "invest"
      },
      "high (4.8%)": {
        "npv_eur": 12100000,
        "irr_pct": 18.7,
        "recommendation": "invest"
      }
    },
    "discount_rate": {
      "5%": { "npv_eur": 10200000 },
      "7%": { "npv_eur": 7840000 },
      "10%": { "npv_eur": 4900000 }
    }
  }
}
```

---

### Decision audit trail

#### `GET /audit/recommendations`

All logged recommendations with outcomes.

Query parameters: `type` (operational/planning), `was_applied`, `sim_day`, `limit`

Response `200`:

```json
{
  "total": 47,
  "recommendations": [
    {
      "id": "uuid",
      "type": "operational",
      "category": "security_lane",
      "recommendation_text": "Open 1 additional lane in Terminal B",
      "predicted_saving_eur": 18600,
      "predicted_cost_eur": 560,
      "net_predicted_benefit_eur": 18040,
      "confidence": 0.81,
      "was_applied": true,
      "applied_at": "2024-06-15T14:32:00Z",
      "actual_saving_eur": 21400,
      "prediction_error_eur": -2800,
      "sim_day": 1
    }
  ]
}
```

#### `GET /audit/summary`

Aggregate recommendation performance metrics.

Response `200`:

```json
{
  "sim_day": 1,
  "total_recommendations": 12,
  "applied": 8,
  "application_rate_pct": 66.7,
  "measured_outcomes": 6,
  "total_predicted_saving_eur": 124000,
  "total_actual_saving_eur": 108300,
  "mean_prediction_error_pct": -12.7,
  "mean_confidence": 0.78,
  "by_category": {
    "security_lane": { "count": 4, "applied": 3, "mean_error_pct": -8.2 },
    "gate_reassign": { "count": 3, "applied": 2, "mean_error_pct": -15.1 },
    "hold_flight": { "count": 3, "applied": 2, "mean_error_pct": -11.4 },
    "gdp": { "count": 2, "applied": 1, "mean_error_pct": -18.9 }
  },
  "model_version": "demand_v2.1_delay_v1.4"
}
```

#### `POST /audit/apply`

Record that a recommendation was applied by the operator.

Request body:

```json
{
  "recommendation_id": "uuid",
  "applied_at_sim_time": "2024-06-15T14:32:00Z"
}
```

---

### Health and observability

#### `GET /health`

Liveness.

#### `GET /ready`

Readiness: checks Neo4j connectivity + ML models loaded.

Response `200`:

```json
{
  "status": "ready",
  "neo4j": true,
  "demand_model_loaded": true,
  "delay_model_loaded": true,
  "demand_model_version": "v2.1",
  "delay_model_version": "v1.4"
}
```

#### `GET /metrics`

Prometheus metrics (text format).

---

## 4. Kafka

The planning-service **does not subscribe to Kafka**. It reads baseline state
from Neo4j when starting a scenario. It **does not produce events** during
scenario runs (the runs are isolated).

The one exception: when a `RecommendationLog` outcome is measured, the service
produces a `RecommendationOutcomeMeasured` event to `cost.events` so the
cost dashboard can update the audit panel without polling.

```json
{
  "event_type": "RecommendationOutcomeMeasured",
  "payload": {
    "recommendation_id": "uuid",
    "predicted_saving_eur": 18600,
    "actual_saving_eur": 21400,
    "prediction_error_eur": -2800,
    "sim_day": 1
  }
}
```

---

## 5. Configuration

| Env variable                           | Default             | Description                            |
| -------------------------------------- | ------------------- | -------------------------------------- |
| `NEO4J_URI`                            | `bolt://neo4j:7687` |                                        |
| `NEO4J_USER`                           | `neo4j`             |                                        |
| `NEO4J_PASSWORD`                       | `art-digital-twin`  |                                        |
| `KAFKA_BROKERS`                        | `kafka:9092`        | Only used for outcome event production |
| `MODELS_PATH`                          | `/app/models`       | LightGBM model files                   |
| `DATA_PATH`                            | `/app/data`         | BTS, Mesonet CSV files                 |
| `MAX_CONCURRENT_SCENARIOS`             | `2`                 | Parallel scenario runs limit           |
| `DEFAULT_MONTE_CARLO_RUNS`             | `100`               | Default when not specified             |
| `DEFAULT_DISCOUNT_RATE`                | `0.07`              | Default WACC for NPV                   |
| `RECOMMENDATION_MEASUREMENT_DELAY_MIN` | `30`                | Sim-minutes before measuring outcome   |
| `LOG_LEVEL`                            | `INFO`              |                                        |

---

## 6. Prometheus metrics

| Metric                                | Type      | Description                                |
| ------------------------------------- | --------- | ------------------------------------------ |
| `planning_scenarios_total`            | Counter   | Scenarios run by status (completed/failed) |
| `planning_scenario_duration_seconds`  | Histogram | Wall-clock time per scenario run           |
| `planning_monte_carlo_runs_total`     | Counter   | Total MC iterations completed              |
| `planning_demand_model_mae`           | Gauge     | Demand model mean absolute error           |
| `planning_delay_model_auc`            | Gauge     | Delay model AUC                            |
| `recommendation_application_rate`     | Gauge     | Fraction of recommendations applied        |
| `recommendation_prediction_error_pct` | Gauge     | Mean prediction error %                    |
| `planning_npv_positive_rate`          | Gauge     | Fraction of scenarios with positive NPV    |

---

## 7. Internal service structure

```
services/planning-service/
├── main.py
├── requirements.txt
├── Dockerfile
├── adapters/
│   ├── base.py            AbstractAdapter interface
│   ├── simulation.py      Wraps sim-orchestrator seed logic
│   ├── bts.py             BTS T-100 CSV reader
│   ├── opensky.py         OpenSky historical CSV reader (stub — not registered)
│   ├── mesonet.py         Iowa State Mesonet CSV reader
│   ├── eurocontrol.py     Eurocontrol STATFOR demand adapter
│   └── registry.py        Runtime adapter selection
├── engine/
│   ├── simulation.py      In-memory planning simulation engine
│   ├── infrastructure.py  InfrastructureConfig dataclass
│   ├── interventions.py   Disruption, Intervention models (counterfactual)
│   ├── results.py         DayResult, KPIDistribution models
│   ├── slots.py           Slot allocation engine (FCFS, priority, ILP)
│   └── network.py         Network resilience & hub dependency analysis
├── scenarios/
│   ├── model.py           PlanningScenario dataclass
│   ├── runner.py          ScenarioRunner, Monte Carlo loop
│   ├── statistics.py      KPI aggregation, percentile computation
│   └── presets.py         Gate / runway / route / security preset generators
├── finance/
│   ├── investment.py      NPV, IRR, payback calculator
│   └── benefit_extractor.py  DayResult delta → annual financial benefit
├── ml/
│   ├── demand_model.py    LightGBM demand surface model
│   ├── delay_model.py     LightGBM delay probability model
│   └── training_pipeline.py  CLI training script
├── db/
│   ├── neo4j.py           Planning Neo4j schema, CRUD
│   ├── queries.py         Aggregation and comparison queries
│   └── audit.py           RecommendationLog CRUD, outcome measurement
├── routers/
│   ├── scenarios.py       Scenario CRUD + run endpoints
│   ├── results.py         Results + comparison endpoints
│   ├── demand.py          Demand forecast + growth projection
│   ├── investment.py      NPV/IRR + sensitivity analysis
│   └── audit.py           Recommendation audit trail endpoints
└── background/
    └── outcome_measurer.py  Async task: measures recommendation outcomes 30 min later
```

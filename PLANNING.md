# Capacity Planning & Investment Analysis

How Arthur International Airport evaluates infrastructure investments using Monte Carlo
simulation and Discounted Cash Flow analysis.

---

## What the Planning Dashboard Shows

The **Planning Dashboard** lets you answer "what if?" questions about airport infrastructure.
You describe a change (add gates, build a runway, open security lanes, add a terminal), and the
system simulates how it would affect delays, costs, revenue, and passenger experience — then
tells you whether the investment is worth it.

Four tabs:

| Tab                  | What it shows                                                       |
| -------------------- | ------------------------------------------------------------------- |
| **Scenario Builder** | Create scenarios from templates or custom infrastructure changes    |
| **Results**          | KPI comparison between baseline and scenario, multi-year projection |
| **Investment**       | NPV, IRR, payback period, cash flow chart, benefit breakdown        |
| **Decision Audit**   | Log of autonomous recommendations with predicted vs actual savings  |

---

## How Scenarios Work

### The Baseline

Every scenario is compared against the **baseline** — the current KART infrastructure
configuration:

| Parameter       | Baseline Value                 |
| --------------- | ------------------------------ |
| Gates           | 42 total (14 per terminal × 3) |
| Runways         | 2 (09L with ILS, 09R without)  |
| Security lanes  | 11 total (A: 4, B: 3, C: 4)    |
| Screening units | 6                              |
| Daily flights   | 420                            |
| Load factor     | 80%                            |
| Annual pax      | ~8 million                     |

### Creating a Scenario

Two ways:

1. **Templates** — pre-built scenarios with auto-calculated costs:
   - Add Gate(s) — expand a terminal by 1–20 gates
   - Add Runway — build a new runway with ILS capability
   - New Route — add a destination with daily flights
   - Security Lanes — adjust lane count per terminal
   - Add Terminal — build a new terminal with gates, security lanes, etc.

2. **Custom** — full control over every infrastructure parameter, demand settings,
   weather source, and investment costs.

### Simulation Parameters

| Parameter        | Default    | Description                                            |
| ---------------- | ---------- | ------------------------------------------------------ |
| Horizon          | month      | Simulation period (day/week/month/year/10year)         |
| Monte Carlo runs | 200        | Number of random iterations for statistical confidence |
| Random seed      | auto       | For reproducible results                               |
| Demand source    | simulation | Where flight schedules come from                       |
| Weather source   | simulation | Weather conditions during simulation                   |

For horizons longer than 30 days, the engine samples 30 representative days
(evenly spaced) to keep runtime manageable.

---

## How Results Are Computed

### Step 1: Dual Simulation

Each scenario triggers **two parallel simulation runs**:

1. **Baseline run** — current KART configuration, same dates and random seeds
2. **Scenario run** — modified infrastructure, same dates and random seeds

Using identical dates and seeds ensures the only variable is the infrastructure change.

### Step 2: Monte Carlo Aggregation

With N Monte Carlo runs, each configuration is simulated N times with different random seeds.
For each KPI, the engine computes:

- **Mean** — expected value across all runs
- **Standard deviation** — spread of outcomes
- **Percentiles** — P5, P25, P50 (median), P75, P95

The P5–P95 range gives you the **90% confidence band** — the range where 90% of outcomes fall.

### Step 3: Delta Computation

For each KPI:

```
delta = scenario_mean - baseline_mean
pct_change = (delta / baseline_mean) × 100
```

A change is classified as:

- **Improvement** (✓): >2% improvement in the right direction
- **Degradation** (✗): >2% degradation
- **Negligible** (—): within ±2%

### KPIs Tracked

| KPI                | Unit    | Lower is better? | Description                                 |
| ------------------ | ------- | ---------------- | ------------------------------------------- |
| Avg Delay          | minutes | Yes              | Average departure delay per flight          |
| On-Time Rate       | %       | No               | Flights departing within 15 min of schedule |
| Missed Connections | /day    | Yes              | Passengers missing connecting flights       |
| Gate Utilisation   | %       | No (up to ~85%)  | Gate-hours used vs available                |
| Runway Utilisation | %       | No (up to ~85%)  | Peak-hour throughput vs theoretical max     |
| EU261 Liability    | €/day   | Yes              | Daily passenger compensation exposure       |
| Total Cost         | €/day   | Yes              | All daily operating costs                   |
| Total Revenue      | €/day   | No               | All daily revenue streams                   |
| Gate Conflicts     | /day    | Yes              | Scheduling clashes requiring rebuffering    |
| Security Wait      | minutes | Yes              | Maximum security checkpoint wait time       |

---

## Cost Model

### Unit Costs (Eurocontrol Standard Inputs 2024)

These are the default cost parameters used for auto-calculating CAPEX and OPEX when you
use templates or the cost estimation API.

| Infrastructure      | CAPEX (one-time) | Annual OPEX | Source                            |
| ------------------- | ---------------- | ----------- | --------------------------------- |
| Gate                | €8,000,000       | €120,000    | Eurocontrol Standard Inputs       |
| Runway              | €800,000,000     | €12,000,000 | ICAO planning guidelines          |
| Security lane       | €250,000         | €204,400    | Equipment + 16h × €35/h × 365d    |
| Screening unit      | €2,000,000       | €300,000    | CT scanner + maintenance          |
| Terminal (per gate) | €12,000,000      | €200,000    | IATA terminal planning guidelines |

### Benefit Extraction

Annual benefits are calculated from the **delta** between scenario and baseline KPIs:

| Benefit Source                 | Formula                                           |
| ------------------------------ | ------------------------------------------------- |
| **Delay cost avoided**         | Δ avg_delay × total_flights × €102/min × 365 days |
| **EU261 liability avoided**    | Δ eu261_liability_eur × 365 days                  |
| **Missed connections avoided** | Δ missed_connections × €285/pax × 365 days        |
| **Revenue uplift**             | Δ total_revenue_eur × 365 days                    |

The €102/min delay cost and €285/pax rebooking cost come from **Eurocontrol Standard Inputs 2024**.

### How to Edit Costs

#### Via the API

Override cost estimation for a specific scenario:

```bash
# Get a token
TOKEN=$(curl -s -X POST http://localhost:3000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | jq -r .token)

# Estimate costs for a proposed change
curl -X POST http://localhost:3000/api/v1/planning/cost-estimate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "gates_per_terminal": {"A": 16, "B": 14, "C": 14},
    "security_lanes_per_terminal": {"A": 5, "B": 3, "C": 4}
  }'
```

#### Via Custom Scenarios

When creating a custom scenario, you can override the auto-calculated CAPEX and OPEX:

```bash
curl -X POST http://localhost:3000/api/v1/planning/scenarios \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Custom costs",
    "horizon": "month",
    "monte_carlo_runs": 50,
    "capex_eur": 5000000,
    "opex_delta_eur": 100000,
    "infrastructure": {
      "gates_per_terminal": {"A": 16, "B": 14, "C": 14}
    }
  }'
```

#### Modifying Default Unit Costs

To change the unit cost constants, edit `services/planning-service/engine/infrastructure.py`
and update the `COST_ESTIMATES` dictionary:

```python
COST_ESTIMATES = {
    "gate": {"capex": 8_000_000, "annual_opex": 120_000},
    "runway": {"capex": 800_000_000, "annual_opex": 12_000_000},
    "security_lane": {"capex": 250_000, "annual_opex": 204_400},
    "screening_unit": {"capex": 2_000_000, "annual_opex": 300_000},
    "terminal": {"capex_per_gate": 12_000_000, "annual_opex_per_gate": 200_000},
}
```

Rebuild the container after editing: `docker compose up --build -d planning-service --no-deps`

---

## Investment Analysis (DCF)

### How NPV Is Calculated

The investment model uses **Discounted Cash Flow (DCF)** analysis:

```
         N
NPV = Σ    CF_t / (1 + r)^t
        t=0

where:
  CF_0 = -CAPEX                          (upfront investment)
  CF_t = Annual Benefit - Annual OPEX     (net annual cash flow, years 1..N)
  r    = discount rate (WACC, default 7%)
  N    = investment horizon (default 25 years)
```

### Decision Criteria

| Metric      | Good        | Marginal        | Bad                  |
| ----------- | ----------- | --------------- | -------------------- |
| **NPV**     | > 0         | > -10% of CAPEX | < -10% of CAPEX      |
| **IRR**     | > WACC (7%) | Near WACC       | < WACC               |
| **Payback** | < 15 years  | 15–25 years     | > investment horizon |

The system recommends:

- **invest** — NPV positive AND IRR exceeds WACC
- **marginal** — NPV near zero, sensitive to assumptions
- **do not invest** — NPV significantly negative

### IRR Computation

IRR (Internal Rate of Return) is the discount rate that makes NPV = 0. It's computed
using a bisection method between -50% and 200% (expanded to 500% if needed).

### Cumulative Cash Flow Chart

The Investment tab shows a horizontal bar chart of cumulative cash flow over time:

```
Y0   ████████████████████  -€16M    (CAPEX outflow)
Y1   ███████████████       -€15.3M
Y2   ██████████████        -€14.5M
...
Y22  █                     -€0.2M
Y23  █                     +€0.5M   ← Payback
Y24  ██                    +€1.2M
Y25  ███                   +€1.9M
```

---

## Multi-Year KPI Projections

The Results tab includes a **multi-year projection** that scales KPIs based on demand growth:

| Growth scenario | Rate | Source                          |
| --------------- | ---- | ------------------------------- |
| Low             | 1.8% | Eurocontrol STATFOR pessimistic |
| Base            | 3.4% | Eurocontrol STATFOR central     |
| High            | 4.8% | Eurocontrol STATFOR optimistic  |

KPIs scale differently with demand:

| KPI type         | Scaling rule                                         |
| ---------------- | ---------------------------------------------------- |
| Demand-sensitive | Linear (delay, missed connections, costs, EU261)     |
| Utilisation      | Sub-linear (√ demand factor, capped at 100%)         |
| Rates            | Slight degradation (-0.5% per year for on-time rate) |
| Revenue          | Sub-linear (demand^0.3)                              |

---

## Decision Audit Trail

The Audit tab tracks every autonomous recommendation the system makes during simulation:

1. System detects a threshold being exceeded (e.g., EU261 > €10K)
2. System recommends an action (e.g., "Open security lane in Terminal A")
3. System records the **predicted cost saving**
4. 30 simulated minutes later, system measures the **actual outcome**
5. Prediction accuracy is computed as: `actual_saving / predicted_saving × 100`

This feedback loop calibrates model accuracy over time.

---

## Architecture (for developers)

```
┌─────────────────────────────────────────────────────┐
│                  planning-service (8009)             │
│                                                     │
│  ┌──────────┐   ┌──────────┐   ┌─────────────────┐ │
│  │ Templates │   │  Runner  │   │ Investment (DCF) │ │
│  │  (5 pre- │──▶│ (Monte   │──▶│ NPV / IRR /     │ │
│  │   built) │   │  Carlo)  │   │ Payback / Rec.  │ │
│  └──────────┘   └──────────┘   └─────────────────┘ │
│       │              │                    │         │
│       ▼              ▼                    ▼         │
│  ┌──────────┐   ┌──────────┐   ┌─────────────────┐ │
│  │ Scenario │   │  SimEng  │   │    Benefit      │ │
│  │  Model   │   │ (per-day │   │   Extractor     │ │
│  │ (in-mem) │   │  engine) │   │ (delta → €/yr)  │ │
│  └──────────┘   └──────────┘   └─────────────────┘ │
│                      │                              │
│                      ▼                              │
│               ┌─────────────┐                       │
│               │   Schedule  │                       │
│               │  Adapters   │                       │
│               │ (sim / BTS) │                       │
│               └─────────────┘                       │
└─────────────────────────────────────────────────────┘
```

### Key Files

| Purpose                | Path                                                                      |
| ---------------------- | ------------------------------------------------------------------------- |
| Service entry point    | `services/planning-service/main.py`                                       |
| REST endpoints         | `services/planning-service/routers/planning.py`                           |
| Infrastructure config  | `services/planning-service/engine/infrastructure.py`                      |
| Simulation engine      | `services/planning-service/engine/simulation.py`                          |
| Day result model       | `services/planning-service/engine/results.py`                             |
| Scenario model + store | `services/planning-service/scenarios/model.py`                            |
| Scenario runner        | `services/planning-service/scenarios/runner.py`                           |
| Pre-built templates    | `services/planning-service/scenarios/templates.py`                        |
| DCF calculator         | `services/planning-service/finance/investment.py`                         |
| Benefit extractor      | `services/planning-service/finance/benefit_extractor.py`                  |
| Cost estimation        | `services/planning-service/engine/infrastructure.py` (`estimate_costs()`) |

### REST API

| Method | Endpoint                                | Description                                  |
| ------ | --------------------------------------- | -------------------------------------------- |
| GET    | `/planning/scenarios`                   | List scenarios (filter by status/horizon)    |
| POST   | `/planning/scenarios`                   | Create custom scenario                       |
| GET    | `/planning/scenarios/{id}`              | Get scenario details                         |
| GET    | `/planning/scenarios/{id}/status`       | Poll run progress                            |
| GET    | `/planning/scenarios/{id}/results`      | Full results for completed scenario          |
| DELETE | `/planning/scenarios/{id}`              | Delete scenario and results                  |
| POST   | `/planning/templates/{name}`            | Create from template                         |
| GET    | `/planning/templates`                   | List available templates                     |
| POST   | `/planning/investment/analyze`          | Standalone NPV/IRR analysis                  |
| POST   | `/planning/investment/sensitivity`      | Sensitivity analysis (multiple growth rates) |
| GET    | `/planning/demand/growth`               | Eurocontrol STATFOR growth projections       |
| POST   | `/planning/demand/forecast/custom`      | Custom demand forecast with shock events     |
| POST   | `/planning/scenarios/compare/multiyear` | Multi-year KPI projection                    |
| GET    | `/planning/baseline`                    | Current infrastructure config + pax          |
| POST   | `/planning/cost-estimate`               | Auto-estimate CAPEX/OPEX from changes        |
| GET    | `/planning/estimate`                    | Estimate scenario run time                   |

### Limitations

- **In-memory storage**: scenarios and results are stored in Python dictionaries. They are lost
  when the container restarts. This is by design for a simulation — not a production limitation.
- **Single-threaded runner**: scenarios run sequentially in FastAPI background tasks. A long
  scenario (year × 200 MC) blocks subsequent runs.
- **No real weather data**: weather effects are simulated, not fetched from a real weather API.

For full technical details, see `docs/services/planning-service/SPEC.md`.

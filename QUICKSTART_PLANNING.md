# Quickstart: Capacity Planning & Investment Analysis

This guide explains how to use the **Planning** dashboard to run capacity
planning scenarios, read simulation results, and interpret investment analysis.

---

## Prerequisites

| Requirement | Detail |
|---|---|
| Stack running | `docker compose up --build` — all services healthy |
| planning-service | Must be `Up` on port 8009 — check with `docker compose ps` |
| Dashboard | Open `http://localhost:5173` |

Navigate to **Planning** from the sidebar.

---

## Concepts

### What is a scenario?

A scenario is a "what-if" simulation that compares a proposed infrastructure
change against the current KART baseline. Every scenario automatically runs
**two simulations** with the same dates and random seeds:

| Run | Configuration |
|---|---|
| **Baseline** | Current KART infrastructure (42 gates, 2 runways, 11 security lanes) |
| **Scenario** | Your proposed change (e.g. +3 gates in Terminal A) |

The difference between the two runs is what you see in the results.

### Monte Carlo

Each scenario runs multiple times (default 200) with different random seeds to
produce a **distribution** of outcomes rather than a single point estimate. The
results show you the mean, p5, and p95 of every KPI.

### Baseline configuration (KART today)

| Resource | Value |
|---|---|
| Gates | Terminal A: 14, Terminal B: 14, Terminal C: 14 (42 total) |
| Runways | 09L (ILS-equipped), 09R (visual only) |
| Security lanes | Terminal A: 4, Terminal B: 3, Terminal C: 4 (11 total) |
| Baggage screening | 6 units, 1 800 bags/hour sorting capacity |
| Daily flights | ~420 |
| Load factor | 80% average |

---

## Tab 1 — Scenario Builder

### Using a template (recommended)

Templates pre-fill infrastructure parameters and cost estimates with industry
benchmarks. Select a template from the dropdown:

| Template | What it does | Key parameters |
|---|---|---|
| **Add Gates** | Expand a terminal with additional contact gates | Terminal (A/B/C), number of gates |
| **Add Runway** | Build a new runway | Runway ID, length (m), ILS yes/no |
| **New Route** | Add a new destination route | Destination city, daily flights, aircraft type |
| **Security Lanes** | Add/remove lanes per terminal | Per-terminal lane count adjustments |

Each template auto-configures:
- **Capex** — one-time capital expenditure (e.g. €8M per gate, €180M for a runway)
- **Opex delta** — annual operating cost change (e.g. €120K/year per gate)
- **Monte Carlo runs** — 200 by default
- **Investment horizon** — 20–25 years depending on asset type
- **Discount rate** — 7% WACC (weighted average cost of capital)

**Step-by-step:**
1. Pick a template from the dropdown.
2. Fill in the parameters (terminal, count, etc.).
3. Review the **Cost Preview** panel — it shows the auto-calculated capex, opex, and horizon.
4. Click **Create & Run**.
5. The scenario appears in the list with status `pending` → `running` → `completed`.

### Custom scenario

Select **Custom Scenario** to manually specify all infrastructure parameters
and cost assumptions. Use this when you want to combine multiple changes
(e.g. add gates AND add security lanes simultaneously).

---

## Tab 2 — Results

Once a scenario completes, select it to view the comparison.

### Infrastructure Changes

At the top, a diff shows exactly what changed between baseline and scenario:
> "+ Added 3 gates in Terminal A (14 → 17)"

### KPI Comparison Table

| Column | What it means |
|---|---|
| **KPI** | The metric name. Hover for a description of how it's computed. |
| **Baseline** | Mean value from the baseline simulation (current infrastructure). |
| **Scenario** | Mean value from the scenario simulation (proposed change). |
| **Change %** | Percentage change from baseline. Green = improvement, red = degradation. |
| **90% Band** | The p5–p95 confidence interval from the Monte Carlo runs. |
| **Verdict** | ✓ = statistically significant improvement, ✗ = degradation, — = negligible. |

### KPI definitions

| KPI | Description | Unit | Good direction |
|---|---|---|---|
| Avg gate utilization | Mean % of time each gate is occupied | % | Lower is better (less congestion) |
| Peak gate utilization | Maximum gate occupancy across all hours | % | Lower is better |
| Avg security wait | Mean passenger wait time at security | minutes | Lower |
| Peak security wait | Maximum security wait across all hours | minutes | Lower |
| Runway throughput | Average landings + takeoffs per hour | ops/hour | Higher |
| Avg turnaround time | Mean aircraft ground time | minutes | Lower |
| Baggage delivery time | Mean time from aircraft to carousel | minutes | Lower |
| Pax connection rate | % of connecting passengers who make their connection | % | Higher |
| Delay propagation | % of delays that cascade to downstream flights | % | Lower |
| Total delay minutes | Sum of all flight delay minutes in the simulated period | minutes | Lower |

### How to read the results

- **Green row** = the scenario improves this KPI vs baseline.
- **Red row** = the scenario makes this KPI worse.
- **Narrow confidence band** = high confidence in the result.
- **Wide confidence band** = high variability; consider running more Monte Carlo iterations.

If most KPIs show ✓ and the investment tab shows NPV > 0, the scenario is
a strong candidate for implementation.

---

## Tab 3 — Investment Analysis

The investment tab runs a **Discounted Cash Flow (DCF)** analysis on the
scenario's cost and benefit projections.

### Headline metrics

| Metric | What it means | Good value |
|---|---|---|
| **NPV** | Net Present Value — total value created/destroyed in today's euros | > 0 |
| **IRR** | Internal Rate of Return — the effective annual return of the investment | > WACC (7%) |
| **Payback** | Years until cumulative cash flows turn positive | < 10 years |
| **Recommendation** | Auto-generated verdict based on NPV and IRR | "Invest" / "Marginal" / "Reject" |

### How benefits are calculated

Annual benefit = operational savings projected from the simulation delta × 365:

| Saving type | Formula | Source |
|---|---|---|
| Delay cost avoided | Δ delay minutes × €102/min | Eurocontrol Standard Inputs 2024 |
| Rebooking cost avoided | Δ missed connections × €285/pax | Industry average |
| EU261 compensation avoided | Δ eligible delays × €250–600/pax | EU regulation |

### Benefit breakdown

Shows the contribution of each saving category to the total annual benefit.
This lets you understand **where** the value comes from — is it mostly delay
reduction? Or passenger connection improvement?

### Cumulative cash flow chart

A horizontal bar chart showing year-by-year cumulative cash flows:
- **Red bars (left)** = the investment hasn't paid back yet.
- **Green bars (right)** = positive cumulative return.
- **Cyan line** = the payback year.

Year 0 is always negative (initial capex). Each subsequent year adds
`annual benefit − opex delta`, discounted at the WACC rate.

### Demand growth projections

At the bottom, Eurocontrol STATFOR growth scenarios (low / base / high) show
how traffic growth assumptions affect long-term benefit projections.

---

## Tab 4 — Audit Log

Lists every scenario created, who triggered it, and its lifecycle
(created → pending → running → completed / failed). Useful for tracking
what simulations have been run and their parameter configurations.

---

## Example workflow

**Question:** *"Should we add 3 gates to Terminal A?"*

1. Go to **Scenario Builder** → select **Add Gates**.
2. Set Terminal = A, Gates = 3.
3. Review cost preview: Capex = €24M, Opex = €360K/year.
4. Click **Create & Run**. Wait for completion (~30 seconds).
5. Switch to **Results** tab.
   - Check that gate utilization dropped (✓ = less congestion).
   - Check security wait (should be unchanged — gates don't affect security).
   - Note the 90% confidence bands — are they tight?
6. Switch to **Investment** tab.
   - NPV = €12.4M → positive, the investment creates value.
   - IRR = 11.2% → above the 7% WACC.
   - Payback = 8 years → reasonable for airport infrastructure.
   - Recommendation: **Invest**.
7. Done. The scenario stays in the audit log for future reference.

---

## API reference (for scripting)

All endpoints are available through the API gateway at `localhost:3000`.

```bash
# Get auth token
TOKEN=$(curl -s -X POST http://localhost:3000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | jq -r .token)

# Create a gate scenario via template
curl -X POST http://localhost:3000/api/v1/planning/templates/add_gate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"terminal": "A", "additional_gates": 3}'

# List all scenarios
curl http://localhost:3000/api/v1/planning/scenarios \
  -H "Authorization: Bearer $TOKEN"

# Get results for a completed scenario
curl http://localhost:3000/api/v1/planning/scenarios/{id}/results \
  -H "Authorization: Bearer $TOKEN"

# Investment analysis
curl http://localhost:3000/api/v1/planning/investment/{id} \
  -H "Authorization: Bearer $TOKEN"
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Scenario stuck in `pending` | planning-service overloaded or crashed | `docker compose restart planning-service` |
| "No investment analysis available" | Template didn't set capex/opex | Use a template instead of custom, or manually set capex > 0 |
| All KPIs show "—" (negligible) | Change is too small to detect | Increase Monte Carlo runs or make a larger infrastructure change |
| Results tab empty | Scenario not yet completed | Wait or check status in Audit tab |
| "API disconnected" banner | Any backend service is unreachable | Check `docker compose ps` — all services must be healthy |
| Time estimate shows "low confidence" | No historical runs yet | Run a few scenarios first; estimation improves after 3+ completed runs |

---

## Worked Example: Full API Walkthrough

This section shows the complete lifecycle of a planning scenario via the API,
with example responses you can use to understand the output format.

### 1. Create a scenario

```bash
curl -s -X POST http://localhost:3000/api/v1/planning/templates/add_gate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"terminal": "B", "additional_gates": 1}' | jq .
```

**Response:**

```json
{
  "id": "a1b2c3d4-...",
  "name": "Add 1 gate(s) to Terminal B",
  "status": "pending",
  "horizon": "day",
  "monte_carlo_runs": 200,
  "estimated_duration_seconds": 245.0,
  "estimated_duration_human": "4 min 5 sec",
  "estimation_confidence": "medium"
}
```

The `estimated_duration_human` field tells you roughly how long the scenario
will take to complete. Confidence improves as the system records more runs.

### 2. Check progress while running

```bash
curl -s http://localhost:3000/api/v1/planning/scenarios/$ID/status \
  -H "Authorization: Bearer $TOKEN" | jq .
```

**Response (mid-run):**

```json
{
  "id": "a1b2c3d4-...",
  "status": "running",
  "progress_pct": 43,
  "runs_completed": 172,
  "runs_total": 400,
  "elapsed_seconds": 135.2,
  "estimated_remaining_seconds": 179.0
}
```

`runs_total` is `monte_carlo_runs × 2` because each scenario runs both a
baseline and a modified simulation.

### 3. Read the results

```bash
curl -s http://localhost:3000/api/v1/planning/scenarios/$ID/results \
  -H "Authorization: Bearer $TOKEN" | jq .
```

**Response (excerpt):**

```json
{
  "scenario_id": "a1b2c3d4-...",
  "status": "completed",
  "run_duration_seconds": 312.5,
  "infrastructure_changes": [
    {
      "resource": "Gates Terminal B",
      "baseline": 14,
      "scenario": 15,
      "delta": "+1"
    }
  ],
  "kpis": {
    "avg_gate_utilization": { "mean": 71.2, "p5": 68.0, "p95": 74.5 },
    "peak_gate_utilization": { "mean": 92.1, "p5": 88.0, "p95": 96.0 },
    "avg_security_wait_min": { "mean": 8.3, "p5": 6.1, "p95": 10.8 },
    "runway_throughput_ops_hr": { "mean": 38.5, "p5": 35.0, "p95": 42.0 },
    "avg_turnaround_min": { "mean": 45.2, "p5": 40.0, "p95": 51.0 },
    "total_delay_minutes": { "mean": 1250.0, "p5": 980.0, "p95": 1520.0 }
  },
  "baseline_kpis": {
    "avg_gate_utilization": { "mean": 74.8, "p5": 71.0, "p95": 78.5 },
    "peak_gate_utilization": { "mean": 95.3, "p5": 91.0, "p95": 99.0 },
    "avg_security_wait_min": { "mean": 8.3, "p5": 6.1, "p95": 10.8 },
    "runway_throughput_ops_hr": { "mean": 38.5, "p5": 35.0, "p95": 42.0 }
  },
  "delta_vs_baseline": {
    "avg_gate_utilization": { "baseline": 74.8, "scenario": 71.2, "delta_pct": -4.8, "verdict": "improved" },
    "peak_gate_utilization": { "baseline": 95.3, "scenario": 92.1, "delta_pct": -3.4, "verdict": "improved" },
    "avg_security_wait_min": { "baseline": 8.3, "scenario": 8.3, "delta_pct": 0.0, "verdict": "negligible" }
  }
}
```

### How to interpret this

1. **Gate utilization dropped from 74.8% → 71.2%** (-4.8%) — the extra gate
   reduced congestion. The narrow p5–p95 band (68–74%) means high confidence.

2. **Security wait unchanged** (0.0%) — expected, since adding a gate doesn't
   affect the security screening process.

3. **Runway throughput unchanged** — also expected; gates don't affect runway ops.

4. **Total delay minutes improved** — fewer gate conflicts → fewer cascading delays.

**Rule of thumb:** If you see improvements in the KPIs directly related to
your change (gates → gate utilization) and no degradation elsewhere, the
scenario is worth evaluating financially.

### 4. Investment analysis

```bash
curl -s http://localhost:3000/api/v1/planning/investment/$ID \
  -H "Authorization: Bearer $TOKEN" | jq .
```

**Response (excerpt):**

```json
{
  "capex": 8000000,
  "opex_delta_annual": 120000,
  "discount_rate": 0.07,
  "horizon_years": 25,
  "annual_benefit": 1850000,
  "npv": 12400000,
  "irr": 0.112,
  "payback_years": 8,
  "recommendation": "invest",
  "annual_benefit_breakdown": {
    "delay_cost_avoided": 1200000,
    "rebooking_cost_avoided": 450000,
    "eu261_avoided": 200000
  },
  "cumulative_cash_flows": [
    -8000000, -6270000, -4630000, -3070000, -1590000,
    -180000, 1160000, 2430000, 3640000, 4790000
  ]
}
```

### How to interpret this

| Metric | Value | Interpretation |
|---|---|---|
| NPV = €12.4M | > 0 | The gate pays for itself and creates €12.4M of value |
| IRR = 11.2% | > 7% WACC | Return exceeds the cost of capital |
| Payback = 8 years | Reasonable | Airport infrastructure typically pays back in 5–15 years |
| Recommendation | "invest" | NPV > 0 and IRR > WACC → green light |

The `annual_benefit_breakdown` shows that **65% of the benefit comes from delay
cost avoidance** (€1.2M/year), followed by rebooking savings (€450K). This is
typical for gate expansion scenarios.

The `cumulative_cash_flows` array shows the investment turning positive in year 6
(the first positive value in the array).

### 5. Service monitoring

```bash
# Check planning service health and run history
curl -s http://localhost:3000/api/v1/planning/service-status \
  -H "Authorization: Bearer $TOKEN" | jq .
```

**Response:**

```json
{
  "scenarios": { "pending": 0, "running": 1, "completed": 5, "failed": 0 },
  "active_runs": 1,
  "timing": {
    "total_samples": 5,
    "mean_duration_seconds": 298.4,
    "median_duration_seconds": 312.5,
    "min_duration_seconds": 45.2,
    "max_duration_seconds": 485.0
  }
}
```

A Grafana dashboard is also available at `http://localhost:3001` under
**Planning & Capacity** — it shows active scenarios, completion rates,
duration percentiles, and Monte Carlo throughput in real time.

### Pre-creation time estimation

```bash
# Estimate how long a scenario will take before creating it
curl -s "http://localhost:3000/api/v1/planning/estimate?horizon=day&monte_carlo_runs=200" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

```json
{
  "estimated_seconds": 245.0,
  "human_readable": "4 min 5 sec",
  "confidence": "medium",
  "based_on_samples": 5
}
```

# Use Case Roadmap — Arthur International Airport

Actionable use cases filtered from `FUTURE_USE_CASES.md`. All items require no paid data,
extend existing architecture, and produce a visible dashboard feature or published artifact.

**Excluded:** 1.1 (real ADS-B + surface radar), 4.2 (airport retail calibration data),
6.2 (airline financial data), 3.2 (ICAO aircraft performance tables — free but high
integration cost for limited simulation value).

---

## Selection Criteria

An item is included only if it meets all three:

1. **No paid data** — all inputs are free, open-source, or already in the simulation
2. **Builds on existing architecture** — extends a current service, no new infrastructure
3. **Concrete deliverable** — produces a visible dashboard feature or published artifact

---

## Phase 1 — Quick Wins (1–2 weeks each)

### 1A. Carbon Footprint Tracker

_Source: use case 3.1_

**Data:** ICAO Carbon Emissions Calculator (free) · ACI Airport Carbon Accreditation benchmarks (free) · IPCC emission factors (public)

**Deliverable:** Carbon tab in the Cost Dashboard with source breakdown, timeline, and a net-zero scenario builder.

**Tasks:**

1. Add `CarbonRecord` node to `DATA_MODEL.md` — properties: `flight_id`, `source` (`apu` | `ground_vehicle` | `terminal` | `flight`), `co2_kg`, `sim_time`
2. Create `carbon-tracker` module in `cost-service` (passive Kafka consumer):
   - `flights.events` → Scope 3 flight emissions: `distance_km × pax × emission_factor_per_pax_km` (ICAO methodology)
   - Turnaround events → APU emissions: `stand_time_minutes × 3 kg CO₂/min` (ICAO reference)
   - `sim.clock` → Terminal energy: `occupancy_pax × 0.012 kWh/pax/h × 0.233 kg CO₂/kWh` (ACI benchmark)
3. Add REST endpoints: `GET /costs/carbon/summary`, `GET /costs/carbon/by-source`, `GET /costs/carbon/timeline`
4. Add Carbon tab to Cost Dashboard: pie chart by source, daily total, timeline chart
5. Add net-zero scenario builder: toggle GPU adoption (−90% APU), EV ground fleet (−80%), solar offset

**Integration:** Extends `cost-service` (port 8008). Uses existing Kafka topics. No new services.

---

### 1B. Counterfactual Delay Analysis

_Source: use case 5.3_

**Data:** None — uses existing simulation replay and what-if engine.

**Deliverable:** "What If" panel in the Planning Results tab showing projected delay reduction and EU261 savings from earlier interventions.

**Tasks:**

1. Add `POST /planning/scenarios/{id}/replay` to `planning-service`:
   - Accepts: `{ decision_overrides: [{ sim_time: "T+10", action: "gdp_start" }] }`
   - Re-runs the scenario with overridden decision timing
   - Returns outcome delta (original vs counterfactual)
2. Add `GET /planning/scenarios/{id}/causal-graph`:
   - Builds a DAG from the event timeline: trigger → cascade → interventions → outcome
   - Returns a JSON adjacency list for frontend rendering
3. Add "What If" panel to Planning Results tab:
   - Slider: "Start GDP at T+N instead of T+45"
   - Display projected delay reduction and EU261 liability saving
4. Add `POST /planning/scenarios/{id}/counterfactual-report`:
   - Returns a structured JSON report comparing N counterfactual decision timings

**Integration:** Extends `planning-service` (port 8009). Uses existing runner and simulation engine.

---

### 1C. Accessibility & Special Assistance Optimisation

_Source: use case 4.3_

**Data:** ECAC Doc 30 service standards (public) · existing `special_assistance` flag on passenger nodes.

**Deliverable:** Accessibility card in the Passenger Dashboard with SLA tracking and hourly staffing recommendations.

**Tasks:**

1. Add `WheelchairResource` node to Neo4j: `{ terminal, total_count, available_count }`
2. Add wheelchair dispatch model to `passenger-service`:
   - Configurable pool size per terminal (set in `airport.yaml`)
   - Queue when demand exceeds supply; track per-passenger wait time
   - Emit `WheelchairDispatched` / `WheelchairReturned` Kafka events
3. Add `GET /passengers/accessibility/sla`:
   - % of SA passengers reaching gate before boarding cutoff
   - Mean check-in-to-gate time: SA vs non-SA
   - Benchmark against ECAC Doc 30 target (90% within MCT)
4. Add `GET /passengers/accessibility/staffing`:
   - Given current demand pattern, recommend wheelchair agents per terminal per hour
5. Add Accessibility card to Passenger Dashboard

**Integration:** Extends `passenger-service` (port 8002). Adds 2 new Kafka event types.

---

## Phase 2 — Medium Effort (2–4 weeks each)

### 2A. Emergency Response Simulation & Training

_Source: use case 1.2_

**Data:** ICAO Annex 14, Chapter 9 (public standard).

**Deliverable:** Emergency Training tab in the Incident Dashboard with tabletop exercise mode and post-exercise scoring.

**Tasks:**

1. Add `EmergencyVehicle` node type: `{ id, type (fire | medical | police), terminal, depot_location, status }`
2. Add vehicle routing engine to `incident-service`:
   - Shortest path from depot to incident using airfield layout graph
   - Response time = `distance / speed + dispatch_delay`
3. Create emergency scenario library (`config/emergencies/*.yaml`):
   - Aircraft accident (ICAO Category 8–10)
   - Bomb threat (terminal evacuation)
   - Mass casualty medical event
   - Fire (terminal or aircraft)
4. Add tabletop exercise mode to `sim-orchestrator`:
   - `POST /sim/exercise/start` — inject emergency, pause simulation
   - `POST /sim/exercise/respond` — operator selects vehicles and routes
   - `POST /sim/exercise/evaluate` — resume simulation, compare operator response vs optimal
5. Add post-exercise report: response time vs target, resource utilisation, estimated casualties avoided
6. Add Emergency Training tab to Incident Dashboard

**Integration:** Extends `incident-service` (port 8005) and `sim-orchestrator` (port 8006).

---

### 2B. Slot Allocation & Coordination Simulator

_Source: use case 2.1_

**Data:** None — uses existing schedule model.

**Deliverable:** Slot Coordination tab in the Planning Dashboard with demand/capacity timeline, allocation results, and algorithm comparison.

**Tasks:**

1. Add `SlotRequest` model: `{ airline, time_window, aircraft_type, priority }`
2. Add slot allocation engine to `planning-service`:
   - Input: slot requests + runway/gate capacity constraints
   - Output: allocation minimising total displacement (requested vs allocated)
   - Algorithm: integer linear program via [PuLP](https://pypi.org/project/PuLP/) (free, pure Python)
3. Add schedule compression: identify flights shiftable ±15 min to improve throughput
4. Add `POST /planning/slots/allocate` and `POST /planning/slots/compress` endpoints
5. Add Slot Coordination tab to Planning Dashboard:
   - Hourly demand vs capacity bar chart
   - Allocation result table (requested vs allocated)
   - Compression opportunities highlighted
6. Compare allocation strategies: FCFS vs optimised vs priority-weighted

**Integration:** Extends `planning-service` (port 8009). Adds `pulp` dependency.

---

### 2C. Terminal Design A/B Testing

_Source: use case 2.2_

**Data:** None — uses existing terminal layout model.

**Deliverable:** Terminal Design tab in the Planning Dashboard with side-by-side KPI comparison, zone density heatmaps, and retail placement optimisation.

**Tasks:**

1. Add `TerminalLayout` config model: gate positions, zone distances, retail zones, security lane positions
2. Add layout comparison engine to `planning-service`:
   - Accept two `InfrastructureConfig + TerminalLayout` pairs
   - Run identical passenger simulations on both
   - Compare: avg walking time, missed connections, retail dwell exposure, boarding delay
3. Add `POST /planning/terminal/compare` endpoint
4. Add `GET /planning/terminal/{layout_id}/density?hour=14` — zone-level passenger density for heatmap rendering
5. Add Terminal Design tab to Planning Dashboard:
   - Side-by-side KPI table
   - Zone density heatmaps
   - Retail placement score per zone
6. Add retail placement optimiser: given retail unit types and terminal zones, find assignment maximising dwell-time exposure

**Integration:** Extends `planning-service` (port 8009). May extend `passenger-service` for the walking time model.

---

### 2D. Network Resilience & Hub Dependency

_Source: use case 2.3_

**Data:** BTS T-100 segment data (already at `data/bts/`, free).

**Deliverable:** Network Resilience tab in the Planning Dashboard with concentration scoring, airline removal scenarios, and diversification recommendations.

**Tasks:**

1. Add hub dependency scoring to `planning-service`:
   - Per airline: share of movements, revenue, and connecting pax
   - Hub dependency index = Herfindahl index across airlines
2. Add `POST /planning/network/disruption`:
   - Input: `{ airline: "UA", reduction_pct: 100 }`
   - Output: impact on total pax, gate utilisation, revenue, and connecting traffic
3. Add `POST /planning/network/diversify`:
   - Input: target dependency score
   - Output: recommended new routes from OurAirports destination pool with gravity-model demand estimate (`demand ∝ pop_origin × pop_dest / distance²`)
4. Add Network Resilience tab to Planning Dashboard:
   - Airline concentration pie chart and dependency score gauge
   - "Remove airline" scenario builder
   - Diversification route recommendations

**Integration:** Extends `planning-service` (port 8009). Uses BTS T-100 data adapter.

---

## Phase 3 — Research Projects (4–8 weeks each)

### 3A. Multi-Agent Reinforcement Learning Benchmark

_Source: use case 5.1_

**Data:** None — the simulation twin is the environment.

**Deliverable:** Reproducibility package (`rl-benchmark/`) with trained MARL policies, interpretable decision-tree extracts, and a benchmark report across 1,000 simulated days.

**Tasks:**

1. Create a `gymnasium` wrapper for the KART simulation:
   - Observation space: flight states, gate states, weather, queue lengths
   - Action space: gate assignment, runway assignment, GDP trigger, security lane management
   - Reward: negative total delay + negative EU261 liability
2. Define 3 agent types: airline (gate requests, pushback timing), ground handler (vehicle dispatch, baggage priority), airport ops (security lanes, runway assignment)
3. Implement baseline policies: random, greedy, rule-based (current system logic)
4. Train MARL policies using `stable-baselines3` + `PettingZoo`:
   - Independent PPO (each agent optimises own reward)
   - Cooperative PPO (shared global reward)
5. Extract learned policies as decision trees (CART via `scikit-learn`) for interpretability
6. Benchmark: MARL vs all baselines across 1,000 simulated days
7. Publish reproducibility package: environment, training scripts, evaluation scripts

**Integration:** New top-level `rl-benchmark/` directory. Uses `planning-service` simulation engine as a library.
**Dependencies:** `gymnasium`, `stable-baselines3`, `pettingzoo`, `scikit-learn`

---

### 3B. Airport Valuation Model

_Source: use case 6.1_

**Data:** ACI airport revenue benchmarks (public) · existing cost model.

**Deliverable:** Valuation tab in the Planning Dashboard with EBITDA simulation, sensitivity analysis, and an auto-generated investment thesis document.

**Tasks:**

1. Add revenue waterfall model to `cost-service`:
   - Revenue streams: landing fees, passenger charges, retail, parking, cargo, slot fees
   - All modelled as functions of `daily_flights × load_factor × pax_per_flight`
2. Add `GET /costs/ebitda?horizon=year`:
   - Revenue minus staffing, energy, maintenance, and incident costs
   - Uses all existing cost model components
3. Add `POST /planning/valuation/sensitivity`:
   - Vary demand growth (low/base/high), fuel price (±30%), EU261 claim rate (±50%)
   - Return EBITDA range per scenario
4. Add `POST /planning/valuation/thesis`:
   - Input: planning scenario ID
   - Output: structured JSON investment case (NPV waterfall, sensitivity tables, risk factors) rendered to PDF via template
5. Add Valuation tab to Planning Dashboard

**Integration:** Extends `cost-service` and `planning-service`.

---

### 3C. Insurance & Risk Modelling

_Source: use case 6.3_

**Data:** None — Monte Carlo simulation on existing incident model.

**Deliverable:** Risk Management tab in the Planning Dashboard with annual loss distribution, VaR gauges, and mitigation ROI table.

**Tasks:**

1. Add `POST /planning/risk/simulate`:
   - Runs 1,000 simulated years at compressed speed
   - Per year: total incident cost, EU261 liability, cascade cost
   - Fits log-normal distribution to annual loss data
2. Add `GET /planning/risk/var`:
   - 95th and 99th percentile annual loss
   - Self-insurance reserve recommendation
3. Add `POST /planning/risk/mitigation`:
   - Input: list of mitigations (improved tracking, faster response, added capacity)
   - Output: VaR reduction per mitigation, mitigation cost, ROI
4. Add Risk Management tab to Planning Dashboard:
   - Annual loss distribution histogram
   - VaR gauge (95th / 99th percentile)
   - Mitigation ROI table
5. Add reinsurance layer optimiser: find optimal retention/attachment point

**Integration:** Extends `planning-service` (port 8009). Uses existing Monte Carlo infrastructure.

---

## Phase 4 — Dashboard Enhancements (< 1 week each)

### 4A. Energy Consumption Dashboard

_Source: use case 3.3_

**Data:** ACI energy benchmarks (free).

**Tasks:**

1. Add energy model to `cost-service`: `kWh = zone_area × occupancy_factor × 0.15 kWh/m²/h`
2. Add `GET /costs/energy/summary` — current consumption by zone
3. Add `GET /costs/energy/forecast` — next 4 hours based on passenger forecast
4. Add Energy card to Cost Dashboard: consumption by zone, daily total, 4-hour forecast
5. Add predictive pre-conditioning: pre-cool/heat zones 30 min before peak using the LightGBM passenger forecast from `passenger-service`

---

### 4B. Airfield Maintenance Scheduler

_Source: use case 1.3_

**Data:** None — simulated pavement condition model.

**Tasks:**

1. Add pavement condition index (PCI) model: `PCI = 100 − 0.001 × cumulative_movements × avg_weight`
2. Add `GET /planning/maintenance/status` — current PCI per runway and taxiway segment
3. Add `POST /planning/maintenance/schedule` — find optimal maintenance window minimising delay cost + pavement degradation cost
4. Add Maintenance card to Planning Dashboard

---

### 4C. Personalised Wayfinding Simulation

_Source: use case 4.1_

**Data:** None — uses existing passenger location model.

**Tasks:**

1. Add notification urgency model to `passenger-service`:
   - `urgency = max(0, 1 − (time_to_departure − walking_time − 5 min buffer) / 30 min)`
2. Add `GET /passengers/{id}/notification-urgency` endpoint
3. Add `POST /passengers/notifications/simulate`:
   - Input: strategy (`immediate` | `optimal-timing` | `15min-before`)
   - Output: late boarding rate and missed connection rate per strategy
4. Add Wayfinding card to Passenger Dashboard

---

## Implementation Priority

| #   | Use Case                   | Effort  | Value           | Data Cost  |
| --- | -------------------------- | ------- | --------------- | ---------- |
| 1   | 1A Carbon Tracker          | 1 week  | High (ESG)      | Free       |
| 2   | 1B Counterfactual Analysis | 1 week  | High (ops)      | Free       |
| 3   | 4A Energy Dashboard        | 3 days  | Medium          | Free       |
| 4   | 4C Wayfinding Simulation   | 3 days  | Medium          | Free       |
| 5   | 1C Accessibility           | 2 weeks | High (social)   | Free       |
| 6   | 2B Slot Allocation         | 3 weeks | High (ops)      | Free       |
| 7   | 4B Maintenance Scheduler   | 1 week  | Medium          | Free       |
| 8   | 2D Network Resilience      | 3 weeks | High (business) | Free (BTS) |
| 9   | 2A Emergency Training      | 4 weeks | High (safety)   | Free       |
| 10  | 2C Terminal Design         | 3 weeks | High (planning) | Free       |
| 11  | 3C Risk Modelling          | 4 weeks | High (finance)  | Free       |
| 12  | 3B Valuation Model         | 6 weeks | High (finance)  | Free       |
| 13  | 3A MARL Benchmark          | 8 weeks | High (research) | Free       |

---

## Data Sources

All sources are free and publicly available.

| Source                           | Location                                       | Used by      |
| -------------------------------- | ---------------------------------------------- | ------------ |
| ICAO Carbon Emissions Calculator | icao.int/environmental-protection/CarbonOffset | 1A           |
| ACI Airport Carbon Accreditation | airportcarbonaccreditation.org                 | 1A           |
| IPCC Emission Factors            | ipcc.ch                                        | 1A           |
| ECAC Doc 30                      | ecac-ceac.org                                  | 1C           |
| ICAO Annex 14 Chapter 9          | icao.int                                       | 2A           |
| BTS T-100 Segment Data           | `data/bts/T100_2026.csv` (in repo)             | 2D           |
| OurAirports destinations         | `data/ourairports/` (in repo)                  | 2D           |
| World Bank population/GDP        | data.worldbank.org                             | 2D           |
| ACI Energy Benchmarks            | aci.aero                                       | 4A           |
| ASRS Aviation Safety Reports     | asrs.arc.nasa.gov                              | Future (5.2) |

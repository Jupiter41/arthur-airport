# ROADMAP — Capacity planning
## Arthur International Airport Digital Twin

Capacity planning transforms the twin from an operational tool into a strategic
decision-support system. The key architectural shift: the operational simulation
runs at 60×–3600× to model the next few hours. Capacity planning runs at 10,000×–100,000×
to model months or years, with Monte Carlo uncertainty quantification and financial
return calculations attached to every infrastructure decision.

Before starting any task, read:
- `CLAUDE.md`
- `docs/architecture/OVERVIEW.md`
- `docs/services/planning-service/SPEC.md` (created alongside this roadmap)
- The relevant `SKILL.md` for each service touched

---

## Why capacity planning is architecturally distinct

| | Operational twin | Capacity planning twin |
|---|---|---|
| Time horizon | Next 2–48 hours | Next 1 month – 10 years |
| Simulation speed | 60×–3600× | 10,000×–100,000× |
| Time resolution | 1 sim-minute | 1 sim-day |
| Uncertainty | Single deterministic run | Monte Carlo (50–500 runs) |
| Data source | Live/recent operational data | Historical + demand forecasts |
| Output | "What is happening / what to do now" | "What to build / what it will cost" |
| Neo4j writes | Per state change | Per scenario summary |
| Decision type | Staffing, gate assignment, lane opening | Runways, terminals, routes, gates |

This means capacity planning **does not run in the operational simulation loop**.
It runs as a separate, isolated process in a dedicated `planning-service` that
spins up its own in-memory simulation engine, runs N scenarios, and writes
summary results — never touching the live Neo4j or Kafka state.

---

## The six planning questions and what each requires

### Q1 — "What happens if we add one more gate to Terminal B?"
**Type:** Infrastructure capex justification
**Method:** Compare baseline vs +1 gate over a full peak season
**Key metrics:** Gate conflict frequency, average turnaround delay, missed connections avoided
**Financial output:** Delay cost reduction (€/year) vs construction cost → IRR

Requires:
- Capacity model with gate constraints
- Seasonal demand curve (not just one day)
- Gate construction cost parameter (configurable)
- Multi-year NPV calculator

---

### Q2 — "Should we add a direct route to [new destination]?"
**Type:** Revenue and network decision
**Method:** Model the new route as an additive demand stream
**Key metrics:** Incremental pax, gate utilisation delta, connection network effect, revenue
**Financial output:** Route profitability model (revenue - costs - slot fees)

Requires:
- Real traffic demand data by city pair (BTS T-100 or Eurocontrol STATFOR)
- Network demand model (hub spoke vs point-to-point gravity model)
- Route profitability calculator

---

### Q3 — "What if we had one more security lane?"
**Type:** Staffing ROI
**Method:** Run peak-day scenarios with N vs N+1 lanes open
**Key metrics:** Average wait time, EU261 exposure, connections saved
**Financial output:** Staffing cost (€/day × operating days) vs EU261 saved

Requires:
- Real passenger throughput benchmarks (BTS or ACI)
- LightGBM queue model already built
- Cost model (EU261 + staffing) already built in ROADMAP_COST.md

---

### Q4 — "Where do connecting passengers go — should we redesign the terminal?"
**Type:** Terminal planning
**Method:** Trace actual connection flows, identify high-traffic corridors
**Key metrics:** Walking time per connection pair, retail exposure per path, missed connections by corridor
**Financial output:** Revenue uplift from improved retail placement, connection revenue retained

Requires:
- Real connection data (schedule data + minimum connection time matrix)
- Physical layout model (already built in Gap 1)
- Walking time model (already built)

---

### Q5 — "If weather closes a runway for 2 hours, what's the best recovery plan?"
**Type:** Operational resilience
**Method:** Monte Carlo over weather scenarios, compare recovery strategies
**Key metrics:** Total delay minutes, diversions, holding fuel cost, recovery time
**Financial output:** Cost of each recovery strategy → optimal plan per weather scenario

Requires:
- Real weather history (Iowa State Mesonet — already in data/)
- Calibrated weather FSM (Task 9.2 of ROADMAP_COST.md)
- Cost model already built

---

### Q6 — "Should we invest in a 3rd runway?"
**Type:** Strategic capex (10-year horizon)
**Method:** Traffic growth projection × capacity constraint model × NPV
**Key metrics:** Year of saturation, peak hour congestion, delay cost trajectory
**Financial output:** 10-year NPV of runway investment vs do-nothing scenario

Requires:
- Demand growth model (ICAO/Eurocontrol long-term traffic forecasts)
- Full runway capacity model calibrated against real throughput
- Construction cost + operating cost parameters
- NPV/IRR calculator with discount rate

---

## Architecture — planning-service

```
planning-service (port 8008)
├── In-memory simulation engine     (runs isolated, no Kafka, no live Neo4j writes)
├── Scenario manager                (define, queue, run, compare scenarios)
├── Demand model                    (calibrated demand surface, seasonal curves)
├── Capacity constraints engine     (gates, runways, security lanes, carousels)
├── Monte Carlo runner              (N independent runs, uncertainty quantification)
├── Investment model                (capex/opex + NPV/IRR calculator)
├── Results store                   (separate Neo4j database or labelled subgraph)
└── REST API                        (scenario CRUD, run, results, comparisons)
```

The planning-service **shares the same Neo4j instance** but writes to a separate
label space (`PlanningScenario`, `PlanningResult`) that never overlaps with
operational nodes (`Flight`, `Passenger`, `Baggage`).

It does **not** subscribe to Kafka. It reads the current operational state from
Neo4j when a scenario starts (as the baseline), then runs entirely in memory.

---

## Phase 1 — Data ingestion layer

### Task P1.1 — Pluggable adapter architecture

**Files to create:**
```
services/planning-service/adapters/
├── base.py              # AbstractAdapter interface
├── simulation.py        # wraps existing sim-orchestrator seed logic
├── bts.py               # reads BTS T-100 CSV files
├── opensky.py           # reads OpenSky historical CSVs
├── mesonet.py           # reads Iowa State Mesonet weather CSVs
└── registry.py          # selects adapter at runtime from config
```

Define the `AbstractAdapter` interface. Every adapter must implement:

```python
from abc import ABC, abstractmethod
from datetime import date

class AbstractAdapter(ABC):

    @abstractmethod
    def get_daily_schedule(self, sim_date: date) -> list[dict]:
        """
        Returns a list of flight dicts matching the Flight Neo4j schema.
        Each dict: flight_number, airline_code, origin_iata, destination_iata,
                   aircraft_type, scheduled_departure, pax_count, distance_km
        """

    @abstractmethod
    def get_weather_sequence(self, sim_date: date) -> list[dict]:
        """
        Returns an ordered list of WeatherParams dicts for each hour of the day.
        """

    @abstractmethod
    def get_passenger_demand(self, origin: str, destination: str,
                              month: int) -> float:
        """
        Returns expected daily passenger count on a given O&D pair for a given month.
        Returns 0.0 if no data available.
        """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable source identifier for reports."""

    @property
    @abstractmethod
    def is_real_data(self) -> bool:
        """True if this adapter uses real-world data."""
```

**Registry pattern — selectable at runtime:**

```python
# config/planning.yaml
adapters:
  schedule: "simulation"     # or "bts", "opensky"
  weather:  "mesonet"        # or "simulation", "live_adds"
  demand:   "bts_t100"       # or "simulation", "eurocontrol"
```

**Verification:** instantiate each adapter, call `get_daily_schedule()` with a test date,
assert a non-empty list of valid flight dicts is returned.

---

### Task P1.2 — BTS T-100 adapter

**File:** `services/planning-service/adapters/bts.py`

BTS Form 41 T-100 data provides monthly passenger and flight counts by airline,
origin, and destination for all US carriers. Free, public domain.

Download: `https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FIM`

Columns used: `YEAR`, `MONTH`, `ORIGIN`, `DEST`, `CARRIER`, `PASSENGERS`,
`DEPARTURES_PERFORMED`, `SEATS`, `AIRCRAFT_TYPE`

```python
class BTSAdapter(AbstractAdapter):

    def __init__(self, csv_path: str):
        self.df = pd.read_csv(csv_path)
        self.df.columns = self.df.columns.str.strip().str.upper()

    def get_passenger_demand(self, origin: str, destination: str,
                              month: int) -> float:
        mask = ((self.df["ORIGIN"] == origin) &
                (self.df["DEST"]   == destination) &
                (self.df["MONTH"]  == month))
        rows = self.df[mask]
        if rows.empty:
            return 0.0
        # Average daily passengers = monthly total / days in month
        monthly_pax = rows["PASSENGERS"].sum()
        days = calendar.monthrange(2023, month)[1]
        return monthly_pax / days

    def get_daily_schedule(self, sim_date: date) -> list[dict]:
        # Build a synthetic but BTS-calibrated schedule for the given date
        month = sim_date.month
        routes = self._get_routes_for_month(month)
        return self._build_schedule(routes, sim_date)
```

**Verification:** load the BTS CSV, call `get_passenger_demand("JFK", "LAX", 7)`,
assert result > 0.

---

### Task P1.3 — Eurocontrol STATFOR demand adapter

**File:** `services/planning-service/adapters/eurocontrol.py`

Eurocontrol STATFOR publishes free long-term traffic forecasts (7-year outlook,
updated annually). Download from:
`https://www.eurocontrol.int/publication/eurocontrol-forecast-2024-2030`

The PDF contains scenario tables (base, low, high growth) by ECAC region.
Parse the relevant table or use the accompanying Excel file.

```python
class EurocontrolDemandAdapter(AbstractAdapter):

    GROWTH_SCENARIOS = {
        "base": 0.034,   # 3.4% CAGR from STATFOR 2024-2030 base case
        "low":  0.018,
        "high": 0.048,
    }

    def get_demand_growth_rate(self, scenario: str = "base") -> float:
        """Annual compound growth rate for the planning scenario."""
        return self.GROWTH_SCENARIOS[scenario]

    def project_annual_pax(self, base_year_pax: int,
                            years_ahead: int,
                            scenario: str = "base") -> int:
        rate = self.get_demand_growth_rate(scenario)
        return int(base_year_pax * (1 + rate) ** years_ahead)
```

---

### Task P1.4 — Iowa State Mesonet weather adapter

**File:** `services/planning-service/adapters/mesonet.py`

Reads the downloaded Mesonet CSV (from `data/weather/{station}_{period}.csv`)
and replays historical weather sequences for planning scenarios.

```python
class MesonetAdapter(AbstractAdapter):

    def __init__(self, csv_path: str):
        self.df = pd.read_csv(csv_path, skiprows=5)  # skip header comments
        self.df["valid"] = pd.to_datetime(self.df["valid"])
        self._classify_categories()

    def _classify_categories(self):
        """Classify each observation into CAVOK/VMC/IMC/LIFR."""
        def classify(row):
            vis_m = float(row.get("vsby", 10)) * 1609
            ceil_ft = float(row.get("skyl1", 9999)) if row.get("skyc1") in ("BKN","OVC") else 9999
            if vis_m > 10000: return "CAVOK"
            if vis_m > 5000 and ceil_ft > 1500: return "VMC"
            if vis_m > 1500 and ceil_ft > 500:  return "IMC"
            return "LIFR"
        self.df["category"] = self.df.apply(classify, axis=1)

    def get_weather_sequence(self, sim_date: date) -> list[dict]:
        """Return hourly weather states for the given date."""
        day_data = self.df[self.df["valid"].dt.date == sim_date]
        return [{"hour": row["valid"].hour, "category": row["category"],
                 "wind_speed_kt": row.get("sknt", 0),
                 "visibility_m": float(row.get("vsby", 10)) * 1609}
                for _, row in day_data.iterrows()]

    def get_transition_matrix(self) -> dict:
        """Empirical FSM transition probabilities from the full dataset."""
        # Compute P(next_hour_state | current_hour_state)
        transitions = defaultdict(lambda: defaultdict(int))
        categories = self.df["category"].tolist()
        for i in range(len(categories) - 1):
            transitions[categories[i]][categories[i+1]] += 1
        # Normalise to probabilities
        matrix = {}
        for from_state, counts in transitions.items():
            total = sum(counts.values())
            matrix[from_state] = {k: v/total for k, v in counts.items()}
        return matrix
```

---

## Phase 2 — In-memory planning simulation engine

### Task P2.1 — Fast planning simulation core

**File:** `services/planning-service/engine/simulation.py`

The planning simulation does **not** use Kafka or Neo4j writes per event.
It runs entirely in Python dicts and dataclasses at maximum speed.

Target: simulate 1 full day in < 500ms (allows 500 Monte Carlo runs in < 4 minutes).

```python
@dataclass
class PlanningSimState:
    """Full airport state at one sim-minute. Immutable snapshot."""
    sim_time:           datetime
    flights:            dict[str, dict]     # flight_id → flight state
    gate_occupancy:     dict[str, str]      # gate_id → flight_id | None
    runway_queues:      dict[str, list]     # runway_id → [flight_ids]
    security_queues:    dict[str, int]      # terminal → queue_depth
    baggage_zones:      dict[str, int]      # zone_id → item_count
    active_incidents:   list[dict]
    costs:              dict[str, float]    # category → cumulative EUR
    revenues:           dict[str, float]
    metrics:            dict[str, float]    # KPIs: delays, missed connections, etc.

class PlanningSimEngine:

    def __init__(self, config: PlanningConfig, adapter: AbstractAdapter):
        self.config  = config
        self.adapter = adapter

    def run_day(self, sim_date: date,
                 infrastructure: InfrastructureConfig) -> DayResult:
        """
        Simulate a single day end-to-end.
        Returns a DayResult with KPIs and financial summary.
        No I/O, no Kafka, no Neo4j.
        """
        schedule = self.adapter.get_daily_schedule(sim_date)
        weather  = self.adapter.get_weather_sequence(sim_date)
        state    = self._initialise_state(schedule, infrastructure)

        for minute in range(24 * 60):
            sim_time = datetime.combine(sim_date, time()) + timedelta(minutes=minute)
            state    = self._tick(state, sim_time, weather, infrastructure)

        return self._build_result(state, sim_date)
```

Key design principle: the planning engine is a **pure function** of its inputs.
Given the same config, adapter data, and random seed, it always produces the same output.
This is what makes Monte Carlo reliable.

---

### Task P2.2 — Infrastructure configuration model

**File:** `services/planning-service/engine/infrastructure.py`

The `InfrastructureConfig` is the object that changes between planning scenarios.

```python
@dataclass
class InfrastructureConfig:
    """Everything that can be changed in a capacity planning scenario."""

    # Gates
    gates_per_terminal: dict[str, int]          # {"A": 14, "B": 14, "C": 14}
    gate_wide_body_capable: dict[str, list[str]] # {"A": ["A07","A08",...]}
    gate_international_capable: dict[str, list[str]]

    # Runways
    runways: list[RunwayConfig]                  # active runway configurations

    # Security
    security_lanes_per_terminal: dict[str, int]  # {"A": 4, "B": 3, "C": 4}

    # Baggage
    screening_units: int                          # total active screening units
    sorting_capacity_per_hour: int               # bags/hr sorting matrix

    # Demand
    daily_flight_target: int                     # schedule size
    load_factor_mean: float
    demand_growth_rate: float                    # annual CAGR for multi-year planning

    @classmethod
    def baseline(cls) -> "InfrastructureConfig":
        """Current KART configuration — the do-nothing baseline."""
        return cls(
            gates_per_terminal={"A": 14, "B": 14, "C": 14},
            gate_wide_body_capable={"A": ["A07","A08","A09"],
                                     "B": ["B07","B08","B09"],
                                     "C": ["C07","C08","C09"]},
            gate_international_capable={"A": list(f"A{i:02d}" for i in range(8,15)),
                                         "B": list(f"B{i:02d}" for i in range(8,15)),
                                         "C": list(f"C{i:02d}" for i in range(8,15))},
            runways=[RunwayConfig("09L", ils=True), RunwayConfig("09R", ils=False)],
            security_lanes_per_terminal={"A": 4, "B": 3, "C": 4},
            screening_units=6,
            sorting_capacity_per_hour=1800,
            daily_flight_target=420,
            load_factor_mean=0.80,
            demand_growth_rate=0.034,
        )
```

---

### Task P2.3 — Day result model and KPI extraction

**File:** `services/planning-service/engine/results.py`

```python
@dataclass
class DayResult:
    """KPIs and financials for one simulated day under one InfrastructureConfig."""
    sim_date:                  date
    infrastructure_label:      str      # "baseline" | "scenario_name"

    # Operations KPIs
    total_flights:             int
    flights_on_time:           int
    flights_delayed:           int
    flights_cancelled:         int
    avg_delay_minutes:         float
    max_cascade_depth:         int
    missed_connections:        int
    gate_conflicts:            int
    holding_events:            int
    security_wait_max_minutes: float

    # Capacity KPIs
    runway_utilisation_pct:    float    # peak hour actual / theoretical max
    gate_utilisation_pct:      float    # hours occupied / total gate-hours
    security_utilisation_pct:  float    # peak queue / (lanes × capacity)
    baggage_utilisation_pct:   float    # peak throughput / sorting capacity

    # Financial KPIs (from cost model)
    total_cost_eur:            float
    total_revenue_eur:         float
    net_eur:                   float
    eu261_liability_eur:       float
    incident_cost_eur:         float

    def on_time_rate(self) -> float:
        return self.flights_on_time / max(1, self.total_flights)

    def cost_per_flight(self) -> float:
        return self.total_cost_eur / max(1, self.total_flights)
```

---

## Phase 3 — Scenario management

### Task P3.1 — Scenario definition model

**File:** `services/planning-service/scenarios/model.py`

```python
@dataclass
class PlanningScenario:
    id:                  str         # UUID
    name:                str
    description:         str
    created_at:          str

    # Simulation parameters
    horizon:             str         # "day" | "week" | "month" | "year" | "10year"
    monte_carlo_runs:    int         # 1 = deterministic, 50–500 = stochastic
    random_seed:         int | None  # None = random, int = reproducible

    # Infrastructure override (vs baseline)
    infrastructure:      InfrastructureConfig

    # Demand override
    demand_source:       str         # "simulation" | "bts" | "eurocontrol"
    demand_multiplier:   float       # 1.0 = no change, 1.2 = +20% demand
    new_routes:          list[dict]  # [{origin, destination, daily_flights}]
    removed_routes:      list[str]   # [route_ids to remove]

    # Weather source
    weather_source:      str         # "simulation" | "mesonet" | "historical_date"
    weather_date:        str | None  # replay a specific historical date's weather

    # Investment costs (for ROI calculation)
    capex_eur:           float       # upfront infrastructure cost
    opex_delta_eur:      float       # annual operating cost change vs baseline
    years_horizon:       int         # for NPV calculation
    discount_rate:       float       # WACC, default 0.08 (8%)
```

**Scenario YAML format** (user-facing):

```yaml
# scenarios/planning/add_terminal_b_gate.yaml

name: "Add gate B15 to Terminal B"
description: >
  Evaluate the impact of adding a 15th gate to Terminal B with wide-body capability.
  Compare against baseline over a full peak week.

horizon: week
monte_carlo_runs: 100
random_seed: 42

infrastructure:
  gates_per_terminal:
    B: 15                        # was 14
  gate_wide_body_capable:
    B: [B07, B08, B09, B15]     # B15 is new wide-body capable

demand_source: bts
demand_multiplier: 1.0

weather_source: mesonet

capex_eur: 12_000_000            # gate construction estimate
opex_delta_eur: 180_000          # additional annual maintenance
years_horizon: 20
discount_rate: 0.07
```

---

### Task P3.2 — Scenario runner

**File:** `services/planning-service/scenarios/runner.py`

```python
class ScenarioRunner:

    def __init__(self, engine: PlanningSimEngine):
        self.engine = engine

    def run(self, scenario: PlanningScenario,
             baseline: PlanningScenario,
             progress_callback=None) -> ScenarioResult:

        # Run baseline
        baseline_results = self._run_scenario(baseline)

        # Run scenario
        scenario_results = self._run_scenario(scenario, progress_callback)

        # Compare
        delta = self._compute_delta(baseline_results, scenario_results)

        # Financial model
        financials = self._compute_financials(delta, scenario)

        return ScenarioResult(
            scenario=scenario,
            baseline_results=baseline_results,
            scenario_results=scenario_results,
            delta=delta,
            financials=financials,
        )

    def _run_scenario(self, scenario: PlanningScenario) -> list[DayResult]:
        """Run N Monte Carlo iterations and return aggregated results."""
        all_runs = []
        dates = self._generate_dates(scenario.horizon)

        for run_idx in range(scenario.monte_carlo_runs):
            seed = (scenario.random_seed or random.randint(0, 999999)) + run_idx
            random.seed(seed)
            run_results = []
            for sim_date in dates:
                result = self.engine.run_day(sim_date, scenario.infrastructure)
                run_results.append(result)
            all_runs.append(run_results)

        return self._aggregate_monte_carlo(all_runs)
```

---

### Task P3.3 — Monte Carlo aggregation

**File:** `services/planning-service/scenarios/statistics.py`

For each KPI, compute mean, standard deviation, p5, p25, p50, p75, p95 across all runs:

```python
@dataclass
class KPIDistribution:
    mean:   float
    std:    float
    p5:     float
    p25:    float
    p50:    float
    p75:    float
    p95:    float

    def confidence_interval_95(self) -> tuple[float, float]:
        return (self.p5, self.p95)

def aggregate_kpi(values: list[float]) -> KPIDistribution:
    arr = np.array(values)
    return KPIDistribution(
        mean=float(np.mean(arr)),
        std=float(np.std(arr)),
        p5=float(np.percentile(arr, 5)),
        p25=float(np.percentile(arr, 25)),
        p50=float(np.percentile(arr, 50)),
        p75=float(np.percentile(arr, 75)),
        p95=float(np.percentile(arr, 95)),
    )
```

The p5–p95 range is the "confidence band" shown in the planning dashboard.
A decision is considered robust only if the p5 outcome (pessimistic case) still
shows a positive NPV.

---

## Phase 4 — Investment model

### Task P4.1 — NPV and IRR calculator

**File:** `services/planning-service/finance/investment.py`

```python
import numpy as np

@dataclass
class InvestmentResult:
    capex_eur:          float
    annual_benefit_eur: float       # mean annual saving vs baseline
    annual_opex_eur:    float       # additional annual operating cost
    net_annual_eur:     float       # benefit - opex
    npv_eur:            float       # net present value over horizon
    irr_pct:            float       # internal rate of return
    payback_years:      float       # years to recover capex
    recommendation:     str         # "invest" | "marginal" | "do not invest"

def compute_investment(capex: float,
                        annual_benefit: float,
                        annual_opex: float,
                        years: int,
                        discount_rate: float) -> InvestmentResult:
    """
    Discounted cash flow analysis for an infrastructure investment.

    cash_flows[0] = -capex (year 0: investment)
    cash_flows[t] = annual_benefit - annual_opex (years 1..N)
    """
    net_annual = annual_benefit - annual_opex
    cash_flows = [-capex] + [net_annual] * years

    # NPV
    npv = sum(cf / (1 + discount_rate) ** t
              for t, cf in enumerate(cash_flows))

    # IRR (solve for r where NPV = 0)
    try:
        irr = float(np.irr(cash_flows)) if hasattr(np, 'irr') else _compute_irr(cash_flows)
    except Exception:
        irr = float('nan')

    # Payback
    cumulative = -capex
    payback = float('inf')
    for year in range(1, years + 1):
        cumulative += net_annual
        if cumulative >= 0:
            payback = year - 1 + (-cumulative + net_annual) / net_annual
            break

    recommendation = (
        "invest"        if npv > 0 and irr > discount_rate else
        "marginal"      if npv > -capex * 0.1 else
        "do not invest"
    )

    return InvestmentResult(
        capex_eur=capex,
        annual_benefit_eur=annual_benefit,
        annual_opex_eur=annual_opex,
        net_annual_eur=net_annual,
        npv_eur=npv,
        irr_pct=irr * 100,
        payback_years=payback,
        recommendation=recommendation,
    )
```

---

### Task P4.2 — Annual benefit extraction from scenario results

**File:** `services/planning-service/finance/benefit_extractor.py`

Convert the delta between scenario and baseline DayResults into an annual financial benefit:

```python
def extract_annual_benefit(delta: ScenarioDelta,
                            operating_days_per_year: int = 365) -> dict[str, float]:
    """
    Translate daily KPI improvements into annual financial value.
    """
    return {
        "eu261_avoided_annual": (
            delta.eu261_liability_eur.mean *
            operating_days_per_year
        ),
        "delay_cost_avoided_annual": (
            delta.avg_delay_minutes.mean *           # minutes saved per day
            delta.total_flights.mean *               # flights affected
            DELAY_COST_PER_MINUTE_EUR *              # from Eurocontrol Standard Inputs
            operating_days_per_year
        ),
        "missed_connections_avoided_annual": (
            delta.missed_connections.mean *
            REBOOKING_COST_PER_PAX_EUR *
            operating_days_per_year
        ),
        "revenue_uplift_annual": (
            delta.total_revenue_eur.mean *
            operating_days_per_year
        ),
        "total_annual_benefit": None  # computed as sum of above
    }

# Eurocontrol Standard Inputs 2024 values:
DELAY_COST_PER_MINUTE_EUR = 102.0   # all-in cost per minute of ATFM delay
REBOOKING_COST_PER_PAX_EUR = 285.0  # average rebooking + accommodation cost
```

---

## Phase 5 — Capacity planning specific scenarios

### Task P5.1 — Gate addition scenario

**File:** `scenarios/planning/templates/add_gate.yaml.template`

Pre-built scenario template. Agent fills in the terminal and gate count:

```yaml
name: "Add {N} gate(s) to Terminal {TERMINAL}"
horizon: month
monte_carlo_runs: 200
infrastructure:
  gates_per_terminal:
    {TERMINAL}: {CURRENT_COUNT + N}
capex_eur: {N * 8_000_000}       # €8M per gate (industry average)
opex_delta_eur: {N * 120_000}    # €120K/year maintenance per gate
years_horizon: 25
discount_rate: 0.07
```

Implement as a Python function that generates the YAML:

```python
def create_gate_scenario(terminal: str, additional_gates: int) -> PlanningScenario:
    baseline = InfrastructureConfig.baseline()
    new_config = replace(baseline,
        gates_per_terminal={
            **baseline.gates_per_terminal,
            terminal: baseline.gates_per_terminal[terminal] + additional_gates
        }
    )
    return PlanningScenario(
        name=f"Add {additional_gates} gate(s) to Terminal {terminal}",
        infrastructure=new_config,
        capex_eur=additional_gates * 8_000_000,
        opex_delta_eur=additional_gates * 120_000,
        monte_carlo_runs=200,
        horizon="month",
        years_horizon=25,
        discount_rate=0.07,
    )
```

---

### Task P5.2 — Runway addition scenario

```python
def create_runway_scenario(runway_id: str,
                             ils_capable: bool,
                             length_m: int = 3000) -> PlanningScenario:
    """
    Add a third runway.
    Cost basis: Heathrow T5 runway estimate ~£14B. Scaled to KART size: ~€800M.
    """
    baseline = InfrastructureConfig.baseline()
    new_runways = baseline.runways + [RunwayConfig(runway_id, ils=ils_capable)]
    new_config = replace(baseline, runways=new_runways)
    return PlanningScenario(
        name=f"Add runway {runway_id}",
        infrastructure=new_config,
        capex_eur=800_000_000,
        opex_delta_eur=12_000_000,
        monte_carlo_runs=100,
        horizon="year",
        years_horizon=30,
        discount_rate=0.06,
    )
```

---

### Task P5.3 — New route scenario

```python
def create_route_scenario(destination_iata: str,
                           daily_flights: int,
                           aircraft_type: str = "A320") -> PlanningScenario:
    """
    Add a new route to destination_iata with daily_flights rotations.
    Revenue estimated from BTS demand model for the city pair.
    """
    baseline = InfrastructureConfig.baseline()
    return PlanningScenario(
        name=f"New route KART → {destination_iata} ({daily_flights} daily)",
        infrastructure=baseline,    # no infrastructure change
        new_routes=[{
            "origin": "ART",
            "destination": destination_iata,
            "daily_flights": daily_flights,
            "aircraft_type": aircraft_type,
        }],
        demand_source="bts",
        capex_eur=0,                # no capex (route launch costs excluded)
        opex_delta_eur=0,
        monte_carlo_runs=100,
        horizon="month",
        years_horizon=5,
        discount_rate=0.08,
    )
```

---

### Task P5.4 — Security lane optimisation scenario

```python
def create_security_scenario(lanes_delta: dict[str, int]) -> PlanningScenario:
    """
    lanes_delta = {"A": +1, "B": +1} means add one lane each in A and B.
    Cost: staffing only (no capex for existing infrastructure).
    """
    baseline = InfrastructureConfig.baseline()
    new_lanes = {
        terminal: baseline.security_lanes_per_terminal[terminal] + delta
        for terminal, delta in {
            **{t: 0 for t in "ABC"},
            **lanes_delta
        }.items()
    }
    annual_staffing_cost = sum(
        delta * 365 * 16 * 35  # 16 hours/day × €35/hour × 365 days
        for delta in lanes_delta.values()
        if delta > 0
    )
    return PlanningScenario(
        name=f"Security lanes: {lanes_delta}",
        infrastructure=replace(baseline,
            security_lanes_per_terminal=new_lanes),
        capex_eur=0,
        opex_delta_eur=annual_staffing_cost,
        monte_carlo_runs=200,
        horizon="week",
        years_horizon=3,
        discount_rate=0.08,
    )
```

---

## Phase 6 — ML demand forecasting

### Task P6.1 — Demand surface model

**File:** `services/planning-service/ml/demand_model.py`

Replace the bimodal synthetic schedule generator with a learnable demand surface.
The model predicts `expected_daily_flights(route, month, day_of_week)`.

```python
import lightgbm as lgb

DEMAND_FEATURES = [
    "month",              # 1–12 (seasonality)
    "day_of_week",        # 0–6
    "is_holiday",         # 0/1 (from a public holiday calendar)
    "distance_km",        # O&D pair distance
    "population_origin",  # city population proxy
    "population_dest",
    "gdp_index_origin",   # economic activity proxy (World Bank, free)
    "gdp_index_dest",
    "historical_avg_pax", # from BTS T-100 (same month, prior years)
    "growth_trend",       # YoY growth rate from historical data
    "is_hub_connection",  # 1 if destination is a major hub
]

def train_demand_model(training_data: pd.DataFrame) -> lgb.LGBMRegressor:
    """
    training_data: one row per (route, date) with actual pax count as target.
    Source: BTS T-100 historical data.
    """
    model = lgb.LGBMRegressor(
        n_estimators=300,
        learning_rate=0.03,
        max_depth=6,
        num_leaves=31,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
    )
    X = training_data[DEMAND_FEATURES]
    y = training_data["actual_pax"]
    model.fit(X, y, eval_set=[(X, y)])
    return model
```

---

### Task P6.2 — Delay prediction model

**File:** `services/planning-service/ml/delay_model.py`

Train a classifier to predict P(delay > 15min) for each flight given:
- Weather forecast for departure hour
- Time of day
- Aircraft type
- Historical on-time performance for the route
- Current airport load (flights in prev 2 hours)
- Day of week / month

Use BTS historical on-time data as training labels. Output a probability score
used by the planning engine to weight delay costs in scenario projections.

---

### Task P6.3 — Model training pipeline

**File:** `services/planning-service/ml/training_pipeline.py`

CLI script that:
1. Loads BTS T-100 CSV from `data/bts/`
2. Loads Mesonet weather CSV from `data/weather/`
3. Trains both models
4. Serialises to `data/models/demand_model.lgbm` and `data/models/delay_model.lgbm`
5. Prints validation metrics (MAE for demand, AUC for delay)

```bash
python -m planning_service.ml.training_pipeline \
  --bts data/bts/T100_2023.csv \
  --weather data/weather/EGLL_2023.csv \
  --output data/models/
```

---

## Phase 7 — Decision audit trail

### Task P7.1 — Recommendation audit log schema

**File:** `services/planning-service/db/audit.py`

Every recommendation (operational or planning) must be logged with its outcome.

Neo4j schema addition — `RecommendationLog` node:

| Property | Type | Description |
|---|---|---|
| `id` | String (UUID) | |
| `type` | Enum | `operational` \| `planning` |
| `recommendation_text` | String | Human-readable action |
| `predicted_saving_eur` | Float | Projected saving at time of recommendation |
| `confidence` | Float | Model confidence at time of recommendation |
| `was_applied` | Boolean | Did the operator apply it? |
| `applied_at` | String | sim_time when applied |
| `actual_saving_eur` | Float | Measured 30/60 sim-min after application |
| `prediction_error_eur` | Float | predicted - actual |
| `sim_day` | Integer | |
| `model_version` | String | LightGBM model version tag |

```cypher
(RecommendationLog)-[:RECOMMENDED_FOR]->(Flight | Terminal | Incident)
```

---

### Task P7.2 — Outcome measurement

**File:** `services/cost-service/services/audit.py`

30 simulated minutes after a recommendation was applied, measure the actual outcome:

```python
async def measure_recommendation_outcome(rec_id: str,
                                          applied_at: datetime,
                                          sim_time: datetime):
    if (sim_time - applied_at).total_seconds() < 30 * 60:
        return  # too early to measure

    # Get costs in the 30 min before vs 30 min after application
    before_cost = await query_cost_in_window(
        applied_at - timedelta(minutes=30), applied_at
    )
    after_cost = await query_cost_in_window(
        applied_at, applied_at + timedelta(minutes=30)
    )

    actual_saving = before_cost - after_cost
    rec = await get_recommendation(rec_id)
    prediction_error = rec.predicted_saving_eur - actual_saving

    await update_recommendation_log(rec_id,
        actual_saving_eur=actual_saving,
        prediction_error_eur=prediction_error
    )
```

This feedback loop is used to:
1. Surface to the operator: "Our last 5 recommendations saved €47K vs predicted €38K (+24%)"
2. Fine-tune the confidence calibration of the recommendation engine over time

---

### Task P7.3 — Audit dashboard panel

Add a "Recommendation history" panel to the `/cost` dashboard:

| Metric | Value |
|---|---|
| Recommendations made (today) | 12 |
| Applied by operator | 8 (67%) |
| Total predicted saving | €124,000 |
| Total actual saving | €108,300 |
| Prediction accuracy | −12.7% (model underestimates) |

A table showing every recommendation, applied/rejected, predicted vs actual saving,
and a sparkline of prediction error over time. This is the transparency layer that
makes the system trustworthy for business use.

---

## Phase 8 — Planning dashboard

### Task P8.1 — Planning page (`/planning`)

New React page with four tabs:

**Tab 1 — Scenario builder**
- Form to define a new planning scenario (YAML editor or structured form)
- Preset templates: + gate, + runway, + security lane, + route, weather stress test
- Run button with live progress indicator (Monte Carlo progress bar)

**Tab 2 — Results comparison**
- Side-by-side KPI comparison: baseline vs scenario
- For each KPI: mean ± confidence band, p5/p95 range displayed as error bars
- Traffic light indicator: green (improvement > 10%), amber (marginal), red (worse)

**Tab 3 — Investment dashboard**
- NPV waterfall chart: capex → annual benefits → cumulative NPV over years
- Payback year marker
- Sensitivity table: NPV under different demand growth assumptions (low/base/high)
- IRR vs WACC comparison with recommendation badge (Invest / Marginal / Do not invest)

**Tab 4 — Decision audit trail**
- Recommendation history table (from Task P7.3)
- Prediction accuracy sparkline
- Model version and last training date

---

## Verification checklist

```bash
# 1. Planning service healthy
curl http://localhost:8008/health | jq .status
# expected: "ok"

# 2. Run a baseline scenario (deterministic, 1 run)
curl -X POST http://localhost:3000/api/v1/planning/scenarios \
  -H "Content-Type: application/json" \
  -d '{"name":"test","horizon":"day","monte_carlo_runs":1,"infrastructure":"baseline"}'
# expected: scenario_id returned

# 3. Run completes in reasonable time
# 1 day × 1 run should complete in < 2 seconds
# 1 month × 100 runs should complete in < 3 minutes

# 4. Add gate scenario shows positive NPV
curl http://localhost:3000/api/v1/planning/scenarios/{id}/results | \
  jq '.financials.npv_eur'
# expected: positive number if gate addition is justified

# 5. Monte Carlo distribution is non-degenerate
curl http://localhost:3000/api/v1/planning/scenarios/{id}/results | \
  jq '.kpis.avg_delay_minutes | {p5, p50, p95}'
# expected: p5 < p50 < p95 (distribution has spread)

# 6. Audit log records outcomes
# Wait 30 sim-min after applying a recommendation, then:
docker compose exec neo4j cypher-shell -u neo4j -p art-digital-twin \
  "MATCH (r:RecommendationLog) WHERE r.actual_saving_eur IS NOT NULL
   RETURN r.recommendation_text, r.predicted_saving_eur, r.actual_saving_eur"
# expected: at least 1 row with non-null actual_saving_eur
```

---

## Data sources reference

| Source | URL | License | Used in |
|---|---|---|---|
| BTS T-100 Market & Segment Data | [transtats.bts.gov](https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FIM) | Public Domain | P1.2, P6.1, P6.3 |
| BTS On-Time Performance | [transtats.bts.gov](https://www.transtats.bts.gov/Tables.asp?QO_VQ=EFD) | Public Domain | P6.2, P6.3 |
| Eurocontrol STATFOR | [eurocontrol.int](https://www.eurocontrol.int/forecasting) | Free download | P1.3 |
| Iowa State Mesonet | [mesonet.agron.iastate.edu](https://mesonet.agron.iastate.edu) | Public Domain | P1.4, P6.3 |
| World Bank GDP data | [data.worldbank.org](https://data.worldbank.org/indicator/NY.GDP.MKTP.CD) | CC BY 4.0 | P6.1 |
| UN World Population | [population.un.org](https://population.un.org/wpp/) | Free | P6.1 |
| Eurocontrol Standard Inputs | [eurocontrol.int](https://www.eurocontrol.int/publication/standard-inputs-eurocontrol-cost-benefit-analyses) | Free download | P4.2 |
| OurAirports | [ourairports.com/data](https://ourairports.com/data/) | CC0 | P5.3 |
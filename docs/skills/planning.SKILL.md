# SKILL — planning-service

## In-memory simulation · Monte Carlo · Investment model · Audit trail

> Full specification: `docs/services/planning-service/SPEC.md`
> Read `docs/skills/SKILL.md` and `docs/skills/python-service.SKILL.md` first.

---

## The fundamental difference from the operational services

Every other service in this project reacts to Kafka events and writes live state.
The planning-service is the opposite: it **reads** a snapshot of live state once,
then runs entirely in memory, producing no Kafka events and no live Neo4j writes
during the simulation run itself.

```
# WRONG — do not do this in planning-service
async with get_driver().session() as session:
    await session.run("SET f.status = 'delayed' ...")   # never write live nodes

# RIGHT — write only to planning namespace nodes
await session.run("CREATE (r:PlanningResult {id: $id, ...})")
await session.run("CREATE (s:PlanningScenario {id: $id, ...})")
```

If you find yourself writing `Flight`, `Passenger`, `Baggage`, `Gate`, or `Runway`
nodes from this service, stop — those are owned by the operational services.

---

## The planning simulation is a pure function

The `PlanningSimEngine.run_day()` method must be a pure function of its inputs.
Given the same `InfrastructureConfig`, `AbstractAdapter` data, and random seed,
it always produces the same `DayResult`. This is what makes Monte Carlo reliable
and scenarios reproducible.

```python
# RIGHT — seed before each run
random.seed(scenario.random_seed + run_idx)
result = engine.run_day(sim_date, infrastructure)

# WRONG — shared global state between runs
_global_queue.append(something)  # breaks reproducibility
```

Never use `datetime.now()` anywhere in the planning engine. The planning engine
has no real-time dependency — it operates on synthetic dates.

---

## InfrastructureConfig is immutable per run

```python
from dataclasses import replace

# RIGHT — create a new config for each scenario
new_config = replace(baseline_config,
    gates_per_terminal={"A": 14, "B": 15, "C": 14}
)

# WRONG — mutate the baseline
baseline_config.gates_per_terminal["B"] = 15  # corrupts baseline for other runs
```

Always use `dataclasses.replace()` to derive a new config from the baseline.
The baseline is a singleton — never mutate it.

---

## Monte Carlo patterns

```python
# Standard pattern for a Monte Carlo scenario run
def run_monte_carlo(scenario: PlanningScenario,
                     engine: PlanningSimEngine) -> list[DayResult]:
    all_results = []
    dates = generate_dates(scenario.horizon)

    for run_idx in range(scenario.monte_carlo_runs):
        # Deterministic seed per run — reproducible even for "random" scenarios
        seed = (scenario.random_seed or random.randint(0, 999_999)) + run_idx
        random.seed(seed)

        run_results = []
        for sim_date in dates:
            result = engine.run_day(sim_date, scenario.infrastructure)
            run_results.append(result)
        all_results.extend(run_results)

    return all_results

# Aggregate into KPIDistribution
import numpy as np

def aggregate(values: list[float]) -> KPIDistribution:
    a = np.array(values)
    return KPIDistribution(
        mean=float(np.mean(a)),  std=float(np.std(a)),
        p5=float(np.percentile(a, 5)),   p25=float(np.percentile(a, 25)),
        p50=float(np.percentile(a, 50)), p75=float(np.percentile(a, 75)),
        p95=float(np.percentile(a, 95)),
    )
```

**Performance target:** 1 simulated day must run in < 500ms.
100 MC runs over 1 week = 700 day-runs = should complete in < 6 minutes.
If a run is slower than 500ms, profile first — the bottleneck is almost always
an accidental Neo4j or I/O call inside the inner loop.

---

## Horizon → date list mapping

```python
from datetime import date, timedelta
import calendar

BASE_DATE = date(2024, 6, 15)   # arbitrary reference Monday

def generate_dates(horizon: str) -> list[date]:
    match horizon:
        case "day":
            return [BASE_DATE]
        case "week":
            return [BASE_DATE + timedelta(days=i) for i in range(7)]
        case "month":
            # 30 days, one per day
            return [BASE_DATE + timedelta(days=i) for i in range(30)]
        case "year":
            # 52 Mondays — one representative day per week
            return [BASE_DATE + timedelta(weeks=i) for i in range(52)]
        case "10year":
            # 120 first-of-months — one representative day per month
            return [
                date(BASE_DATE.year + y, m, 1)
                for y in range(10)
                for m in range(1, 13)
            ]
        case _:
            raise ValueError(f"Unknown horizon: {horizon}")
```

For `year` and `10year` horizons, each date represents one week or one month
respectively. Scale the results accordingly in the KPI aggregation.

---

## NPV calculation

```python
def npv(cash_flows: list[float], discount_rate: float) -> float:
    """
    cash_flows[0] = -capex (year 0)
    cash_flows[1..N] = annual net benefit
    """
    return sum(
        cf / (1 + discount_rate) ** t
        for t, cf in enumerate(cash_flows)
    )

# IRR: solve for r where npv(r) = 0
# numpy_financial is the correct library — not numpy itself
# pip install numpy-financial
import numpy_financial as npf

def irr(cash_flows: list[float]) -> float:
    result = npf.irr(cash_flows)
    if result is None or np.isnan(result):
        return 0.0
    return float(result)
```

Add `numpy-financial>=1.0` to `requirements.txt`.
`np.irr()` was removed from NumPy in v1.20 — do not use it.

---

## Adapter pattern: reading vs instantiating

```python
# The registry selects the adapter at startup based on config
from adapters.registry import get_adapter

schedule_adapter = get_adapter("schedule", config)
weather_adapter  = get_adapter("weather", config)

# Each adapter is stateless — safe to share across MC runs
# Do NOT instantiate a new adapter per run (expensive I/O)
for run_idx in range(n_runs):
    schedule = schedule_adapter.get_daily_schedule(sim_date)  # OK — uses cache
```

Adapters that read CSV files should load the full DataFrame once in `__init__`
and cache it. Never re-read the file on each `get_daily_schedule()` call.

---

## Background task: outcome measurement

The `outcome_measurer.py` background task runs continuously and checks every
30 sim-minutes whether any applied recommendations are due for outcome measurement.

```python
# In main.py lifespan
asyncio.create_task(run_outcome_measurer())

# In background/outcome_measurer.py
async def run_outcome_measurer():
    while True:
        sim_time = get_current_sim_time()   # from Neo4j or cached
        applied = await get_applied_recommendations_due_for_measurement(sim_time)
        for rec in applied:
            await measure_and_record_outcome(rec, sim_time)
        await asyncio.sleep(60)  # check every real minute
```

The `get_current_sim_time()` function must read from Neo4j (the orchestrator
writes it) or from the sim.clock Kafka topic. The planning-service should
subscribe **only** to `sim.clock` for this purpose — no other topics.

---

## Scenario run as FastAPI background task

```python
# routers/scenarios.py
from fastapi import BackgroundTasks

@router.post("/scenarios")
async def create_scenario(body: ScenarioCreate,
                           background_tasks: BackgroundTasks):
    scenario = await create_scenario_in_neo4j(body)
    background_tasks.add_task(run_scenario_task, scenario.id)
    return {"scenario_id": scenario.id, "status": "pending"}

async def run_scenario_task(scenario_id: str):
    try:
        await update_status(scenario_id, "running")
        result = await run_scenario(scenario_id)          # blocking MC run
        await save_result(result)
        await update_status(scenario_id, "completed")
    except Exception as e:
        await update_status(scenario_id, "failed", error=str(e))
```

For long-running scenarios (year/10year × 500 MC runs), the background task
may run for several minutes. This is acceptable — the client polls
`GET /scenarios/{id}/status` or uses the SSE stream.

---

## Gotchas

- **`numpy_financial.irr()` returns NaN for projects that never pay back.** Always
  guard with `if np.isnan(irr): irr = 0.0` before returning to the client.
- **The BTS T-100 CSV has inconsistent column name casing** across download years.
  Always normalise with `df.columns = df.columns.str.strip().str.upper()` on load.
- **Mesonet CSV has comment lines at the top** (lines starting with `#`). Use
  `pd.read_csv(path, comment='#')` or manually skip them.
- **`dataclasses.replace()` does a shallow copy.** If `InfrastructureConfig` contains
  a mutable dict (e.g. `gates_per_terminal`), the copy shares the same dict object.
  Use `copy.deepcopy()` or explicitly copy the dict:
  ```python
  new_config = replace(baseline,
      gates_per_terminal={**baseline.gates_per_terminal, "B": 15}
  )
  ```
- **Monte Carlo with random_seed=None is not reproducible.** Always log the actual
  seed used in the `PlanningResult` so runs can be replayed. Generate the seed
  before the run loop: `actual_seed = scenario.random_seed or random.randint(0, 999_999)`.
- **The planning engine must not import from operational services.** It has its own
  copy of the simulation logic (deliberately simpler — day-resolution, not minute-resolution).
  Do not add `from flight_service.services.state_machine import ...` — that path breaks
  the isolation principle.
- **SSE connections must be closed when the scenario completes.** Use a
  `asyncio.Event` to signal completion and close the generator:
  ```python
  async def scenario_stream(scenario_id: str):
      done = asyncio.Event()
      async for update in watch_scenario(scenario_id, done):
          yield f"data: {json.dumps(update)}\n\n"
  ```

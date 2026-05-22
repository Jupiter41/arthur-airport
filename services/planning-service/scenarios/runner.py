"""Scenario runner — executes planning scenarios with Monte Carlo support.

P3.2 of ROADMAP_PLANNING.md (simplified for Phase 2 delivery).
"""

from __future__ import annotations

import logging
import random
import time
from datetime import date, datetime, timedelta

from adapters.registry import get_schedule_adapter
from engine.results import DayResult, ScenarioResults, aggregate_kpi
from engine.simulation import PlanningSimEngine
from finance.benefit_extractor import extract_annual_benefit
from finance.investment import compute_investment

from .model import PlanningScenario, store_results

logger = logging.getLogger(__name__)


def _horizon_to_days(horizon: str) -> int:
    """Convert horizon string to number of simulation days."""
    return {
        "day": 1,
        "week": 7,
        "month": 30,
        "year": 365,
        "10year": 3650,
    }.get(horizon, 1)


def _generate_dates(horizon: str, start: date | None = None) -> list[date]:
    """Generate simulation dates for the given horizon."""
    if start is None:
        start = date(2026, 6, 15)  # Default mid-year start
    n_days = _horizon_to_days(horizon)
    # For year+ horizons, sample representative days to keep runtime manageable
    if n_days > 30:
        # Sample 30 representative days across the horizon
        step = n_days // 30
        return [start + timedelta(days=i * step) for i in range(30)]
    return [start + timedelta(days=i) for i in range(n_days)]


def run_scenario(scenario: PlanningScenario) -> None:
    """Run a planning scenario (blocking). Updates scenario status in-place."""
    scenario.status = "running"
    scenario.started_at = datetime.utcnow().isoformat()
    scenario.progress_pct = 0
    scenario.runs_completed = 0

    try:
        # Get adapter based on scenario config
        schedule_adapter = get_schedule_adapter(scenario.demand_source)

        # Use schedule adapter for the engine (it provides get_daily_schedule)
        engine = PlanningSimEngine(adapter=schedule_adapter, seed=scenario.random_seed)

        dates = _generate_dates(scenario.horizon)
        n_runs = max(1, scenario.monte_carlo_runs)
        total_work = n_runs * len(dates)

        # Collect results per run
        all_day_results: list[list[DayResult]] = []
        work_done = 0

        for run_idx in range(n_runs):
            # Each Monte Carlo run gets a different seed
            base_seed = scenario.random_seed if scenario.random_seed is not None else random.randint(0, 999_999)
            run_seed = base_seed + run_idx

            run_results: list[DayResult] = []
            for sim_date in dates:
                day_seed = run_seed + sim_date.toordinal()
                result = engine.run_day(
                    sim_date=sim_date,
                    infrastructure=scenario.infrastructure,
                    seed=day_seed,
                )
                result.infrastructure_label = scenario.name or "scenario"
                run_results.append(result)
                work_done += 1

            all_day_results.append(run_results)
            scenario.runs_completed = run_idx + 1
            scenario.progress_pct = int(work_done / total_work * 100)

        # Aggregate results across runs
        results = _aggregate_results(scenario, all_day_results)
        store_results(scenario.id, results.to_dict())

        scenario.status = "completed"
        scenario.completed_at = datetime.utcnow().isoformat()
        scenario.progress_pct = 100
        logger.info(
            "Scenario %s completed: %d runs × %d days in %.1fs",
            scenario.id, n_runs, len(dates), results.run_duration_seconds,
        )

    except Exception as e:
        logger.error("Scenario %s failed: %s", scenario.id, e, exc_info=True)
        scenario.status = "failed"
        scenario.error = str(e)
        scenario.completed_at = datetime.utcnow().isoformat()


def _aggregate_results(
    scenario: PlanningScenario,
    all_runs: list[list[DayResult]],
) -> ScenarioResults:
    """Aggregate day results across Monte Carlo runs into KPI distributions."""
    t0 = time.monotonic()

    # Flatten: collect per-run aggregate KPIs
    run_avg_delay: list[float] = []
    run_on_time_rate: list[float] = []
    run_missed_connections: list[float] = []
    run_gate_util: list[float] = []
    run_runway_util: list[float] = []
    run_eu261: list[float] = []
    run_total_cost: list[float] = []
    run_total_revenue: list[float] = []
    run_gate_conflicts: list[float] = []
    run_security_wait: list[float] = []

    for run_days in all_runs:
        if not run_days:
            continue

        # Average across days within each run
        n = len(run_days)
        run_avg_delay.append(sum(d.avg_delay_minutes for d in run_days) / n)
        run_on_time_rate.append(sum(d.on_time_rate() for d in run_days) / n)
        run_missed_connections.append(sum(d.missed_connections for d in run_days) / n)
        run_gate_util.append(sum(d.gate_utilisation_pct for d in run_days) / n)
        run_runway_util.append(sum(d.runway_utilisation_pct for d in run_days) / n)
        run_eu261.append(sum(d.eu261_liability_eur for d in run_days) / n)
        run_total_cost.append(sum(d.total_cost_eur for d in run_days) / n)
        run_total_revenue.append(sum(d.total_revenue_eur for d in run_days) / n)
        run_gate_conflicts.append(sum(d.gate_conflicts for d in run_days) / n)
        run_security_wait.append(max(d.security_wait_max_minutes for d in run_days))

    kpis = {
        "avg_delay_minutes": aggregate_kpi(run_avg_delay),
        "on_time_rate": aggregate_kpi(run_on_time_rate),
        "missed_connections": aggregate_kpi(run_missed_connections),
        "gate_utilisation_pct": aggregate_kpi(run_gate_util),
        "runway_utilisation_pct": aggregate_kpi(run_runway_util),
        "eu261_liability_eur": aggregate_kpi(run_eu261),
        "total_cost_eur": aggregate_kpi(run_total_cost),
        "total_revenue_eur": aggregate_kpi(run_total_revenue),
        "gate_conflicts": aggregate_kpi(run_gate_conflicts),
        "security_wait_max_minutes": aggregate_kpi(run_security_wait),
    }

    elapsed = time.monotonic() - t0

    return ScenarioResults(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        status="completed",
        kpis=kpis,
        financials=_compute_financials(scenario, kpis),
        annual_benefit_breakdown=_compute_benefit_breakdown(scenario, kpis),
        run_duration_seconds=elapsed,
        computed_at=datetime.utcnow().isoformat(),
    )


def _compute_financials(
    scenario: PlanningScenario,
    kpis: dict,
) -> dict:
    """Run NPV/IRR investment analysis if capex is set."""
    if scenario.capex_eur <= 0:
        return {}

    # Estimate annual benefit from KPI improvements vs a rough baseline
    # (full baseline comparison requires running baseline separately)
    # Use daily net revenue × 365 as a proxy for annual benefit
    net_rev = kpis.get("total_revenue_eur")
    net_cost = kpis.get("total_cost_eur")
    daily_net = (net_rev.mean if net_rev else 0) - (net_cost.mean if net_cost else 0)
    annual_benefit = daily_net * 365

    result = compute_investment(
        capex=scenario.capex_eur,
        annual_benefit=annual_benefit,
        annual_opex=scenario.opex_delta_eur,
        years=scenario.years_horizon,
        discount_rate=scenario.discount_rate,
    )
    return result.to_dict()


def _compute_benefit_breakdown(
    scenario: PlanningScenario,
    kpis: dict,
) -> dict[str, float]:
    """Extract benefit breakdown if capex is set."""
    if scenario.capex_eur <= 0:
        return {}

    # Without a separate baseline run, use zero-baseline for benefit estimation
    from engine.results import KPIDistribution
    empty_baseline: dict[str, KPIDistribution] = {}
    breakdown = extract_annual_benefit(empty_baseline, kpis)
    return breakdown.to_dict()

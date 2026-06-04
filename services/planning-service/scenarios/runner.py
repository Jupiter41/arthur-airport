"""Scenario runner — executes planning scenarios with Monte Carlo support.

Every scenario automatically runs a baseline (do-nothing) comparison using
the same dates, seeds, and adapter configuration. This produces proper
delta_vs_baseline metrics and accurate investment analysis.

P3.2 of ROADMAP_PLANNING.md.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import date, datetime, timedelta

from adapters.registry import get_schedule_adapter, get_weather_adapter
from engine.infrastructure import InfrastructureConfig
from engine.interventions import Disruption, Intervention
from engine.results import DayResult, KPIDistribution, ScenarioResults, aggregate_kpi
from engine.simulation import PlanningSimEngine
from finance.benefit_extractor import extract_annual_benefit
from finance.investment import compute_investment
from scenarios.metrics import planning_metrics

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


# Monthly traffic weights (Northern hemisphere mid-Atlantic hub seasonality).
# Calibrated to BTS T-100 totals: July/August peak, May/Jun/Sep shoulder,
# Jan/Feb off-peak. These sum to 12 — relative weights only.
_MONTH_WEIGHTS: tuple[float, ...] = (
    0.78, 0.74, 0.92, 0.97, 1.06, 1.10,
    1.18, 1.18, 1.08, 1.02, 0.85, 0.92,
)


def _weighted_seasonal_sample(
    start: date, n_days: int, sample_size: int, seed: int = 0,
) -> list[date]:
    """Pick ``sample_size`` dates from a horizon, weighted by monthly traffic.

    Uses a deterministic stratified sample: dates are drawn so that each month
    contributes a number of days proportional to its traffic weight, removing
    the seasonality bias of naïve even-spaced truncation.
    """
    rng = random.Random(seed)
    # Distribute slots across calendar months proportional to month weight.
    weight_sum = sum(_MONTH_WEIGHTS) or 1.0
    raw_alloc = [sample_size * w / weight_sum for w in _MONTH_WEIGHTS]
    alloc = [int(a) for a in raw_alloc]
    # Fractional remainder allocation — give leftover slots to highest residuals.
    remainder = sample_size - sum(alloc)
    fractions = sorted(
        enumerate(raw_alloc), key=lambda x: x[1] - alloc[x[0]], reverse=True,
    )
    for i in range(remainder):
        alloc[fractions[i % 12][0]] += 1

    sampled: list[date] = []
    for month_idx in range(12):
        slots = alloc[month_idx]
        if slots <= 0:
            continue
        candidates: list[date] = []
        cursor = start
        end = start + timedelta(days=n_days)
        while cursor < end:
            if cursor.month == month_idx + 1:
                candidates.append(cursor)
            cursor += timedelta(days=1)
        if not candidates:
            continue
        if slots >= len(candidates):
            sampled.extend(candidates)
        else:
            sampled.extend(rng.sample(candidates, slots))
    sampled.sort()
    return sampled


def _generate_dates(
    horizon: str, start: date | None = None, seed: int | None = None,
) -> list[date]:
    """Generate simulation dates for the given horizon.

    For year/10year horizons, returns a seasonally-weighted sample of 30 days
    so NPV math reflects realistic peak/off-peak traffic mix rather than the
    uniform-spacing bias of the previous implementation.
    """
    if start is None:
        start = date(2026, 1, 1)
    n_days = _horizon_to_days(horizon)
    if n_days > 30:
        return _weighted_seasonal_sample(start, n_days, 30, seed=seed or 0)
    return [start + timedelta(days=i) for i in range(n_days)]


def _run_monte_carlo(
    engine: PlanningSimEngine,
    dates: list[date],
    infra: InfrastructureConfig,
    n_runs: int,
    base_seed: int | None,
    label: str,
    progress_cb=None,
    *,
    demand_multiplier: float = 1.0,
    interventions: list[Intervention] | None = None,
    disruption: Disruption | None = None,
    new_routes: list[dict] | None = None,
) -> list[list[DayResult]]:
    """Run N Monte Carlo iterations for a given infrastructure config.

    Returns a list of run results, each run being a list of DayResult.
    """
    all_runs: list[list[DayResult]] = []
    for run_idx in range(n_runs):
        seed = (base_seed if base_seed is not None else random.randint(0, 999_999)) + run_idx
        run_results: list[DayResult] = []
        for sim_date in dates:
            day_seed = seed + sim_date.toordinal()
            result = engine.run_day(
                sim_date=sim_date,
                infrastructure=infra,
                seed=day_seed,
                demand_multiplier=demand_multiplier,
                interventions=interventions,
                disruption=disruption,
                new_routes=new_routes,
            )
            result.infrastructure_label = label
            run_results.append(result)
        all_runs.append(run_results)
        if progress_cb:
            progress_cb(run_idx + 1)
    return all_runs


def _collect_kpis(all_runs: list[list[DayResult]]) -> dict[str, KPIDistribution]:
    """Aggregate per-run KPIs across Monte Carlo runs into distributions."""
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
    run_total_flights: list[float] = []

    for run_days in all_runs:
        if not run_days:
            continue
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
        run_total_flights.append(sum(d.total_flights for d in run_days) / n)

    return {
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
        "total_flights": aggregate_kpi(run_total_flights),
    }


def _compute_delta(
    baseline_kpis: dict[str, KPIDistribution],
    scenario_kpis: dict[str, KPIDistribution],
) -> dict[str, dict]:
    """Compute delta between scenario and baseline KPIs.

    For cost/delay KPIs: negative delta = improvement (lower is better).
    Returns mean delta and percentage change for each KPI.
    """
    delta: dict[str, dict] = {}
    for key in scenario_kpis:
        b = baseline_kpis.get(key)
        s = scenario_kpis[key]
        if b is None:
            continue
        abs_change = s.mean - b.mean
        pct_change = (abs_change / b.mean * 100) if b.mean != 0 else 0.0
        delta[key] = {
            "baseline_mean": round(b.mean, 4),
            "scenario_mean": round(s.mean, 4),
            "absolute_change": round(abs_change, 4),
            "pct_change": round(pct_change, 2),
        }
    return delta


def _infra_diff(baseline: InfrastructureConfig, scenario: InfrastructureConfig) -> list[dict]:
    """Produce a human-readable list of infrastructure differences."""
    diffs: list[dict] = []
    # Gates
    for t in sorted(set(baseline.gates_per_terminal) | set(scenario.gates_per_terminal)):
        b = baseline.gates_per_terminal.get(t, 0)
        s = scenario.gates_per_terminal.get(t, 0)
        if b != s:
            diffs.append({"parameter": f"Gates (Terminal {t})", "baseline": b, "scenario": s, "change": s - b})
    # Runways
    if baseline.runway_count != scenario.runway_count:
        diffs.append({"parameter": "Runways", "baseline": baseline.runway_count, "scenario": scenario.runway_count, "change": scenario.runway_count - baseline.runway_count})
    # Security lanes
    for t in sorted(set(baseline.security_lanes_per_terminal) | set(scenario.security_lanes_per_terminal)):
        b = baseline.security_lanes_per_terminal.get(t, 0)
        s = scenario.security_lanes_per_terminal.get(t, 0)
        if b != s:
            diffs.append({"parameter": f"Security lanes (Terminal {t})", "baseline": b, "scenario": s, "change": s - b})
    # Baggage
    if baseline.screening_units != scenario.screening_units:
        diffs.append({"parameter": "Screening units", "baseline": baseline.screening_units, "scenario": scenario.screening_units, "change": scenario.screening_units - baseline.screening_units})
    if baseline.sorting_capacity_per_hour != scenario.sorting_capacity_per_hour:
        diffs.append({"parameter": "Sorting capacity/hr", "baseline": baseline.sorting_capacity_per_hour, "scenario": scenario.sorting_capacity_per_hour, "change": scenario.sorting_capacity_per_hour - baseline.sorting_capacity_per_hour})
    # Demand
    if baseline.daily_flight_target != scenario.daily_flight_target:
        diffs.append({"parameter": "Daily flights", "baseline": baseline.daily_flight_target, "scenario": scenario.daily_flight_target, "change": scenario.daily_flight_target - baseline.daily_flight_target})
    return diffs


def run_scenario(scenario: PlanningScenario) -> None:
    """Run a planning scenario with automatic baseline comparison.

    1. Run baseline (do-nothing) with the same dates, seeds, adapter
    2. Run scenario with modified infrastructure
    3. Compute delta (scenario - baseline) for all KPIs
    4. Run investment analysis using the actual delta
    """
    scenario.status = "running"
    scenario.started_at = datetime.utcnow().isoformat()
    scenario.progress_pct = 0
    scenario.runs_completed = 0
    t_start = time.monotonic()
    planning_metrics.active_scenarios.inc()

    try:
        schedule_adapter = get_schedule_adapter(scenario.demand_source)
        # If the scenario asks for a different weather source, plug a second
        # adapter; otherwise the engine reuses the schedule adapter.
        weather_adapter = None
        if scenario.weather_source and scenario.weather_source != scenario.demand_source:
            try:
                weather_adapter = get_weather_adapter(scenario.weather_source)
            except ValueError:
                logger.warning(
                    "Unknown weather_source %r, falling back to schedule adapter",
                    scenario.weather_source,
                )
        engine = PlanningSimEngine(
            adapter=schedule_adapter,
            seed=scenario.random_seed,
            weather_adapter=weather_adapter,
        )

        dates = _generate_dates(scenario.horizon, seed=scenario.random_seed)
        n_runs = max(1, scenario.monte_carlo_runs)
        base_seed = scenario.random_seed if scenario.random_seed is not None else random.randint(0, 999_999)

        # Total work: baseline runs + scenario runs
        total_runs = n_runs * 2

        # ── Phase 1: Run baseline ───────────────────────────
        # Baseline always runs at the natural demand level (multiplier=1) so
        # the delta isolates the infrastructure change from any demand shift.
        baseline_infra = InfrastructureConfig.baseline()
        # 1B — interventions/disruption affect both baseline and scenario so
        # delta KPIs cleanly attribute to infrastructure differences.
        interventions_obj = [Intervention.from_dict(i) for i in scenario.interventions]
        disruption_obj = (
            Disruption.from_dict(scenario.disruption) if scenario.disruption else None
        )
        baseline_runs = _run_monte_carlo(
            engine, dates, baseline_infra, n_runs, base_seed, "baseline",
            progress_cb=lambda done: _update_progress(scenario, done, total_runs),
            interventions=interventions_obj,
            disruption=disruption_obj,
        )
        baseline_kpis = _collect_kpis(baseline_runs)

        # ── Phase 2: Run scenario ───────────────────────────
        scenario_runs = _run_monte_carlo(
            engine, dates, scenario.infrastructure, n_runs, base_seed,
            scenario.name or "scenario",
            progress_cb=lambda done: _update_progress(scenario, n_runs + done, total_runs),
            demand_multiplier=scenario.demand_multiplier,
            interventions=interventions_obj,
            disruption=disruption_obj,
            new_routes=scenario.new_routes or None,
        )
        scenario_kpis = _collect_kpis(scenario_runs)

        # ── Phase 3: Compare ────────────────────────────────
        delta = _compute_delta(baseline_kpis, scenario_kpis)
        infra_changes = _infra_diff(baseline_infra, scenario.infrastructure)

        # ── Phase 4: Financial analysis ─────────────────────
        benefit_breakdown = extract_annual_benefit(baseline_kpis, scenario_kpis)
        annual_benefit = benefit_breakdown.total_annual_benefit

        financials: dict = {}
        if scenario.capex_eur > 0 or scenario.opex_delta_eur > 0:
            inv = compute_investment(
                capex=scenario.capex_eur,
                annual_benefit=max(0, annual_benefit),
                annual_opex=scenario.opex_delta_eur,
                years=scenario.years_horizon,
                discount_rate=scenario.discount_rate,
            )
            financials = inv.to_dict()
            # Add cumulative cash flow series for chart
            net_annual = inv.net_annual_eur
            financials["cumulative_cash_flows"] = []
            cumulative = -scenario.capex_eur
            financials["cumulative_cash_flows"].append(round(cumulative, 2))
            for yr in range(1, scenario.years_horizon + 1):
                cumulative += net_annual
                financials["cumulative_cash_flows"].append(round(cumulative, 2))

        elapsed = time.monotonic() - t_start

        results = ScenarioResults(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            status="completed",
            kpis={k: v for k, v in scenario_kpis.items()},
            baseline_kpis={k: v for k, v in baseline_kpis.items()},
            delta_vs_baseline=delta,
            financials=financials,
            annual_benefit_breakdown=benefit_breakdown.to_dict(),
            infrastructure_changes=infra_changes,
            run_duration_seconds=elapsed,
            computed_at=datetime.utcnow().isoformat(),
        )
        store_results(scenario.id, results.to_dict())

        scenario.status = "completed"
        scenario.completed_at = datetime.utcnow().isoformat()
        scenario.progress_pct = 100
        scenario.runs_completed = n_runs
        planning_metrics.active_scenarios.dec()
        planning_metrics.record_completion(
            horizon=scenario.horizon,
            monte_carlo_runs=n_runs,
            sim_days=len(dates),
            duration_seconds=elapsed,
        )
        logger.info(
            "Scenario %s completed: %d MC runs × %d days (×2 baseline) in %.1fs",
            scenario.id, n_runs, len(dates), elapsed,
        )

    except Exception as e:
        logger.error("Scenario %s failed: %s", scenario.id, e, exc_info=True)
        scenario.status = "failed"
        scenario.error = str(e)
        scenario.completed_at = datetime.utcnow().isoformat()
        planning_metrics.active_scenarios.dec()
        planning_metrics.record_failure()


def _update_progress(scenario: PlanningScenario, done: int, total: int) -> None:
    """Update scenario progress percentage."""
    scenario.progress_pct = min(99, int(done / total * 100))
    scenario.runs_completed = done

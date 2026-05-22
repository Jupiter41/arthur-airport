"""Day result model and KPI extraction for planning simulations.

Captures all operational, capacity, and financial KPIs for a single
simulated day under one InfrastructureConfig. Also defines KPIDistribution
for Monte Carlo aggregation.

P2.3 of ROADMAP_PLANNING.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class DayResult:
    """KPIs and financials for one simulated day under one InfrastructureConfig."""

    sim_date: date
    infrastructure_label: str  # "baseline" | scenario name

    # Operations KPIs
    total_flights: int = 0
    flights_on_time: int = 0
    flights_delayed: int = 0
    flights_cancelled: int = 0
    avg_delay_minutes: float = 0.0
    max_cascade_depth: int = 0
    missed_connections: int = 0
    gate_conflicts: int = 0
    holding_events: int = 0
    security_wait_max_minutes: float = 0.0

    # Capacity KPIs
    runway_utilisation_pct: float = 0.0
    gate_utilisation_pct: float = 0.0
    security_utilisation_pct: float = 0.0
    baggage_utilisation_pct: float = 0.0

    # Financial KPIs (from cost model)
    total_cost_eur: float = 0.0
    total_revenue_eur: float = 0.0
    net_eur: float = 0.0
    eu261_liability_eur: float = 0.0
    incident_cost_eur: float = 0.0

    def on_time_rate(self) -> float:
        return self.flights_on_time / max(1, self.total_flights)

    def cost_per_flight(self) -> float:
        return self.total_cost_eur / max(1, self.total_flights)

    def to_dict(self) -> dict:
        return {
            "sim_date": self.sim_date.isoformat(),
            "infrastructure_label": self.infrastructure_label,
            "total_flights": self.total_flights,
            "flights_on_time": self.flights_on_time,
            "flights_delayed": self.flights_delayed,
            "flights_cancelled": self.flights_cancelled,
            "avg_delay_minutes": round(self.avg_delay_minutes, 2),
            "max_cascade_depth": self.max_cascade_depth,
            "missed_connections": self.missed_connections,
            "gate_conflicts": self.gate_conflicts,
            "holding_events": self.holding_events,
            "security_wait_max_minutes": round(self.security_wait_max_minutes, 1),
            "runway_utilisation_pct": round(self.runway_utilisation_pct, 1),
            "gate_utilisation_pct": round(self.gate_utilisation_pct, 1),
            "security_utilisation_pct": round(self.security_utilisation_pct, 1),
            "baggage_utilisation_pct": round(self.baggage_utilisation_pct, 1),
            "total_cost_eur": round(self.total_cost_eur, 2),
            "total_revenue_eur": round(self.total_revenue_eur, 2),
            "net_eur": round(self.net_eur, 2),
            "eu261_liability_eur": round(self.eu261_liability_eur, 2),
            "incident_cost_eur": round(self.incident_cost_eur, 2),
            "on_time_rate": round(self.on_time_rate(), 4),
            "cost_per_flight": round(self.cost_per_flight(), 2),
        }


@dataclass
class KPIDistribution:
    """Statistical distribution of a KPI across Monte Carlo runs."""

    mean: float = 0.0
    std: float = 0.0
    p5: float = 0.0
    p25: float = 0.0
    p50: float = 0.0
    p75: float = 0.0
    p95: float = 0.0

    def confidence_interval_95(self) -> tuple[float, float]:
        return (self.p5, self.p95)

    def to_dict(self) -> dict:
        return {
            "mean": round(self.mean, 4),
            "std": round(self.std, 4),
            "p5": round(self.p5, 4),
            "p25": round(self.p25, 4),
            "p50": round(self.p50, 4),
            "p75": round(self.p75, 4),
            "p95": round(self.p95, 4),
        }


def aggregate_kpi(values: list[float]) -> KPIDistribution:
    """Compute distribution statistics from a list of KPI values."""
    if not values:
        return KPIDistribution()

    n = len(values)
    sorted_v = sorted(values)
    mean = sum(sorted_v) / n
    variance = sum((x - mean) ** 2 for x in sorted_v) / max(1, n - 1)
    std = variance ** 0.5

    def percentile(pct: float) -> float:
        k = (n - 1) * pct / 100.0
        f = int(k)
        c = f + 1 if f + 1 < n else f
        d = k - f
        return sorted_v[f] + d * (sorted_v[c] - sorted_v[f])

    return KPIDistribution(
        mean=mean,
        std=std,
        p5=percentile(5),
        p25=percentile(25),
        p50=percentile(50),
        p75=percentile(75),
        p95=percentile(95),
    )


@dataclass
class ScenarioResults:
    """Aggregated results for a completed planning scenario."""

    scenario_id: str = ""
    scenario_name: str = ""
    baseline_id: str = ""
    status: str = "completed"
    kpis: dict[str, KPIDistribution] = field(default_factory=dict)
    delta_vs_baseline: dict[str, dict] = field(default_factory=dict)
    financials: dict = field(default_factory=dict)
    annual_benefit_breakdown: dict[str, float] = field(default_factory=dict)
    run_duration_seconds: float = 0.0
    computed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "baseline_id": self.baseline_id,
            "status": self.status,
            "kpis": {k: v.to_dict() for k, v in self.kpis.items()},
            "delta_vs_baseline": self.delta_vs_baseline,
            "financials": self.financials,
            "annual_benefit_breakdown": self.annual_benefit_breakdown,
            "run_duration_seconds": round(self.run_duration_seconds, 2),
            "computed_at": self.computed_at,
        }

"""Scenario model — defines the planning scenario dataclass and storage.

P3.1 of ROADMAP_PLANNING.md (simplified for Phase 2 delivery).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from engine.infrastructure import InfrastructureConfig

logger = logging.getLogger(__name__)


@dataclass
class PlanningScenario:
    """A planning scenario definition."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Simulation parameters
    horizon: str = "day"  # day | week | month | year | 10year
    monte_carlo_runs: int = 1
    random_seed: int | None = None

    # Infrastructure override
    infrastructure: InfrastructureConfig = field(default_factory=InfrastructureConfig.baseline)

    # Demand settings
    demand_source: str = "simulation"  # simulation | bts | eurocontrol
    demand_multiplier: float = 1.0
    new_routes: list[dict] = field(default_factory=list)
    removed_routes: list[str] = field(default_factory=list)

    # Weather settings
    weather_source: str = "simulation"  # simulation | mesonet | historical_date
    weather_date: str | None = None

    # Investment costs
    capex_eur: float = 0.0
    opex_delta_eur: float = 0.0
    years_horizon: int = 25
    discount_rate: float = 0.07

    # Runtime state
    status: str = "pending"  # pending | running | completed | failed
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    progress_pct: int = 0
    runs_completed: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "horizon": self.horizon,
            "monte_carlo_runs": self.monte_carlo_runs,
            "random_seed": self.random_seed,
            "infrastructure": self.infrastructure.to_dict(),
            "demand_source": self.demand_source,
            "weather_source": self.weather_source,
            "capex_eur": self.capex_eur,
            "opex_delta_eur": self.opex_delta_eur,
            "years_horizon": self.years_horizon,
            "discount_rate": self.discount_rate,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "progress_pct": self.progress_pct,
            "runs_completed": self.runs_completed,
        }

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "horizon": self.horizon,
            "monte_carlo_runs": self.monte_carlo_runs,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


# ── In-memory scenario store ────────────────────────────────

_scenarios: dict[str, PlanningScenario] = {}
_results: dict[str, dict] = {}  # scenario_id → ScenarioResults.to_dict()


def store_scenario(scenario: PlanningScenario) -> None:
    _scenarios[scenario.id] = scenario


def get_scenario(scenario_id: str) -> PlanningScenario | None:
    return _scenarios.get(scenario_id)


def list_scenarios(
    status: str | None = None,
    horizon: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[PlanningScenario], int]:
    filtered = list(_scenarios.values())
    if status:
        filtered = [s for s in filtered if s.status == status]
    if horizon:
        filtered = [s for s in filtered if s.horizon == horizon]
    total = len(filtered)
    filtered.sort(key=lambda s: s.created_at, reverse=True)
    return filtered[offset : offset + limit], total


def delete_scenario(scenario_id: str) -> bool:
    if scenario_id in _scenarios:
        del _scenarios[scenario_id]
        _results.pop(scenario_id, None)
        return True
    return False


def store_results(scenario_id: str, results: dict) -> None:
    _results[scenario_id] = results


def get_results(scenario_id: str) -> dict | None:
    return _results.get(scenario_id)

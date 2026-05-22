"""REST API router for planning-service — Phase 1 adapters + Phase 2 scenarios."""

from __future__ import annotations

import asyncio
from datetime import date

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from adapters.registry import (
    get_demand_adapter,
    get_schedule_adapter,
    get_weather_adapter,
    list_available_adapters,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/planning", tags=["planning"])


@router.get("/adapters")
async def list_adapters():
    """List available adapters per domain."""
    return list_available_adapters()


@router.get("/schedule/preview")
async def preview_schedule(
    source: str = Query("simulation", description="Adapter: simulation, bts"),
    date_str: str = Query("2026-01-15", description="Date in YYYY-MM-DD format"),
    limit: int = Query(20, ge=1, le=500),
):
    """Preview a day's flight schedule from the selected adapter."""
    sim_date = date.fromisoformat(date_str)
    adapter = get_schedule_adapter(source)
    schedule = adapter.get_daily_schedule(sim_date)
    return {
        "source": adapter.source_name,
        "is_real_data": adapter.is_real_data,
        "date": date_str,
        "total_flights": len(schedule),
        "flights": schedule[:limit],
    }


@router.get("/weather/preview")
async def preview_weather(
    source: str = Query("simulation", description="Adapter: simulation, mesonet"),
    date_str: str = Query("2026-02-25", description="Date in YYYY-MM-DD format"),
):
    """Preview hourly weather sequence from the selected adapter."""
    sim_date = date.fromisoformat(date_str)
    adapter = get_weather_adapter(source)
    sequence = adapter.get_weather_sequence(sim_date)
    return {
        "source": adapter.source_name,
        "is_real_data": adapter.is_real_data,
        "date": date_str,
        "hours": len(sequence),
        "sequence": sequence,
    }


@router.get("/demand/preview")
async def preview_demand(
    source: str = Query("simulation", description="Adapter: simulation, bts_t100, eurocontrol"),
    origin: str = Query("JFK", description="Origin IATA code"),
    destination: str = Query("LAX", description="Destination IATA code"),
    month: int = Query(7, ge=1, le=12),
):
    """Preview daily passenger demand for an O&D pair."""
    adapter = get_demand_adapter(source)
    demand = adapter.get_passenger_demand(origin, destination, month)
    return {
        "source": adapter.source_name,
        "is_real_data": adapter.is_real_data,
        "origin": origin,
        "destination": destination,
        "month": month,
        "daily_pax": demand,
    }


@router.get("/weather/transitions")
async def weather_transitions(
    csv_path: str = Query("data/weather/EGLL_30days.csv", description="Path to Mesonet CSV"),
):
    """Compute empirical weather state transition matrix from Mesonet data."""
    from adapters.mesonet import MesonetAdapter

    adapter = MesonetAdapter(csv_path)
    matrix = adapter.get_transition_matrix()
    distribution = adapter.get_category_distribution()
    date_range = adapter.get_date_range()
    return {
        "source": adapter.source_name,
        "date_range": [str(d) for d in date_range] if date_range else None,
        "category_distribution": distribution,
        "transition_matrix": matrix,
    }


# ── Phase 2: Scenario CRUD + execution ──────────────────────


class CreateScenarioRequest(BaseModel):
    name: str
    description: str = ""
    horizon: str = Field("day", pattern=r"^(day|week|month|year|10year)$")
    monte_carlo_runs: int = Field(1, ge=1, le=500)
    random_seed: int | None = None
    infrastructure: dict | None = None
    demand_source: str = "simulation"
    weather_source: str = "simulation"
    capex_eur: float = 0.0
    opex_delta_eur: float = 0.0
    years_horizon: int = 25
    discount_rate: float = 0.07


@router.post("/scenarios", status_code=201)
async def create_scenario(
    body: CreateScenarioRequest,
    background_tasks: BackgroundTasks,
):
    """Create and queue a new planning scenario."""
    from engine.infrastructure import InfrastructureConfig
    from scenarios.model import PlanningScenario, store_scenario
    from scenarios.runner import run_scenario

    infra = (
        InfrastructureConfig.from_dict(body.infrastructure)
        if body.infrastructure
        else InfrastructureConfig.baseline()
    )

    scenario = PlanningScenario(
        name=body.name,
        description=body.description,
        horizon=body.horizon,
        monte_carlo_runs=body.monte_carlo_runs,
        random_seed=body.random_seed,
        infrastructure=infra,
        demand_source=body.demand_source,
        weather_source=body.weather_source,
        capex_eur=body.capex_eur,
        opex_delta_eur=body.opex_delta_eur,
        years_horizon=body.years_horizon,
        discount_rate=body.discount_rate,
    )
    store_scenario(scenario)

    # Estimate duration: ~0.5s per day per run
    from scenarios.runner import _horizon_to_days
    n_days = min(_horizon_to_days(body.horizon), 30)  # capped at 30 sample days
    est_seconds = n_days * body.monte_carlo_runs * 0.5

    # Run in background
    background_tasks.add_task(
        asyncio.to_thread, run_scenario, scenario
    )

    return {
        "scenario_id": scenario.id,
        "status": "pending",
        "estimated_duration_seconds": est_seconds,
    }


@router.get("/scenarios")
async def list_scenarios(
    status: str | None = Query(None),
    horizon: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List all planning scenarios."""
    from scenarios.model import list_scenarios as _list

    scenarios, total = _list(status=status, horizon=horizon, limit=limit, offset=offset)
    return {
        "total": total,
        "scenarios": [s.to_summary() for s in scenarios],
    }


@router.get("/scenarios/{scenario_id}")
async def get_scenario(scenario_id: str):
    """Get full scenario detail."""
    from scenarios.model import get_scenario as _get

    scenario = _get(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario.to_dict()


@router.get("/scenarios/{scenario_id}/status")
async def get_scenario_status(scenario_id: str):
    """Lightweight status poll for running scenarios."""
    from scenarios.model import get_scenario as _get

    scenario = _get(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    elapsed = 0.0
    if scenario.started_at:
        from datetime import datetime
        try:
            started = datetime.fromisoformat(scenario.started_at)
            elapsed = (datetime.utcnow() - started).total_seconds()
        except (ValueError, TypeError):
            pass

    return {
        "scenario_id": scenario.id,
        "status": scenario.status,
        "progress_pct": scenario.progress_pct,
        "runs_completed": scenario.runs_completed,
        "runs_total": scenario.monte_carlo_runs,
        "elapsed_seconds": round(elapsed, 1),
        "error": scenario.error,
    }


@router.get("/scenarios/{scenario_id}/results")
async def get_scenario_results(scenario_id: str):
    """Full planning results for a completed scenario."""
    from scenarios.model import get_results, get_scenario as _get

    scenario = _get(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if scenario.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Scenario is {scenario.status}, not completed",
        )

    results = get_results(scenario_id)
    if not results:
        raise HTTPException(status_code=404, detail="Results not found")
    return results


@router.delete("/scenarios/{scenario_id}")
async def delete_scenario_endpoint(scenario_id: str):
    """Delete a scenario and its results."""
    from scenarios.model import delete_scenario

    if not delete_scenario(scenario_id):
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {"deleted": scenario_id}


# ── Phase 4: Investment analysis ────────────────────────────


class InvestmentRequest(BaseModel):
    capex_eur: float = Field(..., ge=0, description="Upfront capital expenditure")
    annual_benefit_eur: float = Field(..., description="Projected annual benefit")
    annual_opex_eur: float = Field(0, ge=0, description="Annual operating cost delta")
    years_horizon: int = Field(25, ge=1, le=50)
    discount_rate: float = Field(0.07, ge=0, le=0.30)


@router.post("/investment/analyze")
async def analyze_investment(body: InvestmentRequest):
    """Standalone NPV/IRR analysis for a given capex and projected benefit."""
    from finance.investment import compute_investment

    result = compute_investment(
        capex=body.capex_eur,
        annual_benefit=body.annual_benefit_eur,
        annual_opex=body.annual_opex_eur,
        years=body.years_horizon,
        discount_rate=body.discount_rate,
    )
    return result.to_dict()


class SensitivityRequest(BaseModel):
    capex_eur: float = Field(..., ge=0)
    annual_benefit_eur: float = Field(...)
    annual_opex_eur: float = Field(0, ge=0)
    years_horizon: int = Field(25, ge=1, le=50)
    discount_rate: float = Field(0.07, ge=0, le=0.30)
    growth_scenarios: dict[str, float] | None = None


@router.post("/investment/sensitivity")
async def investment_sensitivity(body: SensitivityRequest):
    """NPV sensitivity analysis under different demand growth assumptions."""
    from finance.investment import sensitivity_analysis

    results = sensitivity_analysis(
        capex=body.capex_eur,
        annual_benefit=body.annual_benefit_eur,
        annual_opex=body.annual_opex_eur,
        years=body.years_horizon,
        discount_rate=body.discount_rate,
        growth_scenarios=body.growth_scenarios,
    )
    return {"scenarios": results}


@router.get("/scenarios/{scenario_id}/investment")
async def get_scenario_investment(scenario_id: str):
    """Get investment analysis results for a completed scenario."""
    from scenarios.model import get_results, get_scenario as _get

    scenario = _get(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if scenario.status != "completed":
        raise HTTPException(status_code=409, detail=f"Scenario is {scenario.status}")

    results = get_results(scenario_id)
    if not results:
        raise HTTPException(status_code=404, detail="Results not found")

    return {
        "scenario_id": scenario_id,
        "financials": results.get("financials", {}),
        "annual_benefit_breakdown": results.get("annual_benefit_breakdown", {}),
    }


# ── Phase 5: Scenario templates ─────────────────────────────


@router.get("/templates")
async def list_templates():
    """List available pre-built scenario templates."""
    from scenarios.templates import TEMPLATE_CATALOGUE

    return {
        "templates": {
            key: {"name": t["name"], "description": t["description"], "params": t["params"]}
            for key, t in TEMPLATE_CATALOGUE.items()
        }
    }


class GateTemplateRequest(BaseModel):
    terminal: str = Field(..., pattern=r"^[A-C]$", description="Terminal letter (A, B, or C)")
    additional_gates: int = Field(..., ge=1, le=20, description="Number of gates to add")


class RunwayTemplateRequest(BaseModel):
    runway_id: str = Field(..., description="Runway designator, e.g. '27L'")
    ils_capable: bool = Field(True, description="Whether the runway has ILS")
    length_m: int = Field(3000, ge=1500, le=5000, description="Runway length in metres")


class RouteTemplateRequest(BaseModel):
    destination_iata: str = Field(..., min_length=3, max_length=4, description="Destination IATA code")
    daily_flights: int = Field(..., ge=1, le=50, description="Daily flight rotations")
    aircraft_type: str = Field("A320", description="Aircraft type (e.g. A320, B738)")


class SecurityTemplateRequest(BaseModel):
    lanes_delta: dict[str, int] = Field(
        ..., description="Terminal → lane count change, e.g. {'A': 1, 'B': -1}"
    )


@router.post("/templates/add_gate", status_code=201)
async def create_gate_template(body: GateTemplateRequest, background_tasks: BackgroundTasks):
    """Create a gate addition scenario from template."""
    from scenarios.templates import create_gate_scenario
    from scenarios.model import store_scenario

    scenario = create_gate_scenario(body.terminal, body.additional_gates)
    store_scenario(scenario)
    return scenario.to_dict()


@router.post("/templates/add_runway", status_code=201)
async def create_runway_template(body: RunwayTemplateRequest, background_tasks: BackgroundTasks):
    """Create a runway addition scenario from template."""
    from scenarios.templates import create_runway_scenario
    from scenarios.model import store_scenario

    scenario = create_runway_scenario(body.runway_id, body.ils_capable, body.length_m)
    store_scenario(scenario)
    return scenario.to_dict()


@router.post("/templates/new_route", status_code=201)
async def create_route_template(body: RouteTemplateRequest, background_tasks: BackgroundTasks):
    """Create a new route scenario from template."""
    from scenarios.templates import create_route_scenario
    from scenarios.model import store_scenario

    scenario = create_route_scenario(body.destination_iata, body.daily_flights, body.aircraft_type)
    store_scenario(scenario)
    return scenario.to_dict()


@router.post("/templates/security_lanes", status_code=201)
async def create_security_template(body: SecurityTemplateRequest, background_tasks: BackgroundTasks):
    """Create a security lane adjustment scenario from template."""
    from scenarios.templates import create_security_scenario
    from scenarios.model import store_scenario

    scenario = create_security_scenario(body.lanes_delta)
    store_scenario(scenario)
    return scenario.to_dict()

"""REST API router for planning-service — Phase 1 adapters + Phase 2 scenarios."""

from __future__ import annotations

import asyncio
from datetime import date, datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from adapters.registry import (
    get_demand_adapter,
    get_schedule_adapter,
    get_weather_adapter,
    list_available_adapters,
)
from scenarios.metrics import planning_metrics

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
    demand_multiplier: float = Field(1.0, gt=0)
    new_routes: list[dict] = Field(default_factory=list)


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
        demand_multiplier=body.demand_multiplier,
        new_routes=list(body.new_routes),
    )
    store_scenario(scenario)

    # Estimate duration using historical timing data
    estimate = planning_metrics.estimate_duration(body.horizon, body.monte_carlo_runs)
    planning_metrics.scenarios_created.labels(template="custom").inc()

    # Run in background
    background_tasks.add_task(
        asyncio.to_thread, run_scenario, scenario
    )

    return {
        "scenario_id": scenario.id,
        "status": "pending",
        "estimated_duration_seconds": estimate["estimated_seconds"],
        "estimated_duration_human": estimate["human_readable"],
        "estimation_confidence": estimate["confidence"],
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
    estimated_remaining = None
    if scenario.started_at:
        from datetime import datetime
        try:
            started = datetime.fromisoformat(scenario.started_at)
            elapsed = (datetime.utcnow() - started).total_seconds()
        except (ValueError, TypeError):
            pass

    # Estimate remaining time based on progress
    if scenario.status == "running" and scenario.progress_pct > 0:
        rate = elapsed / scenario.progress_pct
        estimated_remaining = round(rate * (100 - scenario.progress_pct), 1)

    return {
        "scenario_id": scenario.id,
        "status": scenario.status,
        "progress_pct": scenario.progress_pct,
        "runs_completed": scenario.runs_completed,
        "runs_total": scenario.monte_carlo_runs * 2,  # baseline + scenario
        "elapsed_seconds": round(elapsed, 1),
        "estimated_remaining_seconds": estimated_remaining,
        "error": scenario.error,
    }


@router.get("/estimate")
async def estimate_duration(
    horizon: str = Query("day", pattern=r"^(day|week|month|year|10year)$"),
    monte_carlo_runs: int = Query(200, ge=1, le=500),
):
    """Estimate how long a scenario would take to run."""
    return planning_metrics.estimate_duration(horizon, monte_carlo_runs)


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
    """Create a gate addition scenario from template and auto-run it."""
    from scenarios.templates import create_gate_scenario
    from scenarios.model import store_scenario
    from scenarios.runner import run_scenario

    scenario = create_gate_scenario(body.terminal, body.additional_gates)
    store_scenario(scenario)
    estimate = planning_metrics.estimate_duration(scenario.horizon, scenario.monte_carlo_runs)
    planning_metrics.scenarios_created.labels(template="add_gate").inc()
    background_tasks.add_task(asyncio.to_thread, run_scenario, scenario)
    return {
        "scenario_id": scenario.id,
        "status": "pending",
        "estimated_duration_seconds": estimate["estimated_seconds"],
        "estimated_duration_human": estimate["human_readable"],
        "estimation_confidence": estimate["confidence"],
        **scenario.to_dict(),
    }


@router.post("/templates/add_runway", status_code=201)
async def create_runway_template(body: RunwayTemplateRequest, background_tasks: BackgroundTasks):
    """Create a runway addition scenario from template and auto-run it."""
    from scenarios.templates import create_runway_scenario
    from scenarios.model import store_scenario
    from scenarios.runner import run_scenario

    scenario = create_runway_scenario(body.runway_id, body.ils_capable, body.length_m)
    store_scenario(scenario)
    estimate = planning_metrics.estimate_duration(scenario.horizon, scenario.monte_carlo_runs)
    planning_metrics.scenarios_created.labels(template="add_runway").inc()
    background_tasks.add_task(asyncio.to_thread, run_scenario, scenario)
    return {
        "scenario_id": scenario.id,
        "status": "pending",
        "estimated_duration_seconds": estimate["estimated_seconds"],
        "estimated_duration_human": estimate["human_readable"],
        "estimation_confidence": estimate["confidence"],
        **scenario.to_dict(),
    }


@router.post("/templates/new_route", status_code=201)
async def create_route_template(body: RouteTemplateRequest, background_tasks: BackgroundTasks):
    """Create a new route scenario from template and auto-run it."""
    from scenarios.templates import create_route_scenario
    from scenarios.model import store_scenario
    from scenarios.runner import run_scenario

    scenario = create_route_scenario(body.destination_iata, body.daily_flights, body.aircraft_type)
    store_scenario(scenario)
    estimate = planning_metrics.estimate_duration(scenario.horizon, scenario.monte_carlo_runs)
    planning_metrics.scenarios_created.labels(template="new_route").inc()
    background_tasks.add_task(asyncio.to_thread, run_scenario, scenario)
    return {
        "scenario_id": scenario.id,
        "status": "pending",
        "estimated_duration_seconds": estimate["estimated_seconds"],
        "estimated_duration_human": estimate["human_readable"],
        "estimation_confidence": estimate["confidence"],
        **scenario.to_dict(),
    }


@router.post("/templates/security_lanes", status_code=201)
async def create_security_template(body: SecurityTemplateRequest, background_tasks: BackgroundTasks):
    """Create a security lane adjustment scenario from template and auto-run it."""
    from scenarios.templates import create_security_scenario
    from scenarios.model import store_scenario
    from scenarios.runner import run_scenario

    scenario = create_security_scenario(body.lanes_delta)
    store_scenario(scenario)
    estimate = planning_metrics.estimate_duration(scenario.horizon, scenario.monte_carlo_runs)
    planning_metrics.scenarios_created.labels(template="security_lanes").inc()
    background_tasks.add_task(asyncio.to_thread, run_scenario, scenario)
    return {
        "scenario_id": scenario.id,
        "status": "pending",
        "estimated_duration_seconds": estimate["estimated_seconds"],
        "estimated_duration_human": estimate["human_readable"],
        "estimation_confidence": estimate["confidence"],
        **scenario.to_dict(),
    }


class TerminalTemplateRequest(BaseModel):
    terminal_letter: str = Field(..., pattern=r"^[D-Z]$", description="Terminal letter (D–Z)")
    gates: int = Field(14, ge=4, le=30, description="Number of gates")
    security_lanes: int = Field(4, ge=1, le=10, description="Number of security lanes")
    wide_body_gates: int = Field(3, ge=0, le=15, description="Wide-body capable gates")
    international_gates: int = Field(7, ge=0, le=20, description="International capable gates")


@router.post("/templates/add_terminal", status_code=201)
async def create_terminal_template(body: TerminalTemplateRequest, background_tasks: BackgroundTasks):
    """Create a new terminal scenario from template and auto-run it."""
    from scenarios.templates import create_terminal_scenario
    from scenarios.model import store_scenario
    from scenarios.runner import run_scenario

    scenario = create_terminal_scenario(
        body.terminal_letter, body.gates, body.security_lanes,
        body.wide_body_gates, body.international_gates,
    )
    store_scenario(scenario)
    estimate = planning_metrics.estimate_duration(scenario.horizon, scenario.monte_carlo_runs)
    planning_metrics.scenarios_created.labels(template="add_terminal").inc()
    background_tasks.add_task(asyncio.to_thread, run_scenario, scenario)
    return {
        "scenario_id": scenario.id,
        "status": "pending",
        "estimated_duration_seconds": estimate["estimated_seconds"],
        "estimated_duration_human": estimate["human_readable"],
        "estimation_confidence": estimate["confidence"],
        **scenario.to_dict(),
    }


# ── Baseline and cost estimation ────────────────────────────


@router.get("/baseline")
async def get_baseline():
    """Return the current KART baseline infrastructure and derived pax estimate."""
    from engine.infrastructure import InfrastructureConfig

    baseline = InfrastructureConfig.baseline()
    # Estimate annual pax: daily_flights × load_factor × avg_pax_per_flight × 365
    avg_pax_per_flight = 150  # weighted average across narrow/wide/regional
    annual_pax = int(
        baseline.daily_flight_target * baseline.load_factor_mean * avg_pax_per_flight * 365
    )
    return {
        "infrastructure": baseline.to_dict(),
        "annual_pax_estimate": annual_pax,
        "daily_flight_target": baseline.daily_flight_target,
        "load_factor_mean": baseline.load_factor_mean,
    }


class CostEstimateRequest(BaseModel):
    infrastructure: dict = Field(..., description="Modified infrastructure config")


@router.post("/cost-estimate")
async def estimate_infrastructure_cost(body: CostEstimateRequest):
    """Estimate CAPEX and annual OPEX from infrastructure changes vs baseline."""
    from engine.infrastructure import InfrastructureConfig, estimate_costs

    baseline = InfrastructureConfig.baseline()
    scenario = InfrastructureConfig.from_dict(body.infrastructure)
    return estimate_costs(baseline, scenario)


# ── Phase 6: ML demand forecasting ──────────────────────────


@router.get("/demand/forecast")
async def demand_forecast(
    origin: str = Query("ART", description="Origin IATA"),
    destination: str = Query("JFK", description="Destination IATA"),
    date_str: str = Query("2026-07-15", description="Forecast date YYYY-MM-DD"),
    distance_km: float = Query(1000.0, ge=0),
    is_hub: bool = Query(False),
):
    """Predict daily passenger demand for a route on a given date."""
    from ml.demand_model import get_demand_model

    forecast_date = date.fromisoformat(date_str)
    model = get_demand_model()
    forecast = model.predict(origin, destination, forecast_date, distance_km, is_hub)
    return {
        "origin": origin,
        "destination": destination,
        "date": date_str,
        "predicted_daily_pax": forecast.predicted_daily_pax,
        "confidence_low": forecast.confidence_low,
        "confidence_high": forecast.confidence_high,
        "model_source": forecast.model_source,
    }


@router.get("/demand/forecast/range")
async def demand_forecast_range(
    origin: str = Query("ART"),
    destination: str = Query("JFK"),
    start_date: str = Query("2026-07-01"),
    days: int = Query(30, ge=1, le=365),
    distance_km: float = Query(1000.0, ge=0),
    is_hub: bool = Query(False),
):
    """Forecast demand for a route over a date range."""
    from ml.demand_model import get_demand_model

    start = date.fromisoformat(start_date)
    model = get_demand_model()
    forecasts = model.forecast_route_range(origin, destination, start, days, distance_km, is_hub)
    return {
        "origin": origin,
        "destination": destination,
        "start_date": start_date,
        "days": days,
        "model_source": forecasts[0].model_source if forecasts else "heuristic",
        "forecasts": [
            {
                "date": f.forecast_date.isoformat(),
                "predicted_daily_pax": f.predicted_daily_pax,
                "confidence_low": f.confidence_low,
                "confidence_high": f.confidence_high,
            }
            for f in forecasts
        ],
    }


@router.get("/demand/growth")
async def demand_growth(
    base_year_pax: int = Query(8_000_000, ge=0),
    years_ahead: int = Query(10, ge=1, le=30),
):
    """Project annual passenger growth using Eurocontrol CAGR scenarios."""
    from adapters.eurocontrol import EurocontrolDemandAdapter

    adapter = EurocontrolDemandAdapter()
    projections = {}
    for scenario in ("low", "base", "high"):
        projected = adapter.project_annual_pax(base_year_pax, years_ahead, scenario)
        rate = adapter.get_demand_growth_rate(scenario)
        projections[scenario] = {
            "growth_rate_pct": round(rate * 100, 1),
            "projected_annual_pax": projected,
            "growth_factor": round((1 + rate) ** years_ahead, 3),
        }
    return {
        "base_year_pax": base_year_pax,
        "years_ahead": years_ahead,
        "projections": projections,
    }


class ForecastRequest(BaseModel):
    base_year_pax: int = Field(8_000_000, ge=0, description="Current annual passengers")
    years_ahead: int = Field(10, ge=1, le=30, description="Projection horizon")
    growth_rate_pct: float = Field(3.4, ge=-10, le=15, description="Custom annual growth %")
    shock_year: int | None = Field(None, ge=1, le=30, description="Year of demand shock")
    shock_pct: float = Field(-20.0, ge=-80, le=50, description="Shock magnitude %")


@router.post("/demand/forecast/custom")
async def custom_forecast(body: ForecastRequest):
    """Project annual traffic with user-adjustable growth rate and optional shock year."""
    rate = body.growth_rate_pct / 100.0
    yearly: list[dict] = []
    pax = float(body.base_year_pax)
    for yr in range(1, body.years_ahead + 1):
        pax *= 1 + rate
        if body.shock_year and yr == body.shock_year:
            pax *= 1 + (body.shock_pct / 100.0)
        yearly.append({"year": yr, "annual_pax": round(pax)})
    return {
        "base_year_pax": body.base_year_pax,
        "growth_rate_pct": body.growth_rate_pct,
        "shock_year": body.shock_year,
        "shock_pct": body.shock_pct if body.shock_year else None,
        "years": yearly,
    }


class MultiYearCompareRequest(BaseModel):
    scenario_ids: list[str] = Field(..., min_length=1, max_length=10)
    years_ahead: int = Field(10, ge=1, le=30)
    growth_rate_pct: float = Field(3.4, ge=-10, le=15)


@router.post("/scenarios/compare/multiyear")
async def compare_multiyear(body: MultiYearCompareRequest):
    """Project scenario KPIs over N years accounting for demand growth.

    Scales demand-sensitive KPIs (delay, utilisation, costs) based on
    annual growth compounding and the measured per-scenario deltas.
    """
    from scenarios.model import get_results, get_scenario as _get

    rate = body.growth_rate_pct / 100.0
    # KPIs that scale linearly with demand
    DEMAND_SCALED = {"avg_delay_minutes", "missed_connections", "eu261_liability_eur", "total_cost_eur"}
    # KPIs that grow sub-linearly with demand (utilisation caps at 100)
    UTIL_SCALED = {"gate_utilisation_pct", "runway_utilisation_pct"}

    result_set: list[dict] = []
    for sid in body.scenario_ids:
        scenario = _get(sid)
        if not scenario or scenario.status != "completed":
            continue
        results = get_results(sid)
        if not results:
            continue

        kpis = results.get("kpis", {})
        yearly_kpis: list[dict] = []

        for yr in range(body.years_ahead + 1):
            demand_factor = (1 + rate) ** yr
            year_kpis: dict[str, float] = {}
            for kpi_name, dist in kpis.items():
                mean = dist.get("mean", 0) if isinstance(dist, dict) else 0
                if kpi_name in DEMAND_SCALED:
                    year_kpis[kpi_name] = round(mean * demand_factor, 2)
                elif kpi_name in UTIL_SCALED:
                    year_kpis[kpi_name] = round(min(100.0, mean * (demand_factor ** 0.5)), 2)
                else:
                    # Rates degrade slightly under higher demand
                    if kpi_name == "on_time_rate":
                        year_kpis[kpi_name] = round(max(0, mean * (1 - 0.005 * yr)), 4)
                    else:
                        year_kpis[kpi_name] = round(mean * (demand_factor ** 0.3), 2)
            yearly_kpis.append({"year": yr, "kpis": year_kpis})

        result_set.append({
            "scenario_id": sid,
            "scenario_name": scenario.name,
            "yearly_kpis": yearly_kpis,
        })

    return {"scenarios": result_set, "years_ahead": body.years_ahead, "growth_rate_pct": body.growth_rate_pct}


@router.get("/delay/predict")
async def predict_delay(
    hour: int = Query(14, ge=0, le=23),
    day_of_week: int = Query(2, ge=0, le=6),
    month: int = Query(7, ge=1, le=12),
    weather_category: int = Query(0, ge=0, le=3, description="0=CAVOK, 1=VMC, 2=IMC, 3=LIFR"),
    flights_prev_2h: int = Query(20, ge=0),
):
    """Predict P(delay > 15 min) for a flight given conditions."""
    from ml.delay_model import get_delay_model

    model = get_delay_model()
    pred = model.predict(
        hour=hour, day_of_week=day_of_week, month=month,
        weather_category=weather_category, flights_prev_2h=flights_prev_2h,
    )
    return {
        "p_delay_15min": pred.p_delay_15min,
        "expected_delay_minutes": pred.expected_delay_minutes,
        "model_source": pred.model_source,
        "context": pred.flight_context,
    }


@router.post("/ml/train")
async def train_models(background_tasks: BackgroundTasks):
    """Train demand and delay ML models from BTS data."""
    import os
    from ml.training_pipeline import run_training_pipeline

    bts_path = os.getenv("BTS_CSV_PATH", "/app/data/bts/T100_reference.csv")

    # Run training in background (can take a few seconds)
    import asyncio

    result = await asyncio.to_thread(run_training_pipeline, bts_path)
    return {"status": "completed", "results": result}


@router.get("/ml/status")
async def ml_model_status():
    """Get current ML model status."""
    from ml.demand_model import get_demand_model
    from ml.delay_model import get_delay_model

    return {
        "demand_model": get_demand_model().to_dict(),
        "delay_model": get_delay_model().to_dict(),
    }


# ── Phase 7: Decision audit trail ───────────────────────────


@router.get("/audit/recommendations")
async def list_audit_recommendations(
    type: str | None = Query(None, description="Filter: operational | planning"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List recommendation audit trail entries."""
    from audit.audit_trail import get_audit_log

    entries, total = get_audit_log(rec_type=type, limit=limit, offset=offset)
    return {"total": total, "entries": entries}


@router.get("/audit/summary")
async def audit_summary():
    """Get recommendation accuracy summary metrics."""
    from audit.audit_trail import get_audit_summary

    return get_audit_summary()


@router.post("/audit/log")
async def log_audit_recommendation(body: dict):
    """Log a recommendation to the audit trail."""
    from audit.audit_trail import log_recommendation

    entry = log_recommendation(
        recommendation_text=body.get("recommendation_text", ""),
        action_type=body.get("action_type", ""),
        predicted_saving_eur=body.get("predicted_saving_eur", 0.0),
        confidence=body.get("confidence", 0.0),
        rec_type=body.get("type", "operational"),
        sim_day=body.get("sim_day", 1),
        sim_time=body.get("sim_time", ""),
        target_type=body.get("target_type", ""),
        target_id=body.get("target_id", ""),
    )
    return entry.to_dict()


@router.post("/audit/apply/{rec_id}")
async def apply_audit_recommendation(rec_id: str, body: dict):
    """Mark a recommendation as applied."""
    from audit.audit_trail import mark_applied

    applied_at = body.get("applied_at", datetime.utcnow().isoformat())
    if mark_applied(rec_id, applied_at):
        return {"status": "applied", "rec_id": rec_id}
    raise HTTPException(status_code=404, detail="Recommendation not found")


@router.post("/audit/outcome/{rec_id}")
async def record_audit_outcome(rec_id: str, body: dict):
    """Record measured outcome for an applied recommendation."""
    from audit.audit_trail import record_outcome

    actual = body.get("actual_saving_eur", 0.0)
    if record_outcome(rec_id, actual):
        return {"status": "recorded", "rec_id": rec_id}
    raise HTTPException(status_code=404, detail="Recommendation not found")

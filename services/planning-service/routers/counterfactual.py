"""Counterfactual delay analysis (1B — ROADMAP_USECASE.md).

Endpoints:
- POST /api/v1/planning/scenarios/{id}/replay
- POST /api/v1/planning/scenarios/{id}/counterfactual-report
- GET  /api/v1/planning/scenarios/{id}/causal-graph
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from engine.interventions import VALID_ACTIONS
from scenarios.metrics import planning_metrics
from scenarios.model import (
    PlanningScenario,
    get_results,
    get_scenario,
    list_scenarios,
    store_scenario,
)
from scenarios.runner import run_scenario

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/planning", tags=["counterfactual"])


class InterventionPayload(BaseModel):
    action: str = Field(..., description=f"One of {sorted(VALID_ACTIONS)}")
    sim_minute: int = Field(..., ge=0, le=1439)
    duration_minutes: int = Field(60, ge=1, le=1440)
    params: dict = Field(default_factory=dict)


class DisruptionPayload(BaseModel):
    sim_minute: int = Field(60, ge=0, le=1439)
    duration_minutes: int = Field(120, ge=1, le=1440)
    capacity_pct: float = Field(0.5, ge=0.0, le=1.0)


class ReplayRequest(BaseModel):
    interventions: list[InterventionPayload] = Field(default_factory=list)
    disruption: DisruptionPayload | None = None
    label: str | None = Field(None, description="Optional human-readable label for the replay")


def _spawn_replay_scenario(
    parent: PlanningScenario,
    interventions: list[dict],
    disruption: dict | None,
    label: str,
) -> PlanningScenario:
    """Create a child scenario referencing the parent."""
    child = PlanningScenario(
        name=f"{parent.name} — {label}",
        description=f"Counterfactual replay of {parent.id}: {label}",
        horizon=parent.horizon,
        monte_carlo_runs=parent.monte_carlo_runs,
        random_seed=parent.random_seed,
        infrastructure=parent.infrastructure,
        demand_source=parent.demand_source,
        weather_source=parent.weather_source,
        capex_eur=parent.capex_eur,
        opex_delta_eur=parent.opex_delta_eur,
        years_horizon=parent.years_horizon,
        discount_rate=parent.discount_rate,
        interventions=interventions,
        disruption=disruption,
        parent_scenario_id=parent.id,
    )
    store_scenario(child)
    return child


@router.post("/scenarios/{scenario_id}/replay", status_code=202)
async def scenario_replay(
    scenario_id: str,
    body: ReplayRequest,
    background_tasks: BackgroundTasks,
):
    """Re-run a scenario with overridden decision timing (1B).

    Returns the new child scenario id; poll ``/scenarios/{child_id}/status`` for progress
    and ``/scenarios/{child_id}/results`` once complete to obtain delta vs the parent baseline.
    """
    parent = get_scenario(scenario_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Scenario not found")

    interventions = [iv.model_dump() for iv in body.interventions]
    disruption = body.disruption.model_dump() if body.disruption else None

    label = body.label or f"replay-{len(interventions)}-iv"
    child = _spawn_replay_scenario(parent, interventions, disruption, label)

    estimate = planning_metrics.estimate_duration(child.horizon, child.monte_carlo_runs)
    planning_metrics.scenarios_created.labels(template="counterfactual").inc()
    background_tasks.add_task(asyncio.to_thread, run_scenario, child)

    return {
        "scenario_id": child.id,
        "parent_scenario_id": parent.id,
        "status": "pending",
        "interventions": interventions,
        "disruption": disruption,
        "estimated_duration_seconds": estimate["estimated_seconds"],
    }


class ShiftItem(BaseModel):
    intervention_index: int = Field(0, ge=0, description="Which intervention in the list to shift")
    shift_minutes: int = Field(..., description="Negative = earlier; positive = later")


class CounterfactualReportRequest(BaseModel):
    base_interventions: list[InterventionPayload]
    disruption: DisruptionPayload | None = None
    shifts: list[int] = Field(
        default_factory=lambda: [-30, -15, 0, 15, 30],
        description="Minute offsets applied to base_interventions[0].sim_minute",
    )
    intervention_index: int = Field(0, ge=0, description="Which intervention to shift")


@router.post("/scenarios/{scenario_id}/counterfactual-report", status_code=202)
async def counterfactual_report(
    scenario_id: str,
    body: CounterfactualReportRequest,
    background_tasks: BackgroundTasks,
):
    """Spawn N replay scenarios varying the timing of one intervention.

    Returns the list of child scenario ids and the shift that produced each.
    Use ``GET /scenarios/{child_id}/results`` once complete to compare KPIs.
    """
    parent = get_scenario(scenario_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if not body.base_interventions:
        raise HTTPException(status_code=400, detail="base_interventions cannot be empty")
    if body.intervention_index >= len(body.base_interventions):
        raise HTTPException(status_code=400, detail="intervention_index out of range")

    base = [iv.model_dump() for iv in body.base_interventions]
    disruption = body.disruption.model_dump() if body.disruption else None

    children: list[dict] = []
    for shift in body.shifts:
        ivs = [dict(iv) for iv in base]
        target = dict(ivs[body.intervention_index])
        new_minute = max(0, min(1439, int(target["sim_minute"]) + shift))
        target["sim_minute"] = new_minute
        ivs[body.intervention_index] = target
        label = f"shift {shift:+d}m → T={new_minute}"
        child = _spawn_replay_scenario(parent, ivs, disruption, label)
        background_tasks.add_task(asyncio.to_thread, run_scenario, child)
        children.append({
            "scenario_id": child.id,
            "shift_minutes": shift,
            "applied_sim_minute": new_minute,
            "label": label,
        })

    return {
        "parent_scenario_id": parent.id,
        "intervention_index": body.intervention_index,
        "children": children,
    }


@router.get("/scenarios/{scenario_id}/causal-graph")
async def causal_graph(scenario_id: str):
    """Return a JSON DAG of trigger → cascade → interventions → outcome KPIs.

    Nodes are produced from the scenario's configured disruption, the listed
    interventions, and headline KPIs from results (when available).
    Edges describe the causal chain.
    """
    scenario = get_scenario(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    nodes: list[dict] = []
    edges: list[dict] = []

    nodes.append({"id": "scenario", "type": "scenario", "label": scenario.name or scenario.id})

    if scenario.disruption:
        nodes.append({
            "id": "disruption",
            "type": "disruption",
            "label": "Synthetic disruption",
            "sim_minute": scenario.disruption.get("sim_minute"),
            "duration_minutes": scenario.disruption.get("duration_minutes"),
            "capacity_pct": scenario.disruption.get("capacity_pct"),
        })
        edges.append({"from": "scenario", "to": "disruption", "kind": "triggers"})

    for idx, iv in enumerate(scenario.interventions):
        nid = f"iv-{idx}"
        nodes.append({
            "id": nid,
            "type": "intervention",
            "label": f"{iv['action']} @ T+{iv['sim_minute']}m",
            "action": iv["action"],
            "sim_minute": iv["sim_minute"],
            "duration_minutes": iv.get("duration_minutes", 60),
            "params": iv.get("params", {}),
        })
        if scenario.disruption:
            edges.append({"from": "disruption", "to": nid, "kind": "responds_to"})
        else:
            edges.append({"from": "scenario", "to": nid, "kind": "responds_to"})

    results = get_results(scenario_id)
    if results:
        kpis = results.get("kpis", {})
        for kpi_name in ("avg_delay_minutes", "missed_connections", "eu261_liability_eur"):
            dist = kpis.get(kpi_name)
            if not dist:
                continue
            nid = f"kpi-{kpi_name}"
            nodes.append({
                "id": nid,
                "type": "kpi",
                "label": kpi_name,
                "mean": dist.get("mean") if isinstance(dist, dict) else None,
            })
            for src in (
                [f"iv-{i}" for i in range(len(scenario.interventions))]
                or (["disruption"] if scenario.disruption else ["scenario"])
            ):
                edges.append({"from": src, "to": nid, "kind": "affects"})

    return {
        "scenario_id": scenario.id,
        "parent_scenario_id": scenario.parent_scenario_id,
        "nodes": nodes,
        "edges": edges,
    }


@router.get("/scenarios/{scenario_id}/replays")
async def list_replays(scenario_id: str):
    """List all counterfactual replays spawned from a parent scenario."""
    parent = get_scenario(scenario_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Scenario not found")

    all_scenarios, _ = list_scenarios(limit=500, offset=0)
    children = [
        s.to_dict() | (
            {"results": get_results(s.id)} if s.status == "completed" else {"results": None}
        )
        for s in all_scenarios
        if s.parent_scenario_id == scenario_id
    ]
    return {"parent_scenario_id": scenario_id, "replays": children}

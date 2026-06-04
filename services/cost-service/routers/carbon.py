"""REST API router for the Carbon Footprint Tracker (1A).

Endpoints under /api/v1/costs/carbon.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from db import neo4j as db
from db.neo4j import carbon_hourly_timeline, carbon_summary_by_source
from services.carbon_tracker import get_carbon_totals

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/costs/carbon", tags=["carbon"])

_factors: dict = {}


def set_factors(factors: dict) -> None:
    global _factors
    _factors = factors


def _require_neo4j() -> None:
    if db._driver is None:
        raise HTTPException(status_code=503, detail="neo4j not connected")


@router.get("/summary")
async def carbon_summary():
    """Running totals for the latest sim_day: total kg CO₂ + by source."""
    totals = get_carbon_totals()
    by_src = totals.get("by_source", {})
    return {
        "sim_day": totals.get("sim_day", 1),
        "sim_time": totals.get("last_updated"),
        "total_kg": totals.get("total_kg", 0.0),
        "total_tonnes": round(totals.get("total_kg", 0.0) / 1000.0, 2),
        "by_source": by_src,
    }


@router.get("/by-source")
async def carbon_by_source(day: int = Query(1, ge=1)):
    """Pie-chart-friendly breakdown for a sim-day."""
    _require_neo4j()
    rows = await carbon_summary_by_source(day)
    total = sum(r.get("total_kg", 0.0) for r in rows)
    return {
        "day": day,
        "total_kg": round(total, 2),
        "items": [
            {
                "source": r["source"],
                "co2_kg": round(r["total_kg"], 2),
                "share_pct": round((r["total_kg"] / total * 100.0) if total > 0 else 0.0, 1),
                "records": r.get("records", 0),
            }
            for r in rows
        ],
    }


@router.get("/timeline")
async def carbon_timeline(day: int = Query(1, ge=1)):
    """Hourly emissions timeline for a sim-day. Always returns 24 hours."""
    _require_neo4j()
    hours = await carbon_hourly_timeline(day)
    return {"day": day, "hours": hours}


@router.get("/factors")
async def carbon_factors():
    """Return loaded carbon emission factors (read-only)."""
    return _factors


class ScenarioRequest(BaseModel):
    """Net-zero scenario builder — toggle interventions and project savings."""

    gpu_adoption_pct: float = Field(0.0, ge=0.0, le=1.0, description="0..1, share of stands using GPU instead of APU")
    ev_ground_fleet_pct: float = Field(0.0, ge=0.0, le=1.0, description="0..1, share of GSE replaced with EVs")
    solar_offset_pct: float = Field(0.0, ge=0.0, le=1.0, description="0..1, share of terminal energy from solar")


@router.post("/scenario")
async def carbon_scenario(body: ScenarioRequest):
    """Compute projected emissions if interventions are applied to current totals.

    Returns baseline totals, projected totals, and savings per source.
    """
    totals = get_carbon_totals()
    by_src: dict = dict(totals.get("by_source", {}))
    base_total = sum(by_src.values())

    sc = _factors.get("scenario", {})
    apu_red = sc.get("gpu_apu_reduction_pct", 0.90)
    ev_red = sc.get("ev_ground_reduction_pct", 0.80)
    solar_red = sc.get("solar_terminal_reduction_pct", 0.50)

    projected = dict(by_src)
    saved: dict[str, float] = {}

    apu_save = by_src.get("apu", 0.0) * body.gpu_adoption_pct * apu_red
    projected["apu"] = max(0.0, by_src.get("apu", 0.0) - apu_save)
    saved["apu"] = round(apu_save, 2)

    gv_save = by_src.get("ground_vehicle", 0.0) * body.ev_ground_fleet_pct * ev_red
    projected["ground_vehicle"] = max(0.0, by_src.get("ground_vehicle", 0.0) - gv_save)
    saved["ground_vehicle"] = round(gv_save, 2)

    term_save = by_src.get("terminal", 0.0) * body.solar_offset_pct * solar_red
    projected["terminal"] = max(0.0, by_src.get("terminal", 0.0) - term_save)
    saved["terminal"] = round(term_save, 2)

    proj_total = sum(projected.values())
    return {
        "baseline_kg": round(base_total, 2),
        "projected_kg": round(proj_total, 2),
        "saved_kg": round(base_total - proj_total, 2),
        "saved_pct": round(((base_total - proj_total) / base_total * 100.0) if base_total > 0 else 0.0, 1),
        "by_source_projected": {k: round(v, 2) for k, v in projected.items()},
        "savings_by_source": saved,
        "interventions": body.model_dump(),
    }

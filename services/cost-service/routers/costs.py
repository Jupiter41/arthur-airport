"""REST API router for cost-service."""

import structlog
from fastapi import APIRouter, Query

from db import neo4j as db
from db.queries import (
    daily_pnl,
    flight_cost_breakdown,
    hourly_cost_curve,
    incident_total_cost,
    most_expensive_incidents,
    terminal_pnl,
)
from services.cost_engine import get_running_totals
from services.recommendations import generate_recommendations

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/costs", tags=["costs"])

# Reference to cost rates — set by main.py on startup
_rates: dict = {}


def set_rates(rates: dict) -> None:
    global _rates
    _rates = rates


@router.get("/summary")
async def cost_summary():
    """Running totals: total cost, revenue, net, by category."""
    totals = get_running_totals()
    total_rev = totals.get("total_revenue_eur", 0.0)
    total_cost = totals.get("total_cost_eur", 0.0)
    net = totals.get("net_eur", 0.0)
    margin = round(net / total_rev * 100, 1) if total_rev > 0 else 0.0
    return {
        "sim_time": totals.get("last_updated"),
        "sim_day": totals.get("sim_day", 1),
        "total_cost_eur": round(total_cost, 2),
        "total_revenue_eur": round(total_rev, 2),
        "net_eur": round(net, 2),
        "margin_pct": margin,
        "by_category": totals.get("by_category", {}),
        "eu261_exposure_eur": round(totals.get("eu261_exposure", 0.0), 2),
    }


@router.get("/pnl")
async def get_pnl(day: int = Query(1, ge=1)):
    """Full P&L for a simulated day."""
    if db._driver is None:
        return {"error": "neo4j not connected"}
    raw = await daily_pnl(db._driver, day)
    # Transform to match frontend CostPnL interface
    by_category: dict[str, float] = {}
    total_records = 0
    for entry in raw.get("costs", []):
        by_category[entry["category"]] = entry["total"]
        total_records += entry.get("count", 0)
    for entry in raw.get("revenues", []):
        by_category[entry["category"]] = entry["total"]
        total_records += entry.get("count", 0)
    return {
        "day": raw.get("sim_day", day),
        "total_cost_eur": raw.get("total_cost_eur", 0),
        "total_revenue_eur": raw.get("total_revenue_eur", 0),
        "net_eur": raw.get("net_eur", 0),
        "by_category": by_category,
        "cost_records": total_records,
    }


@router.get("/flight/{flight_id}")
async def get_flight_costs(flight_id: str):
    """All costs for a specific flight."""
    if db._driver is None:
        return {"error": "neo4j not connected"}
    return await flight_cost_breakdown(db._driver, flight_id)


@router.get("/incident/{incident_id}")
async def get_incident_costs(incident_id: str):
    """Total financial impact of an incident."""
    if db._driver is None:
        return {"error": "neo4j not connected"}
    return await incident_total_cost(db._driver, incident_id)


@router.get("/incidents/ranking")
async def get_incident_ranking(day: int = Query(1, ge=1), limit: int = Query(5, ge=1, le=20)):
    """Top incidents by financial impact."""
    if db._driver is None:
        return {"incidents": []}
    raw = await most_expensive_incidents(db._driver, day, limit)
    # Transform field names to match frontend IncidentCostRanking interface
    incidents = []
    for r in raw:
        direct = r.get("direct_cost", 0.0)
        eu261 = r.get("eu261_cost", 0.0)
        incidents.append({
            "incident_id": r.get("id", ""),
            "type": r.get("type", ""),
            "total_eur": round(r.get("total_impact", 0.0), 2),
            "direct_eur": round(direct, 2),
            "response_eur": round(eu261, 2),
        })
    return {"incidents": incidents}


@router.get("/hourly")
async def get_hourly_curve(day: int = Query(1, ge=1)):
    """Cost curve per simulated hour."""
    if db._driver is None:
        return {"hours": []}
    raw = await hourly_cost_curve(db._driver, day)
    # Transform field names to match frontend HourlyCostPoint interface
    hours = []
    for r in raw:
        cost = r.get("cost", 0.0)
        revenue = r.get("revenue", 0.0)
        hours.append({
            "hour": r.get("hour", 0),
            "cost_eur": round(cost, 2),
            "revenue_eur": round(revenue, 2),
            "net_eur": round(revenue - cost, 2),
        })
    return {"hours": hours}


@router.get("/terminal/{terminal_id}")
async def get_terminal_costs(terminal_id: str, day: int = Query(1, ge=1)):
    """P&L per terminal."""
    if db._driver is None:
        return {"error": "neo4j not connected"}
    return await terminal_pnl(db._driver, terminal_id, day)


@router.get("/rates")
async def get_rates():
    """Current cost rate table."""
    return _rates


@router.patch("/rates")
async def update_rates(overrides: dict):
    """Override cost rates at runtime."""
    def _deep_merge(base: dict, update: dict) -> dict:
        for k, v in update.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                _deep_merge(base[k], v)
            else:
                base[k] = v
        return base

    _deep_merge(_rates, overrides)
    # Push updated rates to consumer
    from kafka.consumer import set_rates
    set_rates(_rates)
    logger.info("cost rates updated", keys=list(overrides.keys()))
    return {"status": "updated", "keys": list(overrides.keys())}


@router.get("/recommendations")
async def get_recommendations():
    """Generate financially-aware recommendations."""
    totals = get_running_totals()
    sim_time = totals.get("last_updated", "")
    return generate_recommendations(totals, sim_time, _rates)

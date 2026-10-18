"""REST API router for cost-service."""

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

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
from services import valuation as valuation_engine

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/costs", tags=["costs"])

def _require_neo4j() -> None:
    """Raise 503 if Neo4j is not connected. Use at the top of any DB-backed handler."""
    if db._driver is None:
        raise HTTPException(status_code=503, detail="neo4j not connected")


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
    _require_neo4j()
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
    _require_neo4j()
    return await flight_cost_breakdown(db._driver, flight_id)


@router.get("/incident/{incident_id}")
async def get_incident_costs(incident_id: str):
    """Total financial impact of an incident."""
    _require_neo4j()
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
            "eu261_eur": round(eu261, 2),
            # Legacy field name — same value as eu261_eur, kept for backward compatibility.
            "response_eur": round(eu261, 2),
        })
    return {"incidents": incidents}


@router.get("/hourly")
async def get_hourly_curve(day: int = Query(1, ge=1)):
    """Cost curve per simulated hour — always returns 24 data points (0-23)."""
    if db._driver is None:
        return {"hours": [{"hour": h, "cost_eur": 0.0, "revenue_eur": 0.0, "net_eur": 0.0} for h in range(24)]}
    raw = await hourly_cost_curve(db._driver, day)
    # Build a lookup from actual data
    by_hour: dict[int, dict] = {}
    for r in raw:
        h = r.get("hour", 0)
        cost = r.get("cost", 0.0)
        revenue = r.get("revenue", 0.0)
        by_hour[h] = {
            "hour": h,
            "cost_eur": round(cost, 2),
            "revenue_eur": round(revenue, 2),
            "net_eur": round(revenue - cost, 2),
        }
    # Pad to full 24 hours so the chart always shows a complete day
    hours = []
    for h in range(24):
        if h in by_hour:
            hours.append(by_hour[h])
        else:
            hours.append({"hour": h, "cost_eur": 0.0, "revenue_eur": 0.0, "net_eur": 0.0})
    return {"hours": hours}


@router.get("/terminal/{terminal_id}")
async def get_terminal_costs(terminal_id: str, day: int = Query(1, ge=1)):
    """P&L per terminal."""
    _require_neo4j()
    return await terminal_pnl(db._driver, terminal_id, day)


@router.get("/rates")
async def get_rates():
    """Current cost rate table."""
    _require_neo4j()
    from services import rates
    return await rates.read()


@router.patch("/rates")
async def update_rates(overrides: dict):
    """Override cost rates at runtime.

    Unknown nested fields, invalid types and non-finite/negative amounts return
    HTTP 400 without changing any field. The complete candidate table and its
    outbox event commit together; independent replica updates serialize.
    """
    _require_neo4j()
    from services import rates
    from _common.financial_rates import rates_version
    try:
        committed = await rates.update(overrides)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "updated", "keys": list(overrides), "version": rates_version(committed)}


@router.get("/recommendations")
async def get_recommendations():
    """Generate financially-aware recommendations."""
    totals = get_running_totals()
    sim_time = totals.get("last_updated", "")
    from services import rates
    return generate_recommendations(totals, sim_time, await rates.read())


# ─── Valuation (3B — Airport Valuation Model) ───────────────────


class ValuationSensitivityRequest(BaseModel):
    """Cartesian product of input deltas applied to the day's EBITDA waterfall."""

    day: int = Field(1, ge=1)
    horizon: str = Field("year", pattern="^(day|week|year)$")
    demand_growth: list[float] = Field(
        default_factory=lambda: [-0.10, 0.0, 0.05],
        description="Multiplicative demand deltas applied to all revenue streams.",
    )
    fuel_price_pct: list[float] = Field(
        default_factory=lambda: [-0.30, 0.0, 0.30],
        description="Multiplicative jet-fuel price deltas (informational — pass-through).",
    )
    eu261_rate_pct: list[float] = Field(
        default_factory=lambda: [-0.50, 0.0, 0.50],
        description="Multiplicative EU261 claim-rate deltas (informational — pass-through).",
    )


class ValuationThesisRequest(BaseModel):
    day: int = Field(1, ge=1)
    horizon: str = Field("year", pattern="^(day|week|year)$")
    demand_growth: list[float] = Field(default_factory=lambda: [-0.05, 0.0, 0.05])
    fuel_price_pct: list[float] = Field(default_factory=lambda: [-0.20, 0.20])
    eu261_rate_pct: list[float] = Field(default_factory=lambda: [-0.25, 0.25])


@router.get("/ebitda")
async def get_ebitda(
    day: int = Query(1, ge=1),
    horizon: str = Query("year", pattern="^(day|week|year)$"),
):
    """Revenue + OpEx waterfall and EBITDA for a sim-day, projected over horizon."""
    _require_neo4j()
    pnl = await daily_pnl(db._driver, day)
    return valuation_engine.build_ebitda(pnl, horizon=horizon)  # type: ignore[arg-type]


@router.post("/valuation/sensitivity")
async def post_valuation_sensitivity(body: ValuationSensitivityRequest):
    """EBITDA per scenario across a 3-axis cartesian product."""
    _require_neo4j()
    pnl = await daily_pnl(db._driver, body.day)
    base = valuation_engine.build_ebitda(pnl, horizon=body.horizon)  # type: ignore[arg-type]
    scenarios = valuation_engine.run_sensitivity(
        base,
        demand_growth=body.demand_growth,
        fuel_price_pct=body.fuel_price_pct,
        eu261_rate_pct=body.eu261_rate_pct,
    )
    return {"baseline": base, "scenarios": scenarios}


@router.post("/valuation/thesis")
async def post_valuation_thesis(body: ValuationThesisRequest):
    """Structured investment-case JSON. Dashboards / PDF renderers consume directly."""
    _require_neo4j()
    pnl = await daily_pnl(db._driver, body.day)
    base = valuation_engine.build_ebitda(pnl, horizon=body.horizon)  # type: ignore[arg-type]
    scenarios = valuation_engine.run_sensitivity(
        base,
        demand_growth=body.demand_growth,
        fuel_price_pct=body.fuel_price_pct,
        eu261_rate_pct=body.eu261_rate_pct,
    )
    return valuation_engine.build_thesis(base, scenarios)

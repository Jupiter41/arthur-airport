"""REST API for multi-airport network simulation (Phase 3)."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.network import get_network_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


# ── Request / Response models ─────────────────────────────────────


class GDPDeclareRequest(BaseModel):
    airport_icao: str
    reason: str
    capacity_reduction_pct: float = 0.50


class GDPLiftRequest(BaseModel):
    airport_icao: str


class PropagateDelayRequest(BaseModel):
    flight_number: str
    source_icao: str
    target_icao: str
    delay_minutes: float


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/network/status")
async def network_status():
    """P3-5: Full network status — airport health, delay propagation, active GDPs."""
    engine = get_network_engine()
    if not engine.enabled:
        raise HTTPException(status_code=404, detail="Network simulation is disabled")
    return engine.get_network_status()


@router.get("/network/airports")
async def network_airports():
    """List all airports in the network with current state."""
    engine = get_network_engine()
    if not engine.enabled:
        raise HTTPException(status_code=404, detail="Network simulation is disabled")
    status = engine.get_network_status()
    return {"airports": status["airports"]}


@router.get("/network/airports/{icao}")
async def network_airport_detail(icao: str):
    """Get detailed status for a specific network airport."""
    engine = get_network_engine()
    airport = engine.get_airport(icao.upper())
    if airport is None:
        raise HTTPException(status_code=404, detail=f"Airport {icao} not in network")
    return {
        "icao": airport.icao,
        "iata": airport.iata,
        "name": airport.name,
        "lat": airport.lat,
        "lon": airport.lon,
        "role": airport.role,
        "daily_movements": airport.daily_movements,
        "current_delay_minutes": round(airport.current_delay_minutes, 1),
        "disruption_level": airport.disruption_level,
        "gdp_active": airport.gdp_active,
        "gdp_departure_rate_pct": round(airport.gdp_departure_rate_pct, 2),
        "recovery_eta_minutes": round(airport.recovery_eta_minutes, 1),
    }


@router.get("/network/arcs")
async def network_arcs():
    """P3-3: Arc data for network map visualization."""
    engine = get_network_engine()
    if not engine.enabled:
        raise HTTPException(status_code=404, detail="Network simulation is disabled")
    return {"arcs": engine.get_airport_pairs_for_map()}


@router.get("/network/gdps")
async def network_gdps():
    """P3-4: List all active Ground Delay Programs."""
    engine = get_network_engine()
    return {"gdps": [
        {
            "airport_icao": g.airport_icao,
            "start_time": g.start_time,
            "reason": g.reason,
            "capacity_reduction_pct": g.capacity_reduction_pct,
            "affected_feeder_airports": g.affected_feeder_airports,
            "departure_rate_pct": g.departure_rate_pct,
        }
        for g in engine.get_active_gdps()
    ]}


@router.post("/network/gdp/declare")
async def declare_gdp(req: GDPDeclareRequest):
    """P3-4: Manually declare a GDP at a specific airport."""
    engine = get_network_engine()
    gdp = engine.declare_gdp(
        airport_icao=req.airport_icao.upper(),
        reason=req.reason,
        capacity_reduction_pct=req.capacity_reduction_pct,
    )
    if gdp is None:
        raise HTTPException(status_code=404, detail=f"Airport {req.airport_icao} not in network")
    return {
        "declared": True,
        "airport_icao": gdp.airport_icao,
        "departure_rate_pct": gdp.departure_rate_pct,
    }


@router.post("/network/gdp/lift")
async def lift_gdp(req: GDPLiftRequest):
    """Manually lift a GDP."""
    engine = get_network_engine()
    success = engine.lift_gdp(req.airport_icao.upper())
    if not success:
        raise HTTPException(status_code=404, detail=f"No active GDP at {req.airport_icao}")
    return {"lifted": True, "airport_icao": req.airport_icao.upper()}


@router.get("/network/propagations")
async def network_propagations():
    """Get recent delay propagation log."""
    engine = get_network_engine()
    status = engine.get_network_status()
    return {"propagations": status["recent_propagations"]}


@router.post("/network/propagate")
async def propagate_delay(req: PropagateDelayRequest):
    """Manually propagate a delay (for testing/debugging)."""
    engine = get_network_engine()
    propagated = engine.propagate_delay(
        flight_number=req.flight_number,
        source_icao=req.source_icao.upper(),
        target_icao=req.target_icao.upper(),
        delay_minutes=req.delay_minutes,
    )
    return {
        "propagated": propagated > 0,
        "propagated_delay_minutes": round(propagated, 1),
    }

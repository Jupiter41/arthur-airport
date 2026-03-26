"""REST API router for flight-service."""

import logging

from fastapi import APIRouter, HTTPException, Query

from db.neo4j import (
    get_all_flights,
    get_flight_by_id,
    get_all_runways,
    get_all_gates,
    get_cascade_info,
)
from kafka.consumer import (
    hold_flight,
    release_flight,
    get_sim_time,
    get_runway_queue,
    get_turnaround_plan,
)
from models.domain import HoldRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


@router.get("/flights")
async def list_flights(
    status: str | None = Query(None, description="Filter by status (comma-separated)"),
    direction: str | None = Query(None, description="arrival or departure"),
    airline: str | None = Query(None, description="2-letter airline code"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List all flights for the current simulated day."""
    sim_time = get_sim_time()
    sim_date_prefix = sim_time.date().isoformat() if sim_time else None

    flights, total = await get_all_flights(
        status=status,
        direction=direction,
        airline=airline,
        sim_date_prefix=sim_date_prefix,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "flights": flights,
    }


@router.get("/flights/{flight_id}")
async def get_flight(flight_id: str):
    """Full flight detail including gate, runway, and turnaround info."""
    flight = await get_flight_by_id(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    # Attach turnaround progress if an active plan exists for this aircraft
    reg = flight.get("aircraft_registration", "")
    if reg:
        plan = get_turnaround_plan(reg)
        if plan:
            flight["turnaround"] = plan.to_dict()
    return flight


@router.get("/flights/{flight_id}/cascade")
async def get_flight_cascade(flight_id: str):
    """Returns the full cascade tree of effects for a delayed/cancelled flight."""
    flight = await get_flight_by_id(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")

    cascade = await get_cascade_info(flight_id)

    return {
        "flight_id": flight_id,
        "flight_number": flight.get("flight_number", ""),
        "delay_minutes": flight.get("delay_minutes", 0),
        "cascade": cascade,
    }


@router.get("/runways")
async def list_runways():
    """Current runway status with queue counts."""
    runways = await get_all_runways()
    rq = get_runway_queue()

    # Augment with in-memory queue counts and capacity
    for rw in runways:
        rw["arrivals_queued"] = max(int(rw.get("arrivals_queued") or 0), rq.arrivals_queued)
        rw["departures_queued"] = max(int(rw.get("departures_queued") or 0), rq.departures_queued)
        rw["capacity_per_hour"] = rq.capacity_per_hour
        observed = rw["arrivals_queued"] + rw["departures_queued"]
        rw["current_rate"] = max(int(rq.current_rate), int(observed))
        rw["runway_id"] = rw.get("id", "")
    return runways


@router.get("/gates")
async def list_gates(
    terminal: str | None = Query(None, description="Filter by terminal (A, B, C)"),
):
    """All gate statuses."""
    terminal_id = f"T-{terminal}" if terminal and not terminal.startswith("T-") else terminal
    gates = await get_all_gates(terminal=terminal_id)
    return {"gates": gates}


@router.post("/flights/{flight_id}/hold")
async def hold_flight_endpoint(flight_id: str, request: HoldRequest):
    """Manually place a flight on hold."""
    sim_time = get_sim_time()
    if not sim_time:
        raise HTTPException(status_code=503, detail="Simulation not running")

    flight = await get_flight_by_id(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")

    status = flight.get("status", "")
    if status not in ("boarding", "scheduled", "approach"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot hold flight in status '{status}'",
        )

    updated = await hold_flight(
        flight_id=flight_id,
        reason=request.reason,
        duration_min=request.expected_duration_minutes,
        sim_time=sim_time,
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to hold flight")
    return updated


@router.post("/flights/{flight_id}/release")
async def release_flight_endpoint(flight_id: str):
    """Release a manually held flight."""
    sim_time = get_sim_time()
    if not sim_time:
        raise HTTPException(status_code=503, detail="Simulation not running")

    flight = await get_flight_by_id(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")

    if flight.get("status") != "delayed":
        raise HTTPException(
            status_code=400,
            detail="Flight is not currently delayed/held",
        )

    updated = await release_flight(flight_id=flight_id, sim_time=sim_time)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to release flight")
    return updated


@router.get("/turnarounds")
async def list_turnarounds():
    """List all active turnaround plans (for ground ops dashboard)."""
    from kafka.consumer import _state
    plans = []
    for reg, plan in _state.turnaround_plans.items():
        plans.append(plan.to_dict())
    return {"turnarounds": plans, "total": len(plans)}

"""Slot allocation & coordination REST API (2B — ROADMAP_USECASE.md).

Endpoints:
- POST /api/v1/planning/slots/allocate
- POST /api/v1/planning/slots/compress
- POST /api/v1/planning/slots/compare
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from engine.slots import (
    SlotRequest,
    allocate_fcfs,
    allocate_optimised,
    allocate_priority,
    compare_strategies,
    find_compression_opportunities,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/planning/slots", tags=["slots"])


# ── Request models ──────────────────────────────────────────


class SlotRequestPayload(BaseModel):
    id: str = Field(..., description="Unique request identifier")
    airline: str = Field(..., description="Airline IATA code")
    requested_hour: int = Field(..., ge=0, le=23, description="Requested departure/arrival hour")
    requested_minute: int = Field(0, ge=0, le=59)
    aircraft_type: str = Field("A320", description="Aircraft ICAO type designator")
    priority: int = Field(1, ge=1, le=3, description="1=standard, 2=medium, 3=high")
    direction: str = Field("departure", pattern=r"^(departure|arrival)$")


class AllocateRequest(BaseModel):
    requests: list[SlotRequestPayload] = Field(
        ..., min_length=1, max_length=1000,
        description="Slot requests to allocate",
    )
    strategy: str = Field(
        "optimised",
        pattern=r"^(fcfs|priority_weighted|optimised)$",
        description="Allocation strategy",
    )
    hourly_capacity: int = Field(60, ge=10, le=200, description="Max movements per hour")


class CompressRequest(BaseModel):
    schedule: list[dict] = Field(
        ..., min_length=1, max_length=2000,
        description="Flight schedule (list of flight dicts with scheduled_departure)",
    )
    hourly_capacity: int = Field(60, ge=10, le=200)
    shift_limit_minutes: int = Field(15, ge=5, le=60)


class CompareRequest(BaseModel):
    requests: list[SlotRequestPayload] = Field(
        ..., min_length=1, max_length=1000,
    )
    hourly_capacity: int = Field(60, ge=10, le=200)


# ── Endpoints ───────────────────────────────────────────────


@router.post("/allocate")
async def allocate_slots(body: AllocateRequest):
    """Allocate slot requests using the specified strategy.

    Strategies:
    - ``fcfs``: First-Come-First-Served (baseline)
    - ``priority_weighted``: High-priority requests get first pick
    - ``optimised``: ILP minimising total displacement (requires PuLP)
    """
    requests = [
        SlotRequest(
            id=r.id,
            airline=r.airline,
            requested_hour=r.requested_hour,
            requested_minute=r.requested_minute,
            aircraft_type=r.aircraft_type,
            priority=r.priority,
            direction=r.direction,
        )
        for r in body.requests
    ]

    match body.strategy:
        case "fcfs":
            result = allocate_fcfs(requests, body.hourly_capacity)
        case "priority_weighted":
            result = allocate_priority(requests, body.hourly_capacity)
        case "optimised":
            try:
                result = allocate_optimised(requests, body.hourly_capacity)
            except ImportError as e:
                raise HTTPException(status_code=501, detail=str(e))
        case _:
            raise HTTPException(status_code=400, detail=f"Unknown strategy: {body.strategy}")

    return result.to_dict()


@router.post("/compress")
async def compress_schedule(body: CompressRequest):
    """Identify flights that can be shifted ±N minutes to smooth demand peaks.

    Returns a list of compression opportunities with suggested time shifts
    and expected throughput gains.
    """
    opportunities = find_compression_opportunities(
        body.schedule,
        hourly_capacity=body.hourly_capacity,
        shift_limit_minutes=body.shift_limit_minutes,
    )

    return {
        "total_opportunities": len(opportunities),
        "shift_limit_minutes": body.shift_limit_minutes,
        "hourly_capacity": body.hourly_capacity,
        "opportunities": [
            {
                "flight_number": o.flight_number,
                "airline": o.airline,
                "current_time": f"{o.current_hour:02d}:{o.current_minute:02d}",
                "suggested_time": f"{o.suggested_hour:02d}:{o.suggested_minute:02d}",
                "shift_minutes": o.shift_minutes,
                "reason": o.reason,
                "throughput_gain_pct": o.throughput_gain_pct,
            }
            for o in opportunities
        ],
    }


@router.post("/compare")
async def compare_allocation_strategies(body: CompareRequest):
    """Run all three allocation strategies and return side-by-side comparison.

    Useful for evaluating the benefit of ILP optimisation vs simpler strategies.
    """
    requests = [
        SlotRequest(
            id=r.id,
            airline=r.airline,
            requested_hour=r.requested_hour,
            requested_minute=r.requested_minute,
            aircraft_type=r.aircraft_type,
            priority=r.priority,
            direction=r.direction,
        )
        for r in body.requests
    ]

    return compare_strategies(requests, body.hourly_capacity)

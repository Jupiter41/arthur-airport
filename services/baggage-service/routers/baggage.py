"""REST API router for baggage-service.

Base path: /api/v1
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db.neo4j import (
    get_all_baggage,
    get_baggage_by_id,
    get_baggage_by_tag,
    get_baggage_counts_by_status,
    get_flagged_baggage,
)
from kafka.consumer import get_sim_time, get_conveyor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


@router.get("/baggage")
async def list_baggage(
    flight_id: Optional[str] = Query(None),
    passenger_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="Comma-separated status filter"),
    flagged: Optional[bool] = Query(None),
    zone: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items, total = await get_all_baggage(
        flight_id=flight_id,
        passenger_id=passenger_id,
        status=status,
        flagged=flagged,
        zone=zone,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "items": items}


@router.get("/baggage/conveyor-status")
async def conveyor_status():
    """Overall conveyor system status — used by integration tests and dashboard."""
    conveyor = get_conveyor()
    sim_time = get_sim_time()
    zones = conveyor.get_zone_summary()
    total_in_system = sum(z.get("items", 0) for z in zones)
    return {
        "sim_time": sim_time.isoformat() if sim_time else None,
        "total_in_system": total_in_system,
        "zones": zones,
    }


@router.get("/baggage/tag/{tag}")
async def get_baggage_by_tag_endpoint(tag: str):
    bag = await get_baggage_by_tag(tag)
    if not bag:
        raise HTTPException(status_code=404, detail="Baggage tag not found")
    return bag


@router.get("/baggage/{baggage_id}")
async def get_baggage_detail(baggage_id: str):
    bag = await get_baggage_by_id(baggage_id)
    if not bag:
        raise HTTPException(status_code=404, detail="Baggage not found")
    return bag


@router.get("/flow/summary")
async def flow_summary():
    sim_time = get_sim_time()
    conveyor = get_conveyor()

    by_status = await get_baggage_counts_by_status()

    # Compute total in system (exclude terminal states)
    terminal_states = {"collected", "lost"}
    total_in_system = sum(
        v for k, v in by_status.items() if k not in terminal_states
    )

    # Get flagged count
    flagged_active = by_status.get("flagged", 0)

    # Get zone info from conveyor
    zones = conveyor.get_zone_summary()
    system_failures = conveyor.get_system_failures_count()

    return {
        "sim_time": sim_time.isoformat() if sim_time else None,
        "total_in_system": total_in_system,
        "by_status": by_status,
        "flagged_active": flagged_active,
        "system_failures_active": system_failures,
        "zones": zones,
    }


@router.get("/flow/map")
async def flow_map():
    conveyor = get_conveyor()
    zones = conveyor.get_zone_summary()
    return {"zones": zones}


@router.get("/flagged")
async def list_flagged():
    items = await get_flagged_baggage()
    flagged = []
    for item in items:
        flagged.append({
            "id": item.get("id"),
            "tag": item.get("tag"),
            "passenger_name": item.get("passenger_name"),
            "flight_number": item.get("flight_number"),
            "flag_reason": item.get("flag_reason"),
            "dg_class": item.get("dg_class"),
            "current_zone": item.get("last_scan_zone"),
            "flagged_at": item.get("flagged_at"),
            "review_status": item.get("review_status", "pending"),
        })
    return {"flagged": flagged}

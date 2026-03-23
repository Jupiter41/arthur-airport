"""REST control API for sim-orchestrator."""

import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services import clock
from services.schedule import get_schedule_from_neo4j
from kafka.producer import emit_inject_incident
from db.neo4j import get_driver

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

VALID_SPEEDS = {1, 10, 60, 600, 3600}


# ── Request/Response models ─────────────────────────────────────


class SpeedRequest(BaseModel):
    speed_multiplier: int


class ResetRequest(BaseModel):
    confirm: bool


class InjectRequest(BaseModel):
    type: str
    severity: str
    location: str
    description: Optional[str] = None


class StatusResponse(BaseModel):
    running: bool
    paused: bool
    sim_time: str
    real_time: str
    speed_multiplier: int
    day_number: int
    tick_number: int
    real_elapsed_seconds: int = 0
    sim_elapsed_minutes: int = 0
    active_incidents: int = 0
    weather_category: str = "CAVOK"
    flights_today: int = 0
    passengers_today: int = 0


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/sim/status")
async def sim_status():
    state = clock.get_state()
    # Get flight/passenger counts from Neo4j
    flights_today = 0
    passengers_today = 0
    try:
        driver = get_driver()
        async with driver.session() as session:
            sim_date = clock.get_sim_time().date().isoformat()
            result = await session.run(
                "MATCH (f:Flight) WHERE f.scheduled_time STARTS WITH $prefix RETURN count(f) AS cnt",
                prefix=sim_date,
            )
            record = await result.single()
            if record:
                flights_today = record["cnt"]

            result = await session.run(
                "MATCH (p:Passenger) RETURN count(p) AS cnt"
            )
            record = await result.single()
            if record:
                passengers_today = record["cnt"]
    except Exception:
        pass

    return {
        "running": state["running"],
        "paused": state["paused"],
        "sim_time": state["sim_time"],
        "real_time": state["real_time"],
        "speed_multiplier": state["speed_multiplier"],
        "day_number": state["day_number"],
        "tick_number": state["tick_number"],
        "real_elapsed_seconds": state["tick_number"],
        "sim_elapsed_minutes": state["tick_number"],
        "active_incidents": 0,
        "weather_category": "CAVOK",
        "flights_today": flights_today,
        "passengers_today": passengers_today,
    }


@router.patch("/sim/speed")
async def sim_speed(req: SpeedRequest):
    if req.speed_multiplier not in VALID_SPEEDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid speed. Valid values: {sorted(VALID_SPEEDS)}",
        )
    clock.set_speed(req.speed_multiplier)
    return await sim_status()


@router.post("/sim/pause")
async def sim_pause():
    clock.pause()
    return {"paused": True, "sim_time": clock.get_sim_time().isoformat()}


@router.post("/sim/resume")
async def sim_resume():
    clock.resume()
    return {"paused": False, "sim_time": clock.get_sim_time().isoformat()}


@router.post("/sim/reset")
async def sim_reset(req: ResetRequest):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true")

    clock.pause()

    # Wipe all data from Neo4j in batches
    try:
        driver = get_driver()
        deleted = True
        while deleted:
            async with driver.session() as session:
                result = await session.run(
                    "MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(*) AS cnt"
                )
                record = await result.single()
                deleted = record and record["cnt"] > 0
        logger.info("Neo4j data wiped for reset")
    except Exception as e:
        logger.error("Error wiping Neo4j: %s", e)
        raise HTTPException(status_code=500, detail="Reset failed during Neo4j wipe")

    clock.reset_to_start()

    # Re-seed (import here to avoid circular deps)
    from db.seed import seed_airport_structure
    from db.neo4j import create_constraints_and_indexes
    from services.seeder import seed_day

    await create_constraints_and_indexes()
    await seed_airport_structure()
    await seed_day(sim_day=1)

    clock.resume()
    return {"reset": True, "new_sim_time": clock.get_sim_time().isoformat()}


@router.post("/sim/inject", status_code=201)
async def sim_inject(req: InjectRequest):
    sim_time = clock.get_sim_time()
    emit_inject_incident(
        sim_time=sim_time,
        incident_type=req.type,
        severity=req.severity,
        location=req.location,
        trigger="manual",
        description=req.description,
    )
    return {"injected": True, "type": req.type, "sim_time": sim_time.isoformat()}


@router.get("/sim/schedule")
async def sim_schedule(
    terminal: Optional[str] = None,
    direction: Optional[str] = None,
    status: Optional[str] = None,
):
    sim_date = clock.get_sim_time().date()
    flights = await get_schedule_from_neo4j(sim_date)

    if terminal:
        flights = [f for f in flights if f.get("gate_id", "").startswith(terminal)]
    if direction:
        flights = [f for f in flights if f.get("direction") == direction]
    if status:
        flights = [f for f in flights if f.get("status") == status]

    return {
        "sim_day": clock.get_sim_day(),
        "sim_date": sim_date.isoformat(),
        "total_flights": len(flights),
        "flights": flights,
    }


@router.get("/sim/metrics")
async def sim_metrics():
    latencies = clock.get_tick_latencies()
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    p99_latency = sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0

    return {
        "tick_latency_ms_avg": round(avg_latency, 1),
        "tick_latency_ms_p99": round(p99_latency, 1),
        "kafka_produce_lag_ms": 0,
        "neo4j_write_latency_ms_avg": 0,
        "events_produced_total": clock.get_events_produced(),
        "missed_ticks": 0,
        "sim_time_drift_ms": 0,
    }

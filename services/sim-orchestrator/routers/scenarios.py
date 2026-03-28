"""REST API for scenario management."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from models.scenario import ScenarioDefinition

from services import clock
from services.scenario_engine import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


class RunScenarioRequest(BaseModel):
    speed: Optional[int] = None  # override sim speed for this run


class ForkScenarioRequest(BaseModel):
    name: str


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/scenarios")
async def list_scenarios():
    """List all available scenario definitions."""
    engine = get_engine()
    return {"scenarios": engine.list_scenarios()}


@router.post("/scenarios", status_code=201)
async def create_scenario(definition: ScenarioDefinition):
    """Create a custom scenario definition."""
    engine = get_engine()
    try:
        created = engine.create_definition(definition)
        return {"created": True, "scenario": engine.get_definition_payload(created.name)}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put("/scenarios/{name}")
async def update_scenario(name: str, definition: ScenarioDefinition):
    """Update one custom scenario definition."""
    engine = get_engine()
    try:
        updated = engine.update_definition(name, definition)
        return {"updated": True, "scenario": engine.get_definition_payload(updated.name)}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/scenarios/{name}")
async def delete_scenario(name: str):
    """Delete one custom scenario definition."""
    engine = get_engine()
    try:
        engine.delete_definition(name)
        return {"deleted": True, "name": name}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/scenarios/{name}/fork", status_code=201)
async def fork_scenario(name: str, req: ForkScenarioRequest):
    """Fork a scenario to a new custom scenario name."""
    engine = get_engine()
    try:
        forked = engine.fork_definition(name, req.name)
        return {"created": True, "scenario": engine.get_definition_payload(forked.name)}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/scenarios/active")
async def get_active_scenario():
    """Get the currently active scenario run with live metrics."""
    engine = get_engine()
    run = engine.get_active_run()
    if run is None:
        return {"active": False}

    return {
        "active": True,
        "run_id": run.run_id,
        "scenario_name": run.scenario_name,
        "status": run.status.value,
        "events_injected": run.events_injected,
        "snapshots_collected": len(run.metric_snapshots),
        "latest_metrics": run.metric_snapshots[-1].model_dump() if run.metric_snapshots else None,
        "sim_time": clock.get_sim_time().isoformat(),
    }


@router.post("/scenarios/active/stop")
async def stop_active_scenario():
    """Stop the currently active scenario run."""
    engine = get_engine()
    if not engine.is_active():
        raise HTTPException(status_code=409, detail="No active scenario to stop")

    result = engine.stop_run()
    if result is None:
        raise HTTPException(status_code=500, detail="Failed to stop scenario")

    return {
        "stopped": True,
        "run_id": result.run_id,
        "status": result.status.value,
        "summary": result.summary,
    }


@router.get("/scenarios/results")
async def list_results():
    """List all past scenario run results."""
    engine = get_engine()
    return {"results": engine.get_past_results()}


@router.get("/scenarios/results/{run_id}")
async def get_result(run_id: str):
    """Get detailed result of a specific scenario run."""
    engine = get_engine()
    result = engine.get_result(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return result.model_dump()


@router.get("/scenarios/{name}")
async def get_scenario(name: str):
    """Get a specific scenario definition."""
    engine = get_engine()
    payload = engine.get_definition_payload(name)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Scenario '{name}' not found")
    return payload


@router.post("/scenarios/{name}/run", status_code=201)
async def run_scenario(name: str, req: Optional[RunScenarioRequest] = None):
    """Start a scenario run.

    This resets the simulation, applies seed overrides, and begins
    executing the scenario's event timeline.
    """
    engine = get_engine()

    defn = engine.get_definition(name)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Scenario '{name}' not found")

    if engine.is_active():
        raise HTTPException(status_code=409, detail="A scenario is already running")

    # Pause the clock while we reset
    clock.pause()

    # Reset simulation
    try:
        from db.neo4j import get_driver, create_constraints_and_indexes
        from db.seed import seed_airport_structure
        from services.seeder import seed_day, emit_initial_weather

        # Wipe Neo4j
        driver = get_driver()
        deleted = True
        while deleted:
            async with driver.session() as session:
                result = await session.run(
                    "MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(*) AS cnt"
                )
                record = await result.single()
                deleted = record and record["cnt"] > 0

        clock.reset_to_start()
        await create_constraints_and_indexes()
        await seed_airport_structure()

        # Apply seed overrides
        weather = "CAVOK"
        if defn.seed_overrides:
            if defn.seed_overrides.weather:
                weather = defn.seed_overrides.weather.value
            # daily_flights and load_factor overrides applied via env-like state
            # For now they flow through the standard seeding with default parameters

        await seed_day(sim_day=1)
        await emit_initial_weather(category=weather)

    except Exception as e:
        clock.resume()
        logger.error("Failed to reset for scenario: %s", e)
        raise HTTPException(status_code=500, detail=f"Reset failed: {e}")

    # Set speed
    speed = defn.sim_speed
    if req and req.speed:
        speed = req.speed
    clock.set_speed(speed)

    # Start the scenario run
    sim_time = clock.get_sim_time()
    try:
        run = engine.start_run(name, sim_time)
    except ValueError as e:
        clock.resume()
        raise HTTPException(status_code=409, detail=str(e))

    # Resume the clock
    clock.resume()

    return {
        "started": True,
        "run_id": run.run_id,
        "scenario_name": name,
        "speed": speed,
        "sim_time": sim_time.isoformat(),
        "duration_sim_minutes": defn.duration_sim_minutes,
    }

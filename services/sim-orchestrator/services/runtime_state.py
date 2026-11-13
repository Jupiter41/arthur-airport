"""Neo4j checkpoint for the shared simulation's clock and operator settings."""
import json
import asyncio
from datetime import datetime

from db.neo4j import get_driver
from services import clock
from services.settings import get_settings, update_settings
from kafka.producer import produce_event

_lock = asyncio.Lock()


async def checkpoint(*, command: str | None = None) -> None:
    async with _lock:
        await _write_checkpoint(command=command)


async def _write_checkpoint(*, command: str | None = None) -> None:
    state = clock.get_state()
    settings = get_settings().model_dump()
    try:
        async with get_driver().session() as session:
            await session.run(
                "MERGE (s:SimState {id: 'airport'}) "
                "SET s.sim_time=$sim_time, s.day_number=$day, s.tick_number=$tick, "
                "s.speed_multiplier=$speed, s.paused=$paused, s.settings_json=$settings",
                sim_time=state["sim_time"], day=state["day_number"],
                tick=state["tick_number"], speed=state["speed_multiplier"],
                paused=state["paused"], settings=json.dumps(settings),
            )
    except Exception:
        clock.pause()
        raise
    if command:
        produce_event(topic="sim.clock", event_type="SimControlChanged",
                      sim_time=clock.get_sim_time(), key="control",
                      payload={"command": command, "paused": state["paused"],
                               "speed_multiplier": state["speed_multiplier"],
                               "settings": settings})


async def restore() -> bool:
    async with get_driver().session() as session:
        result = await session.run("MATCH (s:SimState {id: 'airport'}) RETURN properties(s) AS state")
        record = await result.single()
    if not record:
        return False
    state = record["state"]
    update_settings(json.loads(state["settings_json"]))
    clock.restore_state(datetime.fromisoformat(state["sim_time"]),
                        int(state["day_number"]), int(state["tick_number"]),
                        int(state["speed_multiplier"]))
    if state["paused"]:
        clock.pause()
    else:
        clock.resume()
    return True

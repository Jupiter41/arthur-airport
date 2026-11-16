"""Neo4j checkpoint for the shared simulation's clock and operator settings."""
import json
import asyncio
import logging
from datetime import datetime, timezone

from db.neo4j import get_driver
from services import clock
from services.settings import get_settings, update_settings
from kafka.producer import produce_event

_lock = asyncio.Lock()
logger = logging.getLogger(__name__)

# A clock checkpoint is retried on transient database errors before the
# simulation is paused. One lock timeout or a briefly exhausted transaction
# memory pool must not stop the whole airport until an operator resumes it.
CHECKPOINT_RETRY_DELAYS_S = (0.2, 0.5, 1.0, 2.0)


def _is_transient(exc: BaseException) -> bool:
    try:
        from neo4j.exceptions import ServiceUnavailable, SessionExpired, TransientError
    except ImportError:  # pragma: no cover - driver always present in the service
        return False
    return isinstance(exc, (TransientError, ServiceUnavailable, SessionExpired))


def legacy_clock_bound(values: list[dict], start: datetime) -> datetime | None:
    """Recorded progress only: future timetables are not clock evidence."""
    def utc(value) -> datetime | None:
        try:
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except (ValueError, TypeError):
            return None

    floor = utc(start)
    candidates = [parsed for row in values if (parsed := utc(row.get("at"))) is not None]
    latest = max(candidates, default=floor)
    return latest if latest > floor else None


async def _restore_legacy() -> bool:
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (f:Flight) WHERE f.actual_time IS NOT NULL AND f.actual_time <> '' "
            "RETURN DISTINCT f.actual_time AS at "
            "UNION ALL MATCH (p:PassengerRuntime {id:'latest'}) RETURN p.last_tick_sim_time AS at "
            "UNION ALL MATCH (b:BaggageOutboxSeq {id:'latest'}) RETURN b.last_tick_sim_time AS at"
        )
        rows = await result.data()
    recovered = legacy_clock_bound(rows, clock.SIM_START_TIME)
    if recovered is None:
        return False
    start = clock.SIM_START_TIME.replace(tzinfo=None)
    if clock.SIM_START_TIME.tzinfo is not None:
        start = clock.SIM_START_TIME.astimezone(timezone.utc).replace(tzinfo=None)
    day = (recovered.date() - start.date()).days + 1
    tick = max(0, int((recovered - start).total_seconds() // 60))
    clock.restore_state(recovered, day, tick, clock.get_speed())
    clock.pause()
    await checkpoint(command="legacy_clock_recovered")
    logger.warning("Recovered legacy airport clock at %s (day %s); paused for verification", recovered, day)
    return True


async def checkpoint(*, command: str | None = None) -> None:
    async with _lock:
        await _write_checkpoint(command=command)


async def _write_checkpoint(*, command: str | None = None) -> None:
    state = clock.get_state()
    settings = get_settings().model_dump()
    delays = iter(CHECKPOINT_RETRY_DELAYS_S)
    while True:
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
            break
        except Exception as exc:
            delay = next(delays, None) if _is_transient(exc) else None
            if delay is None:
                clock.pause()
                raise
            logger.warning("Clock checkpoint transient failure; retrying in %.1fs", delay,
                           exc_info=True)
            await asyncio.sleep(delay)
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
        return await _restore_legacy()
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

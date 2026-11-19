import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from db.neo4j import (
    check_neo4j,
    close_neo4j,
    create_constraints_and_indexes,
    wait_for_neo4j,
)
from db.seed import airport_exists, seed_airport_structure
from kafka.producer import (
    check_kafka,
    close_kafka_producer,
    init_kafka_producer,
    wait_for_kafka,
)
from kafka.consumer import init_kafka_consumer, start_consumer, stop_consumer
from routers.sim import router as sim_router
from routers.scenarios import router as scenarios_router
from routers.debug import router as debug_router
from routers.network import router as network_router
from services.airport_config import load_airport_runtime_config
from services import clock
from services.fixtures import load_fixtures
from services.injector import set_seed
from services.network import get_network_engine, reset_network_engine
from services.scenario_engine import get_engine
from services.seeder import emit_initial_weather, seed_day
from services.runtime_state import checkpoint, restore

from _common._logging import setup_logging

setup_logging("sim-orchestrator")

logger = logging.getLogger("sim-orchestrator")


async def _on_hour_boundary(sim_time):
    """Clock callback fired every simulated hour.

    Probabilistic incident injection is handled by incident-service
    (which has weather-aware probability modifiers). The orchestrator
    only injects incidents via scenarios or manual API triggers.
    """
    logger.debug("Hour boundary reached: %s", sim_time)


_seed_task: asyncio.Task | None = None


async def _on_day_boundary(next_day: int, sim_time):
    """Clock callback fired at 23:30 — seeds next day's flights, passengers, and baggage.

    Seeding (~70k passengers, ~100k bags, ~15 s) runs in the background so the
    clock keeps ticking; ``_on_day_start`` waits for it at midnight only if it
    has not finished, which only happens at high simulation speeds.
    """
    global _seed_task
    if _seed_task is not None and not _seed_task.done():
        await _seed_task
    _seed_task = asyncio.create_task(seed_day(sim_day=next_day), name=f"seed-day-{next_day}")


async def _on_day_start(new_day: int, sim_time):
    """Midnight barrier: the new day's schedule must exist before its first tick."""
    global _seed_task
    task, _seed_task = _seed_task, None
    if task is None:
        # Retry an already-consumed failed barrier on operator resume.
        await seed_day(sim_day=new_day)
        return
    if not task.done():
        logger.info("Waiting for day %d seeding to finish before its first tick", new_day)
    try:
        await task
    except Exception:
        logger.exception("Background seeding of day %d failed; retrying inline", new_day)
        await seed_day(sim_day=new_day)


async def _on_tick(sim_time):
    """Clock callback fired every sim-minute — drives the scenario engine and network."""
    engine = get_engine()
    await engine.on_tick(sim_time)
    # Tick the network engine for delay recovery and GDP evaluation
    net = get_network_engine()
    net.on_tick(sim_time)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager for sim-orchestrator.

    Startup sequence:
        1. Load fixture data (airlines, destinations, aircraft types)
        2. Connect Neo4j & Kafka
        3. Seed airport structure (terminals, gates, runways)
        4. Seed Day 1 schedule + passengers + baggage
        5. Emit initial CAVOK weather
        6. Start the virtual clock loop
    """
    # 0. Load and validate airport config
    runtime = load_airport_runtime_config()
    logger.info(
        "Airport config loaded: %s (%s/%s)",
        runtime.identity.name,
        runtime.identity.iata,
        runtime.identity.icao,
    )

    # 1. Load fixtures
    load_fixtures()

    # 1b. Load BTS calibration data (calibrates schedule & passenger generation)
    from services.bts_calibration import load_bts_calibration
    bts = load_bts_calibration()
    if bts.loaded:
        logger.info(
            "BTS calibration active: %d routes, global LF=%.3f",
            bts.total_routes, bts.global_load_factor,
        )
    else:
        logger.info("BTS calibration not available — using default simulation parameters")

    # 2. Wait for Neo4j
    await wait_for_neo4j(max_attempts=12, delay_s=5)

    # 3. Wait for Kafka
    await wait_for_kafka(max_attempts=12, delay_s=5)

    # 4. Initialize Kafka producer
    init_kafka_producer()

    # 5. Create constraints and indexes
    await create_constraints_and_indexes()

    # 6. Seed airport structure if not already present
    if not await airport_exists():
        await seed_airport_structure()

    # Resume the shared airport instead of rewinding it on container restart.
    restored = await restore()
    await seed_day(sim_day=clock.get_sim_day())

    # 8. Emit initial weather
    if not restored:
        await emit_initial_weather()
        await checkpoint(command="initialize")

    # 9. Configure clock callbacks and start loop
    set_seed(42)
    clock.configure_callbacks(
        on_hour=_on_hour_boundary,
        on_day=_on_day_boundary,
        on_tick=_on_tick,
        on_checkpoint=checkpoint,
        on_day_start=_on_day_start,
    )

    # 10. Load scenario definitions
    engine = get_engine()
    engine.load_definitions()

    # 11. Initialize network engine and consumer for delay propagation
    net_engine = get_network_engine()
    if net_engine.enabled:
        logger.info("Network simulation enabled: %s (%d airports)",
                     net_engine.config.name, len(net_engine.config.airports))
        init_kafka_consumer()
        start_consumer()

    # RC4: follow owner tick watermarks for clock back-pressure.
    from services import watermark
    watermark_stop = asyncio.Event()
    watermark_task = asyncio.create_task(watermark.run_consumer(watermark_stop))

    clock_task = asyncio.create_task(clock.run_clock_loop())

    def _clock_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("clock loop crashed", exc_info=exc)

    clock_task.add_done_callback(_clock_done)

    logger.info("sim-orchestrator startup complete — clock running")
    yield

    # Shutdown
    clock.stop()
    watermark_stop.set()
    watermark_task.cancel()
    clock_task.cancel()
    try:
        await clock_task
    except asyncio.CancelledError:
        pass
    await checkpoint()
    stop_consumer()
    close_kafka_producer()
    reset_network_engine()
    await close_neo4j()
    from _common._tracing import shutdown_tracing
    shutdown_tracing()
    logger.info("sim-orchestrator shutdown complete")


app = FastAPI(title="sim-orchestrator", lifespan=lifespan)

from _common._tracing import init_tracing  # noqa: E402
init_tracing(app, "sim-orchestrator")

Instrumentator().instrument(app).expose(app)

app.include_router(sim_router)
app.include_router(scenarios_router)
app.include_router(debug_router)
app.include_router(network_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/perf")
async def perf():
    """P6-3: Tick processing performance stats."""
    from _common._profiler import get_perf_stats
    return get_perf_stats()


@app.get("/ready")
async def ready():
    from _common.ready import readiness_response

    return await readiness_response({
        "neo4j": check_neo4j,
        "kafka": check_kafka,
    })

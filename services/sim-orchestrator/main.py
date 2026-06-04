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

from _logging import setup_logging

setup_logging("sim-orchestrator")

logger = logging.getLogger("sim-orchestrator")


async def _on_hour_boundary(sim_time):
    """Clock callback fired every simulated hour.

    Probabilistic incident injection is handled by incident-service
    (which has weather-aware probability modifiers). The orchestrator
    only injects incidents via scenarios or manual API triggers.
    """
    logger.debug("Hour boundary reached: %s", sim_time)


async def _on_day_boundary(next_day: int, sim_time):
    """Clock callback fired at 23:30 — seeds next day's flights, passengers, and baggage."""
    await seed_day(sim_day=next_day)


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

    # 7. Seed Day 1 schedule + passengers + baggage
    await seed_day(sim_day=1)

    # 8. Emit initial weather
    await emit_initial_weather()

    # 9. Configure clock callbacks and start loop
    set_seed(42)
    clock.configure_callbacks(
        on_hour=_on_hour_boundary,
        on_day=_on_day_boundary,
        on_tick=_on_tick,
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
    stop_consumer()
    close_kafka_producer()
    reset_network_engine()
    await close_neo4j()
    from _tracing import shutdown_tracing
    shutdown_tracing()
    logger.info("sim-orchestrator shutdown complete")


app = FastAPI(title="sim-orchestrator", lifespan=lifespan)

from _tracing import init_tracing  # noqa: E402
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
    from _profiler import get_perf_stats
    return get_perf_stats()


@app.get("/ready")
async def ready():
    from _common.ready import readiness_response

    return await readiness_response({
        "neo4j": check_neo4j,
        "kafka": check_kafka,
    })

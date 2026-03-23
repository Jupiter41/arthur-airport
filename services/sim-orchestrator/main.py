import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
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
from routers.sim import router as sim_router
from services import clock
from services.fixtures import load_fixtures
from services.injector import evaluate_probabilistic_events, set_seed
from services.seeder import emit_initial_weather, seed_day

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("sim-orchestrator")


async def _on_hour_boundary(sim_time):
    """Called by clock on each simulated hour boundary."""
    await evaluate_probabilistic_events(sim_time)


async def _on_day_boundary(next_day: int, sim_time):
    """Called by clock at 23:30 to seed next day."""
    await seed_day(sim_day=next_day)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Load fixtures
    load_fixtures()

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
    clock.configure_callbacks(on_hour=_on_hour_boundary, on_day=_on_day_boundary)
    asyncio.create_task(clock.run_clock_loop())

    logger.info("sim-orchestrator startup complete — clock running")
    yield

    # Shutdown
    clock.stop()
    close_kafka_producer()
    await close_neo4j()
    logger.info("sim-orchestrator shutdown complete")


app = FastAPI(title="sim-orchestrator", lifespan=lifespan)

Instrumentator().instrument(app).expose(app)

app.include_router(sim_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    neo4j_ok = await check_neo4j()
    kafka_ok = await check_kafka()

    if not neo4j_ok or not kafka_ok:
        raise HTTPException(
            status_code=503,
            detail={"status": "not ready", "neo4j": neo4j_ok, "kafka": kafka_ok},
        )
    return {"status": "ready", "neo4j": neo4j_ok, "kafka": kafka_ok}

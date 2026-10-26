"""cost-service — Financial layer for the Arthur Airport digital twin.

Port: 8008
Consumes: sim.clock, flights.events, incidents.events, baggage.events, passengers.events
Produces: cost.events
"""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from _common._logging import setup_logging

setup_logging("cost-service")

from db.neo4j import (  # noqa: E402
    check_neo4j,
    close_neo4j,
    create_constraints_and_indexes,
    rebuild_running_totals,
    wait_for_neo4j,
)
from kafka.consumer import run_consumer, set_carbon_factors, stop_consumer  # noqa: E402
from kafka.producer import (  # noqa: E402
    check_kafka,
    close_kafka_producer,
    init_kafka_producer,
    wait_for_kafka,
)
from routers.costs import router as costs_router  # noqa: E402
from services import carbon_tracker  # noqa: E402
from services import rates as rate_store  # noqa: E402
from services.cost_engine import init_running_totals  # noqa: E402
from services import ledger, outbox  # noqa: E402

logger = structlog.get_logger("cost-service")

CARBON_FIXTURES_PATH = Path(__file__).parent / "fixtures" / "carbon_factors.json"


def load_carbon_factors() -> dict:
    """Load carbon emission factor fixtures."""
    with open(CARBON_FIXTURES_PATH) as f:
        factors = json.load(f)
    logger.info("carbon factors loaded", keys=list(factors.keys()))
    return factors


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Wait for Neo4j
    await wait_for_neo4j(max_attempts=12, delay_s=5)

    # 2. Wait for Kafka
    await wait_for_kafka(max_attempts=12, delay_s=5)

    # 3. Initialize Kafka producer
    init_kafka_producer()

    # 4. Create Neo4j constraints and indexes
    await create_constraints_and_indexes()

    # 5b. Load carbon factors
    carbon_factors = load_carbon_factors()
    set_carbon_factors(carbon_factors)
    from routers import carbon as carbon_router_module
    carbon_router_module.set_factors(carbon_factors)

    # 6. Rebuild running totals from Neo4j
    totals = await rebuild_running_totals()
    if totals:
        init_running_totals(totals)
        logger.info(
            "running totals restored",
            cost=totals.get("total_cost_eur", 0),
            revenue=totals.get("total_revenue_eur", 0),
        )
    await carbon_tracker.restore_totals_from_db()
    await ledger.initialize()
    await rate_store.refresh_fuel_once()

    # 7. Start Kafka consumer
    consumer_task = asyncio.create_task(run_consumer())

    def _consumer_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("kafka consumer crashed", error=str(exc), exc_info=exc)

    consumer_task.add_done_callback(_consumer_done)
    outbox_stop = asyncio.Event()
    outbox_task = asyncio.create_task(outbox.run(outbox_stop))

    # Background fuel-price refresh — no-op when FUEL_PRICE_URL is unset.
    fuel_task = asyncio.create_task(rate_store.refresh_fuel_loop())
    logger.info("cost-service started")

    yield

    # Shutdown
    stop_consumer()
    outbox_stop.set()
    fuel_task.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(consumer_task, outbox_task, fuel_task, return_exceptions=True), timeout=15,
        )
    except asyncio.TimeoutError:
        logger.warning("financial background tasks exceeded shutdown budget")
    close_kafka_producer()
    await close_neo4j()


app = FastAPI(
    title="cost-service",
    description="Financial layer for Arthur International Airport",
    version="1.0.0",
    lifespan=lifespan,
)

# Prometheus metrics
Instrumentator().instrument(app).expose(app)

# Mount router
app.include_router(costs_router)

from routers.carbon import router as carbon_router  # noqa: E402
app.include_router(carbon_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cost-service"}


@app.get("/ready")
async def ready():
    from _common.ready import readiness_response

    return await readiness_response({
        "neo4j": check_neo4j,
        "kafka": check_kafka,
    })


# Init tracing (no-op if OTEL_ENABLED=false)
try:
    from _common._tracing import init_tracing
    init_tracing(app, "cost-service")
except ImportError:
    pass

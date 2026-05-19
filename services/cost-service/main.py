"""cost-service — Financial layer for the Arthur Airport digital twin.

Port: 8008
Consumes: sim.clock, flights.events, incidents.events, baggage.events, passengers.events
Produces: cost.events
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from _logging import setup_logging

setup_logging("cost-service")

from db.neo4j import (  # noqa: E402
    check_neo4j,
    close_neo4j,
    create_constraints_and_indexes,
    rebuild_running_totals,
    wait_for_neo4j,
)
from kafka.consumer import run_consumer, set_rates, stop_consumer  # noqa: E402
from kafka.producer import (  # noqa: E402
    check_kafka,
    close_kafka_producer,
    init_kafka_producer,
    wait_for_kafka,
)
from routers.costs import router as costs_router  # noqa: E402
from routers.costs import set_rates as router_set_rates  # noqa: E402
from services.cost_engine import init_running_totals  # noqa: E402

logger = logging.getLogger("cost-service")

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "cost_rates.json"


def load_cost_rates() -> dict:
    """Load cost rate fixtures from JSON file."""
    with open(FIXTURES_PATH) as f:
        rates = json.load(f)
    logger.info("cost rates loaded", keys=list(rates.keys()))
    return rates


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

    # 5. Load cost rates
    rates = load_cost_rates()
    set_rates(rates)
    router_set_rates(rates)

    # 6. Rebuild running totals from Neo4j
    totals = await rebuild_running_totals()
    if totals:
        init_running_totals(totals)
        logger.info(
            "running totals restored",
            cost=totals.get("total_cost_eur", 0),
            revenue=totals.get("total_revenue_eur", 0),
        )

    # 7. Start Kafka consumer
    consumer_task = asyncio.create_task(run_consumer())
    logger.info("cost-service started")

    yield

    # Shutdown
    stop_consumer()
    close_kafka_producer()
    await close_neo4j()
    consumer_task.cancel()


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


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cost-service"}


@app.get("/ready")
async def ready():
    neo4j_ok = await check_neo4j()
    kafka_ok = check_kafka()
    if neo4j_ok and kafka_ok:
        return {"status": "ready", "neo4j": "ok", "kafka": "ok"}
    return {"status": "not ready", "neo4j": "ok" if neo4j_ok else "down", "kafka": "ok" if kafka_ok else "down"}


# Init tracing (no-op if OTEL_ENABLED=false)
try:
    from _tracing import init_tracing
    init_tracing(app, "cost-service")
except ImportError:
    pass

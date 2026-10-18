"""planning-service — Capacity planning simulation engine.

Port: 8009
Runs isolated simulations; persists scenarios/results/audit in Neo4j and
publishes committed lifecycle events through a durable outbox.
"""

from contextlib import asynccontextmanager
import asyncio
import os
import threading

import structlog
from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

from _logging import setup_logging

setup_logging("planning-service")

from adapters.registry import list_available_adapters  # noqa: E402
from routers.planning import router as planning_router  # noqa: E402
from routers.counterfactual import router as counterfactual_router  # noqa: E402
from routers.slots import router as slots_router  # noqa: E402
from routers.network import router as network_router  # noqa: E402
from scenarios.metrics import planning_metrics  # noqa: E402

logger = structlog.get_logger("planning-service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from confluent_kafka import Producer
    from db import store, outbox
    from scenarios import jobs

    await asyncio.to_thread(store.initialize)
    producer = Producer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "client.id": "planning-service", "acks": "all",
    })
    stop = asyncio.Event()
    task = asyncio.create_task(outbox.run(producer, stop))
    worker_stop = threading.Event()
    worker = asyncio.create_task(jobs.run(worker_stop))
    app.state.worker = worker
    app.state.producer = producer
    logger.info("planning-service started", port=8009)
    try:
        yield
    finally:
        worker_stop.set()
        await worker
        stop.set()
        await task
        await asyncio.to_thread(producer.flush, 10)
        await asyncio.to_thread(store.close)
        logger.info("planning-service stopped")


app = FastAPI(
    title="planning-service",
    description="Capacity planning engine for Arthur International Airport",
    version="0.1.0",
    lifespan=lifespan,
)

Instrumentator().instrument(app).expose(app)

app.include_router(planning_router)
app.include_router(counterfactual_router)
app.include_router(slots_router)
app.include_router(network_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "planning-service"}


@app.get("/ready")
async def ready():
    from db import store
    neo4j_ok = await asyncio.to_thread(store.ready)
    producer = getattr(app.state, "producer", None)
    kafka_ok = False
    worker = getattr(app.state, "worker", None)
    worker_ok = worker is not None and not worker.done()
    if producer is not None:
        try:
            metadata = await asyncio.to_thread(producer.list_topics, timeout=3)
            kafka_ok = bool(metadata.brokers)
        except Exception:
            pass
    if not neo4j_ok or not kafka_ok or not worker_ok:
        raise HTTPException(status_code=503, detail={"neo4j": neo4j_ok, "kafka": kafka_ok, "worker": worker_ok})
    return {"status": "ready", "neo4j": True, "kafka": True, "worker": True}


@app.get("/api/v1/planning/adapters")
async def get_adapters():
    """List all available data source adapters."""
    return list_available_adapters()


@app.get("/api/v1/planning/service-status")
async def service_status():
    """Overall planning service status including active runs and metrics."""
    from scenarios.model import list_scenarios as _list

    running, running_count = await asyncio.to_thread(_list, status="running", limit=1000)
    _, completed_count = await asyncio.to_thread(_list, status="completed")
    _, failed_count = await asyncio.to_thread(_list, status="failed")
    _, pending_count = await asyncio.to_thread(_list, status="pending")
    _, total = await asyncio.to_thread(_list)

    return {
        "service": "planning-service",
        "status": "ok",
        "scenarios": {
            "total": total,
            "pending": pending_count,
            "running": running_count,
            "completed": completed_count,
            "failed": failed_count,
        },
        "active_runs": [
            {
                "id": s.id,
                "name": s.name,
                "progress_pct": s.progress_pct,
                "runs_completed": s.runs_completed,
                "monte_carlo_runs": s.monte_carlo_runs,
            }
            for s in running
        ],
        "timing": planning_metrics.get_timing_stats(),
    }

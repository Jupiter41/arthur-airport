"""planning-service — Capacity planning simulation engine.

Port: 8009
No Kafka subscription — reads baseline state from Neo4j, runs isolated
in-memory simulations, writes results to Neo4j (PlanningScenario, PlanningResult).
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from _logging import setup_logging

setup_logging("planning-service")

from adapters.registry import list_available_adapters  # noqa: E402
from routers.planning import router as planning_router  # noqa: E402

logger = structlog.get_logger("planning-service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("planning-service started", port=8009)
    yield
    logger.info("planning-service stopped")


app = FastAPI(
    title="planning-service",
    description="Capacity planning engine for Arthur International Airport",
    version="0.1.0",
    lifespan=lifespan,
)

Instrumentator().instrument(app).expose(app)

app.include_router(planning_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "planning-service"}


@app.get("/ready")
async def ready():
    return {"status": "ready"}


@app.get("/api/v1/planning/adapters")
async def get_adapters():
    """List all available data source adapters."""
    return list_available_adapters()

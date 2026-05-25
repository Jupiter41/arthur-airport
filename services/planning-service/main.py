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
from scenarios.metrics import planning_metrics  # noqa: E402

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


@app.get("/api/v1/planning/service-status")
async def service_status():
    """Overall planning service status including active runs and metrics."""
    from scenarios.model import list_scenarios as _list

    running, _ = _list(status="running")
    completed, _ = _list(status="completed")
    failed, _ = _list(status="failed")
    pending, _ = _list(status="pending")
    all_scenarios, total = _list()

    return {
        "service": "planning-service",
        "status": "ok",
        "scenarios": {
            "total": total,
            "pending": len(pending),
            "running": len(running),
            "completed": len(completed),
            "failed": len(failed),
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

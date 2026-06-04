import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from prometheus_fastapi_instrumentator import Instrumentator

from db.neo4j import (
    check_neo4j,
    close_neo4j,
    create_constraints_and_indexes,
    wait_for_neo4j,
)
from kafka.consumer import (
    get_sim_time,
    is_consumer_running,
    load_spatial_positions,
    rebuild_security_from_neo4j,
    run_consumer,
    set_ws_broadcast,
    stop_consumer,
)
from kafka.producer import (
    check_kafka,
    close_kafka_producer,
    init_kafka_producer,
    wait_for_kafka,
)
from _logging import setup_logging

setup_logging("passenger-service")

from ml.inference import load_models  # noqa: E402
from routers.passengers import router as passengers_router  # noqa: E402
from routers.accessibility import router as accessibility_router  # noqa: E402
from services.zones import rebuild_from_neo4j  # noqa: E402
from services import wheelchair  # noqa: E402

logger = logging.getLogger("passenger-service")

# Suppress noisy Neo4j property-not-found warnings
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

# --- WebSocket connection manager ---
_ws_clients: set[WebSocket] = set()


async def ws_broadcast(message: dict) -> None:
    """Broadcast a message to all connected WebSocket clients."""
    global _ws_clients
    if not _ws_clients:
        return
    data = json.dumps(message)
    disconnected = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.add(ws)
    _ws_clients -= disconnected


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager for passenger-service.

    Startup: Neo4j → Kafka → producer → constraints → zone rebuild →
    security queue rebuild → ML model load → WS callback → consumer task.
    """
    # 1. Wait for Neo4j
    await wait_for_neo4j(max_attempts=12, delay_s=5)

    # 2. Wait for Kafka
    await wait_for_kafka(max_attempts=12, delay_s=5)

    # 3. Initialize Kafka producer
    init_kafka_producer()

    # 4. Create constraints and indexes
    await create_constraints_and_indexes()

    # 5. Rebuild zone density from Neo4j
    await rebuild_from_neo4j()

    # 5b. Rebuild in-memory security queues from Neo4j
    await rebuild_security_from_neo4j()

    # 5c. Load spatial positions for walking time computation
    await load_spatial_positions()

    # 5d. Configure wheelchair pool from airport.yaml (1C — accessibility)
    _configure_accessibility_from_yaml()

    # 6. Load any existing ML models
    load_models()

    # 7. Register WebSocket broadcast callback
    set_ws_broadcast(ws_broadcast)

    # 8. Start Kafka consumer as background task
    consumer_task = asyncio.create_task(run_consumer())

    def _consumer_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("kafka consumer crashed", exc_info=exc)

    consumer_task.add_done_callback(_consumer_done)

    logger.info("passenger-service startup complete")
    yield

    # Shutdown
    stop_consumer()
    close_kafka_producer()
    await close_neo4j()
    from _tracing import shutdown_tracing
    shutdown_tracing()
    logger.info("passenger-service shutdown complete")


def _configure_accessibility_from_yaml() -> None:
    """Load accessibility section from config/airport.yaml and apply to wheelchair pool."""
    import yaml

    candidates = [
        os.getenv("AIRPORT_CONFIG"),
        "/app/config/airport.yaml",
        os.path.join(os.path.dirname(__file__), "..", "..", "config", "airport.yaml"),
    ]
    cfg: dict | None = None
    for path in candidates:
        if not path:
            continue
        try:
            with open(path) as fh:
                cfg = yaml.safe_load(fh) or {}
                logger.info("accessibility: loaded config from %s", path)
                break
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.warning("accessibility: failed to read %s: %s", path, exc)
    accessibility = (cfg or {}).get("accessibility") or {}
    wheelchair.configure_pools(
        total_per_terminal=accessibility.get("total_per_terminal"),
        sla_target_pct=accessibility.get("sla_target_pct"),
        boarding_cutoff_minutes=accessibility.get("boarding_cutoff_minutes"),
        max_dispatch_wait_minutes=accessibility.get("max_dispatch_wait_minutes"),
    )


app = FastAPI(title="passenger-service", lifespan=lifespan)

from _tracing import init_tracing  # noqa: E402
init_tracing(app, "passenger-service")

Instrumentator().instrument(app).expose(app)

app.include_router(passengers_router)
app.include_router(accessibility_router)


@app.websocket("/ws/passengers")
async def websocket_passengers(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    logger.info("WebSocket client connected (%d total)", len(_ws_clients))

    sim_time = get_sim_time()
    try:
        await ws.send_text(json.dumps({
            "type": "connected",
            "sim_time": sim_time.isoformat() if sim_time else None,
        }))
    except Exception:
        pass

    try:
        while True:
            data = await ws.receive_text()
            try:
                frame = json.loads(data)
                if "filter" in frame:
                    pass
            except (json.JSONDecodeError, TypeError):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(_ws_clients))


@app.get("/health")
async def health():
    from kafka.consumer import get_consumer_health
    return {"status": "ok", "consumer": get_consumer_health()}


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
        "consumer": is_consumer_running,
    })

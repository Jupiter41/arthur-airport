import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from prometheus_fastapi_instrumentator import Instrumentator

from db.neo4j import (
    check_neo4j,
    close_neo4j,
    create_constraints_and_indexes,
    get_driver,
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
    publish_confirmed,
    publish_batch_confirmed,
    wait_for_kafka,
)
from _common import outbox as _outbox
from _common._logging import setup_logging
from _common.airport_config import load_airport_runtime_config

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
    from services import flow_projection
    await flow_projection.refresh()
    flow_stop = asyncio.Event()
    flow_task = asyncio.create_task(flow_projection.run(flow_stop))
    consumer_task = asyncio.create_task(run_consumer())

    def _consumer_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("kafka consumer crashed", exc_info=exc)

    consumer_task.add_done_callback(_consumer_done)

    # 9. Start the transactional outbox delivery loop (G1) — drains
    #    PassengerOutbox to Kafka, deleting each row only after broker ack.
    outbox_stop = asyncio.Event()
    import structlog
    outbox_task = asyncio.create_task(
        _outbox.run(
            "PassengerOutbox", get_driver, publish_confirmed, outbox_stop,
            logger=structlog.get_logger("passenger-service.outbox"),
            publish_batch_confirmed=publish_batch_confirmed,
        )
    )

    logger.info("passenger-service startup complete")
    yield

    # Shutdown
    stop_consumer()
    outbox_stop.set()
    flow_stop.set()
    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.gather(flow_task, return_exceptions=True), timeout=5)
    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.gather(consumer_task, return_exceptions=True), timeout=5)
    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.gather(outbox_task, return_exceptions=True), timeout=5)
    close_kafka_producer()
    await close_neo4j()
    from _common._tracing import shutdown_tracing
    shutdown_tracing()
    logger.info("passenger-service shutdown complete")


def _configure_accessibility_from_yaml() -> None:
    """Apply accessibility section from config/airport.yaml (shared loader)."""
    accessibility = load_airport_runtime_config().accessibility
    wheelchair.configure_pools(
        total_per_terminal=accessibility.total_per_terminal,
        sla_target_pct=accessibility.sla_target_pct,
        boarding_cutoff_minutes=accessibility.boarding_cutoff_minutes,
        max_dispatch_wait_minutes=accessibility.max_dispatch_wait_minutes,
    )


app = FastAPI(title="passenger-service", lifespan=lifespan)

from _common._tracing import init_tracing  # noqa: E402
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
    from _common._profiler import get_perf_stats
    return get_perf_stats()


@app.get("/ready")
async def ready():
    from _common.ready import readiness_response

    return await readiness_response({
        "neo4j": check_neo4j,
        "kafka": check_kafka,
        "consumer": is_consumer_running,
    })

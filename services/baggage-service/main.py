import asyncio
import json
import logging
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
    run_consumer,
    stop_consumer,
    is_consumer_running,
    set_ws_broadcast,
    get_sim_time,
    _state as consumer_state,
)
from kafka.producer import (
    check_kafka,
    close_kafka_producer,
    init_kafka_producer,
    wait_for_kafka,
)
from _logging import setup_logging

setup_logging("baggage-service")

from routers.baggage import router as baggage_router  # noqa: E402

logger = logging.getLogger("baggage-service")

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
    """FastAPI lifespan manager for baggage-service.

    Startup: Neo4j → Kafka → producer → constraints → WS callback →
    conveyor state rebuild from Neo4j → consumer task.
    """
    # 1. Wait for Neo4j
    await wait_for_neo4j(max_attempts=12, delay_s=5)

    # 2. Wait for Kafka
    await wait_for_kafka(max_attempts=12, delay_s=5)

    # 3. Initialize Kafka producer
    init_kafka_producer()

    # 4. Create constraints and indexes
    await create_constraints_and_indexes()

    # 5. Register WebSocket broadcast callback
    set_ws_broadcast(ws_broadcast)

    # 6. Rebuild in-memory state from Neo4j (startup catch-up)
    await consumer_state.rebuild_from_neo4j()

    # 7. Start Kafka consumer as background task
    consumer_task = asyncio.create_task(run_consumer())

    def _consumer_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("kafka consumer crashed", exc_info=exc)

    consumer_task.add_done_callback(_consumer_done)

    logger.info("baggage-service startup complete")
    yield

    # Shutdown
    stop_consumer()
    close_kafka_producer()
    await close_neo4j()
    from _tracing import shutdown_tracing
    shutdown_tracing()
    logger.info("baggage-service shutdown complete")


app = FastAPI(title="baggage-service", lifespan=lifespan)

from _tracing import init_tracing  # noqa: E402
init_tracing(app, "baggage-service")

Instrumentator().instrument(app).expose(app)

app.include_router(baggage_router)


@app.websocket("/ws/baggage")
async def websocket_baggage(ws: WebSocket):
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
            await ws.receive_text()
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

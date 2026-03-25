import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
from routers.baggage import router as baggage_router

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
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
    asyncio.create_task(run_consumer())

    logger.info("baggage-service startup complete")
    yield

    # Shutdown
    stop_consumer()
    close_kafka_producer()
    await close_neo4j()
    logger.info("baggage-service shutdown complete")


app = FastAPI(title="baggage-service", lifespan=lifespan)

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
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    neo4j_ok = await check_neo4j()
    kafka_ok = await check_kafka()
    consumer_ok = is_consumer_running()

    if not neo4j_ok or not kafka_ok or not consumer_ok:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not ready",
                "neo4j": neo4j_ok,
                "kafka": kafka_ok,
                "consumer": consumer_ok,
            },
        )
    return {
        "status": "ready",
        "neo4j": neo4j_ok,
        "kafka": kafka_ok,
        "consumer": consumer_ok,
    }

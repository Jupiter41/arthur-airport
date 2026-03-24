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
    get_sim_time,
    is_consumer_running,
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
from ml.inference import load_models
from routers.passengers import router as passengers_router
from services.zones import rebuild_from_neo4j

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
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

    # 6. Load any existing ML models
    load_models()

    # 7. Register WebSocket broadcast callback
    set_ws_broadcast(ws_broadcast)

    # 8. Start Kafka consumer as background task
    asyncio.create_task(run_consumer())

    logger.info("passenger-service startup complete")
    yield

    # Shutdown
    stop_consumer()
    close_kafka_producer()
    await close_neo4j()
    logger.info("passenger-service shutdown complete")


app = FastAPI(title="passenger-service", lifespan=lifespan)

Instrumentator().instrument(app).expose(app)

app.include_router(passengers_router)


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

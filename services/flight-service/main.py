import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from prometheus_fastapi_instrumentator import Instrumentator

from _logging import setup_logging

setup_logging("flight-service")

from db.neo4j import (  # noqa: E402
    check_neo4j,
    close_neo4j,
    create_constraints_and_indexes,
    migrate_flight_properties,
    wait_for_neo4j,
)
from kafka.consumer import run_consumer, stop_consumer, is_consumer_running, set_ws_broadcast, _state as consumer_state  # noqa: E402
from kafka.producer import (  # noqa: E402
    check_kafka,
    close_kafka_producer,
    init_kafka_producer,
    wait_for_kafka,
)
from routers.flights import router as flights_router  # noqa: E402

logger = logging.getLogger("flight-service")

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
    """FastAPI lifespan manager — initialises Neo4j, Kafka, and the consumer loop.

    Startup sequence:
        1. Connect to Neo4j (retry up to 12×)
        2. Connect to Kafka (retry up to 12×)
        3. Initialise Kafka producer
        4. Create graph constraints/indexes
        5. Register WS broadcast callback
        6. Rebuild in-memory state from Neo4j
        7. Start Kafka consumer background task

    Shutdown: stops consumer, flushes producer, closes Neo4j driver.
    """
    # 1. Wait for Neo4j
    await wait_for_neo4j(max_attempts=12, delay_s=5)

    # 2. Wait for Kafka
    await wait_for_kafka(max_attempts=12, delay_s=5)

    # 3. Initialize Kafka producer
    init_kafka_producer()

    # 4. Create constraints and indexes
    await create_constraints_and_indexes()

    # 4b. Backfill missing properties on legacy Flight nodes
    await migrate_flight_properties()

    # 5. Register WebSocket broadcast callback
    set_ws_broadcast(ws_broadcast)

    # 6. Rebuild in-memory state from Neo4j (startup catch-up)
    await consumer_state.rebuild_from_neo4j()

    # 7. Start Kafka consumer as background task
    asyncio.create_task(run_consumer())

    # 8. Start ADS-B polling if enabled (Phase 1.1)
    if os.getenv("ADSB_ENABLED", "false").lower() == "true":
        from services.adsb import get_adsb_cache
        asyncio.create_task(get_adsb_cache().start_polling())

    logger.info("flight-service startup complete")
    yield

    # Shutdown
    stop_consumer()
    if os.getenv("ADSB_ENABLED", "false").lower() == "true":
        from services.adsb import get_adsb_cache
        get_adsb_cache().stop()
    close_kafka_producer()
    await close_neo4j()
    from _tracing import shutdown_tracing
    shutdown_tracing()
    logger.info("flight-service shutdown complete")


app = FastAPI(title="flight-service", lifespan=lifespan)

from _tracing import init_tracing  # noqa: E402
init_tracing(app, "flight-service")

Instrumentator().instrument(app).expose(app)

app.include_router(flights_router)


@app.websocket("/ws/flights")
async def websocket_flights(ws: WebSocket):
    """WebSocket endpoint for real-time flight event streaming.

    Sends a ``connected`` message on accept with the current sim_time,
    then keeps the connection alive until the client disconnects.
    All flight state changes are pushed via ``ws_broadcast``.
    """
    await ws.accept()
    _ws_clients.add(ws)
    logger.info("WebSocket client connected (%d total)", len(_ws_clients))

    # Send connection message
    from kafka.consumer import get_sim_time
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
    """Liveness probe — always returns 200 if the process is running."""
    return {"status": "ok"}


@app.get("/perf")
async def perf():
    """P6-3: Tick processing performance stats."""
    from _profiler import get_perf_stats
    return get_perf_stats()


@app.get("/ready")
async def ready():
    """Readiness probe — returns 200 only when Neo4j, Kafka, and the consumer are healthy."""
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

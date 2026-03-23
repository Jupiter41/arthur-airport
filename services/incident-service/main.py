import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup — connections will be initialized here in later sprints
    yield
    # shutdown — connections will be closed here in later sprints


app = FastAPI(title="incident-service", lifespan=lifespan)

Instrumentator().instrument(app).expose(app)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    neo4j_ok = False
    kafka_ok = False

    # Check Neo4j
    try:
        from neo4j import AsyncGraphDatabase

        driver = AsyncGraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
            auth=(
                os.getenv("NEO4J_USER", "neo4j"),
                os.getenv("NEO4J_PASSWORD", "art-digital-twin"),
            ),
        )
        await driver.verify_connectivity()
        await driver.close()
        neo4j_ok = True
    except Exception:
        pass

    # Check Kafka
    try:
        from confluent_kafka.admin import AdminClient

        admin = AdminClient(
            {"bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092")}
        )
        metadata = admin.list_topics(timeout=5)
        kafka_ok = metadata is not None
    except Exception:
        pass

    if not neo4j_ok or not kafka_ok:
        raise HTTPException(
            status_code=503,
            detail={"status": "not ready", "neo4j": neo4j_ok, "kafka": kafka_ok},
        )
    return {"status": "ready", "neo4j": neo4j_ok, "kafka": kafka_ok}

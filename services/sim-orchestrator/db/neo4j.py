"""Neo4j async driver initialization and helpers for sim-orchestrator."""

import asyncio
import logging
import os

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None

CONSTRAINTS = [
    "CREATE CONSTRAINT flight_id IF NOT EXISTS FOR (f:Flight) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT passenger_id IF NOT EXISTS FOR (p:Passenger) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT baggage_tag IF NOT EXISTS FOR (b:Baggage) REQUIRE b.tag IS UNIQUE",
    "CREATE CONSTRAINT gate_id IF NOT EXISTS FOR (g:Gate) REQUIRE g.id IS UNIQUE",
    "CREATE CONSTRAINT runway_id IF NOT EXISTS FOR (r:Runway) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT incident_id IF NOT EXISTS FOR (i:Incident) REQUIRE i.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX flight_number IF NOT EXISTS FOR (f:Flight) ON (f.flight_number)",
    "CREATE INDEX flight_status IF NOT EXISTS FOR (f:Flight) ON (f.status)",
    "CREATE INDEX passenger_pnr IF NOT EXISTS FOR (p:Passenger) ON (p.pnr)",
    "CREATE INDEX baggage_status IF NOT EXISTS FOR (b:Baggage) ON (b.status)",
    "CREATE INDEX incident_type IF NOT EXISTS FOR (i:Incident) ON (i.type)",
    "CREATE INDEX incident_status IF NOT EXISTS FOR (i:Incident) ON (i.status)",
]


async def init_neo4j() -> None:
    """Initialize the Neo4j async driver and verify connectivity."""
    global _driver
    _driver = AsyncGraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "art-digital-twin"),
        ),
        max_connection_pool_size=int(os.getenv("NEO4J_POOL_SIZE", "50")),
        connection_acquisition_timeout=float(os.getenv("NEO4J_POOL_TIMEOUT", "60")),
        max_connection_lifetime=int(os.getenv("NEO4J_CONN_LIFETIME", "3600")),
    )
    await _driver.verify_connectivity()
    logger.info("Neo4j driver initialized")


async def close_neo4j() -> None:
    """Close the Neo4j driver."""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


def get_driver() -> AsyncDriver:
    """Return the active Neo4j driver. Raises if not initialized."""
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialised")
    return _driver


async def wait_for_neo4j(max_attempts: int = 12, delay_s: float = 5) -> None:
    """Wait for Neo4j to become available with exponential backoff."""
    for attempt in range(1, max_attempts + 1):
        try:
            await init_neo4j()
            return
        except Exception as e:
            wait = delay_s * min(attempt, 6)
            logger.warning(
                "Neo4j not ready (attempt %d/%d): %s — retrying in %.0fs",
                attempt, max_attempts, e, wait,
            )
            if _driver:
                try:
                    await _driver.close()
                except Exception:
                    pass
            await asyncio.sleep(wait)
    raise RuntimeError(f"Neo4j not reachable after {max_attempts} attempts")


async def create_constraints_and_indexes() -> None:
    """Create all uniqueness constraints and lookup indexes."""
    async with get_driver().session() as session:
        for stmt in CONSTRAINTS + INDEXES:
            await session.run(stmt)
    logger.info("Neo4j constraints and indexes created")


async def execute_query(query: str, **params):
    """Execute a single Cypher query and return records."""
    async with get_driver().session() as session:
        result = await session.run(query, **params)
        return [record async for record in result]


async def check_neo4j() -> bool:
    """Health check: verify Neo4j connectivity."""
    try:
        if _driver is None:
            return False
        await _driver.verify_connectivity()
        return True
    except Exception:
        return False

"""Neo4j async driver initialization and helpers for sim-orchestrator."""

import logging

from _common import neo4j_client

logger = logging.getLogger(__name__)

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
    await neo4j_client.init_driver()


async def close_neo4j() -> None:
    await neo4j_client.close_driver()


def get_driver():
    return neo4j_client.get_driver()


async def wait_for_neo4j(max_attempts: int = 12, delay_s: float = 5) -> None:
    await neo4j_client.wait_for_driver(max_attempts=max_attempts, delay_s=delay_s)


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
    return await neo4j_client.check_connectivity()

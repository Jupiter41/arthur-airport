"""Neo4j async driver for analysis-service.

Operational domain data is read-only. Analysis owns durable action proposals.
"""

import asyncio
import logging
import os

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None


async def init_neo4j() -> None:
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
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


def get_driver() -> AsyncDriver:
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialised")
    return _driver


async def check_neo4j() -> bool:
    try:
        if _driver is None:
            return False
        await _driver.verify_connectivity()
        return True
    except Exception:
        return False


async def wait_for_neo4j(max_attempts: int = 12, delay_s: float = 5) -> None:
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


# ── Query helpers ────────────────────────────────────────────


async def query_gate_availability() -> dict:
    """Return per-terminal gate availability: {terminal: {total, occupied, free}}."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run("""
            MATCH (t:Terminal)-[:HAS_GATE]->(g:Gate)
            OPTIONAL MATCH (f:Flight)-[:ASSIGNED_TO]->(g)
            WHERE f.status IN ['boarding', 'turnaround', 'arrived', 'scheduled', 'ready_for_departure']
            WITH t.name AS terminal, count(g) AS total,
                 count(f) AS occupied
            RETURN terminal, total, occupied, total - occupied AS free
            ORDER BY terminal
        """)
        records = await result.data()
    return {
        r["terminal"]: {
            "total": r["total"],
            "occupied": r["occupied"],
            "free": r["free"],
        }
        for r in records
    }


async def query_flights_waiting_for_gate() -> int:
    """Count flights that need a gate but don't have one."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run("""
            MATCH (f:Flight)
            WHERE f.status IN ['approaching', 'holding', 'landed']
            AND NOT (f)-[:ASSIGNED_TO]->(:Gate)
            RETURN count(f) AS cnt
        """)
        record = await result.single()
    return record["cnt"] if record else 0


async def query_connection_clusters(min_cluster_size: int = 5) -> list[dict]:
    """Find groups of connecting passengers on the same delayed inbound + outbound."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run("""
            MATCH (p:Passenger {connection: true})-[:ON_FLIGHT]->(inbound:Flight)
            WHERE inbound.direction = 'arrival'
              AND inbound.delay_minutes > 0
              AND NOT p.status IN ['boarded', 'departed_airport', 'missed_connection']
            MATCH (outbound:Flight {id: p.connection_flight_id})
            WHERE outbound.id <> inbound.id AND outbound.direction = 'departure'
              AND outbound.status IN ['scheduled', 'boarding']
            WITH inbound, outbound,
                 collect(p.id) AS passengers,
                 count(p) AS pax_count,
                 inbound.delay_minutes AS inbound_delay
            WHERE pax_count >= $min_size
            RETURN inbound.id AS inbound_flight,
                   outbound.id AS outbound_flight,
                   pax_count, passengers, inbound_delay,
                   outbound.scheduled_time AS connection_departure
            ORDER BY pax_count DESC
        """, min_size=min_cluster_size)
        records = await result.data()
    return records


async def query_runway_capacity() -> dict:
    """Return current runway status and queued flight counts."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run("""
            MATCH (r:Runway)
            OPTIONAL MATCH (f:Flight)-[:USES_RUNWAY]->(r)
            WHERE f.status IN ['approaching', 'holding', 'ready_for_departure', 'taxiing']
            WITH r, count(f) AS queued
            RETURN r.id AS runway_id, r.status AS status,
                   r.direction AS direction, queued
            ORDER BY r.id
        """)
        records = await result.data()
    return {r["runway_id"]: r for r in records}


async def query_active_flights_summary() -> dict:
    """Return active flight counts by status."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run("""
            MATCH (f:Flight)
            WHERE NOT f.status IN ['completed', 'cancelled']
            RETURN f.status AS status, count(f) AS cnt
        """)
        records = await result.data()
    return {r["status"]: r["cnt"] for r in records}


async def load_operational_projection() -> dict:
    """Read owner data through Neo4j, never through service-to-service HTTP."""
    async def read(tx):
        queries = {
            "flights": (
                "MATCH (f:Flight) WHERE NOT f.status IN ['completed', 'cancelled', 'diverted'] "
                "OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate) "
                "RETURN properties(f) AS flight, g.id AS gate_id, g.terminal_id AS terminal_id"
            ),
            "gates": "MATCH (g:Gate) RETURN properties(g) AS gate",
            "incidents": "MATCH (i:Incident) WHERE i.status <> 'resolved' RETURN properties(i) AS incident",
            "weather": (
                "MATCH (:Airport)-[:CURRENT_WEATHER]->(w:WeatherState) "
                "RETURN properties(w) AS weather ORDER BY w.timestamp DESC LIMIT 1"
            ),
            "baggage": "MATCH (p:BaggageProjection {id: 'latest'}) RETURN p.document AS document",
        }
        snapshot = {}
        for key, query in queries.items():
            result = await tx.run(query)
            snapshot[key] = await result.data()
        return snapshot

    async with get_driver().session() as session:
        return await session.execute_read(read)

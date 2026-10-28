"""Neo4j async driver for analysis-service.

Operational domain data is read-only. Analysis owns durable action proposals.
"""

import logging

from _common import neo4j_client

logger = logging.getLogger(__name__)


async def init_neo4j() -> None:
    await neo4j_client.init_driver()


async def close_neo4j() -> None:
    await neo4j_client.close_driver()


def get_driver():
    return neo4j_client.get_driver()


async def check_neo4j() -> bool:
    return await neo4j_client.check_connectivity()


async def wait_for_neo4j(max_attempts: int = 12, delay_s: float = 5) -> None:
    await neo4j_client.wait_for_driver(max_attempts=max_attempts, delay_s=delay_s)


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

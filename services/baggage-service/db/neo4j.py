"""Neo4j async driver and Baggage persistence for baggage-service."""

import asyncio
import logging
import os
from datetime import datetime

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None

CONSTRAINTS = [
    "CREATE CONSTRAINT baggage_tag IF NOT EXISTS FOR (b:Baggage) REQUIRE b.tag IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX baggage_status IF NOT EXISTS FOR (b:Baggage) ON (b.status)",
    "CREATE INDEX baggage_id IF NOT EXISTS FOR (b:Baggage) ON (b.id)",
    "CREATE INDEX scan_event_baggage_tag IF NOT EXISTS FOR (s:ScanEvent) ON (s.baggage_tag)",
]


async def init_neo4j() -> None:
    global _driver
    _driver = AsyncGraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "art-digital-twin"),
        ),
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


async def create_constraints_and_indexes() -> None:
    driver = get_driver()
    async with driver.session() as session:
        for stmt in CONSTRAINTS + INDEXES:
            await session.run(stmt)
    logger.info("Baggage constraints and indexes created")


# ---------------------------------------------------------------------------
# Baggage CRUD
# ---------------------------------------------------------------------------

async def get_all_baggage(
    flight_id: str | None = None,
    passenger_id: str | None = None,
    status: str | None = None,
    flagged: bool | None = None,
    zone: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return baggage items with optional filters. Returns (items, total_count)."""
    driver = get_driver()

    where_clauses: list[str] = []
    params: dict = {"limit": limit, "offset": offset}

    if flight_id:
        where_clauses.append("f.id = $flight_id")
        params["flight_id"] = flight_id
    if passenger_id:
        where_clauses.append("p.id = $passenger_id")
        params["passenger_id"] = passenger_id
    if status:
        statuses = [s.strip() for s in status.split(",")]
        where_clauses.append("b.status IN $statuses")
        params["statuses"] = statuses
    if flagged is not None:
        where_clauses.append("b.is_dangerous_goods = $flagged")
        params["flagged"] = flagged
    if zone:
        where_clauses.append("b.last_scan_zone = $zone")
        params["zone"] = zone

    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    count_query = f"""
    MATCH (b:Baggage)
    OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    OPTIONAL MATCH (b)-[:LOADED_ON]->(f:Flight)
    {where}
    RETURN count(b) AS total
    """
    data_query = f"""
    MATCH (b:Baggage)
    OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    OPTIONAL MATCH (b)-[:LOADED_ON]->(f:Flight)
    {where}
    RETURN b {{
        .id, .tag, .status, .weight_kg, .is_dangerous_goods,
        .dg_class, .last_scan_zone, .last_scan_at, .carousel
    }} AS baggage,
    p.id AS passenger_id,
    p.name AS passenger_name,
    f.flight_number AS flight_number,
    f.id AS flight_id
    ORDER BY b.last_scan_at DESC
    SKIP $offset LIMIT $limit
    """

    async with driver.session() as session:
        count_result = await session.run(count_query, **params)
        count_record = await count_result.single()
        total = count_record["total"] if count_record else 0

        data_result = await session.run(data_query, **params)
        records = [record async for record in data_result]

    items = []
    for r in records:
        bag = dict(r["baggage"])
        bag["passenger_id"] = r["passenger_id"]
        bag["passenger_name"] = r["passenger_name"]
        bag["flight_number"] = r["flight_number"]
        bag["flight_id"] = r["flight_id"]
        items.append(bag)

    return items, total


async def get_baggage_by_id(baggage_id: str) -> dict | None:
    """Get a single baggage item with scan history."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage {id: $id})
    OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    OPTIONAL MATCH (b)-[:LOADED_ON]->(f:Flight)
    OPTIONAL MATCH (b)-[:SCANNED_AT]->(s:ScanEvent)
    WITH b, p, f, s
    ORDER BY s.at ASC
    RETURN b {
        .id, .tag, .status, .weight_kg, .is_dangerous_goods,
        .dg_class, .last_scan_zone, .last_scan_at, .carousel
    } AS baggage,
    p { .id, .name, .pnr } AS passenger,
    f { .id, .flight_number, .status } AS flight,
    collect(s { .zone, .status, .at }) AS scan_history
    """
    async with driver.session() as session:
        result = await session.run(query, id=baggage_id)
        record = await result.single()
        if not record:
            return None
        bag = dict(record["baggage"])
        bag["passenger"] = dict(record["passenger"]) if record["passenger"] else None
        bag["flight"] = dict(record["flight"]) if record["flight"] else None
        bag["scan_history"] = [dict(s) for s in record["scan_history"]]
        return bag


async def get_baggage_by_tag(tag: str) -> dict | None:
    """Look up baggage by 10-digit barcode tag."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage {tag: $tag})
    OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    OPTIONAL MATCH (b)-[:LOADED_ON]->(f:Flight)
    OPTIONAL MATCH (b)-[:SCANNED_AT]->(s:ScanEvent)
    WITH b, p, f, s
    ORDER BY s.at ASC
    RETURN b {
        .id, .tag, .status, .weight_kg, .is_dangerous_goods,
        .dg_class, .last_scan_zone, .last_scan_at, .carousel
    } AS baggage,
    p { .id, .name, .pnr } AS passenger,
    f { .id, .flight_number, .status } AS flight,
    collect(s { .zone, .status, .at }) AS scan_history
    """
    async with driver.session() as session:
        result = await session.run(query, tag=tag)
        record = await result.single()
        if not record:
            return None
        bag = dict(record["baggage"])
        bag["passenger"] = dict(record["passenger"]) if record["passenger"] else None
        bag["flight"] = dict(record["flight"]) if record["flight"] else None
        bag["scan_history"] = [dict(s) for s in record["scan_history"]]
        return bag


async def update_baggage_status(
    baggage_id: str,
    new_status: str,
    scan_zone: str,
    sim_time: datetime,
) -> dict | None:
    """Update baggage status, last scan info, and append a ScanEvent node."""
    driver = get_driver()
    sim_time_str = sim_time.isoformat()
    query = """
    MATCH (b:Baggage {id: $id})
    SET b.status = $status,
        b.last_scan_zone = $zone,
        b.last_scan_at = $at
    CREATE (s:ScanEvent {
        baggage_tag: b.tag,
        zone: $zone,
        status: $status,
        at: $at
    })
    CREATE (b)-[:SCANNED_AT]->(s)
    RETURN b {
        .id, .tag, .status, .weight_kg, .is_dangerous_goods,
        .dg_class, .last_scan_zone, .last_scan_at
    } AS baggage
    """
    async with driver.session() as session:
        result = await session.run(
            query,
            id=baggage_id,
            status=new_status,
            zone=scan_zone,
            at=sim_time_str,
        )
        record = await result.single()
        if not record:
            return None
        return dict(record["baggage"])


async def flag_baggage(
    baggage_id: str,
    flag_reason: str,
    scan_zone: str,
    sim_time: datetime,
    review_status: str = "pending",
) -> dict | None:
    """Flag a baggage item (DG detected or false positive)."""
    driver = get_driver()
    sim_time_str = sim_time.isoformat()
    query = """
    MATCH (b:Baggage {id: $id})
    SET b.status = 'flagged',
        b.last_scan_zone = $zone,
        b.last_scan_at = $at,
        b.flag_reason = $flag_reason,
        b.flagged_at = $at,
        b.review_status = $review_status
    CREATE (s:ScanEvent {
        baggage_tag: b.tag,
        zone: $zone,
        status: 'flagged',
        at: $at
    })
    CREATE (b)-[:SCANNED_AT]->(s)
    RETURN b {
        .id, .tag, .status, .weight_kg, .is_dangerous_goods,
        .dg_class, .last_scan_zone, .last_scan_at,
        .flag_reason, .flagged_at, .review_status
    } AS baggage
    """
    async with driver.session() as session:
        result = await session.run(
            query,
            id=baggage_id,
            zone=scan_zone,
            at=sim_time_str,
            flag_reason=flag_reason,
            review_status=review_status,
        )
        record = await result.single()
        if not record:
            return None
        return dict(record["baggage"])


async def get_baggage_counts_by_status() -> dict[str, int]:
    """Get count of baggage items grouped by status."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage)
    RETURN b.status AS status, count(b) AS cnt
    """
    async with driver.session() as session:
        result = await session.run(query)
        records = [record async for record in result]
    return {r["status"]: r["cnt"] for r in records if r["status"]}


async def get_baggage_by_zone(zone: str) -> list[dict]:
    """Get all baggage currently in a specific zone."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage {last_scan_zone: $zone})
    WHERE b.status NOT IN ['collected', 'lost']
    RETURN b.id AS id, b.tag AS tag, b.status AS status
    """
    async with driver.session() as session:
        result = await session.run(query, zone=zone)
        return [dict(r) async for r in result]


async def get_flagged_baggage() -> list[dict]:
    """Get all currently flagged baggage items."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage)
    WHERE b.status = 'flagged' OR b.review_status = 'pending'
    OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    OPTIONAL MATCH (b)-[:LOADED_ON]->(f:Flight)
    RETURN b {
        .id, .tag, .status, .is_dangerous_goods, .dg_class,
        .last_scan_zone, .flag_reason, .flagged_at, .review_status
    } AS baggage,
    p.name AS passenger_name,
    f.flight_number AS flight_number
    """
    async with driver.session() as session:
        result = await session.run(query)
        records = [record async for record in result]
    items = []
    for r in records:
        bag = dict(r["baggage"])
        bag["passenger_name"] = r["passenger_name"]
        bag["flight_number"] = r["flight_number"]
        items.append(bag)
    return items


async def get_flight_baggage(flight_id: str, statuses: list[str] | None = None) -> list[dict]:
    """Get all baggage loaded on a specific flight, optionally filtered by status."""
    driver = get_driver()
    status_filter = ""
    params: dict = {"fid": flight_id}
    if statuses:
        status_filter = "AND b.status IN $statuses"
        params["statuses"] = statuses
    query = f"""
        MATCH (b:Baggage)-[:LOADED_ON]->(f:Flight {{id: $fid}})
        OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    WHERE true {status_filter}
    RETURN b.id AS id, b.tag AS tag, b.status AS status,
            b.last_scan_zone AS last_scan_zone,
            p.id AS passenger_id
    """
    async with driver.session() as session:
        result = await session.run(query, **params)
        return [dict(r) async for r in result]


async def get_dropped_off_baggage_for_departures(sim_time: datetime) -> list[dict]:
    """Get baggage in 'dropped_off' status linked to departure flights.
    Includes flights in any non-terminal state so we can catch up if the service
    started after flights had already departed."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage {status: 'dropped_off'})-[:LOADED_ON]->(f:Flight)
    WHERE f.direction = 'departure'
      AND f.status <> 'cancelled'
    OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
    RETURN b.id AS id, b.tag AS tag, b.is_dangerous_goods AS is_dg,
           b.dg_class AS dg_class, b.weight_kg AS weight_kg,
           f.id AS flight_id, f.flight_number AS flight_number,
           f.estimated_time AS estimated_time,
           f.status AS flight_status,
           p.id AS passenger_id,
           g.terminal_id AS terminal_id
    """
    async with driver.session() as session:
        result = await session.run(query)
        return [dict(r) async for r in result]


async def set_baggage_carousel(baggage_id: str, carousel: int, sim_time: datetime) -> None:
    """Set the carousel number for a baggage item."""
    get_driver()
    await _run_simple(
        "MATCH (b:Baggage {id: $id}) SET b.carousel = $carousel",
        id=baggage_id,
        carousel=carousel,
    )


async def _run_simple(query: str, **params) -> None:
    driver = get_driver()
    async with driver.session() as session:
        await session.run(query, **params)


async def set_loaded_on_timestamp(
    baggage_id: str, flight_id: str, sim_time: datetime
) -> None:
    """Set loaded_at on LOADED_ON, creating the relationship if needed."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage {id: $bid})
    MATCH (f:Flight {id: $fid})
    MERGE (b)-[r:LOADED_ON]->(f)
    SET r.loaded_at = $at
    """
    async with driver.session() as session:
        await session.run(
            query,
            bid=baggage_id,
            fid=flight_id,
            at=sim_time.isoformat(),
        )


async def get_baggage_in_pipeline() -> list[dict]:
    """Return bags currently in the conveyor pipeline (inducted/screening/sorting/loaded/in_hold/flagged)."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage)
    WHERE b.status IN ['inducted', 'screening', 'sorting', 'loaded', 'in_hold', 'flagged']
    OPTIONAL MATCH (b)-[:LOADED_ON]->(f:Flight)
    RETURN b.id AS id, b.status AS status, b.current_zone AS current_zone,
           b.last_scan_at AS last_scan_at, f.id AS flight_id
    """
    async with driver.session() as session:
        result = await session.run(query)
        return [dict(record) async for record in result]

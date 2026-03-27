"""Neo4j async driver and Passenger persistence for passenger-service."""

import asyncio
import logging
import os
from datetime import datetime

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None

CONSTRAINTS = [
    "CREATE CONSTRAINT passenger_id IF NOT EXISTS FOR (p:Passenger) REQUIRE p.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX passenger_pnr IF NOT EXISTS FOR (p:Passenger) ON (p.pnr)",
    "CREATE INDEX passenger_status IF NOT EXISTS FOR (p:Passenger) ON (p.status)",
    "CREATE INDEX passenger_location IF NOT EXISTS FOR (p:Passenger) ON (p.location_zone)",
    "CREATE INDEX passenger_flight IF NOT EXISTS FOR (p:Passenger) ON (p.flight_id)",
    "CREATE INDEX flight_scheduled IF NOT EXISTS FOR (f:Flight) ON (f.scheduled_time)",
    "CREATE INDEX flight_direction IF NOT EXISTS FOR (f:Flight) ON (f.direction)",
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
    logger.info("Passenger constraints and indexes created")


# ---------------------------------------------------------------------------
# Passenger CRUD
# ---------------------------------------------------------------------------

async def get_all_passengers(
    flight_id: str | None = None,
    flight_number: str | None = None,
    status: str | None = None,
    zone: str | None = None,
    connection: bool | None = None,
    special_assistance: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return passengers with optional filters. Returns (items, total)."""
    driver = get_driver()

    where_clauses: list[str] = []
    params: dict = {"limit": limit, "offset": offset}

    if flight_id:
        where_clauses.append("f.id = $flight_id")
        params["flight_id"] = flight_id
    if flight_number:
        where_clauses.append("f.flight_number = $flight_number")
        params["flight_number"] = flight_number
    if status:
        statuses = [s.strip() for s in status.split(",")]
        where_clauses.append("p.status IN $statuses")
        params["statuses"] = statuses
    if zone:
        where_clauses.append("p.location_zone = $zone")
        params["zone"] = zone
    if connection is not None:
        where_clauses.append("p.connection = $connection")
        params["connection"] = connection
    if special_assistance is not None:
        where_clauses.append("p.special_assistance = $sa")
        params["sa"] = special_assistance

    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    count_query = f"""
    MATCH (p:Passenger)-[:ON_FLIGHT]->(f:Flight)
    {where}
    RETURN count(p) AS total
    """
    data_query = f"""
    MATCH (p:Passenger)-[:ON_FLIGHT]->(f:Flight)
    {where}
    RETURN p {{
        .id, .name, .pnr, .status, .location_zone, .seat,
        .connection, .special_assistance
    }} AS passenger,
    f.flight_number AS flight_number
    ORDER BY p.name
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
        pax = dict(r["passenger"])
        pax["flight_number"] = r["flight_number"]
        items.append(pax)

    return items, total


async def get_passenger_by_id(passenger_id: str) -> dict | None:
    """Get full passenger detail with flight, baggage, and timeline."""
    driver = get_driver()
    query = """
    MATCH (p:Passenger {id: $id})-[:ON_FLIGHT]->(f:Flight)
    OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
    OPTIONAL MATCH (p)-[:CARRIES]->(b:Baggage)
    RETURN p {
        .id, .name, .pnr, .nationality, .status, .location_zone,
        .seat, .connection, .connection_flight_id, .special_assistance,
        .checked_in_at, .security_queue_at, .airside_at, .at_gate_at,
        .boarded_at, .deplaning_at, .baggage_claim_at, .departed_airport_at,
        .dwell_minutes, .connection_risk
    } AS passenger,
    f { .id, .flight_number, .status, .estimated_time, .scheduled_time } AS flight,
    g.id AS gate_id,
    collect(b { .tag, .status }) AS baggage
    """
    async with driver.session() as session:
        result = await session.run(query, id=passenger_id)
        record = await result.single()
        if not record:
            return None
        pax = dict(record["passenger"])
        flight_data = dict(record["flight"]) if record["flight"] else {}
        flight_data["gate_id"] = record["gate_id"]
        pax["flight"] = flight_data
        pax["baggage"] = [dict(b) for b in record["baggage"]]

        # Build timeline from timestamp fields
        timeline = []
        for status_key, ts_key in [
            ("checked_in", "checked_in_at"),
            ("security_queue", "security_queue_at"),
            ("airside", "airside_at"),
            ("at_gate", "at_gate_at"),
            ("boarded", "boarded_at"),
            ("deplaning", "deplaning_at"),
            ("baggage_claim", "baggage_claim_at"),
            ("departed_airport", "departed_airport_at"),
        ]:
            ts = pax.get(ts_key)
            if ts:
                timeline.append({"status": status_key, "at": ts})
        pax["timeline"] = timeline

        return pax


async def search_passengers(pnr: str | None = None, name: str | None = None) -> list[dict]:
    """Search passengers by PNR or partial name."""
    driver = get_driver()
    if pnr:
        query = """
        MATCH (p:Passenger {pnr: $pnr})-[:ON_FLIGHT]->(f:Flight)
        RETURN p { .id, .name, .pnr, .status, .location_zone } AS passenger,
               f.flight_number AS flight_number
        LIMIT 10
        """
        params = {"pnr": pnr.upper()}
    elif name:
        query = """
        MATCH (p:Passenger)-[:ON_FLIGHT]->(f:Flight)
        WHERE toLower(p.name) CONTAINS toLower($name)
        RETURN p { .id, .name, .pnr, .status, .location_zone } AS passenger,
               f.flight_number AS flight_number
        LIMIT 20
        """
        params = {"name": name}
    else:
        return []

    async with driver.session() as session:
        result = await session.run(query, **params)
        records = [record async for record in result]
    items = []
    for r in records:
        pax = dict(r["passenger"])
        pax["flight_number"] = r["flight_number"]
        items.append(pax)
    return items


async def update_passenger_status(
    passenger_id: str, new_status: str, new_zone: str, sim_time: datetime,
) -> dict | None:
    """Update passenger status and location zone, setting the timestamp field."""
    driver = get_driver()
    ts_field = f"{new_status}_at"
    sim_str = sim_time.isoformat()
    query = f"""
    MATCH (p:Passenger {{id: $id}})
    SET p.status = $status,
        p.location_zone = $zone,
        p.{ts_field} = $ts
    RETURN p.id AS id, p.status AS status, p.location_zone AS zone
    """
    async with driver.session() as session:
        result = await session.run(
            query, id=passenger_id, status=new_status, zone=new_zone, ts=sim_str,
        )
        record = await result.single()
        return dict(record) if record else None


async def bulk_update_status(
    passenger_ids: list[str], new_status: str, new_zone: str, sim_time: datetime,
) -> int:
    """Bulk update status for multiple passengers. Returns count updated."""
    if not passenger_ids:
        return 0
    driver = get_driver()
    ts_field = f"{new_status}_at"
    sim_str = sim_time.isoformat()
    query = f"""
    UNWIND $ids AS pid
    MATCH (p:Passenger {{id: pid}})
    SET p.status = $status,
        p.location_zone = $zone,
        p.{ts_field} = $ts
    RETURN count(p) AS cnt
    """
    async with driver.session() as session:
        result = await session.run(
            query, ids=passenger_ids, status=new_status, zone=new_zone, ts=sim_str,
        )
        record = await result.single()
        return record["cnt"] if record else 0


async def set_passenger_dwell(passenger_id: str, dwell_minutes: int) -> None:
    """Set dwell_minutes on a passenger (sampled once on airside transition)."""
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (p:Passenger {id: $id}) SET p.dwell_minutes = $dwell",
            id=passenger_id, dwell=dwell_minutes,
        )


async def bulk_set_dwell(items: list[tuple[str, int]]) -> None:
    """Batch-set dwell_minutes for multiple passengers in one UNWIND query."""
    if not items:
        return
    driver = get_driver()
    rows = [{"id": pid, "dwell": dwell} for pid, dwell in items]
    async with driver.session() as session:
        await session.run(
            """
            UNWIND $rows AS r
            MATCH (p:Passenger {id: r.id})
            SET p.dwell_minutes = r.dwell
            """,
            rows=rows,
        )


async def set_connection_risk(passenger_id: str, risk: str) -> None:
    """Update connection risk level on a passenger node."""
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (p:Passenger {id: $id}) SET p.connection_risk = $risk",
            id=passenger_id, risk=risk,
        )


async def update_passenger_location(passenger_id: str, new_zone: str) -> None:
    """Update only location_zone for a passenger without changing status timestamps."""
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (p:Passenger {id: $id}) SET p.location_zone = $zone",
            id=passenger_id,
            zone=new_zone,
        )


async def get_zone_density() -> dict[str, int]:
    """Get passenger count per location_zone."""
    driver = get_driver()
    query = """
    MATCH (p:Passenger)
    WHERE p.location_zone IS NOT NULL
      AND NOT p.status IN ['departed_airport', 'boarded']
    RETURN p.location_zone AS zone, count(p) AS n
    """
    async with driver.session() as session:
        result = await session.run(query)
        records = [record async for record in result]
    return {r["zone"]: r["n"] for r in records}


async def get_passengers_by_status(status: str, scheduled_before: str | None = None) -> list[dict]:
    """Get all passengers with a given status.

    If scheduled_before is provided (ISO datetime string), only returns passengers
    on flights with scheduled_time <= that value. This dramatically reduces result
    sets for statuses like 'booked' where most passengers are far from their flight.
    """
    driver = get_driver()
    if scheduled_before:
        query = """
        MATCH (p:Passenger {status: $status})-[:ON_FLIGHT]->(f:Flight)
        WHERE f.scheduled_time <= $before
        OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
        RETURN p.id AS id, p.name AS name, f.id AS flight_id,
               p.special_assistance AS special_assistance,
               p.location_zone AS location_zone,
               p.dwell_minutes AS dwell_minutes,
               p.airside_at AS airside_at,
               p.deplaning_at AS deplaning_at,
               p.baggage_claim_at AS baggage_claim_at,
               p.customs_at AS customs_at,
               p.connection AS connection,
               p.connection_flight_id AS connection_flight_id,
               f.flight_number AS flight_number,
               f.estimated_time AS estimated_time,
               f.scheduled_time AS scheduled_time,
               f.status AS flight_status,
               f.direction AS direction,
               f.flight_type AS flight_type,
               g.id AS gate_id,
               g.terminal_id AS terminal_id
        """
        async with driver.session() as session:
            result = await session.run(query, status=status, before=scheduled_before)
            return [dict(r) async for r in result]
    else:
        query = """
        MATCH (p:Passenger {status: $status})-[:ON_FLIGHT]->(f:Flight)
        OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
        RETURN p.id AS id, p.name AS name, f.id AS flight_id,
               p.special_assistance AS special_assistance,
               p.location_zone AS location_zone,
               p.dwell_minutes AS dwell_minutes,
               p.airside_at AS airside_at,
               p.deplaning_at AS deplaning_at,
               p.baggage_claim_at AS baggage_claim_at,
               p.customs_at AS customs_at,
               p.connection AS connection,
               p.connection_flight_id AS connection_flight_id,
               f.flight_number AS flight_number,
               f.estimated_time AS estimated_time,
               f.scheduled_time AS scheduled_time,
               f.status AS flight_status,
               f.direction AS direction,
               f.flight_type AS flight_type,
               g.id AS gate_id,
               g.terminal_id AS terminal_id
        """
        async with driver.session() as session:
            result = await session.run(query, status=status)
            return [dict(r) async for r in result]


async def get_passengers_by_flight(flight_id: str) -> list[dict]:
    """Get all passengers on a specific flight."""
    driver = get_driver()
    query = """
    MATCH (p:Passenger)-[:ON_FLIGHT]->(f:Flight {id: $fid})
    RETURN p.id AS id, p.name AS name, p.status AS status,
           p.location_zone AS location_zone,
           p.special_assistance AS special_assistance,
           p.connection AS connection,
           p.pnr AS pnr
    """
    async with driver.session() as session:
        result = await session.run(query, fid=flight_id)
        return [dict(r) async for r in result]


async def get_connecting_passengers() -> list[dict]:
    """Get all connecting passengers with their flight info."""
    driver = get_driver()
    query = """
    MATCH (p:Passenger {connection: true})-[:ON_FLIGHT]->(f:Flight)
    WHERE NOT p.status IN ['departed_airport', 'boarded', 'missed_connection']
    OPTIONAL MATCH (cf:Flight {id: p.connection_flight_id})
    OPTIONAL MATCH (p)-[:CARRIES]->(b:Baggage)
    OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(ig:Gate)
    OPTIONAL MATCH (cf)-[:ASSIGNED_TO]->(cg:Gate)
    RETURN p.id AS id, p.name AS name, p.pnr AS pnr,
           p.status AS status, p.connection_risk AS connection_risk,
           p.special_assistance AS special_assistance,
           f.flight_number AS inbound_flight,
           f.delay_minutes AS inbound_delay,
           f.estimated_time AS inbound_estimated,
           f.status AS inbound_status,
           ig.id AS inbound_gate_id,
           cf.flight_number AS connection_flight,
           cf.estimated_time AS connection_estimated,
           cf.scheduled_time AS connection_scheduled,
           cg.id AS connection_gate_id,
           count(b) AS baggage_count
    """
    async with driver.session() as session:
        result = await session.run(query)
        return [dict(r) async for r in result]


async def get_departure_flights_in_window(sim_time: datetime, window_min: int = 90) -> list[dict]:
    """Get departure flights within a time window, grouped by terminal."""
    driver = get_driver()
    end_time = sim_time.isoformat()
    from datetime import timedelta
    window_end = (sim_time + timedelta(minutes=window_min)).isoformat()
    query = """
    MATCH (f:Flight)-[:ASSIGNED_TO]->(g:Gate)
    WHERE f.direction = 'departure'
      AND f.status IN ['scheduled', 'boarding', 'delayed']
      AND f.estimated_time >= $start AND f.estimated_time <= $end
    RETURN g.terminal_id AS terminal_id,
           count(f) AS flight_count,
           sum(f.pax_count) AS total_pax
    """
    async with driver.session() as session:
        result = await session.run(query, start=end_time, end=window_end)
        return [dict(r) async for r in result]


async def get_status_counts() -> dict[str, int]:
    """Get passenger counts by status."""
    driver = get_driver()
    query = """
    MATCH (p:Passenger)
    RETURN p.status AS status, count(p) AS cnt
    """
    async with driver.session() as session:
        result = await session.run(query)
        records = [record async for record in result]
    return {r["status"]: r["cnt"] for r in records if r["status"]}


async def get_alerts(
    alert_type: str | None = None,
    urgency: str | None = None,
    flight_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Get recent alerts from in-memory store (no Neo4j storage for alerts)."""
    # Alerts are stored in-memory and provided via the consumer module
    return []

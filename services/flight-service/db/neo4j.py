"""Neo4j async driver and Flight/Gate/Runway persistence for flight-service."""

import asyncio
import logging
import os
from datetime import datetime

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None

CONSTRAINTS = [
    "CREATE CONSTRAINT flight_id IF NOT EXISTS FOR (f:Flight) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT gate_id IF NOT EXISTS FOR (g:Gate) REQUIRE g.id IS UNIQUE",
    "CREATE CONSTRAINT runway_id IF NOT EXISTS FOR (r:Runway) REQUIRE r.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX flight_number IF NOT EXISTS FOR (f:Flight) ON (f.flight_number)",
    "CREATE INDEX flight_status IF NOT EXISTS FOR (f:Flight) ON (f.status)",
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
    logger.info("Flight constraints and indexes created")


# ---------------------------------------------------------------------------
# Flight CRUD
# ---------------------------------------------------------------------------

async def get_all_flights(
    status: str | None = None,
    direction: str | None = None,
    airline: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return flights with optional filters. Returns (flights, total_count)."""
    driver = get_driver()

    where_clauses = []
    params: dict = {"limit": limit, "offset": offset}

    if status:
        statuses = [s.strip() for s in status.split(",")]
        where_clauses.append("f.status IN $statuses")
        params["statuses"] = statuses
    if direction:
        where_clauses.append("f.direction = $direction")
        params["direction"] = direction
    if airline:
        where_clauses.append("f.airline_code = $airline")
        params["airline"] = airline

    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    count_query = f"MATCH (f:Flight) {where} RETURN count(f) AS total"
    data_query = f"""
    MATCH (f:Flight) {where}
    OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
    OPTIONAL MATCH (f)-[:USES_RUNWAY]->(r:Runway)
    RETURN f {{
        .id, .flight_number, .airline_code, .direction, .status,
        .aircraft_type, .origin_iata, .destination_iata,
        .scheduled_time, .estimated_time, .delay_minutes,
        .pax_count, .seat_capacity
    }} AS flight,
    g.id AS gate_id,
    r.id AS runway_id
    ORDER BY f.scheduled_time ASC
    SKIP $offset LIMIT $limit
    """

    async with driver.session() as session:
        count_result = await session.run(count_query, **params)
        count_record = await count_result.single()
        total = count_record["total"] if count_record else 0

        data_result = await session.run(data_query, **params)
        records = [record async for record in data_result]

    flights = []
    for r in records:
        flight = dict(r["flight"])
        flight["gate_id"] = r["gate_id"]
        flight["runway_id"] = r["runway_id"]
        flights.append(flight)

    return flights, total


async def get_flight_by_id(flight_id: str) -> dict | None:
    """Get a single flight with gate and runway info."""
    driver = get_driver()
    query = """
    MATCH (f:Flight {id: $id})
    OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
    OPTIONAL MATCH (f)-[:USES_RUNWAY]->(r:Runway)
    RETURN f {
        .id, .flight_number, .airline_code, .direction, .status,
        .aircraft_type, .aircraft_registration, .origin_iata, .destination_iata,
        .scheduled_time, .estimated_time, .actual_time,
        .delay_minutes, .delay_reason, .pax_count, .seat_capacity
    } AS flight,
    g { .id, .terminal_id, .jetbridge, .status } AS gate,
    r { .id, .status, .ils } AS runway
    """
    async with driver.session() as session:
        result = await session.run(query, id=flight_id)
        record = await result.single()
        if not record:
            return None
        flight = dict(record["flight"])
        flight["gate"] = dict(record["gate"]) if record["gate"] else None
        flight["runway"] = dict(record["runway"]) if record["runway"] else None
        return flight


async def get_active_flights(sim_time: datetime) -> list[dict]:
    """Get all flights in active (non-terminal) states for FSM processing."""
    driver = get_driver()
    query = """
    MATCH (f:Flight)
    WHERE f.status IN ['scheduled', 'boarding', 'delayed', 'departed', 'airborne', 'approach', 'landed', 'taxiing']
    OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
    OPTIONAL MATCH (f)-[:USES_RUNWAY]->(r:Runway)
    RETURN f {
        .id, .flight_number, .airline_code, .direction, .status,
        .aircraft_type, .aircraft_registration, .origin_iata, .destination_iata,
        .scheduled_time, .estimated_time, .actual_time,
        .delay_minutes, .delay_reason, .pax_count, .seat_capacity
    } AS flight,
    g.id AS gate_id,
    r.id AS runway_id
    """
    async with driver.session() as session:
        result = await session.run(query)
        records = [record async for record in result]

    flights = []
    for r in records:
        flight = dict(r["flight"])
        flight["gate_id"] = r["gate_id"]
        flight["runway_id"] = r["runway_id"]
        flights.append(flight)
    return flights


async def update_flight_status(
    flight_id: str,
    new_status: str,
    sim_time: datetime,
    delay_minutes: int | None = None,
    delay_reason: str | None = None,
    estimated_time: str | None = None,
    actual_time: str | None = None,
) -> dict | None:
    """Update flight status and optional related fields atomically."""
    driver = get_driver()

    set_clauses = ["f.status = $status"]
    params: dict = {"id": flight_id, "status": new_status}

    if delay_minutes is not None:
        set_clauses.append("f.delay_minutes = $delay_minutes")
        params["delay_minutes"] = delay_minutes
    if delay_reason is not None:
        set_clauses.append("f.delay_reason = $delay_reason")
        params["delay_reason"] = delay_reason
    if estimated_time is not None:
        set_clauses.append("f.estimated_time = $estimated_time")
        params["estimated_time"] = estimated_time
    if actual_time is not None:
        set_clauses.append("f.actual_time = $actual_time")
        params["actual_time"] = actual_time

    set_clause = ", ".join(set_clauses)
    query = f"""
    MATCH (f:Flight {{id: $id}})
    SET {set_clause}
    RETURN f {{
        .id, .flight_number, .airline_code, .direction, .status,
        .aircraft_type, .aircraft_registration, .origin_iata, .destination_iata,
        .scheduled_time, .estimated_time, .actual_time,
        .delay_minutes, .delay_reason, .pax_count, .seat_capacity
    }} AS flight
    """
    async with driver.session() as session:
        result = await session.run(query, **params)
        record = await result.single()
        if not record:
            return None
        return dict(record["flight"])


async def apply_delay(
    flight_id: str,
    delay_minutes: int,
    reason: str,
    new_estimated_time: str,
    sim_time: datetime,
) -> dict | None:
    """Apply delay to a flight (set delayed status + update times)."""
    driver = get_driver()
    query = """
    MATCH (f:Flight {id: $id})
    SET f.status = 'delayed',
        f.delay_minutes = $delay_minutes,
        f.delay_reason = $reason,
        f.estimated_time = $estimated_time
    RETURN f {
        .id, .flight_number, .airline_code, .direction, .status,
        .aircraft_type, .aircraft_registration, .origin_iata, .destination_iata,
        .scheduled_time, .estimated_time, .actual_time,
        .delay_minutes, .delay_reason, .pax_count, .seat_capacity
    } AS flight
    """
    async with driver.session() as session:
        result = await session.run(
            query,
            id=flight_id,
            delay_minutes=delay_minutes,
            reason=reason,
            estimated_time=new_estimated_time,
        )
        record = await result.single()
        return dict(record["flight"]) if record else None


# ---------------------------------------------------------------------------
# Gate management
# ---------------------------------------------------------------------------

async def assign_flight_to_gate(flight_id: str, gate_id: str, sim_time: datetime) -> None:
    """Create ASSIGNED_TO relationship between flight and gate. Remove old assignment first."""
    driver = get_driver()
    query = """
    MATCH (f:Flight {id: $flight_id})
    OPTIONAL MATCH (f)-[old:ASSIGNED_TO]->(:Gate)
    DELETE old
    WITH f
    MATCH (g:Gate {id: $gate_id})
    MERGE (f)-[r:ASSIGNED_TO]->(g)
    SET r.assigned_at = $assigned_at,
        g.status = 'occupied',
        g.last_assigned_at = $assigned_at
    """
    async with driver.session() as session:
        await session.run(
            query,
            flight_id=flight_id,
            gate_id=gate_id,
            assigned_at=sim_time.isoformat(),
        )


async def release_gate(flight_id: str) -> str | None:
    """Remove ASSIGNED_TO relationship when flight departs. Returns released gate_id."""
    driver = get_driver()
    query = """
    MATCH (f:Flight {id: $flight_id})-[r:ASSIGNED_TO]->(g:Gate)
    DELETE r
    SET g.status = 'available'
    RETURN g.id AS gate_id
    """
    async with driver.session() as session:
        result = await session.run(query, flight_id=flight_id)
        record = await result.single()
        return record["gate_id"] if record else None


async def get_available_gate(terminal_id: str) -> str | None:
    """Find an available gate in the specified terminal."""
    driver = get_driver()
    query = """
    MATCH (t:Terminal {id: $terminal_id})-[:HAS_GATE]->(g:Gate)
    WHERE g.status = 'available'
      AND NOT EXISTS {
        MATCH (fl:Flight)-[:ASSIGNED_TO]->(g)
        WHERE fl.status IN ['boarding', 'delayed', 'scheduled']
      }
    RETURN g.id AS gate_id
    ORDER BY g.id
    LIMIT 1
    """
    async with driver.session() as session:
        result = await session.run(query, terminal_id=terminal_id)
        record = await result.single()
        return record["gate_id"] if record else None


async def get_all_gates(terminal: str | None = None) -> list[dict]:
    """Get all gates with occupancy info (one row per gate)."""
    driver = get_driver()
    where = "WHERE g.terminal_id = $terminal" if terminal else ""
    params = {"terminal": terminal} if terminal else {}
    query = f"""
    MATCH (g:Gate)
    {where}
    OPTIONAL MATCH (f:Flight)-[:ASSIGNED_TO]->(g)
    WHERE f.status IN ['boarding', 'delayed', 'scheduled', 'landed', 'taxiing', 'at_gate']
    WITH g, f
    ORDER BY f.estimated_time DESC
    WITH g, head(collect(f)) AS f
    RETURN g.id AS id,
           g.terminal_id AS terminal_id,
           g.status AS status,
           g.jetbridge AS jetbridge,
           f.flight_number AS flight_number,
           f.estimated_time AS occupied_until
    ORDER BY g.id
    """
    async with driver.session() as session:
        result = await session.run(query, **params)
        records = [record async for record in result]

    gates = []
    for r in records:
        gates.append({
            "id": r["id"],
            "terminal": r["terminal_id"] or "",
            "status": r["status"],
            "jetbridge": r["jetbridge"],
            "flight_number": r["flight_number"],
            "occupied_until": r["occupied_until"],
        })
    return gates


async def is_gate_occupied(gate_id: str) -> bool:
    """Check if a gate currently has an active flight assigned."""
    driver = get_driver()
    query = """
    MATCH (f:Flight)-[:ASSIGNED_TO]->(g:Gate {id: $gate_id})
    WHERE f.status IN ['boarding', 'delayed', 'scheduled', 'landed', 'taxiing', 'at_gate']
    RETURN count(f) AS count
    """
    async with driver.session() as session:
        result = await session.run(query, gate_id=gate_id)
        record = await result.single()
        return record["count"] > 0 if record else False


# ---------------------------------------------------------------------------
# Runway management
# ---------------------------------------------------------------------------

async def assign_flight_to_runway(flight_id: str, runway_id: str, operation: str, sim_time: datetime) -> None:
    """Create USES_RUNWAY relationship between flight and runway."""
    driver = get_driver()
    query = """
    MATCH (f:Flight {id: $flight_id})
    OPTIONAL MATCH (f)-[old:USES_RUNWAY]->(:Runway)
    DELETE old
    WITH f
    MATCH (r:Runway {id: $runway_id})
    MERGE (f)-[rel:USES_RUNWAY]->(r)
    SET rel.operation = $operation,
        rel.at = $at
    """
    async with driver.session() as session:
        await session.run(
            query,
            flight_id=flight_id,
            runway_id=runway_id,
            operation=operation,
            at=sim_time.isoformat(),
        )


async def get_all_runways() -> list[dict]:
    """Get all runways with current usage info."""
    driver = get_driver()
    query = """
    MATCH (r:Runway)
    OPTIONAL MATCH (f:Flight)-[rel:USES_RUNWAY]->(r)
    WHERE f.status IN ['approach', 'landed', 'departed', 'boarding', 'delayed']
    WITH r,
         sum(CASE WHEN rel.operation = 'landing' AND f.status IN ['approach', 'landed'] THEN 1 ELSE 0 END) AS arr_count,
         sum(CASE WHEN rel.operation = 'takeoff' AND f.status IN ['departed', 'boarding', 'delayed'] THEN 1 ELSE 0 END) AS dep_count
    RETURN r.id AS id,
           r.status AS status,
           r.current_use AS current_use,
           r.ils AS ils,
           arr_count,
           dep_count
    ORDER BY r.id
    """
    async with driver.session() as session:
        result = await session.run(query)
        records = [record async for record in result]

    runways = []
    for rec in records:
        runways.append({
            "id": rec["id"],
            "status": rec["status"],
            "current_use": rec["current_use"],
            "ils": rec["ils"],
            "arrivals_queued": rec["arr_count"],
            "departures_queued": rec["dep_count"],
        })
    return runways


async def get_open_runway(ils_required: bool = False) -> str | None:
    """Find an open runway, optionally requiring ILS."""
    driver = get_driver()
    where = "WHERE r.status = 'open'"
    if ils_required:
        where += " AND r.ils = true"
    query = f"""
    MATCH (r:Runway)
    {where}
    RETURN r.id AS runway_id
    LIMIT 1
    """
    async with driver.session() as session:
        result = await session.run(query)
        record = await result.single()
        return record["runway_id"] if record else None


# ---------------------------------------------------------------------------
# Turnaround queries
# ---------------------------------------------------------------------------

async def get_paired_flight(aircraft_registration: str, direction: str) -> dict | None:
    """Get the paired flight for turnaround (if direction='arrival', get the departure and vice versa)."""
    other_direction = "departure" if direction == "arrival" else "arrival"
    driver = get_driver()
    query = """
    MATCH (f:Flight {aircraft_registration: $reg, direction: $dir})
    RETURN f {
        .id, .flight_number, .status, .direction,
        .scheduled_time, .estimated_time, .delay_minutes, .aircraft_type
    } AS flight
    LIMIT 1
    """
    async with driver.session() as session:
        result = await session.run(query, reg=aircraft_registration, dir=other_direction)
        record = await result.single()
        return dict(record["flight"]) if record else None


async def get_boarded_percentage(flight_id: str) -> float:
    """Get the percentage of passengers boarded on a flight."""
    driver = get_driver()
    query = """
    MATCH (f:Flight {id: $id})
    OPTIONAL MATCH (p:Passenger)-[:ON_FLIGHT]->(f)
    WITH f, count(p) AS total
    OPTIONAL MATCH (p2:Passenger {status: 'boarded'})-[:ON_FLIGHT]->(f)
    RETURN total,
           count(p2) AS boarded,
           CASE WHEN total = 0 THEN 1.0
                ELSE toFloat(count(p2)) / total
           END AS pct
    """
    async with driver.session() as session:
        result = await session.run(query, id=flight_id)
        record = await result.single()
        if not record:
            return 1.0
        return record["pct"]


async def get_cascade_info(flight_id: str) -> dict:
    """Get cascade impact info for a delayed/cancelled flight."""
    driver = get_driver()
    flight = await get_flight_by_id(flight_id)
    if not flight:
        return {}

    # Get connecting passengers at risk
    pax_query = """
    MATCH (p:Passenger {connection: true})-[:ON_FLIGHT]->(f:Flight {id: $id})
    RETURN count(p) AS total,
           count(CASE WHEN p.status <> 'boarded' THEN 1 END) AS at_risk
    """

    # Get baggage count
    bag_query = """
    MATCH (b:Baggage)-[:LOADED_ON]->(f:Flight {id: $id})
    RETURN count(b) AS total
    """

    # Get turnaround info
    turnaround = None
    if flight.get("aircraft_registration"):
        paired = await get_paired_flight(
            flight["aircraft_registration"],
            flight.get("direction", "departure"),
        )
        if paired and paired.get("direction") == "departure":
            turnaround = {
                "next_flight": paired["flight_number"],
                "next_flight_id": paired["id"],
                "propagated_delay_minutes": 0,
            }

    async with driver.session() as session:
        pax_result = await session.run(pax_query, id=flight_id)
        pax_record = await pax_result.single()

        bag_result = await session.run(bag_query, id=flight_id)
        bag_record = await bag_result.single()

    cascade = {
        "connecting_passengers": {
            "count": pax_record["total"] if pax_record else 0,
            "at_risk": pax_record["at_risk"] if pax_record else 0,
        },
        "baggage_held": {
            "count": bag_record["total"] if bag_record else 0,
        },
    }

    if turnaround:
        cascade["turnaround_delay"] = turnaround

    return cascade

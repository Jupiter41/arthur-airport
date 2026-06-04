"""Neo4j async driver and CostRecord persistence for cost-service."""

import os

import structlog
from neo4j import AsyncGraphDatabase, AsyncDriver

from _common.infra import wait_for_neo4j_ready

logger = structlog.get_logger(__name__)

_driver: AsyncDriver | None = None

CONSTRAINTS = [
    "CREATE CONSTRAINT cost_record_id IF NOT EXISTS FOR (c:CostRecord) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT carbon_record_id IF NOT EXISTS FOR (c:CarbonRecord) REQUIRE c.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX cost_record_category IF NOT EXISTS FOR (c:CostRecord) ON (c.category)",
    "CREATE INDEX cost_record_sim_day IF NOT EXISTS FOR (c:CostRecord) ON (c.sim_day)",
    "CREATE INDEX carbon_record_source IF NOT EXISTS FOR (c:CarbonRecord) ON (c.source)",
    "CREATE INDEX carbon_record_sim_day IF NOT EXISTS FOR (c:CarbonRecord) ON (c.sim_day)",
]


async def _init_driver() -> None:
    global _driver
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "art-digital-twin")
    _driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    await _driver.verify_connectivity()


async def _close_driver() -> None:
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


async def wait_for_neo4j(max_attempts: int = 12, delay_s: int = 5) -> None:
    await wait_for_neo4j_ready(
        init_fn=_init_driver,
        close_driver_fn=_close_driver,
        logger=logger,
        max_attempts=max_attempts,
        delay_s=delay_s,
    )


async def check_neo4j() -> bool:
    if _driver is None:
        return False
    try:
        await _driver.verify_connectivity()
        return True
    except Exception:
        return False


async def close_neo4j() -> None:
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


async def create_constraints_and_indexes() -> None:
    if _driver is None:
        return
    async with _driver.session() as session:
        for stmt in CONSTRAINTS + INDEXES:
            await session.run(stmt)
    logger.info("neo4j constraints and indexes created")


async def write_cost_record(record: dict) -> None:
    """Write a single CostRecord node to Neo4j."""
    if _driver is None:
        return
    async with _driver.session() as session:
        await session.run(
            """
            CREATE (c:CostRecord {
                id: $id,
                category: $category,
                amount_eur: $amount_eur,
                currency: 'EUR',
                sim_time: $sim_time,
                sim_day: $sim_day,
                description: $description,
                is_revenue: $is_revenue
            })
            """,
            **record,
        )


async def link_cost_to_flight(cost_id: str, flight_id: str) -> None:
    if _driver is None:
        return
    async with _driver.session() as session:
        await session.run(
            """
            MATCH (c:CostRecord {id: $cost_id})
            MATCH (f:Flight {id: $flight_id})
            MERGE (c)-[:FOR_FLIGHT]->(f)
            """,
            cost_id=cost_id,
            flight_id=flight_id,
        )


async def link_cost_to_incident(cost_id: str, incident_id: str) -> None:
    if _driver is None:
        return
    async with _driver.session() as session:
        await session.run(
            """
            MATCH (c:CostRecord {id: $cost_id})
            MATCH (i:Incident {id: $incident_id})
            MERGE (c)-[:CAUSED_BY]->(i)
            """,
            cost_id=cost_id,
            incident_id=incident_id,
        )


async def link_cost_to_terminal(cost_id: str, terminal_id: str) -> None:
    if _driver is None:
        return
    async with _driver.session() as session:
        await session.run(
            """
            MATCH (c:CostRecord {id: $cost_id})
            MATCH (t:Terminal {id: $terminal_id})
            MERGE (c)-[:FOR_TERMINAL]->(t)
            """,
            cost_id=cost_id,
            terminal_id=terminal_id,
        )


async def link_cost_to_airport_day(cost_id: str, day: int) -> None:
    if _driver is None:
        return
    async with _driver.session() as session:
        await session.run(
            """
            MATCH (c:CostRecord {id: $cost_id})
            MATCH (a:Airport)
            MERGE (c)-[:FOR_DAY {day: $day}]->(a)
            """,
            cost_id=cost_id,
            day=day,
        )


async def get_flight_info(flight_id: str) -> dict | None:
    """Read flight details needed for cost calculations."""
    if _driver is None:
        return None
    async with _driver.session() as session:
        result = await session.run(
            """
            MATCH (f:Flight {id: $id})
            RETURN f.id AS id, f.flight_number AS flight_number,
                   f.aircraft_type AS aircraft_type,
                   f.pax_count AS pax_count,
                   f.direction AS direction,
                   f.distance_km AS distance_km,
                   f.delay_minutes AS delay_minutes,
                   f.seat_capacity AS seat_capacity,
                   f.gate_id AS gate_id
            """,
            id=flight_id,
        )
        record = await result.single()
        return dict(record) if record else None


async def get_holding_flights() -> list[dict]:
    """Get flights in approach status that may be in holding."""
    if _driver is None:
        return []
    async with _driver.session() as session:
        result = await session.run(
            """
            MATCH (f:Flight)
            WHERE f.status = 'approach'
            RETURN f.id AS id, f.aircraft_type AS aircraft_type,
                   f.flight_number AS flight_number
            """
        )
        return [dict(r) async for r in result]


async def rebuild_running_totals() -> dict:
    """Rebuild running totals from Neo4j on restart — only for the latest sim day."""
    if _driver is None:
        return {}
    async with _driver.session() as session:
        # First, determine the latest sim_day in the database
        day_result = await session.run(
            "MATCH (c:CostRecord) RETURN max(c.sim_day) AS latest_day"
        )
        day_record = await day_result.single()
        latest_day = day_record["latest_day"] if day_record and day_record["latest_day"] is not None else 1

        # Now sum only that day's records
        result = await session.run(
            """
            MATCH (c:CostRecord {sim_day: $day})
            RETURN c.is_revenue AS is_revenue, c.category AS category,
                   sum(c.amount_eur) AS total
            """,
            day=latest_day,
        )
        totals: dict = {
            "total_cost_eur": 0.0,
            "total_revenue_eur": 0.0,
            "by_category": {},
            "sim_day": latest_day,
        }
        async for r in result:
            if r["is_revenue"]:
                totals["total_revenue_eur"] += r["total"]
            else:
                totals["total_cost_eur"] += r["total"]
                totals["by_category"][r["category"]] = r["total"]
        totals["net_eur"] = totals["total_revenue_eur"] - totals["total_cost_eur"]
        return totals


# ---------------------------------------------------------------------------
# Carbon (1A — Carbon Footprint Tracker)
# ---------------------------------------------------------------------------

async def write_carbon_record(record: dict) -> None:
    """Persist a CarbonRecord node."""
    if _driver is None:
        return
    async with _driver.session() as session:
        await session.run(
            """
            MERGE (c:CarbonRecord {id: $id})
            SET c += $props
            """,
            id=record["id"],
            props={k: v for k, v in record.items() if k != "id" and v is not None},
        )


async def link_carbon_to_flight(carbon_id: str, flight_id: str) -> None:
    if _driver is None or not flight_id:
        return
    async with _driver.session() as session:
        await session.run(
            """
            MATCH (c:CarbonRecord {id: $cid})
            MATCH (f:Flight {id: $fid})
            MERGE (c)-[:FOR_FLIGHT]->(f)
            """,
            cid=carbon_id,
            fid=flight_id,
        )


async def link_carbon_to_terminal(carbon_id: str, terminal_id: str) -> None:
    if _driver is None or not terminal_id:
        return
    async with _driver.session() as session:
        await session.run(
            """
            MATCH (c:CarbonRecord {id: $cid})
            MERGE (t:Terminal {id: $tid})
            MERGE (c)-[:FOR_TERMINAL]->(t)
            """,
            cid=carbon_id,
            tid=terminal_id,
        )


async def link_carbon_to_airport_day(carbon_id: str, day: int) -> None:
    if _driver is None:
        return
    async with _driver.session() as session:
        await session.run(
            """
            MATCH (c:CarbonRecord {id: $cid})
            MERGE (a:Airport {iata: 'ART'})
            MERGE (c)-[:FOR_DAY {day: $day}]->(a)
            """,
            cid=carbon_id,
            day=int(day),
        )


async def rebuild_carbon_totals() -> dict:
    """Rebuild running carbon totals from Neo4j on restart (latest sim day only)."""
    if _driver is None:
        return {}
    async with _driver.session() as session:
        day_result = await session.run(
            "MATCH (c:CarbonRecord) RETURN max(c.sim_day) AS latest_day"
        )
        day_record = await day_result.single()
        latest_day = (
            day_record["latest_day"] if day_record and day_record["latest_day"] is not None else 1
        )
        result = await session.run(
            """
            MATCH (c:CarbonRecord {sim_day: $day})
            RETURN c.source AS source, sum(c.co2_kg) AS total_kg
            """,
            day=latest_day,
        )
        totals: dict = {"sim_day": latest_day, "total_kg": 0.0, "by_source": {}}
        async for r in result:
            kg = float(r["total_kg"] or 0.0)
            totals["by_source"][r["source"]] = kg
            totals["total_kg"] += kg
        return totals


async def carbon_summary_by_source(sim_day: int | None = None) -> list[dict]:
    """Return per-source totals for the given (or latest) sim day.

    Each row: ``{"source": str, "total_kg": float, "records": int}``.
    """
    if _driver is None:
        return []
    async with _driver.session() as session:
        if sim_day is None:
            day_record = await (await session.run(
                "MATCH (c:CarbonRecord) RETURN max(c.sim_day) AS latest_day"
            )).single()
            sim_day = (
                day_record["latest_day"] if day_record and day_record["latest_day"] is not None else 1
            )
        result = await session.run(
            """
            MATCH (c:CarbonRecord {sim_day: $day})
            RETURN c.source AS source, sum(c.co2_kg) AS total_kg, count(c) AS records
            ORDER BY total_kg DESC
            """,
            day=int(sim_day),
        )
        return [
            {
                "source": r["source"],
                "total_kg": float(r["total_kg"] or 0.0),
                "records": int(r["records"]),
            }
            async for r in result
        ]


async def carbon_hourly_timeline(sim_day: int | None = None) -> list[dict]:
    """Return per-hour CO₂ totals for the given (or latest) sim day."""
    if _driver is None:
        return []
    async with _driver.session() as session:
        if sim_day is None:
            day_record = await (await session.run(
                "MATCH (c:CarbonRecord) RETURN max(c.sim_day) AS latest_day"
            )).single()
            sim_day = (
                day_record["latest_day"] if day_record and day_record["latest_day"] is not None else 1
            )
        result = await session.run(
            """
            MATCH (c:CarbonRecord {sim_day: $day})
            WITH c, toInteger(split(split(c.sim_time, 'T')[1], ':')[0]) AS hour
            RETURN hour, sum(c.co2_kg) AS total_kg
            ORDER BY hour
            """,
            day=int(sim_day),
        )
        return [
            {"hour": int(r["hour"]), "co2_kg": float(r["total_kg"] or 0.0)}
            async for r in result
        ]

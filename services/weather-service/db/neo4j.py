"""Neo4j async driver and WeatherState persistence for weather-service."""

import asyncio
import logging
import os
from datetime import datetime

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None

CONSTRAINTS = [
    "CREATE CONSTRAINT weather_state_id IF NOT EXISTS FOR (w:WeatherState) REQUIRE w.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX weather_state_timestamp IF NOT EXISTS FOR (w:WeatherState) ON (w.timestamp)",
    "CREATE INDEX weather_state_category IF NOT EXISTS FOR (w:WeatherState) ON (w.category)",
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
    logger.info("WeatherState constraints and indexes created")


async def persist_weather_state(
    weather_id: str,
    category: str,
    sim_time: datetime,
    visibility_m: int,
    wind_direction: int,
    wind_speed_kt: int,
    wind_gust_kt: int,
    ceiling_ft: int | None,
    temperature_c: float,
    dew_point_c: float,
    qnh_hpa: int,
    phenomena: list[str],
    runway_impact: str,
) -> None:
    """Create a new WeatherState node and update the chain atomically.

    In a single transaction:
    1. Create the new WeatherState node
    2. Find the current Airport->CURRENT_WEATHER pointer
    3. Link new state via PREVIOUS_WEATHER to the old state
    4. Move the Airport->CURRENT_WEATHER pointer to the new state
    """
    driver = get_driver()
    query = """
    // Create the new WeatherState node
    CREATE (w:WeatherState {
        id: $id,
        timestamp: datetime($timestamp),
        category: $category,
        visibility_m: $visibility_m,
        wind_direction: $wind_direction,
        wind_speed_kt: $wind_speed_kt,
        wind_gust_kt: $wind_gust_kt,
        ceiling_ft: $ceiling_ft,
        temperature_c: $temperature_c,
        dew_point_c: $dew_point_c,
        qnh_hpa: $qnh_hpa,
        phenomena: $phenomena,
        runway_impact: $runway_impact
    })
    WITH w
    // Find the airport node
    MATCH (a:Airport {icao: 'KART'})
    // Optionally find existing current weather
    OPTIONAL MATCH (a)-[old_rel:CURRENT_WEATHER]->(old:WeatherState)
    // Delete old pointer if it exists
    FOREACH (_ IN CASE WHEN old_rel IS NOT NULL THEN [1] ELSE [] END |
        DELETE old_rel
    )
    // Link new state to old state via PREVIOUS_WEATHER
    FOREACH (_ IN CASE WHEN old IS NOT NULL THEN [1] ELSE [] END |
        CREATE (w)-[:PREVIOUS_WEATHER]->(old)
    )
    // Create new pointer
    CREATE (a)-[:CURRENT_WEATHER]->(w)
    RETURN w.id AS id
    """
    async with driver.session() as session:
        await session.run(
            query,
            id=weather_id,
            timestamp=sim_time.isoformat(),
            category=category,
            visibility_m=visibility_m,
            wind_direction=wind_direction,
            wind_speed_kt=wind_speed_kt,
            wind_gust_kt=wind_gust_kt,
            ceiling_ft=ceiling_ft if ceiling_ft is not None else -1,
            temperature_c=temperature_c,
            dew_point_c=dew_point_c,
            qnh_hpa=qnh_hpa,
            phenomena=phenomena,
            runway_impact=runway_impact,
        )
    logger.info("Persisted WeatherState %s (%s) at %s", weather_id, category, sim_time)


async def get_current_weather() -> dict | None:
    """Get the current weather state from Neo4j."""
    driver = get_driver()
    query = """
    MATCH (a:Airport {icao: 'KART'})-[:CURRENT_WEATHER]->(w:WeatherState)
    RETURN w {
        .id, .category, .visibility_m, .wind_direction, .wind_speed_kt,
        .wind_gust_kt, .ceiling_ft, .temperature_c, .dew_point_c,
        .qnh_hpa, .phenomena, .runway_impact,
        timestamp: toString(w.timestamp)
    } AS weather
    """
    async with driver.session() as session:
        result = await session.run(query)
        record = await result.single()
        if record is None:
            return None
        w = dict(record["weather"])
        # Fix ceiling_ft sentinel
        if w.get("ceiling_ft") == -1:
            w["ceiling_ft"] = None
        return w


async def get_weather_history(hours: int = 12) -> list[dict]:
    """Get weather history by traversing the PREVIOUS_WEATHER chain.

    Returns states in chronological order (oldest first).
    Filters by sim_time relative to the current weather's timestamp.
    """
    driver = get_driver()
    query = """
    MATCH (a:Airport {icao: 'KART'})-[:CURRENT_WEATHER]->(current:WeatherState)
    MATCH path = (current)-[:PREVIOUS_WEATHER*0..]->(state:WeatherState)
    WHERE state.timestamp >= current.timestamp - duration({hours: $hours})
    RETURN state {
        .id, .category, .visibility_m, .wind_direction, .wind_speed_kt,
        .wind_gust_kt, .ceiling_ft, .temperature_c, .dew_point_c,
        .qnh_hpa, .phenomena, .runway_impact,
        timestamp: toString(state.timestamp)
    } AS weather
    ORDER BY state.timestamp ASC
    """
    async with driver.session() as session:
        result = await session.run(query, hours=hours)
        records = [record async for record in result]
        states = []
        for record in records:
            w = dict(record["weather"])
            if w.get("ceiling_ft") == -1:
                w["ceiling_ft"] = None
            states.append(w)
        return states

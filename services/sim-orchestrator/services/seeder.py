"""Seeder orchestration — coordinates schedule + passenger + baggage seeding."""

import logging
import os
from datetime import timedelta

from db.neo4j import get_driver
from services.clock import get_sim_time, get_sim_day, SIM_START_TIME
from services.schedule import generate_schedule
from services.passengers import generate_passengers
from services.baggage import generate_baggage, generate_arrival_baggage
from kafka.producer import emit_flight_schedule_seeded, emit_weather_state_changed

logger = logging.getLogger(__name__)

DAILY_FLIGHT_TARGET = int(os.getenv("DAILY_FLIGHT_TARGET", "420"))


async def _day_already_seeded(sim_date) -> bool:
    """Check if flights for this date already exist in Neo4j."""
    driver = get_driver()
    prefix = sim_date.isoformat()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (f:Flight) WHERE f.scheduled_time STARTS WITH $prefix RETURN count(f) AS cnt",
            prefix=prefix,
        )
        record = await result.single()
        return record and record["cnt"] > 0


async def seed_day(sim_day: int) -> None:
    """Seed a full simulated day: flights, passengers, and baggage.

    Idempotent — skips if flights for the target date already exist in Neo4j.
    Uses a deterministic RNG seed derived from the day number so repeated runs
    produce identical data.
    """
    sim_date = (SIM_START_TIME + timedelta(days=sim_day - 1)).date()

    if await _day_already_seeded(sim_date):
        logger.info("Day %d (%s) already seeded — skipping", sim_day, sim_date)
        return

    target_departures = DAILY_FLIGHT_TARGET // 2  # half departures, half arrivals

    logger.info("Seeding day %d (%s): %d departures target", sim_day, sim_date, target_departures)

    # Deterministic seed based on day number
    rng_seed = 42 + sim_day

    # 1. Generate flights
    flights = await generate_schedule(sim_date, target_departures=target_departures, seed=rng_seed)

    # 2. Generate passengers (departures only — arrival pax aren't at the airport)
    departure_flights = [f for f in flights if f["direction"] == "departure"]
    total_pax, passengers = await generate_passengers(departure_flights, seed=rng_seed + 1000)

    # 3. Generate baggage
    total_bags_departure, _ = await generate_baggage(passengers, seed=rng_seed + 2000)
    arrival_flights = [f for f in flights if f["direction"] == "arrival"]
    total_bags_arrival, _ = await generate_arrival_baggage(arrival_flights, seed=rng_seed + 3000)
    total_bags = total_bags_departure + total_bags_arrival

    # 4. Emit FlightScheduleSeeded event
    sim_time = get_sim_time() if get_sim_day() >= 1 else SIM_START_TIME
    emit_flight_schedule_seeded(sim_time, sim_day, flights)

    logger.info(
        "Day %d seeded: %d flights, %d passengers, %d baggage",
        sim_day, len(flights), total_pax, total_bags,
    )


async def emit_initial_weather() -> None:
    """Emit initial CAVOK weather state."""
    sim_time = get_sim_time()
    emit_weather_state_changed(sim_time, "CAVOK")
    logger.info("Initial weather state emitted: CAVOK")

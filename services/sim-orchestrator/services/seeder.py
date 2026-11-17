"""Seeder orchestration — coordinates schedule + passenger + baggage seeding."""

import logging
from datetime import timedelta

from db.neo4j import get_driver
from services.clock import get_sim_time, get_sim_day, SIM_START_TIME
from services.schedule import generate_schedule
from services.passengers import generate_passengers
from services.baggage import generate_baggage, generate_arrival_baggage
from kafka.producer import emit_flight_schedule_seeded, emit_weather_state_changed

logger = logging.getLogger(__name__)


def _daily_flight_target() -> int:
    """Resolve daily flight target from env override or airport config."""
    from services.settings import get_settings
    return get_settings().daily_flights


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


def _check_bhs_capacity(departure_flights: list[dict], bags: list[dict]) -> list[dict]:
    """RC6: warn when a seeded day's bag peak exceeds the BHS headroom."""
    from _common.airport_config import load_airport_runtime_config
    from _common.bhs_capacity import check_capacity, demand_by_terminal_hour

    cfg = load_airport_runtime_config().operations.baggage
    demand = demand_by_terminal_hour(bags, {f["id"]: f for f in departure_flights})
    violations = check_capacity(demand, cfg)
    if violations:
        from metrics import sim_bhs_capacity_violations_total
        for v in violations:
            sim_bhs_capacity_violations_total.labels(scope=v["scope"]).inc()
            logger.warning(
                "BHS sizing: %s peak %d bags at %02dh exceeds %.0f%% of %d/h min-stage capacity",
                v["scope"], v["peak_bags"], v["hour"], cfg.capacity_headroom * 100,
                v["capacity_hr"],
            )
    return violations


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

    target_departures = _daily_flight_target() // 2  # half departures, half arrivals

    logger.info("Seeding day %d (%s): %d departures target", sim_day, sim_date, target_departures)

    # Deterministic seed based on day number
    rng_seed = 42 + sim_day

    # 1. Generate flights
    flights = await generate_schedule(sim_date, target_departures=target_departures, seed=rng_seed)

    # 2. Generate passengers (cargo flights carry freight, not passengers)
    departure_flights = [
        f for f in flights
        if f["direction"] == "departure" and f.get("flight_type") != "cargo"
    ]
    dep_pax, passengers = await generate_passengers(departure_flights, seed=rng_seed + 1000)
    arrival_flights_for_pax = [
        f for f in flights
        if f["direction"] == "arrival" and f.get("flight_type") != "cargo"
    ]
    local_pax: dict[str, int] = {}
    for p in passengers:
        local_pax[p["flight_id"]] = local_pax.get(p["flight_id"], 0) + 1
    free_seats = {f["id"]: max(0, int(f.get("seat_capacity") or 0) - local_pax.get(f["id"], 0))
                  for f in departure_flights}
    arr_pax, arrivals = await generate_passengers(
        arrival_flights_for_pax, seed=rng_seed + 1500, initial_status="airborne",
        onward_departures=departure_flights, onward_free_seats=free_seats,
    )
    # Transfers fly on their onward departure too: count them in its load.
    transfers: dict[str, int] = {}
    for p in arrivals:
        if p["connection_flight_id"]:
            transfers[p["connection_flight_id"]] = transfers.get(p["connection_flight_id"], 0) + 1
    for f in departure_flights:
        f["pax_count"] = local_pax.get(f["id"], 0) + transfers.get(f["id"], 0)
    if transfers:
        from services.passengers import _update_flight_pax_counts
        await _update_flight_pax_counts(
            {fid: local_pax.get(fid, 0) + n for fid, n in transfers.items()})
    total_pax = dep_pax + arr_pax

    # 3. Generate baggage
    flight_type_map = {f["id"]: f.get("flight_type", "") for f in flights}
    total_bags_departure, departure_bags = await generate_baggage(passengers, seed=rng_seed + 2000, flight_type_map=flight_type_map)
    arrival_flights = arrival_flights_for_pax
    total_bags_arrival, _ = await generate_arrival_baggage(arrival_flights, seed=rng_seed + 3000)
    total_bags = total_bags_departure + total_bags_arrival
    _check_bhs_capacity(departure_flights, departure_bags)

    # 4. Emit FlightScheduleSeeded event
    sim_time = get_sim_time() if get_sim_day() >= 1 else SIM_START_TIME
    emit_flight_schedule_seeded(sim_time, sim_day, flights)

    logger.info(
        "Day %d seeded: %d flights, %d passengers, %d baggage",
        sim_day, len(flights), total_pax, total_bags,
    )


async def emit_initial_weather(category: str = "CAVOK") -> None:
    """Emit initial weather state (default CAVOK, overridable for scenarios)."""
    sim_time = get_sim_time()
    emit_weather_state_changed(sim_time, category)
    logger.info("Initial weather state emitted: %s", category)

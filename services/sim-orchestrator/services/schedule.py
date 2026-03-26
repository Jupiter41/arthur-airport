"""Flight schedule generation — bimodal departure distribution + paired arrivals."""

import logging
import random
from datetime import date, datetime, time, timedelta
from uuid import uuid4

import numpy as np

from db.neo4j import get_driver
from services.fixtures import get_fixtures

logger = logging.getLogger(__name__)

# Airline-to-terminal preference mapping built from fixtures
_airline_terminal: dict[str, str] = {}

# Aircraft registration counter per airline
_reg_counters: dict[str, int] = {}


def _build_airline_lookup() -> None:
    """Build airline lookup dicts from fixtures."""
    global _airline_terminal, _reg_counters
    fixtures = get_fixtures()
    for airline in fixtures["airlines"]:
        _airline_terminal[airline["code"]] = airline["preferred_terminal"]
        _reg_counters.setdefault(airline["code"], 0)


def _classify_flight(destination: dict, aircraft: dict) -> tuple[str, str]:
    """Return (flight_type, route_category) based on destination region and aircraft.

    Mapping:
      domestic  → domestic / short_haul
      shorthaul → international_short / medium_haul
      longhaul  → international_long / long_haul
    """
    region = destination.get("region", "domestic")
    if region == "domestic":
        return "domestic", "short_haul"
    elif region == "shorthaul":
        return "international_short", "medium_haul"
    else:  # longhaul
        return "international_long", "long_haul"


def _sample_airline(rng: random.Random) -> dict:
    """Weight-select an airline based on market_share."""
    fixtures = get_fixtures()
    airlines = fixtures["airlines"]
    weights = [a["market_share"] for a in airlines]
    return rng.choices(airlines, weights=weights, k=1)[0]


def _sample_destination(rng: random.Random) -> dict:
    """Weight-select a destination."""
    fixtures = get_fixtures()
    destinations = fixtures["destinations"]
    weights = [d["weight"] for d in destinations]
    return rng.choices(destinations, weights=weights, k=1)[0]


def _sample_aircraft_type(airline: dict, destination: dict, rng: random.Random) -> dict:
    """Select aircraft type considering airline fleet and route distance."""
    fixtures = get_fixtures()
    types_by_icao = {t["icao"]: t for t in fixtures["aircraft_types"]}
    fleet = airline.get("fleet", list(types_by_icao.keys()))
    available = [types_by_icao[icao] for icao in fleet if icao in types_by_icao]
    if not available:
        available = fixtures["aircraft_types"]

    # Filter by range — aircraft must be able to reach destination
    dist = destination["distance_nm"]
    capable = [a for a in available if a["range_nm"] >= dist]
    if not capable:
        capable = available  # fallback

    weights = [a["weight"] for a in capable]
    return rng.choices(capable, weights=weights, k=1)[0]


def _generate_registration(airline_code: str) -> str:
    """Generate a unique aircraft registration."""
    _reg_counters.setdefault(airline_code, 0)
    _reg_counters[airline_code] += 1
    return f"ART-{airline_code}{_reg_counters[airline_code]:03d}"


def _generate_flight_number(airline_code: str, rng: random.Random) -> str:
    """Generate a flight number like AX412."""
    num = rng.randint(100, 999)
    return f"{airline_code}{num}"


def sample_departure_slots(n: int, sim_date: date, np_rng: np.random.Generator) -> list[datetime]:
    """Sample n departure times from a bimodal distribution with peaks at 07:30 and 17:30."""
    peak1 = np_rng.normal(loc=7.5, scale=1.5, size=n // 2)
    peak2 = np_rng.normal(loc=17.5, scale=1.5, size=n - n // 2)
    hours = np.concatenate([peak1, peak2])
    hours = np.clip(hours, 5.0, 23.0)
    slots = []
    for h in sorted(hours):
        hour = int(h)
        minute = int((h - hour) * 60)
        # Round to nearest 5 minutes
        minute = round(minute / 5) * 5
        if minute >= 60:
            hour += 1
            minute = 0
        if hour > 23:
            hour = 23
            minute = 55
        slots.append(datetime.combine(sim_date, time(hour=hour, minute=minute)))
    return slots


def _assign_gate(terminal_pref: str, gate_usage: dict[str, datetime], dep_time: datetime) -> str:
    """Assign a gate from preferred terminal. Falls back to others if full."""
    for t in [terminal_pref, "A", "B", "C"]:
        for n in range(1, GATES_PER_TERMINAL + 1):
            gate_id = f"{t}{n:02d}"
            last_used = gate_usage.get(gate_id)
            if last_used is None or dep_time >= last_used + timedelta(minutes=45):
                gate_usage[gate_id] = dep_time
                return gate_id
    # Absolute fallback — assign first gate in preferred terminal
    return f"{terminal_pref}01"


GATES_PER_TERMINAL = 14
FLIGHT_NUMBER_USED: set[str] = set()


async def generate_schedule(
    sim_date: date,
    target_departures: int = 210,
    seed: int | None = None,
) -> list[dict]:
    """Generate a full day's flight schedule and persist to Neo4j.

    Creates *target_departures* departure flights using a bimodal time
    distribution (peaks at 07:30 and 17:30), plus a paired arrival for
    each departure (90-minute turnaround). Each flight gets an airline,
    destination, aircraft type, gate, and runway assigned.

    Args:
        sim_date: The simulated date for the schedule.
        target_departures: Number of departures to generate (arrivals are equal).
        seed: RNG seed for deterministic generation.

    Returns:
        List of flight dicts ready for Kafka emission.
    """
    _build_airline_lookup()

    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    FLIGHT_NUMBER_USED.clear()

    # Generate departure slots
    dep_slots = sample_departure_slots(target_departures, sim_date, np_rng)

    flights: list[dict] = []
    gate_usage: dict[str, datetime] = {}
    runway_toggle = 0

    for dep_time in dep_slots:
        airline = _sample_airline(rng)
        destination = _sample_destination(rng)
        aircraft = _sample_aircraft_type(airline, destination, rng)
        registration = _generate_registration(airline["code"])

        # Generate unique flight number
        for _ in range(50):
            fn = _generate_flight_number(airline["code"], rng)
            if fn not in FLIGHT_NUMBER_USED:
                FLIGHT_NUMBER_USED.add(fn)
                break

        terminal_pref = _airline_terminal.get(airline["code"], "A")
        gate_id = _assign_gate(terminal_pref, gate_usage, dep_time)

        flight_type, route_category = _classify_flight(destination, aircraft)

        # Departure flight
        dep_id = str(uuid4())
        dep_flight = {
            "id": dep_id,
            "flight_number": fn,
            "airline_code": airline["code"],
            "direction": "departure",
            "status": "scheduled",
            "aircraft_type": aircraft["icao"],
            "aircraft_registration": registration,
            "origin_iata": "ART",
            "destination_iata": destination["iata"],
            "scheduled_time": dep_time.isoformat(),
            "estimated_time": dep_time.isoformat(),
            "delay_minutes": 0,
            "seat_capacity": aircraft["seat_capacity"],
            "pax_count": 0,  # filled by passenger generation
            "gate_id": gate_id,
            "runway_id": "09L" if runway_toggle % 2 == 0 else "09R",
            "flight_type": flight_type,
            "route_category": route_category,
        }
        flights.append(dep_flight)

        # Paired arrival — 90 min before departure (turnaround)
        arr_time = dep_time - timedelta(minutes=90)
        if arr_time < datetime.combine(sim_date, time(4, 0)):
            arr_time = datetime.combine(sim_date, time(4, 0))

        arr_id = str(uuid4())
        arr_fn_suffix = rng.randint(100, 999)
        arr_fn = f"{airline['code']}{arr_fn_suffix}"
        for _ in range(50):
            if arr_fn not in FLIGHT_NUMBER_USED:
                FLIGHT_NUMBER_USED.add(arr_fn)
                break
            arr_fn_suffix = rng.randint(100, 999)
            arr_fn = f"{airline['code']}{arr_fn_suffix}"

        arr_flight = {
            "id": arr_id,
            "flight_number": arr_fn,
            "airline_code": airline["code"],
            "direction": "arrival",
            "status": "scheduled",
            "aircraft_type": aircraft["icao"],
            "aircraft_registration": registration,
            "origin_iata": destination["iata"],
            "destination_iata": "ART",
            "scheduled_time": arr_time.isoformat(),
            "estimated_time": arr_time.isoformat(),
            "delay_minutes": 0,
            "seat_capacity": aircraft["seat_capacity"],
            "pax_count": 0,
            "gate_id": gate_id,
            "runway_id": "27R" if runway_toggle % 2 == 0 else "27L",
            "flight_type": flight_type,
            "route_category": route_category,
        }
        flights.append(arr_flight)
        runway_toggle += 1

    # Write all flights to Neo4j in batches
    await _persist_flights(flights)

    logger.info(
        "Schedule generated: %d flights for %s (%d departures, %d arrivals)",
        len(flights), sim_date, target_departures, target_departures,
    )
    return flights


async def _persist_flights(flights: list[dict]) -> None:
    """Batch-insert flights into Neo4j using UNWIND."""
    driver = get_driver()
    batch_size = 100
    for i in range(0, len(flights), batch_size):
        batch = flights[i : i + batch_size]
        async with driver.session() as session:
            await session.run(
                """
                UNWIND $flights AS f
                MATCH (g:Gate {id: f.gate_id})
                MATCH (r:Runway {id: f.runway_id})
                CREATE (fl:Flight {
                    id: f.id,
                    flight_number: f.flight_number,
                    airline_code: f.airline_code,
                    direction: f.direction,
                    status: f.status,
                    aircraft_type: f.aircraft_type,
                    aircraft_registration: f.aircraft_registration,
                    origin_iata: f.origin_iata,
                    destination_iata: f.destination_iata,
                    scheduled_time: f.scheduled_time,
                    estimated_time: f.estimated_time,
                    delay_minutes: f.delay_minutes,
                    delay_reason: '',
                    seat_capacity: f.seat_capacity,
                    pax_count: f.pax_count,
                    flight_type: f.flight_type,
                    route_category: f.route_category
                })
                CREATE (fl)-[:ASSIGNED_TO]->(g)
                CREATE (fl)-[:USES_RUNWAY {operation: CASE WHEN f.direction = 'departure' THEN 'takeoff' ELSE 'landing' END}]->(r)
                """,
                flights=batch,
            )


async def get_schedule_from_neo4j(sim_date: date | None = None) -> list[dict]:
    """Fetch today's flight schedule from Neo4j."""
    driver = get_driver()
    async with driver.session() as session:
        if sim_date:
            date_prefix = sim_date.isoformat()
            result = await session.run(
                """
                MATCH (f:Flight)
                WHERE f.scheduled_time STARTS WITH $prefix
                OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
                RETURN f, g.id AS gate_id
                ORDER BY f.scheduled_time
                """,
                prefix=date_prefix,
            )
        else:
            result = await session.run(
                """
                MATCH (f:Flight)
                OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
                RETURN f, g.id AS gate_id
                ORDER BY f.scheduled_time
                """
            )
        records = [record async for record in result]
        flights = []
        for record in records:
            props = dict(record["f"])
            props["gate_id"] = record["gate_id"]
            flights.append(props)
        return flights

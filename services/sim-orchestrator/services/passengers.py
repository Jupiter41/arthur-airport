"""Passenger generation — Beta-distributed load factor per flight."""

import logging
import random
import string
from uuid import uuid4

from scipy.stats import beta as beta_dist

from db.neo4j import get_driver
from services.fixtures import get_fixtures

logger = logging.getLogger(__name__)

LOAD_FACTOR_ALPHA = 8
LOAD_FACTOR_BETA = 2  # mean ~0.80

CONNECTION_PROBABILITY = 0.20
SPECIAL_ASSISTANCE_PROBABILITY = 0.05


def _generate_pnr(rng: random.Random) -> str:
    """Generate a 6-character alphanumeric PNR."""
    chars = string.ascii_uppercase + string.digits
    return "".join(rng.choices(chars, k=6))


def _generate_seat(row: int, rng: random.Random) -> str:
    """Generate a seat assignment like 23A."""
    letters = "ABCDEF"
    return f"{row}{rng.choice(letters)}"


async def generate_passengers(
    flights: list[dict],
    seed: int | None = None,
) -> tuple[int, list[dict]]:
    """Generate passengers for all flights and write to Neo4j.

    Returns (total_pax_count, list of passenger dicts).
    """
    rng = random.Random(seed)
    fixtures = get_fixtures()
    first_names = fixtures["first_names"]
    surnames = fixtures["surnames"]
    nationalities = fixtures["nationalities"]
    nat_codes = [n["code"] for n in nationalities]
    nat_weights = [n["weight"] for n in nationalities]

    pnr_set: set[str] = set()
    all_passengers: list[dict] = []
    flight_pax_counts: dict[str, int] = {}

    # Seed scipy RNG
    beta_rng = beta_dist(LOAD_FACTOR_ALPHA, LOAD_FACTOR_BETA)
    beta_rng_state = rng.getstate()  # sync

    for flight in flights:
        seat_cap = flight["seat_capacity"]
        load_factor = float(beta_rng.rvs(random_state=rng.randint(0, 2**31)))
        load_factor = max(0.5, min(1.0, load_factor))
        pax_count = round(seat_cap * load_factor)

        passengers = []
        for i in range(pax_count):
            pid = str(uuid4())
            first = rng.choice(first_names)
            last = rng.choice(surnames)
            nationality = rng.choices(nat_codes, weights=nat_weights, k=1)[0]

            # unique PNR
            pnr = _generate_pnr(rng)
            while pnr in pnr_set:
                pnr = _generate_pnr(rng)
            pnr_set.add(pnr)

            seat = _generate_seat(i // 6 + 1, rng)
            is_connection = rng.random() < CONNECTION_PROBABILITY
            is_special = rng.random() < SPECIAL_ASSISTANCE_PROBABILITY

            pax = {
                "id": pid,
                "name": f"{first} {last}",
                "pnr": pnr,
                "nationality": nationality,
                "status": "checked_in",
                "location_zone": "check-in",
                "seat": seat,
                "special_assistance": is_special,
                "connection": is_connection,
                "connection_flight_id": None,
                "flight_id": flight["id"],
            }
            passengers.append(pax)

        all_passengers.extend(passengers)
        flight_pax_counts[flight["id"]] = pax_count

    # Write to Neo4j in batches
    await _persist_passengers(all_passengers)

    # Update pax_count on flights
    await _update_flight_pax_counts(flight_pax_counts)

    logger.info("Generated %d passengers for %d flights", len(all_passengers), len(flights))
    return len(all_passengers), all_passengers


async def _persist_passengers(passengers: list[dict]) -> None:
    """Batch-insert passengers into Neo4j and create BOOKED_ON relationships."""
    driver = get_driver()
    batch_size = 2000
    for i in range(0, len(passengers), batch_size):
        batch = passengers[i : i + batch_size]
        async with driver.session() as session:
            await session.run(
                """
                UNWIND $passengers AS p
                MATCH (f:Flight {id: p.flight_id})
                CREATE (pax:Passenger {
                    id: p.id,
                    name: p.name,
                    pnr: p.pnr,
                    nationality: p.nationality,
                    status: p.status,
                    location_zone: p.location_zone,
                    seat: p.seat,
                    special_assistance: p.special_assistance,
                    connection: p.connection,
                    connection_flight_id: p.connection_flight_id
                })
                CREATE (pax)-[:ON_FLIGHT]->(f)
                """,
                passengers=batch,
            )


async def _update_flight_pax_counts(counts: dict[str, int]) -> None:
    """Update pax_count on Flight nodes."""
    driver = get_driver()
    items = [{"id": fid, "pax_count": cnt} for fid, cnt in counts.items()]
    batch_size = 200
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        async with driver.session() as session:
            await session.run(
                """
                UNWIND $items AS item
                MATCH (f:Flight {id: item.id})
                SET f.pax_count = item.pax_count
                """,
                items=batch,
            )

"""Baggage generation — Poisson-distributed bag count per passenger."""

import logging
import random
from uuid import uuid4

import numpy as np

from db.neo4j import get_driver
from services.fixtures import get_fixtures

logger = logging.getLogger(__name__)

POISSON_LAMBDA = 1.2
DG_PROBABILITY = 0.002
WEIGHT_MEAN_KG = 18.0
WEIGHT_STD_KG = 4.0
WEIGHT_MIN_KG = 2.0
WEIGHT_MAX_KG = 32.0


def _generate_tag(counter: int) -> str:
    """Generate a 10-digit barcode tag."""
    return f"{counter:010d}"


async def generate_baggage(
    passengers: list[dict],
    seed: int | None = None,
) -> tuple[int, list[dict]]:
    """Generate baggage for all passengers and write to Neo4j.

    Returns (total_bag_count, list of baggage dicts).
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    fixtures = get_fixtures()
    dg_classes = fixtures["dg_classes"]
    dg_class_ids = [d["class"] for d in dg_classes]

    all_baggage: list[dict] = []
    tag_counter = 1

    for pax in passengers:
        bag_count = int(np_rng.poisson(POISSON_LAMBDA))
        bag_count = min(bag_count, 5)  # reasonable cap

        for _ in range(bag_count):
            bag_id = str(uuid4())
            tag = _generate_tag(tag_counter)
            tag_counter += 1

            weight = float(np_rng.normal(WEIGHT_MEAN_KG, WEIGHT_STD_KG))
            weight = max(WEIGHT_MIN_KG, min(WEIGHT_MAX_KG, round(weight, 1)))

            is_dg = rng.random() < DG_PROBABILITY
            dg_class = rng.choice(dg_class_ids) if is_dg else None

            bag = {
                "id": bag_id,
                "tag": tag,
                "weight_kg": weight,
                "status": "dropped_off",
                "is_dangerous_goods": is_dg,
                "dg_class": dg_class,
                "last_scan_zone": "check-in",
                "last_scan_at": None,
                "carousel": None,
                "passenger_id": pax["id"],
                "flight_id": pax["flight_id"],
            }
            all_baggage.append(bag)

    # Write to Neo4j in batches
    await _persist_baggage(all_baggage)

    logger.info("Generated %d baggage items for %d passengers", len(all_baggage), len(passengers))
    return len(all_baggage), all_baggage


async def generate_arrival_baggage(
    arrival_flights: list[dict],
    seed: int | None = None,
) -> tuple[int, list[dict]]:
    """Generate inbound baggage for arrival flights.

    Arrival baggage starts as already loaded in aircraft hold and will move
    to carousel when the arrival reaches at_gate.
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    fixtures = get_fixtures()
    dg_classes = fixtures["dg_classes"]
    dg_class_ids = [d["class"] for d in dg_classes]

    all_baggage: list[dict] = []
    tag_counter = 5_000_000_000
    flight_pax_counts: dict[str, int] = {}

    for flight in arrival_flights:
        seat_capacity = int(flight.get("seat_capacity") or 0)
        if seat_capacity <= 0:
            continue

        # Synthetic inbound load factor around 80%.
        load_factor = max(0.5, min(1.0, float(np_rng.normal(0.8, 0.12))))
        pax_count = max(1, round(seat_capacity * load_factor))
        bag_count = int(np_rng.poisson(max(1.0, pax_count * POISSON_LAMBDA)))
        bag_count = max(1, min(bag_count, seat_capacity * 3))

        # Track pax_count to update the arrival Flight node
        flight_pax_counts[flight["id"]] = pax_count

        for _ in range(bag_count):
            bag_id = str(uuid4())
            tag = _generate_tag(tag_counter)
            tag_counter += 1

            weight = float(np_rng.normal(WEIGHT_MEAN_KG, WEIGHT_STD_KG))
            weight = max(WEIGHT_MIN_KG, min(WEIGHT_MAX_KG, round(weight, 1)))

            is_dg = rng.random() < DG_PROBABILITY
            dg_class = rng.choice(dg_class_ids) if is_dg else None

            bag = {
                "id": bag_id,
                "tag": tag,
                "weight_kg": weight,
                "status": "in_hold",
                "is_dangerous_goods": is_dg,
                "dg_class": dg_class,
                "last_scan_zone": "aircraft-hold",
                "last_scan_at": None,
                "carousel": None,
                "flight_id": flight["id"],
            }
            all_baggage.append(bag)

    await _persist_arrival_baggage(all_baggage)

    # Update pax_count on arrival Flight nodes only if no Passenger nodes were created.
    # When generate_passengers has already seeded arrival Passenger nodes, the
    # authoritative pax_count is set there — skip overwriting.
    # if flight_pax_counts:
    #     await _update_arrival_pax_counts(flight_pax_counts)

    logger.info(
        "Generated %d inbound baggage items for %d arrival flights",
        len(all_baggage),
        len(arrival_flights),
    )
    return len(all_baggage), all_baggage


async def _persist_baggage(baggage: list[dict]) -> None:
    """Batch-insert baggage into Neo4j and create relationships."""
    driver = get_driver()
    batch_size = 2000
    for i in range(0, len(baggage), batch_size):
        batch = baggage[i : i + batch_size]
        async with driver.session() as session:
            # Create baggage nodes + relationships in a single query
            await session.run(
                """
                UNWIND $baggage AS b
                MATCH (pax:Passenger {id: b.passenger_id})
                MATCH (f:Flight {id: b.flight_id})
                CREATE (bag:Baggage {
                    id: b.id,
                    tag: b.tag,
                    weight_kg: b.weight_kg,
                    status: b.status,
                    is_dangerous_goods: b.is_dangerous_goods,
                    dg_class: b.dg_class,
                    last_scan_zone: b.last_scan_zone,
                    last_scan_at: b.last_scan_at,
                    carousel: b.carousel
                })
                CREATE (pax)-[:CARRIES]->(bag)
                CREATE (bag)-[:LOADED_ON]->(f)
                """,
                baggage=batch,
            )


async def _persist_arrival_baggage(baggage: list[dict]) -> None:
    """Batch-insert inbound baggage linked directly to arrival flights."""
    if not baggage:
        return

    driver = get_driver()
    batch_size = 2000
    for i in range(0, len(baggage), batch_size):
        batch = baggage[i : i + batch_size]
        async with driver.session() as session:
            await session.run(
                """
                UNWIND $baggage AS b
                MATCH (f:Flight {id: b.flight_id})
                CREATE (bag:Baggage {
                    id: b.id,
                    tag: b.tag,
                    weight_kg: b.weight_kg,
                    status: b.status,
                    is_dangerous_goods: b.is_dangerous_goods,
                    dg_class: b.dg_class,
                    last_scan_zone: b.last_scan_zone,
                    last_scan_at: b.last_scan_at,
                    carousel: b.carousel
                })
                CREATE (bag)-[:LOADED_ON]->(f)
                """,
                baggage=batch,
            )


async def _update_arrival_pax_counts(counts: dict[str, int]) -> None:
    """Update pax_count on arrival Flight nodes (synthetic — no Passenger nodes exist)."""
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

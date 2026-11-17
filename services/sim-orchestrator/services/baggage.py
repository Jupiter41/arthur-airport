"""Baggage generation — Poisson-distributed bag count per passenger."""

import logging
import random
from uuid import uuid4

import numpy as np

from db.neo4j import get_driver
from services.fixtures import get_fixtures

logger = logging.getLogger(__name__)

DG_PROBABILITY = 0.002
WEIGHT_MEAN_KG = 18.0
WEIGHT_STD_KG = 4.0
WEIGHT_MIN_KG = 2.0
WEIGHT_MAX_KG = 32.0


def _bag_config():
    """RC6: checked-bag λ by flight type lives in config/airport.yaml."""
    from _common.airport_config import load_airport_runtime_config
    return load_airport_runtime_config().operations.baggage


def _generate_tag(counter: int) -> str:
    """Generate a 10-digit barcode tag from a globally-unique counter."""
    return f"{counter:010d}"


def _unique_tag_start() -> int:
    """Return a high, random starting counter to avoid collisions with existing tags."""
    import time
    # Use timestamp-based offset + random jitter to avoid collisions across calls
    base = int(time.time() * 1000) % 9_000_000_000 + 1_000_000_000
    return base + random.randint(0, 999_999)


async def generate_baggage(
    passengers: list[dict],
    seed: int | None = None,
    flight_type_map: dict[str, str] | None = None,
) -> tuple[int, list[dict]]:
    """Generate baggage for all passengers and write to Neo4j.

    Args:
        passengers: list of passenger dicts with at least {id, flight_id}
        seed: RNG seed
        flight_type_map: optional flight_id → flight_type lookup for per-type lambda

    Returns (total_bag_count, list of baggage dicts).
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    fixtures = get_fixtures()
    dg_classes = fixtures["dg_classes"]
    dg_class_ids = [d["class"] for d in dg_classes]

    all_baggage: list[dict] = []
    tag_counter = _unique_tag_start()
    cfg = _bag_config()

    for pax in passengers:
        # Checked bags per passenger ~ Poisson(λ by flight type). Zero is a
        # valid outcome (carry-on only): no one-bag floor (RC6).
        flight_id = pax.get("flight_id", "")
        lam = cfg.bags_lambda((flight_type_map or {}).get(flight_id, ""))
        bag_count = int(np_rng.poisson(lam)) if lam > 0 else 0
        bag_count = min(bag_count, cfg.max_bags_per_pax)

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
    arrival_passengers: list[dict] | None = None,
) -> tuple[int, list[dict]]:
    """Generate inbound baggage for arrival flights.

    Arrival baggage starts as already loaded in aircraft hold and will move
    to carousel when the arrival reaches at_gate.

    With ``arrival_passengers`` the flight's load is its seeded passengers, and
    connecting passengers (``connection_flight_id`` set) get their own transfer
    bags: ``CARRIES`` from the passenger, ``transfer_flight_id`` = the onward
    departure (baggage-service routes them through the BHS onto it). Anonymous
    bags are drawn for the other passengers only.
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    # Separate stream: transfer bags leave the anonymous draws unchanged.
    transfer_rng = np.random.default_rng(None if seed is None else seed + 17)
    pax_by_flight: dict[str, list[dict]] = {}
    for pax in arrival_passengers or []:
        pax_by_flight.setdefault(pax["flight_id"], []).append(pax)
    transfer_bags: list[dict] = []
    fixtures = get_fixtures()
    dg_classes = fixtures["dg_classes"]
    dg_class_ids = [d["class"] for d in dg_classes]

    all_baggage: list[dict] = []
    tag_counter = _unique_tag_start()
    flight_pax_counts: dict[str, int] = {}
    cfg = _bag_config()

    for flight in arrival_flights:
        seat_capacity = int(flight.get("seat_capacity") or 0)
        if seat_capacity <= 0:
            continue

        # Synthetic inbound load factor around 80%.
        load_factor = max(0.5, min(1.0, float(np_rng.normal(0.8, 0.12))))
        pax_count = max(1, round(seat_capacity * load_factor))
        lam = cfg.bags_lambda(flight.get("flight_type"))
        flight_pax = pax_by_flight.get(flight["id"])
        if flight_pax is not None:
            connecting = [p for p in flight_pax if p.get("connection_flight_id")]
            pax_count = len(flight_pax) - len(connecting)
            for pax in connecting:
                n = int(transfer_rng.poisson(lam)) if lam > 0 else 0
                for _ in range(min(n, cfg.max_bags_per_pax)):
                    weight = float(transfer_rng.normal(WEIGHT_MEAN_KG, WEIGHT_STD_KG))
                    transfer_bags.append({
                        "id": str(uuid4()),
                        "tag": _generate_tag(tag_counter),
                        "weight_kg": max(WEIGHT_MIN_KG, min(WEIGHT_MAX_KG, round(weight, 1))),
                        "status": "in_hold",
                        "is_dangerous_goods": False,
                        "dg_class": None,
                        "last_scan_zone": "aircraft-hold",
                        "last_scan_at": None,
                        "carousel": None,
                        "flight_id": flight["id"],
                        "passenger_id": pax["id"],
                        "transfer_flight_id": pax["connection_flight_id"],
                    })
                    tag_counter += 1
        bag_count = int(np_rng.poisson(max(0, pax_count) * lam)) if lam > 0 else 0
        bag_count = min(bag_count, seat_capacity * cfg.max_bags_per_pax)
        if bag_count == 0:
            continue

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
    await _persist_transfer_baggage(transfer_bags)
    all_baggage.extend(transfer_bags)

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
            # MERGE on tag to avoid ConstraintError on duplicate tags
            await session.run(
                """
                UNWIND $baggage AS b
                MATCH (pax:Passenger {id: b.passenger_id})
                MATCH (f:Flight {id: b.flight_id})
                MERGE (bag:Baggage {tag: b.tag})
                ON CREATE SET
                    bag.id = b.id,
                    bag.weight_kg = b.weight_kg,
                    bag.status = b.status,
                    bag.is_dangerous_goods = b.is_dangerous_goods,
                    bag.dg_class = b.dg_class,
                    bag.last_scan_zone = b.last_scan_zone,
                    bag.last_scan_at = b.last_scan_at,
                    bag.carousel = b.carousel
                FOREACH (_ IN CASE WHEN bag.last_scan_at IS NULL THEN [1] ELSE [] END |
                    SET bag:UnscannedBaggage)
                MERGE (pax)-[:CARRIES]->(bag)
                MERGE (bag)-[:LOADED_ON]->(f)
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
            # MERGE on tag to avoid ConstraintError on duplicate tags
            await session.run(
                """
                UNWIND $baggage AS b
                MATCH (f:Flight {id: b.flight_id})
                MERGE (bag:Baggage {tag: b.tag})
                ON CREATE SET
                    bag.id = b.id,
                    bag.weight_kg = b.weight_kg,
                    bag.status = b.status,
                    bag.is_dangerous_goods = b.is_dangerous_goods,
                    bag.dg_class = b.dg_class,
                    bag.last_scan_zone = b.last_scan_zone,
                    bag.last_scan_at = b.last_scan_at,
                    bag.carousel = b.carousel
                FOREACH (_ IN CASE WHEN bag.last_scan_at IS NULL THEN [1] ELSE [] END |
                    SET bag:UnscannedBaggage)
                MERGE (bag)-[:LOADED_ON]->(f)
                """,
                baggage=batch,
            )


async def _persist_transfer_baggage(baggage: list[dict]) -> None:
    """Transfer bags: in the inbound hold, carried by the connecting passenger."""
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
                MATCH (pax:Passenger {id: b.passenger_id})
                MATCH (f:Flight {id: b.flight_id})
                MERGE (bag:Baggage {tag: b.tag})
                ON CREATE SET
                    bag.id = b.id,
                    bag.weight_kg = b.weight_kg,
                    bag.status = b.status,
                    bag.is_dangerous_goods = b.is_dangerous_goods,
                    bag.dg_class = b.dg_class,
                    bag.last_scan_zone = b.last_scan_zone,
                    bag.last_scan_at = b.last_scan_at,
                    bag.carousel = b.carousel,
                    bag.transfer_flight_id = b.transfer_flight_id
                FOREACH (_ IN CASE WHEN bag.last_scan_at IS NULL THEN [1] ELSE [] END |
                    SET bag:UnscannedBaggage)
                MERGE (pax)-[:CARRIES]->(bag)
                MERGE (bag)-[:LOADED_ON]->(f)
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

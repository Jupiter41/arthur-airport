"""Baggage generation — Poisson-distributed bag count per passenger."""

import logging
import random
from uuid import uuid4

import numpy as np

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
    """Generate a provisional barcode; the baggage owner allocates the final tag."""
    return f"{counter:010d}"


def _unique_tag_start() -> int:
    """Return a provisional counter; this is not a global uniqueness guarantee."""
    import time
    # Use timestamp-based offset + random jitter to avoid collisions across calls
    base = int(time.time() * 1000) % 9_000_000_000 + 1_000_000_000
    return base + random.randint(0, 999_999)


async def generate_baggage(
    passengers: list[dict],
    seed: int | None = None,
    flight_type_map: dict[str, str] | None = None,
) -> tuple[int, list[dict]]:
    """Generate a baggage manifest without domain writes.

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

    logger.info("Generated %d baggage items for %d passengers", len(all_baggage), len(passengers))
    return len(all_baggage), all_baggage


async def generate_arrival_baggage(
    arrival_flights: list[dict],
    seed: int | None = None,
    arrival_passengers: list[dict] | None = None,
) -> tuple[int, list[dict]]:
    """Inbound bags belong to named passengers, including local arrivals.

    The same per-passenger Poisson/cap distribution is used in both directions.
    No anonymous substitute load is invented when a manifest is absent.
    """
    types = {f["id"]: f.get("flight_type", "") for f in arrival_flights}
    passengers = [p for p in arrival_passengers or [] if p["flight_id"] in types]
    count, bags = await generate_baggage(passengers, seed=seed, flight_type_map=types)
    by_id = {p["id"]: p for p in passengers}
    for bag in bags:
        bag.update(status="in_hold", last_scan_zone="aircraft-hold")
        bag["transfer_flight_id"] = by_id[bag["passenger_id"]].get("connection_flight_id")
    logger.info("Generated %d inbound bags for %d passengers", count, len(passengers))
    return count, bags

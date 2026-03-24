"""Zone density tracker — in-memory counts rebuilt from Neo4j on startup.

Hot path: updated incrementally on each state change. Never queries Neo4j per tick.
"""

from collections import defaultdict

from db.neo4j import get_driver

# Zone capacity definitions (from SPEC §7)
ZONE_CAPACITIES: dict[str, int] = {
    "check-in-A": 200, "check-in-B": 200, "check-in-C": 200,
    "security-A": 120, "security-B": 120, "security-C": 120,
    "airside-A": 800, "airside-B": 800, "airside-C": 800,
    "arrivals-hall": 500,
    "baggage-claim": 900,  # 6 carousels × 150
}

# Gate capacities default to 180 per gate
DEFAULT_GATE_CAPACITY = 180
DEFAULT_CAROUSEL_CAPACITY = 150

_zone_density: dict[str, int] = defaultdict(int)


def get_density() -> dict[str, int]:
    """Get current zone density snapshot."""
    return dict(_zone_density)


def get_zone_count(zone: str) -> int:
    return _zone_density.get(zone, 0)


def get_capacity(zone: str) -> int:
    """Get capacity for a zone."""
    if zone in ZONE_CAPACITIES:
        return ZONE_CAPACITIES[zone]
    if zone.startswith("gate-"):
        return DEFAULT_GATE_CAPACITY
    if zone.startswith("carousel-"):
        return DEFAULT_CAROUSEL_CAPACITY
    return 500  # default


def move_passenger(old_zone: str | None, new_zone: str) -> None:
    """Update density when a passenger moves zones."""
    if old_zone:
        _zone_density[old_zone] = max(0, _zone_density[old_zone] - 1)
    _zone_density[new_zone] += 1


def remove_passenger(zone: str) -> None:
    """Remove a passenger from a zone (e.g. departed_airport)."""
    _zone_density[zone] = max(0, _zone_density[zone] - 1)


async def rebuild_from_neo4j() -> None:
    """Rebuild zone density from Neo4j on startup."""
    global _zone_density
    _zone_density = defaultdict(int)

    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (p:Passenger) WHERE p.location_zone IS NOT NULL "
            "AND NOT p.status IN ['departed_airport', 'boarded'] "
            "RETURN p.location_zone AS zone, count(p) AS n"
        )
        async for record in result:
            _zone_density[record["zone"]] = record["n"]


def get_terminal_queue_depth(terminal: str) -> int:
    """Get security queue depth for a terminal."""
    return _zone_density.get(f"security-{terminal}", 0)


def get_heatmap_zones() -> list[dict]:
    """Build heatmap zone list for REST API."""
    zones = []
    for zone_id, density in sorted(_zone_density.items()):
        if density <= 0:
            continue
        capacity = get_capacity(zone_id)
        load_pct = round((density / capacity) * 100, 1) if capacity > 0 else 0
        zones.append({
            "zone_id": zone_id,
            "density": density,
            "capacity": capacity,
            "load_pct": load_pct,
        })
    return zones

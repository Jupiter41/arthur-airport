"""Zone density tracker — in-memory counts rebuilt from Neo4j on startup.

Hot path: updated incrementally on each state change. Never queries Neo4j per tick.
"""

from collections import defaultdict

from db.neo4j import get_driver

# Zone capacity definitions — physical space limits for heatmap display.
# Values calibrated against sim throughput: 420 flights/day, ~50K pax,
# 3 terminals × 14 gates.  These represent the comfortable maximum
# occupancy; the heatmap turns red above ~85%.
ZONE_CAPACITIES: dict[str, int] = {
    "check-in-A": 2000, "check-in-B": 2000, "check-in-C": 2000,
    "security-A": 500, "security-B": 500, "security-C": 500,
    "airside-A": 2000, "airside-B": 2000, "airside-C": 2000,
    "arrivals-hall": 1000,
    "baggage-claim": 1500,  # 6 carousels × 250
    "customs": 800,
}

# Gate capacities default to 180 per gate (single-gate hold room)
DEFAULT_GATE_CAPACITY = 180
DEFAULT_CAROUSEL_CAPACITY = 400

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
    """Build heatmap zone list for REST API.

    Returns all predefined zones (even with 0 density) so the dashboard
    always has a complete heatmap grid.
    """
    zones = []

    # Predefined zones that the dashboard expects
    expected_zones = list(ZONE_CAPACITIES.keys())
    for n in range(1, 7):
        expected_zones.append(f"carousel-{n}")

    # Include predefined zones plus any dynamically populated ones (e.g. gate zones)
    all_zone_ids = set(expected_zones) | set(_zone_density.keys())

    for zone_id in sorted(all_zone_ids):
        density = _zone_density.get(zone_id, 0)
        capacity = get_capacity(zone_id)
        load_pct = round((density / capacity) * 100, 1) if capacity > 0 else 0

        # Derive zone_type and terminal from zone_id
        parts = zone_id.rsplit("-", 1)
        terminal = parts[-1] if len(parts) == 2 and parts[-1] in ("A", "B", "C") else ""
        zone_type = parts[0] if terminal else zone_id.split("-")[0]

        zones.append({
            "zone_id": zone_id,
            "zone_type": zone_type,
            "terminal": terminal,
            "density": density,
            "capacity": capacity,
            "load_pct": load_pct,
        })
    return zones

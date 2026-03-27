"""Airport structure seeding — idempotent, runs once at startup."""

import logging

from db.neo4j import get_driver
from services.fixtures import get_fixtures

logger = logging.getLogger(__name__)

TERMINALS = ["A", "B", "C"]
GATES_PER_TERMINAL = 14
RUNWAYS = ["09L", "27R", "09R", "27L"]

# Gate capability map: terminal → (international_capable gate range, wide_body_capable gate range)
# Terminal A: main international hub — all international, first 6 wide-body
# Terminal B: mixed — first 10 international, first 4 wide-body
# Terminal C: domestic only — no international, first 2 wide-body (overflow/cargo)
GATE_CAPABILITIES: dict[str, dict[str, set[int]]] = {
    "A": {"international": set(range(1, 15)), "wide_body": set(range(1, 7))},
    "B": {"international": set(range(1, 11)), "wide_body": set(range(1, 5))},
    "C": {"international": set(), "wide_body": set(range(1, 3))},
}


async def airport_exists() -> bool:
    """Check if the Airport node already exists in Neo4j."""
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (a:Airport {icao: 'KART'}) RETURN a LIMIT 1"
        )
        record = await result.single()
        return record is not None


async def seed_airport_structure() -> None:
    """Seed the static airport structure: Airport, Terminals, Gates, Runways.

    Uses MERGE for full idempotency — safe to re-run on restart.
    Includes spatial positions from layout.json fixture.
    """
    driver = get_driver()
    layout = get_fixtures().get("layout", {})
    terminal_positions = layout.get("terminals", {})
    gate_positions = layout.get("gates", {})
    runway_positions = layout.get("runways", {})

    async with driver.session() as session:
        # Airport node
        await session.run(
            "MERGE (a:Airport {icao: 'KART'}) "
            "SET a.iata = 'ART', "
            "    a.name = 'Arthur International Airport', "
            "    a.timezone = 'America/Arthur', "
            "    a.total_gates = 42, "
            "    a.created_at = datetime()"
        )

        # Terminals + Gates
        for t in TERMINALS:
            tid = f"T-{t}"
            tpos = terminal_positions.get(tid, {})
            await session.run(
                "MERGE (t:Terminal {id: $tid}) "
                "SET t.name = $name, t.gate_count = $gc, t.open = true, "
                "    t.position_x = $px, t.position_y = $py "
                "WITH t "
                "MATCH (a:Airport {icao: 'KART'}) "
                "MERGE (a)-[:HAS_TERMINAL]->(t)",
                tid=tid,
                name=f"Terminal {t}",
                gc=GATES_PER_TERMINAL,
                px=tpos.get("x", 500),
                py=tpos.get("y", 400),
            )
            for n in range(1, GATES_PER_TERMINAL + 1):
                gate_id = f"{t}{n:02d}"
                caps = GATE_CAPABILITIES[t]
                intl = n in caps["international"]
                wb = n in caps["wide_body"]
                gpos = gate_positions.get(gate_id, {})
                await session.run(
                    "MERGE (g:Gate {id: $gid}) "
                    "SET g.terminal_id = $tid, g.status = 'available', "
                    "    g.pier = $pier, g.jetbridge = true, "
                    "    g.international_capable = $intl, "
                    "    g.wide_body_capable = $wb, "
                    "    g.last_assigned_at = null, "
                    "    g.position_x = $px, g.position_y = $py "
                    "WITH g "
                    "MATCH (t:Terminal {id: $tid}) "
                    "MERGE (t)-[:HAS_GATE]->(g)",
                    gid=gate_id,
                    tid=tid,
                    pier=t,
                    intl=intl,
                    wb=wb,
                    px=gpos.get("x", 500),
                    py=gpos.get("y", 400),
                )

        # Runways
        for rwy in RUNWAYS:
            rpos = runway_positions.get(rwy, {})
            await session.run(
                "MERGE (r:Runway {id: $id}) "
                "SET r.status = 'open', "
                "    r.current_use = 'idle', "
                "    r.surface = 'asphalt', "
                "    r.length_m = 3500, "
                "    r.ils = ($id IN ['09L', '27R']), "
                "    r.threshold_x = $tx, r.threshold_y = $ty "
                "WITH r "
                "MATCH (a:Airport {icao: 'KART'}) "
                "MERGE (a)-[:HAS_RUNWAY]->(r)",
                id=rwy,
                tx=rpos.get("threshold_x", 500),
                ty=rpos.get("threshold_y", 800),
            )

    logger.info(
        "Airport structure seeded: 1 Airport, %d Terminals, %d Gates, %d Runways",
        len(TERMINALS),
        len(TERMINALS) * GATES_PER_TERMINAL,
        len(RUNWAYS),
    )

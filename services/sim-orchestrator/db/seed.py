"""Airport structure seeding — idempotent, runs once at startup."""

import logging

from db.neo4j import get_driver

logger = logging.getLogger(__name__)

TERMINALS = ["A", "B", "C"]
GATES_PER_TERMINAL = 14
RUNWAYS = ["09L", "27R", "09R", "27L"]


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
    """
    driver = get_driver()
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
            await session.run(
                "MERGE (t:Terminal {id: $tid}) "
                "SET t.name = $name, t.gate_count = $gc, t.open = true "
                "WITH t "
                "MATCH (a:Airport {icao: 'KART'}) "
                "MERGE (a)-[:HAS_TERMINAL]->(t)",
                tid=tid,
                name=f"Terminal {t}",
                gc=GATES_PER_TERMINAL,
            )
            for n in range(1, GATES_PER_TERMINAL + 1):
                gate_id = f"{t}{n:02d}"
                await session.run(
                    "MERGE (g:Gate {id: $gid}) "
                    "SET g.terminal_id = $tid, g.status = 'available', "
                    "    g.pier = $pier, g.jetbridge = true, "
                    "    g.last_assigned_at = null "
                    "WITH g "
                    "MATCH (t:Terminal {id: $tid}) "
                    "MERGE (t)-[:HAS_GATE]->(g)",
                    gid=gate_id,
                    tid=tid,
                    pier=t,
                )

        # Runways
        for rwy in RUNWAYS:
            await session.run(
                "MERGE (r:Runway {id: $id}) "
                "SET r.status = 'open', "
                "    r.current_use = 'idle', "
                "    r.surface = 'asphalt', "
                "    r.length_m = 3500, "
                "    r.ils = ($id IN ['09L', '27R']) "
                "WITH r "
                "MATCH (a:Airport {icao: 'KART'}) "
                "MERGE (a)-[:HAS_RUNWAY]->(r)",
                id=rwy,
            )

    logger.info(
        "Airport structure seeded: 1 Airport, %d Terminals, %d Gates, %d Runways",
        len(TERMINALS),
        len(TERMINALS) * GATES_PER_TERMINAL,
        len(RUNWAYS),
    )

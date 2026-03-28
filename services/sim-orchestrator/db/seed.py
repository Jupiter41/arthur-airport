"""Airport structure seeding — idempotent, runs once at startup."""

import logging

from db.neo4j import get_driver
from services.airport_config import load_airport_runtime_config
from services.fixtures import get_fixtures

logger = logging.getLogger(__name__)

def _gate_capability_flags(terminal_idx: int, gate_number: int, gate_count: int) -> tuple[bool, bool]:
    """Return (international_capable, wide_body_capable) for a gate.

    Capability defaults remain intentionally conservative and deterministic:
    - First terminal: all international, first 40% wide-body.
    - Second terminal: first 70% international, first 25% wide-body.
    - Remaining terminals: domestic-first, first 15% wide-body for overflow.
    """
    if terminal_idx == 0:
        intl_cutoff = gate_count
        wide_cutoff = max(1, round(gate_count * 0.40))
    elif terminal_idx == 1:
        intl_cutoff = max(1, round(gate_count * 0.70))
        wide_cutoff = max(1, round(gate_count * 0.25))
    else:
        intl_cutoff = 0
        wide_cutoff = max(1, round(gate_count * 0.15))

    return gate_number <= intl_cutoff, gate_number <= wide_cutoff


async def airport_exists() -> bool:
    """Check if the Airport node already exists in Neo4j."""
    runtime = load_airport_runtime_config()
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (a:Airport {icao: $icao}) RETURN a LIMIT 1",
            icao=runtime.identity.icao,
        )
        record = await result.single()
        return record is not None


async def seed_airport_structure() -> None:
    """Seed the static airport structure: Airport, Terminals, Gates, Runways.

    Uses MERGE for full idempotency — safe to re-run on restart.
    Includes spatial positions from layout.json fixture.
    """
    driver = get_driver()
    runtime = load_airport_runtime_config()
    layout = get_fixtures().get("layout", {})
    terminal_positions = layout.get("terminals", {})
    gate_positions = layout.get("gates", {})
    runway_positions = layout.get("runways", {})
    terminal_codes = runtime.terminal_codes
    gates_per_terminal = runtime.gates_per_terminal_map
    total_gates = runtime.total_gates
    runway_directions = runtime.runway_directions

    async with driver.session() as session:
        # Airport node
        await session.run(
            "MERGE (a:Airport {icao: $icao}) "
            "SET a.iata = $iata, "
            "    a.name = $name, "
            "    a.timezone = $timezone, "
            "    a.total_gates = $total_gates, "
            "    a.created_at = datetime()",
            icao=runtime.identity.icao,
            iata=runtime.identity.iata,
            name=runtime.identity.name,
            timezone=runtime.identity.timezone,
            total_gates=total_gates,
        )

        # Terminals + Gates
        for terminal_idx, t in enumerate(terminal_codes):
            tid = f"T-{t}"
            tpos = terminal_positions.get(tid, {})
            fallback_terminal_y = 150 + terminal_idx * 250
            await session.run(
                "MERGE (t:Terminal {id: $tid}) "
                "SET t.name = $name, t.gate_count = $gc, t.open = true, "
                "    t.position_x = $px, t.position_y = $py "
                "WITH t "
                "MATCH (a:Airport {icao: $icao}) "
                "MERGE (a)-[:HAS_TERMINAL]->(t)",
                tid=tid,
                name=f"Terminal {t}",
                gc=gates_per_terminal[t],
                px=tpos.get("x", 500),
                py=tpos.get("y", fallback_terminal_y),
                icao=runtime.identity.icao,
            )
            for n in range(1, gates_per_terminal[t] + 1):
                gate_id = f"{t}{n:02d}"
                intl, wb = _gate_capability_flags(terminal_idx, n, gates_per_terminal[t])
                gpos = gate_positions.get(gate_id, {})
                gate_spacing = 780 / max(1, gates_per_terminal[t] - 1)
                fallback_gate_x = round(110 + (n - 1) * gate_spacing)
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
                    px=gpos.get("x", fallback_gate_x),
                    py=gpos.get("y", fallback_terminal_y),
                )

        # Runways
        for runway_idx, rwy in enumerate(runway_directions):
            rwy_id = rwy["id"]
            rpos = runway_positions.get(rwy_id, {})
            if not rpos:
                fallback_y = 800 + runway_idx * 50
                rpos = {
                    "threshold_x": 100,
                    "threshold_y": fallback_y,
                    "end_x": 900,
                    "end_y": fallback_y,
                }
            await session.run(
                "MERGE (r:Runway {id: $id}) "
                "SET r.status = 'open', "
                "    r.current_use = 'idle', "
                "    r.surface = 'asphalt', "
                "    r.length_m = $length_m, "
                "    r.ils = $ils, "
                "    r.threshold_x = $tx, r.threshold_y = $ty, "
                "    r.end_x = $ex, r.end_y = $ey "
                "WITH r "
                "MATCH (a:Airport {icao: $icao}) "
                "MERGE (a)-[:HAS_RUNWAY]->(r)",
                id=rwy_id,
                length_m=rwy["length_m"],
                ils=rwy["ils"],
                tx=rpos.get("threshold_x", 500),
                ty=rpos.get("threshold_y", 800),
                ex=rpos.get("end_x", 500),
                ey=rpos.get("end_y", 820),
                icao=runtime.identity.icao,
            )

    logger.info(
        "Airport structure seeded: 1 Airport, %d Terminals, %d Gates, %d Runways",
        len(terminal_codes),
        total_gates,
        len(runway_directions),
    )

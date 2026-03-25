"""Neo4j async driver and Incident persistence for incident-service."""

import asyncio
import logging
import os
from datetime import datetime

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None

CONSTRAINTS = [
    "CREATE CONSTRAINT incident_id IF NOT EXISTS FOR (i:Incident) REQUIRE i.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX incident_type IF NOT EXISTS FOR (i:Incident) ON (i.type)",
    "CREATE INDEX incident_status IF NOT EXISTS FOR (i:Incident) ON (i.status)",
]


async def init_neo4j() -> None:
    global _driver
    _driver = AsyncGraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "art-digital-twin"),
        ),
    )
    await _driver.verify_connectivity()
    logger.info("Neo4j driver initialized")


async def close_neo4j() -> None:
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


def get_driver() -> AsyncDriver:
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialised")
    return _driver


async def check_neo4j() -> bool:
    try:
        if _driver is None:
            return False
        await _driver.verify_connectivity()
        return True
    except Exception:
        return False


async def wait_for_neo4j(max_attempts: int = 12, delay_s: float = 5) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            await init_neo4j()
            return
        except Exception as e:
            wait = delay_s * min(attempt, 6)
            logger.warning(
                "Neo4j not ready (attempt %d/%d): %s — retrying in %.0fs",
                attempt, max_attempts, e, wait,
            )
            if _driver:
                try:
                    await _driver.close()
                except Exception:
                    pass
            await asyncio.sleep(wait)
    raise RuntimeError(f"Neo4j not reachable after {max_attempts} attempts")


async def create_constraints_and_indexes() -> None:
    async with get_driver().session() as session:
        for stmt in CONSTRAINTS + INDEXES:
            await session.run(stmt)
    logger.info("Neo4j constraints and indexes created")


# ── Incident CRUD ──────────────────────────────────────────────


async def create_incident_node(incident: dict) -> None:
    """Create an Incident node in Neo4j."""
    async with get_driver().session() as session:
        await session.run(
            """
            CREATE (i:Incident {
                id: $id,
                type: $type,
                severity: $severity,
                status: $status,
                trigger: $trigger,
                title: $title,
                location: $location,
                description: $description,
                protocol: $protocol,
                started_at: $started_at,
                resolved_at: $resolved_at,
                contained_at: $contained_at,
                ttr_minutes: $ttr_minutes,
                ttr_remaining: $ttr_remaining,
                cascade_depth: $cascade_depth,
                subtype: $subtype
            })
            """,
            id=incident["id"],
            type=incident["type"],
            severity=incident["severity"],
            status=incident["status"],
            trigger=incident["trigger"],
            title=incident.get("title", ""),
            location=incident["location"],
            description=incident.get("description", ""),
            protocol=incident.get("protocol", ""),
            started_at=incident["started_at"],
            resolved_at=incident.get("resolved_at"),
            contained_at=incident.get("contained_at"),
            ttr_minutes=incident.get("ttr_minutes"),
            ttr_remaining=incident.get("ttr_remaining"),
            cascade_depth=incident.get("cascade_depth", 0),
            subtype=incident.get("subtype", ""),
        )


async def create_spawned_relationship(
    parent_id: str, child_id: str, reason: str, sim_time: datetime
) -> None:
    """Create (:Incident)-[:SPAWNED]->(:Incident) relationship."""
    async with get_driver().session() as session:
        await session.run(
            """
            MATCH (parent:Incident {id: $parent_id})
            MATCH (child:Incident {id: $child_id})
            CREATE (parent)-[:SPAWNED {reason: $reason, at: $at}]->(child)
            """,
            parent_id=parent_id,
            child_id=child_id,
            reason=reason,
            at=sim_time.isoformat(),
        )


_ALLOWED_AFFECTS_LABELS = frozenset({"Flight", "Gate", "Runway"})


async def create_affects_relationship(
    incident_id: str, entity_label: str, entity_id: str, impact: str
) -> None:
    """Create (:Incident)-[:AFFECTS]->(Entity) relationship."""
    if entity_label not in _ALLOWED_AFFECTS_LABELS:
        raise ValueError(f"Invalid entity label: {entity_label}")
    async with get_driver().session() as session:
        await session.run(
            f"""
            MATCH (i:Incident {{id: $incident_id}})
            MATCH (e:{entity_label} {{id: $entity_id}})
            MERGE (i)-[r:AFFECTS]->(e)
            SET r.impact = $impact
            """,
            incident_id=incident_id,
            entity_id=entity_id,
            impact=impact,
        )


async def get_flights_at_gate(gate_id: str) -> list[str]:
    """Return flight IDs currently assigned to a gate."""
    async with get_driver().session() as session:
        result = await session.run(
            """
            MATCH (f:Flight)-[:ASSIGNED_TO]->(g:Gate {id: $gate_id})
            WHERE NOT f.status IN ['departed', 'airborne', 'cancelled']
            RETURN f.id AS id
            """,
            gate_id=gate_id,
        )
        return [r["id"] async for r in result]


async def get_flights_on_runway(runway_id: str) -> list[str]:
    """Return flight IDs currently using a runway."""
    async with get_driver().session() as session:
        result = await session.run(
            """
            MATCH (f:Flight)-[:USES_RUNWAY]->(r:Runway {id: $runway_id})
            WHERE f.status IN ['approach', 'landed', 'taxiing', 'departed']
            RETURN f.id AS id
            """,
            runway_id=runway_id,
        )
        return [r["id"] async for r in result]


async def get_incident_by_id(incident_id: str) -> dict | None:
    """Get a single incident by ID."""
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (i:Incident {id: $id}) RETURN i",
            id=incident_id,
        )
        record = await result.single()
        if not record:
            return None
        return dict(record["i"])


async def get_incidents(
    status: str | None = None,
    type_filter: str | None = None,
    severity: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Get filtered list of incidents."""
    conditions = []
    params: dict = {"limit": limit}

    if status:
        conditions.append("i.status = $status")
        params["status"] = status
    if type_filter:
        conditions.append("i.type = $type_filter")
        params["type_filter"] = type_filter
    if severity:
        conditions.append("i.severity = $severity")
        params["severity"] = severity

    where_clause = " AND ".join(conditions)
    if where_clause:
        where_clause = "WHERE " + where_clause

    query = f"""
        MATCH (i:Incident)
        {where_clause}
        RETURN i
        ORDER BY i.started_at DESC
        LIMIT $limit
    """

    async with get_driver().session() as session:
        result = await session.run(query, **params)
        records = await result.data()
        return [dict(r["i"]) for r in records]


async def get_active_incidents_with_ttr() -> list[dict]:
    """Get all active incidents that have a TTR countdown."""
    async with get_driver().session() as session:
        result = await session.run(
            """
            MATCH (i:Incident)
            WHERE i.status = 'active' AND i.ttr_remaining IS NOT NULL
            RETURN i
            """
        )
        records = await result.data()
        return [dict(r["i"]) for r in records]


async def update_ttr_remaining(incident_id: str, ttr_remaining: int) -> None:
    """Update TTR remaining for an incident."""
    async with get_driver().session() as session:
        await session.run(
            """
            MATCH (i:Incident {id: $id})
            SET i.ttr_remaining = $ttr_remaining
            """,
            id=incident_id,
            ttr_remaining=ttr_remaining,
        )


async def update_incident_status(
    incident_id: str,
    new_status: str,
    sim_time: datetime,
    note: str = "",
) -> dict | None:
    """Update incident status (contain or resolve)."""
    time_field = "resolved_at" if new_status == "resolved" else "contained_at"
    async with get_driver().session() as session:
        result = await session.run(
            f"""
            MATCH (i:Incident {{id: $id}})
            SET i.status = $status,
                i.{time_field} = $at,
                i.resolution_note = $note
            RETURN i
            """,
            id=incident_id,
            status=new_status,
            at=sim_time.isoformat(),
            note=note,
        )
        record = await result.single()
        return dict(record["i"]) if record else None


async def get_cascade_tree(incident_id: str) -> list[dict]:
    """Get full cascade tree for an incident via SPAWNED relationships."""
    async with get_driver().session() as session:
        result = await session.run(
            """
            MATCH path = (root:Incident {id: $incident_id})-[:SPAWNED*0..5]->(child:Incident)
            RETURN child, length(path) AS depth
            ORDER BY depth
            """,
            incident_id=incident_id,
        )
        records = await result.data()
        return [{"depth": r["depth"], **dict(r["child"])} for r in records]


async def get_cascade_children(incident_id: str) -> list[dict]:
    """Get direct children of an incident."""
    async with get_driver().session() as session:
        result = await session.run(
            """
            MATCH (parent:Incident {id: $id})-[:SPAWNED]->(child:Incident)
            RETURN child
            """,
            id=incident_id,
        )
        records = await result.data()
        return [dict(r["child"]) for r in records]


async def get_affected_flights(incident_id: str) -> list[dict]:
    """Get flights affected by an incident (and its cascade children)."""
    async with get_driver().session() as session:
        result = await session.run(
            """
            MATCH (root:Incident {id: $id})-[:SPAWNED*0..5]->(i:Incident)
            MATCH (i)-[:AFFECTS]->(f:Flight)
            RETURN DISTINCT f.id AS id, f.flight_number AS flight_number,
                   f.delay_minutes AS delay_minutes, f.status AS status
            """,
            id=incident_id,
        )
        records = await result.data()
        return records


async def count_incidents(status: str | None = None) -> int:
    """Count incidents, optionally filtered by status."""
    if status:
        query = "MATCH (i:Incident {status: $status}) RETURN count(i) AS total"
        params = {"status": status}
    else:
        query = "MATCH (i:Incident) RETURN count(i) AS total"
        params = {}

    async with get_driver().session() as session:
        result = await session.run(query, **params)
        record = await result.single()
        return record["total"] if record else 0


async def get_all_active_incidents() -> list[dict]:
    """Get all active incidents."""
    async with get_driver().session() as session:
        result = await session.run(
            """
            MATCH (i:Incident)
            WHERE i.status IN ['active', 'contained']
            RETURN i
            ORDER BY i.started_at DESC
            """
        )
        records = await result.data()
        return [dict(r["i"]) for r in records]


async def find_active_incident_by_type_and_location(
    incident_type: str, location: str
) -> dict | None:
    """Find an active incident of a given type at a specific location."""
    async with get_driver().session() as session:
        result = await session.run(
            """
            MATCH (i:Incident {type: $type, location: $location})
            WHERE i.status IN ['active', 'contained']
            RETURN i
            LIMIT 1
            """,
            type=incident_type,
            location=location,
        )
        record = await result.single()
        return dict(record["i"]) if record else None


async def resolve_children(incident_id: str, sim_time: datetime) -> list[str]:
    """Resolve all children of an incident recursively."""
    async with get_driver().session() as session:
        result = await session.run(
            """
            MATCH (root:Incident {id: $id})-[:SPAWNED*1..5]->(child:Incident)
            WHERE child.status <> 'resolved'
            SET child.status = 'resolved',
                child.resolved_at = $at
            RETURN child.id AS child_id
            """,
            id=incident_id,
            at=sim_time.isoformat(),
        )
        records = await result.data()
        return [r["child_id"] for r in records]

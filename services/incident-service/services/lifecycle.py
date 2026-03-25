"""Incident lifecycle — create, contain, resolve, TTR countdown."""

import logging
import random
from datetime import datetime, timedelta
from uuid import uuid4

from db.neo4j import (
    create_incident_node,
    create_spawned_relationship,
    create_affects_relationship,
    get_active_incidents_with_ttr,
    get_incident_by_id,
    get_flights_at_gate,
    get_flights_on_runway,
    resolve_children,
    update_incident_status,
    update_ttr_remaining,
)

logger = logging.getLogger(__name__)

# ── TTR ranges (simulated minutes) ───────────────────────────

TTR_RANGES: dict[str, tuple[int, int] | None] = {
    "runway_incursion": (15, 45),
    "baggage_fire": (20, 60),
    "security_breach": (30, 90),
    "system_failure": (10, 120),
    "severe_weather": None,
    "security_congestion": None,
    # Cascade child types — inherit short TTR from parent context
    "runway_closure_holding_stack": (10, 35),
    "departure_ground_stop": (8, 30),
    "gate_congestion": (5, 20),
    "zone_lockdown": (20, 70),
    "security_queue_frozen": (15, 50),
    "boarding_delayed": (10, 40),
    "flight_delayed": (10, 40),
    "make_up_zone_offline": (15, 45),
    "flight_baggage_not_loaded": (10, 35),
    "runway_capacity_reduction": None,
    "holding_stack": None,
    "departure_ground_delay": None,
    "flight_delays_cascade": None,
    "baggage_throughput_reduction": (10, 60),
    "make_up_delay": (10, 40),
    "flight_departure_delay": (10, 40),
}


def sample_ttr(incident_type: str) -> int | None:
    r = TTR_RANGES.get(incident_type)
    return random.randint(*r) if r else None


# ── Default descriptions ─────────────────────────────────────

DEFAULT_DESCRIPTIONS: dict[str, str] = {
    "runway_incursion": "Vehicle or aircraft detected on active runway without clearance.",
    "baggage_fire": "Fire or dangerous goods hazard detected in baggage handling area.",
    "security_breach": "Unauthorized individual or object detected in restricted zone.",
    "severe_weather": "Weather conditions degraded to instrument flight rules.",
    "system_failure": "Infrastructure failure detected in airport systems.",
    "security_congestion": "Security queue wait time exceeds operational threshold.",
}

# ── Protocol mapping ─────────────────────────────────────────

PROTOCOLS: dict[str, dict[str, str]] = {
    "runway_incursion": {"high": "RUNWAY_STOP", "critical": "RUNWAY_STOP"},
    "baggage_fire": {"medium": "BAGGAGE_HOLD", "high": "BAGGAGE_HOLD"},
    "security_breach": {
        "medium": "ZONE_LOCKDOWN",
        "high": "TERMINAL_LOCKDOWN",
        "critical": "FULL_EVACUATION",
    },
    "severe_weather": {"medium": "LOW_VIS_PROCEDURES", "critical": "LOW_VIS_PROCEDURES"},
    "system_failure": {},
    "security_congestion": {},
}

# ── Valid status transitions ─────────────────────────────────

VALID_TRANSITIONS = {
    "active": {"contained", "resolved"},
    "contained": {"resolved"},
    "resolved": set(),
}


# Callbacks — set by main.py/consumer.py at startup
_on_incident_created = None
_on_incident_status_changed = None
_on_cascade = None


def set_lifecycle_callbacks(
    on_created=None, on_status_changed=None, on_cascade=None
):
    global _on_incident_created, _on_incident_status_changed, _on_cascade
    _on_incident_created = on_created
    _on_incident_status_changed = on_status_changed
    _on_cascade = on_cascade


async def create_incident(
    type: str,
    severity: str,
    location: str,
    trigger: str,
    sim_time: datetime,
    description: str = "",
    cascade_depth: int = 0,
    parent_id: str | None = None,
    subtype: str = "",
) -> dict:
    """Create a new incident: write to Neo4j, produce events, trigger cascades."""
    incident_id = str(uuid4())
    ttr = sample_ttr(type)

    protocol = ""
    proto_map = PROTOCOLS.get(type, {})
    if severity in proto_map:
        protocol = proto_map[severity]

    title = f"{type.replace('_', ' ').title()} — {location}"
    desc = description or DEFAULT_DESCRIPTIONS.get(type, "")

    estimated_resolution = None
    if ttr is not None:
        estimated_resolution = (sim_time + timedelta(minutes=ttr)).isoformat()

    incident = {
        "id": incident_id,
        "type": type,
        "severity": severity,
        "status": "active",
        "trigger": trigger,
        "title": title,
        "location": location,
        "description": desc,
        "protocol": protocol,
        "started_at": sim_time.isoformat(),
        "resolved_at": None,
        "contained_at": None,
        "ttr_minutes": ttr,
        "ttr_remaining": ttr,
        "cascade_depth": cascade_depth,
        "subtype": subtype,
        "estimated_resolution_at": estimated_resolution,
    }

    # Persist to Neo4j
    await create_incident_node(incident)

    # Create AFFECTS relationships for impacted infrastructure and flights
    await _link_affects(incident_id, location, type)

    # Activate protocol in the protocol lifecycle manager
    if protocol:
        from services.protocols import get_protocol_manager
        get_protocol_manager().activate(protocol, incident_id)

    # Create SPAWNED relationship if this is a cascade child
    if parent_id:
        await create_spawned_relationship(
            parent_id, incident_id, f"cascade:{type}", sim_time
        )

    # Notify — producer will emit IncidentCreated + IncidentAlert
    if _on_incident_created:
        await _on_incident_created(incident, sim_time, parent_id)

    # Evaluate cascades
    from services.cascade import evaluate_cascades
    await evaluate_cascades(incident, sim_time)

    logger.info(
        "Incident created: %s type=%s severity=%s location=%s depth=%d ttr=%s",
        incident_id[:8], type, severity, location, cascade_depth, ttr,
    )

    return incident


async def contain_incident(incident_id: str, sim_time: datetime, note: str = "") -> dict | None:
    """Mark an incident as contained."""
    incident = await get_incident_by_id(incident_id)
    if not incident:
        return None
    if incident["status"] not in VALID_TRANSITIONS or "contained" not in VALID_TRANSITIONS.get(
        incident["status"], set()
    ):
        return None

    updated = await update_incident_status(incident_id, "contained", sim_time, note)

    if _on_incident_status_changed and updated:
        await _on_incident_status_changed(updated, "contained", sim_time, note)

    logger.info("Incident contained: %s", incident_id[:8])
    return updated


async def resolve_incident(incident_id: str, sim_time: datetime, note: str = "") -> dict | None:
    """Mark an incident as resolved and resolve all children."""
    incident = await get_incident_by_id(incident_id)
    if not incident:
        return None
    if incident["status"] == "resolved":
        return incident

    updated = await update_incident_status(incident_id, "resolved", sim_time, note)

    # Deactivate protocol in the protocol lifecycle manager
    protocol = incident.get("protocol")
    if protocol:
        from services.protocols import get_protocol_manager
        get_protocol_manager().deactivate(protocol, incident_id)

    # Resolve children
    child_ids = await resolve_children(incident_id, sim_time)
    for child_id in child_ids:
        child = await get_incident_by_id(child_id)
        if child and _on_incident_status_changed:
            await _on_incident_status_changed(child, "resolved", sim_time, "parent resolved")

    if _on_incident_status_changed and updated:
        await _on_incident_status_changed(updated, "resolved", sim_time, note)

    logger.info(
        "Incident resolved: %s (+ %d children)", incident_id[:8], len(child_ids)
    )
    return updated


async def tick_ttr(sim_time: datetime) -> None:
    """Advance TTR countdown for all active incidents. Auto-resolve when TTR reaches 0."""
    active = await get_active_incidents_with_ttr()
    for incident in active:
        ttr = incident.get("ttr_remaining")
        if ttr is None:
            continue
        ttr -= 1
        await update_ttr_remaining(incident["id"], ttr)
        if ttr <= 0:
            await resolve_incident(
                incident["id"], sim_time, note="Auto-resolved: TTR elapsed"
            )


async def _link_affects(incident_id: str, location: str, incident_type: str) -> None:
    """Create AFFECTS relationships from incident to impacted infrastructure and flights."""
    loc_lower = location.lower()
    impact = incident_type.replace("_", " ")

    try:
        if "runway" in loc_lower:
            runway_id = location.replace("runway-", "")
            await create_affects_relationship(incident_id, "Runway", runway_id, impact)
            flight_ids = await get_flights_on_runway(runway_id)
            for fid in flight_ids:
                await create_affects_relationship(incident_id, "Flight", fid, impact)
            if flight_ids:
                logger.info("Incident %s AFFECTS runway %s + %d flights", incident_id[:8], runway_id, len(flight_ids))

        if "gate" in loc_lower:
            gate_id = location.replace("gate-", "")
            await create_affects_relationship(incident_id, "Gate", gate_id, impact)
            flight_ids = await get_flights_at_gate(gate_id)
            for fid in flight_ids:
                await create_affects_relationship(incident_id, "Flight", fid, impact)
            if flight_ids:
                logger.info("Incident %s AFFECTS gate %s + %d flights", incident_id[:8], gate_id, len(flight_ids))
    except Exception as e:
        logger.error("Failed to create AFFECTS links for incident %s: %s", incident_id[:8], e)

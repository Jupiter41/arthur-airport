"""Incident report builder — structured JSON for each incident."""

import logging
from datetime import datetime

from db.neo4j import get_incident_by_id, get_cascade_tree, get_affected_flights

logger = logging.getLogger(__name__)

# ── Recommendations per type ─────────────────────────────────

RECOMMENDATIONS: dict[str, list[str]] = {
    "runway_incursion": [
        "Review ground vehicle tracking procedures.",
        "Consider additional runway guard installations.",
        "Audit ATC frequency monitoring compliance.",
    ],
    "baggage_fire": [
        "Inspect baggage screening equipment calibration.",
        "Review DG acceptance procedures.",
        "Schedule fire suppression system maintenance.",
    ],
    "security_breach": [
        "Review CCTV coverage in affected zone.",
        "Conduct access control audit.",
        "Evaluate security staffing during peak hours.",
    ],
    "severe_weather": [
        "Review de-icing fluid inventory levels.",
        "Validate CAT II/III ILS approach procedures.",
        "Confirm pilot weather briefing protocols.",
    ],
    "system_failure": [
        "Schedule preventive maintenance for affected systems.",
        "Review redundancy and failover configurations.",
        "Update incident response runbooks.",
    ],
}


async def build_report(incident_id: str, sim_time: datetime) -> dict | None:
    """Build a structured incident report."""
    incident = await get_incident_by_id(incident_id)
    if not incident:
        return None

    cascade_nodes = await get_cascade_tree(incident_id)
    affected_flights = await get_affected_flights(incident_id)
    total_delay = sum(f.get("delay_minutes", 0) or 0 for f in affected_flights)

    # Calculate duration
    duration_min = None
    if incident.get("resolved_at"):
        try:
            resolved = datetime.fromisoformat(incident["resolved_at"])
            started = datetime.fromisoformat(incident["started_at"])
            duration_min = int((resolved - started).total_seconds() / 60)
        except (ValueError, TypeError):
            pass

    # Build timeline summary
    timeline_summary = _build_timeline_summary(incident, cascade_nodes, duration_min)

    # Count cascade events (subtract 1 for the root itself)
    cascade_events = max(0, len(cascade_nodes) - 1)

    # Protocols activated
    protocols = []
    for node in cascade_nodes:
        proto = node.get("protocol", "")
        if proto and proto not in protocols:
            protocols.append(proto)

    # Get incident type for recommendations  
    base_type = incident.get("type", "")
    recs = RECOMMENDATIONS.get(base_type, [])

    return {
        "incident_id": incident_id,
        "report_generated_at": sim_time.isoformat(),
        "title": f"{incident.get('type', '').replace('_', ' ').title()} — "
                 f"{incident.get('location', '')} — {incident.get('started_at', '')[:10]}",
        "type": incident.get("type", ""),
        "severity": incident.get("severity", ""),
        "trigger": incident.get("trigger", ""),
        "timeline_summary": timeline_summary,
        "total_flights_affected": len(affected_flights),
        "total_delay_minutes_caused": total_delay,
        "cascade_events": cascade_events,
        "protocols_activated": protocols,
        "recommendations": recs,
    }


def _build_timeline_summary(
    incident: dict, cascade_nodes: list[dict], duration_min: int | None
) -> str:
    """Build a human-readable timeline summary string."""
    parts = []
    inc_type = incident.get("type", "unknown").replace("_", " ").title()
    started = incident.get("started_at", "")[:16]

    parts.append(f"{inc_type} detected at {started}Z.")

    protocol = incident.get("protocol", "")
    if protocol:
        parts.append(f"{protocol} protocol activated.")

    # Count cascade children  
    cascade_count = max(0, len(cascade_nodes) - 1)
    if cascade_count > 0:
        parts.append(f"{cascade_count} cascade event(s) triggered.")

    if incident.get("resolved_at"):
        resolved = incident["resolved_at"][:16]
        parts.append(f"Resolved at {resolved}Z.")

    if duration_min is not None:
        parts.append(f"{duration_min} minutes of disruption.")

    return " ".join(parts)

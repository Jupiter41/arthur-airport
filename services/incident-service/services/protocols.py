"""Emergency protocol activation and alert generation."""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Protocol definitions ─────────────────────────────────────

PROTOCOL_ACTIONS: dict[str, str] = {
    "RUNWAY_STOP": "All ground traffic stop; approach aircraft go-around.",
    "BAGGAGE_HOLD": "ARFF dispatch; make-up zone evacuated.",
    "ZONE_LOCKDOWN": "Pier sealed; security re-screening.",
    "TERMINAL_LOCKDOWN": "Terminal closed; all boarding suspended.",
    "FULL_EVACUATION": "All terminals evacuated; emergency services deployed.",
    "LOW_VIS_PROCEDURES": "CAT II/III ILS activated; reduced taxi speed.",
}

DASHBOARD_COLORS: dict[str, str] = {
    "low": "blue",
    "medium": "yellow",
    "high": "orange",
    "critical": "red",
}


def build_alert(incident: dict, sim_time: datetime) -> dict:
    """Build an alert dict for dashboard notification."""
    severity = incident.get("severity", "medium")
    protocol = incident.get("protocol", "")
    type_label = incident.get("type", "unknown").replace("_", " ").title()

    if protocol:
        short = f"{protocol} active. {PROTOCOL_ACTIONS.get(protocol, '')}"
    else:
        short = f"{type_label} at {incident.get('location', 'unknown')}."

    title = f"{severity.upper()} — {type_label} at {incident.get('location', 'unknown')}"

    return {
        "incident_id": incident["id"],
        "severity": severity,
        "title": title,
        "short_message": short,
        "affected_zones": [incident.get("location", "unknown")],
        "dashboard_color": DASHBOARD_COLORS.get(severity, "yellow"),
        "sound_alert": protocol != "",
        "at": sim_time.isoformat(),
    }


def get_protocol_for_incident(incident_type: str, severity: str) -> str:
    """Return the protocol code for a given incident type and severity."""
    from services.lifecycle import PROTOCOLS
    proto_map = PROTOCOLS.get(incident_type, {})
    return proto_map.get(severity, "")


def get_protocol_description(protocol_code: str) -> str:
    """Return human-readable description for a protocol."""
    return PROTOCOL_ACTIONS.get(protocol_code, "")

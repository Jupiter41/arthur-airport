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

# Precedence order: higher index = higher priority
PROTOCOL_PRIORITY = [
    "LOW_VIS_PROCEDURES",
    "BAGGAGE_HOLD",
    "RUNWAY_STOP",
    "ZONE_LOCKDOWN",
    "TERMINAL_LOCKDOWN",
    "FULL_EVACUATION",
]

DASHBOARD_COLORS: dict[str, str] = {
    "low": "blue",
    "medium": "yellow",
    "high": "orange",
    "critical": "red",
}


# ── Protocol lifecycle manager ───────────────────────────────


class ProtocolManager:
    """Tracks active emergency protocols with override semantics.

    FULL_EVACUATION overrides all other protocols. When multiple protocols
    are active, the highest-priority one is the effective protocol.
    """

    def __init__(self) -> None:
        # Maps protocol_code → set of incident_ids that activated it
        self._active: dict[str, set[str]] = {}

    def activate(self, protocol_code: str, incident_id: str) -> str | None:
        """Activate a protocol for an incident. Returns the effective protocol.

        If FULL_EVACUATION is already active, lower protocols are suppressed.
        Returns the effective (highest-priority) active protocol code.
        """
        if not protocol_code:
            return self.effective_protocol()

        if protocol_code not in self._active:
            self._active[protocol_code] = set()
        self._active[protocol_code].add(incident_id)

        effective = self.effective_protocol()
        if effective != protocol_code:
            logger.info(
                "Protocol %s activated by %s but overridden by %s",
                protocol_code, incident_id[:8], effective,
            )
        else:
            logger.info("Protocol %s activated by incident %s", protocol_code, incident_id[:8])

        return effective

    def deactivate(self, protocol_code: str, incident_id: str) -> str | None:
        """Deactivate a protocol for a specific incident.

        If other incidents still require this protocol, it stays active.
        Returns the new effective protocol (or None if none active).
        """
        if protocol_code in self._active:
            self._active[protocol_code].discard(incident_id)
            if not self._active[protocol_code]:
                del self._active[protocol_code]
                logger.info("Protocol %s fully deactivated", protocol_code)

        return self.effective_protocol()

    def effective_protocol(self) -> str | None:
        """Return the currently effective (highest-priority) active protocol."""
        if not self._active:
            return None
        # Find the highest-priority active protocol
        best = None
        best_priority = -1
        for code in self._active:
            try:
                priority = PROTOCOL_PRIORITY.index(code)
            except ValueError:
                priority = -1
            if priority > best_priority:
                best_priority = priority
                best = code
        return best

    def get_active_protocols(self) -> dict[str, list[str]]:
        """Return all active protocols with their incident IDs."""
        return {code: sorted(ids) for code, ids in self._active.items()}

    def is_evacuation_active(self) -> bool:
        """Check if FULL_EVACUATION is currently active."""
        return "FULL_EVACUATION" in self._active

    def clear(self) -> None:
        """Clear all active protocols (for testing)."""
        self._active.clear()


# Module-level singleton
_protocol_manager = ProtocolManager()


def get_protocol_manager() -> ProtocolManager:
    return _protocol_manager


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

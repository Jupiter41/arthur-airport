"""Cascade engine — rule-based child incident spawning with depth limit."""

import logging
import os

from datetime import datetime

logger = logging.getLogger(__name__)

CASCADE_MAX_DEPTH = int(os.getenv("CASCADE_MAX_DEPTH", "5"))

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# ── Cascade rules table ─────────────────────────────────────
# Each parent type maps to a list of rules. Each rule defines:
#   child_type:     the type of child incident to create
#   min_severity:   parent must be at least this severe
#   delay_sim_min:  ignored for now (instant cascade)
#   child_severity: severity assigned to the child

CASCADE_RULES: dict[str, list[dict]] = {
    "runway_incursion": [
        {
            "child_type": "runway_closure_holding_stack",
            "min_severity": "high",
            "delay_sim_min": 0,
            "child_severity": "high",
        },
    ],
    "runway_closure_holding_stack": [
        {
            "child_type": "departure_ground_stop",
            "min_severity": "high",
            "delay_sim_min": 1,
            "child_severity": "medium",
        },
    ],
    "departure_ground_stop": [
        {
            "child_type": "gate_congestion",
            "min_severity": "medium",
            "delay_sim_min": 2,
            "child_severity": "low",
        },
    ],
    "baggage_fire": [
        {
            "child_type": "make_up_zone_offline",
            "min_severity": "medium",
            "delay_sim_min": 0,
            "child_severity": "medium",
        },
    ],
    "make_up_zone_offline": [
        {
            "child_type": "flight_baggage_not_loaded",
            "min_severity": "medium",
            "delay_sim_min": 0,
            "child_severity": "low",
        },
    ],
    "security_breach": [
        {
            "child_type": "zone_lockdown",
            "min_severity": "medium",
            "delay_sim_min": 0,
            "child_severity": "medium",
        },
    ],
    "zone_lockdown": [
        {
            "child_type": "security_queue_frozen",
            "min_severity": "medium",
            "delay_sim_min": 0,
            "child_severity": "medium",
        },
    ],
    "security_queue_frozen": [
        {
            "child_type": "boarding_delayed",
            "min_severity": "medium",
            "delay_sim_min": 5,
            "child_severity": "low",
        },
    ],
    "boarding_delayed": [
        {
            "child_type": "flight_delayed",
            "min_severity": "low",
            "delay_sim_min": 0,
            "child_severity": "low",
        },
    ],
    "severe_weather": [
        {
            "child_type": "runway_capacity_reduction",
            "min_severity": "medium",
            "delay_sim_min": 0,
            "child_severity": "medium",
        },
    ],
    "runway_capacity_reduction": [
        {
            "child_type": "holding_stack",
            "min_severity": "medium",
            "delay_sim_min": 0,
            "child_severity": "low",
        },
    ],
    "holding_stack": [
        {
            "child_type": "departure_ground_delay",
            "min_severity": "low",
            "delay_sim_min": 0,
            "child_severity": "low",
        },
    ],
    "departure_ground_delay": [
        {
            "child_type": "flight_delays_cascade",
            "min_severity": "low",
            "delay_sim_min": 0,
            "child_severity": "low",
        },
    ],
    "system_failure": [
        {
            "child_type": "baggage_throughput_reduction",
            "min_severity": "medium",
            "delay_sim_min": 0,
            "child_severity": "low",
        },
    ],
    "baggage_throughput_reduction": [
        {
            "child_type": "make_up_delay",
            "min_severity": "low",
            "delay_sim_min": 0,
            "child_severity": "low",
        },
    ],
    "make_up_delay": [
        {
            "child_type": "flight_baggage_not_loaded",
            "min_severity": "low",
            "delay_sim_min": 0,
            "child_severity": "low",
        },
    ],
    "security_congestion": [
        {
            "child_type": "boarding_delayed",
            "min_severity": "medium",
            "delay_sim_min": 0,
            "child_severity": "low",
        },
    ],
}

# Track which parent incidents have already cascaded (cycle prevention)
_cascaded_incidents: set[str] = set()
_MAX_CASCADE_TRACKING = 50000


def _check_and_mark_cascaded(incident_id: str) -> bool:
    """Returns True if already cascaded (duplicate). Marks as cascaded if not."""
    if incident_id in _cascaded_incidents:
        return True
    if len(_cascaded_incidents) > _MAX_CASCADE_TRACKING:
        # Evict oldest entries
        to_remove = list(_cascaded_incidents)[:_MAX_CASCADE_TRACKING // 2]
        for item in to_remove:
            _cascaded_incidents.discard(item)
    _cascaded_incidents.add(incident_id)
    return False


async def evaluate_cascades(parent: dict, sim_time: datetime) -> None:
    """Evaluate cascade rules for a parent incident and create children."""
    depth = parent.get("cascade_depth", 0)

    if depth >= CASCADE_MAX_DEPTH:
        logger.debug(
            "Cascade depth limit reached (%d) for %s — no children created",
            depth, parent["id"][:8],
        )
        return

    # Cycle prevention: don't cascade the same incident twice
    if _check_and_mark_cascaded(parent["id"]):
        logger.warning("Duplicate cascade attempt for %s — skipping", parent["id"][:8])
        return

    rules = CASCADE_RULES.get(parent["type"], [])
    if not rules:
        return

    parent_severity_rank = SEVERITY_RANK.get(parent["severity"], 0)

    for rule in rules:
        min_rank = SEVERITY_RANK.get(rule["min_severity"], 0)
        if parent_severity_rank < min_rank:
            continue

        # Import here to avoid circular import
        from services.lifecycle import create_incident

        child = await create_incident(
            type=rule["child_type"],
            severity=rule["child_severity"],
            location=parent["location"],
            trigger="cascade",
            sim_time=sim_time,
            description=f"Cascade from {parent['type']} at {parent['location']}",
            cascade_depth=depth + 1,
            parent_id=parent["id"],
        )

        logger.info(
            "Cascade: %s → %s (depth %d → %d)",
            parent["type"], rule["child_type"], depth, depth + 1,
        )

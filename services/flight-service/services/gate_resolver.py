"""Gate conflict resolver — detects and resolves gate assignment conflicts.

When multiple flights need the same gate at overlapping times, the resolver
finds the nearest available gate in the same terminal (or any terminal as fallback).
"""

import logging
from datetime import datetime

from db.neo4j import (
    get_available_gate,
    assign_flight_to_gate,
    is_gate_occupied,
)

logger = logging.getLogger(__name__)

# Terminal ID mapping from gate prefix
TERMINAL_MAP = {
    "A": "T-A",
    "B": "T-B",
    "C": "T-C",
}

# Fallback order for each terminal
TERMINAL_FALLBACK = {
    "T-A": ["T-B", "T-C"],
    "T-B": ["T-A", "T-C"],
    "T-C": ["T-B", "T-A"],
}


def _gate_to_terminal(gate_id: str) -> str:
    """Extract terminal ID from gate ID (e.g. 'B07' -> 'T-B')."""
    if gate_id and len(gate_id) >= 1:
        return TERMINAL_MAP.get(gate_id[0], "T-A")
    return "T-A"


async def check_and_resolve_conflict(
    flight_id: str,
    gate_id: str,
    sim_time: datetime,
) -> dict | None:
    """Check if a gate is occupied and resolve conflict if needed.

    Returns:
        None if no conflict
        {"new_gate": "C12", "reason": "cascade_delay_reassignment"} if reassigned
    """
    occupied = await is_gate_occupied(gate_id)
    if not occupied:
        return None

    logger.info("Gate conflict detected: gate %s for flight %s", gate_id, flight_id)

    # Try same terminal first
    terminal = _gate_to_terminal(gate_id)
    new_gate = await get_available_gate(terminal)

    # Try fallback terminals
    if not new_gate:
        for fallback_terminal in TERMINAL_FALLBACK.get(terminal, []):
            new_gate = await get_available_gate(fallback_terminal)
            if new_gate:
                break

    if not new_gate:
        logger.warning(
            "No available gate found for flight %s (original: %s)", flight_id, gate_id
        )
        return None

    # Reassign
    await assign_flight_to_gate(flight_id, new_gate, sim_time)
    logger.info(
        "Gate conflict resolved: flight %s reassigned from %s to %s",
        flight_id, gate_id, new_gate,
    )
    return {"new_gate": new_gate, "reason": "cascade_delay_reassignment"}


async def ensure_gate_assigned(
    flight_id: str,
    current_gate_id: str | None,
    preferred_terminal: str | None,
    sim_time: datetime,
) -> str | None:
    """Ensure a flight has a gate assigned. Returns the gate ID (new or existing).

    If the flight already has a valid gate, return it.
    If the gate is occupied, resolve the conflict.
    If no gate, find one.
    """
    if current_gate_id:
        conflict = await check_and_resolve_conflict(flight_id, current_gate_id, sim_time)
        if conflict:
            return conflict["new_gate"]
        return current_gate_id

    # No gate assigned — find one
    terminal = preferred_terminal or "T-A"
    if not terminal.startswith("T-"):
        terminal = f"T-{terminal}"

    gate = await get_available_gate(terminal)
    if not gate:
        for fallback in TERMINAL_FALLBACK.get(terminal, []):
            gate = await get_available_gate(fallback)
            if gate:
                break

    if gate:
        await assign_flight_to_gate(flight_id, gate, sim_time)
        logger.info("Gate %s assigned to flight %s", gate, flight_id)
    else:
        logger.warning("No gate available for flight %s", flight_id)

    return gate

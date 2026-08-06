"""Pure parsing/validation for `passengers.commands` — no I/O.

Commands are imperatives published by the api-gateway (operator) and
analysis-service (agent) on the `passengers.commands` topic.
passenger-service is the sole consumer and authority.

This module turns a raw command envelope into a typed, validated command
(or a rejection reason). It performs **no I/O**.
"""

from __future__ import annotations

from dataclasses import dataclass

VALID_TERMINALS: frozenset[str] = frozenset({"A", "B", "C"})
MAX_LANES = 20


@dataclass(frozen=True)
class OpenSecurityLane:
    """Change the number of open security lanes at a terminal checkpoint."""

    terminal: str
    lanes_open: int


Command = OpenSecurityLane

_KNOWN_COMMANDS = {"OpenSecurityLane"}


def parse_command(
    command_type: str | None, payload: dict | None
) -> tuple[Command | None, str | None]:
    """Parse+validate a command envelope's ``command_type``/``payload``.

    Returns ``(command, None)`` on success or ``(None, reason)`` on rejection.
    Pure — no I/O.
    """
    if not command_type or command_type not in _KNOWN_COMMANDS:
        return None, f"unknown command_type: {command_type!r}"
    if not isinstance(payload, dict):
        return None, "payload is not an object"

    return _parse_open_lane(payload)


def _parse_open_lane(payload: dict) -> tuple[Command | None, str | None]:
    terminal = payload.get("terminal")
    if not isinstance(terminal, str) or terminal not in VALID_TERMINALS:
        return None, f"OpenSecurityLane: terminal must be one of {sorted(VALID_TERMINALS)}"

    lanes = _coerce_positive_int(payload.get("lanes_open"))
    if lanes is None:
        return None, "OpenSecurityLane: lanes_open must be a positive integer"
    if lanes > MAX_LANES:
        return None, f"OpenSecurityLane: lanes_open exceeds maximum ({MAX_LANES})"

    return OpenSecurityLane(terminal=terminal, lanes_open=lanes), None


def _coerce_positive_int(value: object) -> int | None:
    """Coerce to a positive int; reject bools, zero, negatives."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        try:
            n = int(value)
        except ValueError:
            return None
        return n if n > 0 else None
    return None

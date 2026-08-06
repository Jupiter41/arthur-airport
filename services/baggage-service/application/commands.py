"""Pure parsing/validation for `baggage.commands` — no I/O.

Commands are imperatives published by the api-gateway (operator) and
analysis-service (agent) on the `baggage.commands` topic.
baggage-service is the sole consumer and authority.

This module turns a raw command envelope into a typed, validated command
(or a rejection reason). It performs **no I/O**.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RedirectBaggage:
    """Re-assign a baggage item to a different flight."""

    bag_id: str
    target_flight_id: str


Command = RedirectBaggage

_KNOWN_COMMANDS = {"RedirectBaggage"}


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

    return _parse_redirect(payload)


def _parse_redirect(payload: dict) -> tuple[Command | None, str | None]:
    bag_id = payload.get("bag_id")
    if not isinstance(bag_id, str) or not bag_id:
        return None, "RedirectBaggage: missing bag_id"

    target_flight_id = payload.get("target_flight_id")
    if not isinstance(target_flight_id, str) or not target_flight_id:
        return None, "RedirectBaggage: missing target_flight_id"

    if bag_id == target_flight_id:
        return None, "RedirectBaggage: bag_id and target_flight_id must differ"

    return RedirectBaggage(bag_id=bag_id, target_flight_id=target_flight_id), None

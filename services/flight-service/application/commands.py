"""Pure parsing/validation for `flights.commands` — no I/O.

Commands are imperatives published by the api-gateway (operator) and
analysis-service (agent) on the `flights.commands` topic. flight-service is the
sole consumer and the authority that decides whether to execute them.

This module turns a raw command envelope into a typed, validated command (or a
rejection reason). It performs **no I/O**: precondition checks that need the
live flight (does it exist? is its status holdable?) are done by the adapter
after loading the flight, but the *rule* for which statuses are holdable lives
here as a pure predicate so it stays unit-testable and consistent with the REST
path.
"""

from __future__ import annotations

from dataclasses import dataclass

# A hold is only meaningful before/at the decision points where a flight can
# still be delayed. Mirrors the REST hold endpoint's guard.
HOLDABLE_STATUSES: frozenset[str] = frozenset({"boarding", "scheduled", "approach"})


@dataclass(frozen=True)
class HoldFlight:
    """Delay a flight for a stated reason and expected duration."""

    flight_id: str
    reason: str
    duration_min: int


@dataclass(frozen=True)
class ReassignGate:
    """Move a flight's gate assignment to a specific gate."""

    flight_id: str
    gate_id: str


@dataclass(frozen=True)
class GroundDelayProgram:
    """Hold a batch of departures at gate for a staggered GDP."""

    flight_ids: list[str]
    stagger_minutes: int
    reason: str

    def __post_init__(self) -> None:
        if not self.flight_ids:
            raise ValueError("GroundDelayProgram: flight_ids must not be empty")


Command = HoldFlight | ReassignGate | GroundDelayProgram

_KNOWN_COMMANDS = {"HoldFlight", "ReassignGate", "GroundDelayProgram"}


def parse_command(
    command_type: str | None, payload: dict | None
) -> tuple[Command | None, str | None]:
    """Parse+validate a command envelope's ``command_type``/``payload``.

    Returns ``(command, None)`` on success or ``(None, reason)`` on rejection.
    Pure — no I/O, no live-flight lookups.
    """
    if not command_type or command_type not in _KNOWN_COMMANDS:
        return None, f"unknown command_type: {command_type!r}"
    if not isinstance(payload, dict):
        return None, "payload is not an object"

    if command_type == "HoldFlight":
        return _parse_hold(payload)
    if command_type == "GroundDelayProgram":
        return _parse_gdp(payload)
    return _parse_reassign(payload)


def _parse_hold(payload: dict) -> tuple[Command | None, str | None]:
    flight_id = payload.get("flight_id")
    if not isinstance(flight_id, str) or not flight_id:
        return None, "HoldFlight: missing flight_id"

    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason:
        return None, "HoldFlight: missing reason"

    # Accept both the command field and the legacy REST field name.
    raw_duration = payload.get("duration_min", payload.get("expected_duration_minutes"))
    duration = _coerce_positive_int(raw_duration)
    if duration is None:
        return None, "HoldFlight: duration_min must be a positive integer"

    return HoldFlight(flight_id=flight_id, reason=reason, duration_min=duration), None


def _parse_reassign(payload: dict) -> tuple[Command | None, str | None]:
    flight_id = payload.get("flight_id")
    if not isinstance(flight_id, str) or not flight_id:
        return None, "ReassignGate: missing flight_id"

    gate_id = payload.get("gate_id")
    if not isinstance(gate_id, str) or not gate_id:
        return None, "ReassignGate: missing gate_id"

    return ReassignGate(flight_id=flight_id, gate_id=gate_id), None


def _parse_gdp(payload: dict) -> tuple[Command | None, str | None]:
    flight_ids = payload.get("flight_ids")
    if not isinstance(flight_ids, list) or not flight_ids:
        return None, "GroundDelayProgram: flight_ids must be a non-empty list"
    if not all(isinstance(fid, str) and fid for fid in flight_ids):
        return None, "GroundDelayProgram: all flight_ids must be non-empty strings"

    stagger = _coerce_positive_int(payload.get("stagger_minutes", 10))
    if stagger is None:
        return None, "GroundDelayProgram: stagger_minutes must be a positive integer"

    reason = payload.get("reason", "ground_delay_program")
    if not isinstance(reason, str) or not reason:
        return None, "GroundDelayProgram: reason must be a non-empty string"

    return GroundDelayProgram(flight_ids=list(flight_ids), stagger_minutes=stagger, reason=reason), None


def validate_hold_precondition(status: str) -> str | None:
    """Return a rejection reason if ``status`` can't be held, else None."""
    if status not in HOLDABLE_STATUSES:
        return f"cannot hold flight in status {status!r}"
    return None


def _coerce_positive_int(value: object) -> int | None:
    """Coerce to a positive int (accepts int or numeric str); None if invalid.

    A bool is rejected (``True``/``False`` are ints in Python but never a valid
    duration).
    """
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

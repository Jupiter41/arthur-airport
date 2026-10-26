"""Pure parsing/validation for `incidents.commands` — no I/O.

Commands are imperatives published by the api-gateway (operator) and
analysis-service (agent) on the `incidents.commands` topic. incident-service is
the sole consumer and the authority that decides whether to execute them.

This module turns a raw command envelope into a typed, validated command (or a
rejection reason). It performs **no I/O**: whether the *target incident* exists
and is in a legal state is checked by the adapter after loading it, but the
transition *rule* lives here as a pure predicate so it stays unit-testable and
consistent with the REST contain/resolve endpoints and `lifecycle.VALID_TRANSITIONS`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Mirror of lifecycle.VALID_TRANSITIONS, kept pure so the command precondition
# matches the REST path. Containing requires the incident still be active;
# resolving is legal from active or contained (and is an idempotent no-op if the
# incident is already resolved — the executor handles that case).
_CAN_CONTAIN: frozenset[str] = frozenset({"active"})
_CAN_RESOLVE: frozenset[str] = frozenset({"active", "contained"})


@dataclass(frozen=True)
class ContainIncident:
    """Move an active incident into the contained state."""

    incident_id: str
    note: str


@dataclass(frozen=True)
class ResolveIncident:
    """Resolve an active/contained incident (and its children)."""

    incident_id: str
    note: str


Command = ContainIncident | ResolveIncident

_KNOWN_COMMANDS = {"ContainIncident", "ResolveIncident"}


def parse_command(
    command_type: str | None, payload: dict | None
) -> tuple[Command | None, str | None]:
    """Parse+validate a command envelope's ``command_type``/``payload``.

    Returns ``(command, None)`` on success or ``(None, reason)`` on rejection.
    Pure — no I/O, no live-incident lookups.
    """
    if not command_type or command_type not in _KNOWN_COMMANDS:
        return None, f"unknown command_type: {command_type!r}"
    if not isinstance(payload, dict):
        return None, "payload is not an object"

    incident_id = payload.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        return None, f"{command_type}: missing incident_id"

    note = payload.get("note", "")
    if not isinstance(note, str):
        return None, f"{command_type}: note must be a string"

    if command_type == "ContainIncident":
        return ContainIncident(incident_id=incident_id, note=note), None
    return ResolveIncident(incident_id=incident_id, note=note), None


def validate_contain_precondition(status: str) -> str | None:
    """Return a rejection reason if ``status`` can't be contained, else None."""
    if status not in _CAN_CONTAIN:
        return f"cannot contain incident in status {status!r}"
    return None


def validate_resolve_precondition(status: str) -> str | None:
    """Return a rejection reason if ``status`` can't be resolved, else None.

    ``resolved`` is **not** an error — resolving an already-resolved incident is
    an idempotent success handled by the executor — so it is allowed here too.
    """
    if status not in _CAN_RESOLVE and status != "resolved":
        return f"cannot resolve incident in status {status!r}"
    return None

"""Approval queue for autonomous/agent-proposed actions (A9).

The autonomous engine no longer silently applies (or silently drops) actions.
Every action it wants to take becomes a **Proposal** in this queue:

  - actions that are safe *and* confident are auto-approved (recorded for audit,
    executed immediately by the engine);
  - safety-guarded actions (and, optionally, low-confidence ones) are enqueued
    **pending** and require a human Approve/Reject in the dashboard.

This module is pure and in-memory: it stores proposals and enforces the legal
state transitions (pending → approved → executed, or pending → rejected). The
gating *rule* (`classify`) and the recommendation→command *mapping*
(`to_flight_command`) are pure functions so they can be unit-tested without
Kafka/Neo4j. The Kafka side (emit `ActionProposed`, forward approved
`HoldFlight`/`ReassignGate` to `flights.commands`) lives in the router/consumer,
which call into here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import uuid4

# ── Proposal lifecycle states ────────────────────────────────
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
EXECUTED = "executed"

# ── Gating verdicts (classify) ───────────────────────────────
AUTO = "auto"      # safe + confident → auto-approve and execute
HUMAN = "human"    # needs a human Approve/Reject
BLOCK = "block"    # operator-blocked → do nothing
SKIP = "skip"      # below confidence threshold → do nothing (not surfaced)


@dataclass
class Proposal:
    id: str
    action_type: str
    description: str
    parameters: dict
    confidence_score: float
    proposed_by: str
    proposed_at: str
    recommendation_id: str | None = None
    bottleneck_id: str | None = None
    status: str = PENDING
    requires_human: bool = True
    emitted: bool = False
    decided_by: str | None = None
    decided_at: str | None = None
    reject_reason: str | None = None
    executed_at: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("emitted", None)  # internal bookkeeping, not part of the API/event
        return d


_queue: list[Proposal] = []
MAX_QUEUE = 200


def clear() -> None:
    """Reset the queue (tests / sim reset)."""
    _queue.clear()


def classify(
    action_type: str,
    confidence: float,
    *,
    safety_guarded: bool,
    blocked: bool,
    threshold: float,
) -> str:
    """Pure gating rule → one of AUTO / HUMAN / BLOCK / SKIP.

    - operator-blocked actions are never taken (BLOCK);
    - safety-guarded actions always require a human (HUMAN), regardless of
      confidence — this is what "activating SAFETY_GUARDED_ACTIONS" means: they
      are surfaced for approval instead of being silently dropped;
    - otherwise, confident actions auto-apply (AUTO) and low-confidence ones are
      skipped (SKIP).
    """
    if blocked:
        return BLOCK
    if safety_guarded:
        return HUMAN
    if confidence >= threshold:
        return AUTO
    return SKIP


def propose(
    *,
    action_type: str,
    description: str,
    parameters: dict,
    confidence_score: float,
    proposed_by: str,
    proposed_at: datetime,
    recommendation_id: str | None = None,
    bottleneck_id: str | None = None,
    requires_human: bool = True,
) -> Proposal:
    """Add a proposal. requires_human=False marks it already-approved (auto)."""
    proposal = Proposal(
        id=f"prop-{uuid4().hex[:12]}",
        action_type=action_type,
        description=description,
        parameters=dict(parameters),
        confidence_score=confidence_score,
        proposed_by=proposed_by,
        proposed_at=proposed_at.isoformat(),
        recommendation_id=recommendation_id,
        bottleneck_id=bottleneck_id,
        status=PENDING if requires_human else APPROVED,
        requires_human=requires_human,
    )
    _queue.append(proposal)
    if len(_queue) > MAX_QUEUE:
        _queue.pop(0)
    return proposal


def get(proposal_id: str) -> Proposal | None:
    return next((p for p in _queue if p.id == proposal_id), None)


def list_all() -> list[Proposal]:
    return list(_queue)


def list_pending() -> list[Proposal]:
    return [p for p in _queue if p.status == PENDING]


def take_unemitted() -> list[Proposal]:
    """Return proposals whose ActionProposed event hasn't been emitted yet.

    Marks them emitted so a caller (the consumer) emits each exactly once.
    """
    fresh = [p for p in _queue if not p.emitted]
    for p in fresh:
        p.emitted = True
    return fresh


def approve(proposal_id: str, sim_time: datetime, decided_by: str) -> Proposal | None:
    """pending → approved. Returns None if unknown or not pending."""
    p = get(proposal_id)
    if p is None or p.status != PENDING:
        return None
    p.status = APPROVED
    p.decided_by = decided_by
    p.decided_at = sim_time.isoformat()
    return p


def reject(
    proposal_id: str, sim_time: datetime, decided_by: str, reason: str = ""
) -> Proposal | None:
    """pending → rejected. Returns None if unknown or not pending."""
    p = get(proposal_id)
    if p is None or p.status != PENDING:
        return None
    p.status = REJECTED
    p.decided_by = decided_by
    p.decided_at = sim_time.isoformat()
    p.reject_reason = reason
    return p


def mark_executed(proposal_id: str, sim_time: datetime) -> Proposal | None:
    """approved → executed. Returns None if unknown or not approved."""
    p = get(proposal_id)
    if p is None or p.status != APPROVED:
        return None
    p.status = EXECUTED
    p.executed_at = sim_time.isoformat()
    return p


def to_flight_command(
    action_type: str, parameters: dict
) -> tuple[str, dict] | None:
    """Map an approved action to a concrete `flights.commands` command.

    Returns ``(command_type, payload)`` when the action targets a concrete
    flight and carries the required parameters, else ``None`` (the action is
    recorded as a fact only). This is the honest seam: a real command is formed
    only when a concrete ``flight_id`` (+ ``gate_id`` / duration) is present —
    aggregate/terminal-level recommendations map to nothing here.
    """
    flight_id = parameters.get("flight_id")
    if not isinstance(flight_id, str) or not flight_id:
        return None

    if action_type == "reassign_gate":
        gate_id = parameters.get("gate_id")
        if isinstance(gate_id, str) and gate_id:
            return "ReassignGate", {"flight_id": flight_id, "gate_id": gate_id}
        return None

    if action_type in ("hold_connecting_flight", "delay_taxi"):
        duration = parameters.get("duration_min", parameters.get("hold_minutes"))
        reason = parameters.get("reason") or action_type
        if isinstance(duration, int) and not isinstance(duration, bool) and duration > 0:
            return "HoldFlight", {
                "flight_id": flight_id,
                "reason": reason,
                "duration_min": duration,
            }
        return None

    return None

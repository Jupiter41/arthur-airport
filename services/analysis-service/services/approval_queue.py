"""Approval queue for autonomous/agent-proposed actions (A9).

The autonomous engine no longer silently applies (or silently drops) actions.
Every action it wants to take becomes a **Proposal** in this queue:

  - actions that are safe *and* confident are auto-approved (recorded for audit,
    dispatched by the adapter and confirmed by the owner);
  - safety-guarded actions (and, optionally, low-confidence ones) are enqueued
    **pending** and require a human Approve/Reject in the dashboard.

This module is pure and in-memory: it stores proposals and enforces the legal
state transitions (pending → approved → dispatched → executed/failed, or pending → rejected). The
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
DISPATCHED = "dispatched"
FAILED = "failed"

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
    dispatched_at: str | None = None
    command_id: str | None = None
    failure_reason: str | None = None

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
    # Active commands must never be evicted while waiting for confirmation.
    while len(_queue) > MAX_QUEUE:
        terminal = next((p for p in _queue if p.status in {EXECUTED, FAILED, REJECTED}), None)
        if terminal is None:
            break
        _queue.remove(terminal)
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
    """Receipt-confirmed dispatched → executed."""
    p = get(proposal_id)
    if p is None or p.status != DISPATCHED:
        return None
    p.status = EXECUTED
    p.executed_at = sim_time.isoformat()
    return p


def mark_dispatched(proposal_id: str) -> Proposal | None:
    p = get(proposal_id)
    if p is None or p.status != APPROVED:
        return None
    p.command_id = p.id
    p.status = DISPATCHED
    return p


def mark_failed(proposal_id: str, reason: str) -> Proposal | None:
    p = get(proposal_id)
    if p is None or p.status not in {APPROVED, DISPATCHED}:
        return None
    p.status = FAILED
    p.failure_reason = reason
    return p


def to_flight_command(
    action_type: str, parameters: dict
) -> tuple[str, dict] | None:
    """Compatibility shim over the canonical multi-domain command mapper."""
    from _common.commands import action_command
    intent = action_command(action_type, parameters)
    if intent is not None and intent.topic == "flights.commands":
        return intent.command_type, intent.payload
    return None


def restore(documents: list[dict]) -> None:
    """Rebuild the application cache from Neo4j after a restart."""
    clear()
    for document in sorted(documents, key=lambda d: d["proposed_at"]):
        _queue.append(Proposal(**document))

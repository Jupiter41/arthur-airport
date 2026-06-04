"""Wheelchair / special-assistance dispatch (1C — ROADMAP_USECASE.md).

Models a per-terminal pool of wheelchairs serving passengers flagged with
``special_assistance``. Tracks request → dispatch → return wait times, persists
``WheelchairAssignment`` records to Neo4j, and exposes SLA and staffing analytics
based on ECAC Doc 30 (90% of SA passengers reaching the gate before the boarding
cutoff).

Lifecycle hooks (driven from the passenger consumer):
  ``request(terminal, pid, sim_time, scheduled_dep_iso, flight_id)`` — when a SA
  passenger transitions to ``checked_in``. Either dispatches immediately or
  queues until a chair is free.

  ``mark_at_gate(pid, sim_time)`` — records SLA outcome.

  ``release(pid, sim_time)`` — frees the chair and emits ``WheelchairReturned``.

All state is in-memory but persisted to Neo4j on every dispatch/return so the
service can rebuild state on restart.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# ── Module-level configuration & state ────────────────────────────────────

# Defaults match config/airport.yaml; overridden via configure_pools().
_DEFAULT_TOTAL: dict[str, int] = {"A": 8, "B": 12, "C": 8}
_DEFAULT_TARGET_PCT: float = 90.0
_DEFAULT_BOARDING_CUTOFF_MIN: int = 15
_DEFAULT_MAX_WAIT_MIN: int = 30


@dataclass
class _Assignment:
    """Single SA passenger's wheelchair lifecycle record."""

    id: str
    passenger_id: str
    terminal: str
    flight_id: str | None
    scheduled_dep_iso: str | None
    requested_at: datetime
    dispatched_at: datetime | None = None
    arrived_at_gate_at: datetime | None = None
    released_at: datetime | None = None
    queued_position: int = 0  # position at time of request (0 means served immediately)
    sla_met: bool | None = None  # set when arrived_at_gate_at recorded

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "passenger_id": self.passenger_id,
            "terminal": self.terminal,
            "flight_id": self.flight_id,
            "scheduled_dep_iso": self.scheduled_dep_iso,
            "requested_at": self.requested_at.isoformat(),
            "dispatched_at": self.dispatched_at.isoformat() if self.dispatched_at else None,
            "arrived_at_gate_at": (
                self.arrived_at_gate_at.isoformat() if self.arrived_at_gate_at else None
            ),
            "released_at": self.released_at.isoformat() if self.released_at else None,
            "queued_position": self.queued_position,
            "sla_met": self.sla_met,
        }


@dataclass
class _Pool:
    terminal: str
    total: int
    in_use: int = 0
    queue: list[str] = field(default_factory=list)  # passenger_ids waiting

    @property
    def available(self) -> int:
        return max(0, self.total - self.in_use)


_pools: dict[str, _Pool] = {}
_assignments: dict[str, _Assignment] = {}  # passenger_id → active assignment
_completed: list[_Assignment] = []  # cleared each sim day for SLA reporting
_target_pct: float = _DEFAULT_TARGET_PCT
_boarding_cutoff_min: int = _DEFAULT_BOARDING_CUTOFF_MIN
_max_wait_min: int = _DEFAULT_MAX_WAIT_MIN

# Last sim-time observed; used to detect day rollover and auto-rotate stats.
_last_sim_day: int | None = None


def configure_pools(
    *,
    total_per_terminal: dict[str, int] | None = None,
    sla_target_pct: float | None = None,
    boarding_cutoff_minutes: int | None = None,
    max_dispatch_wait_minutes: int | None = None,
) -> None:
    """Apply config from airport.yaml. Idempotent — safe to call again."""
    global _target_pct, _boarding_cutoff_min, _max_wait_min
    totals = total_per_terminal or _DEFAULT_TOTAL
    for terminal, total in totals.items():
        existing = _pools.get(terminal)
        if existing:
            existing.total = int(total)
        else:
            _pools[terminal] = _Pool(terminal=terminal, total=int(total))
    if sla_target_pct is not None:
        _target_pct = float(sla_target_pct)
    if boarding_cutoff_minutes is not None:
        _boarding_cutoff_min = int(boarding_cutoff_minutes)
    if max_dispatch_wait_minutes is not None:
        _max_wait_min = int(max_dispatch_wait_minutes)


def reset_for_tests() -> None:
    """Clear all in-memory state (test helper only)."""
    _pools.clear()
    _assignments.clear()
    _completed.clear()
    global _last_sim_day
    _last_sim_day = None


# ── Public API ─────────────────────────────────────────────────────────────

async def request(
    *,
    terminal: str,
    passenger_id: str,
    sim_time: datetime,
    scheduled_dep_iso: str | None,
    flight_id: str | None = None,
    name: str | None = None,
) -> dict:
    """Register a SA passenger's wheelchair request.

    If a chair is free, dispatches immediately; otherwise enqueues.
    Returns the assignment record (with ``dispatched_at`` populated when served).
    Idempotent per ``passenger_id``.
    """
    if passenger_id in _assignments:
        return _assignments[passenger_id].to_record()

    pool = _pools.setdefault(terminal, _Pool(terminal=terminal, total=_DEFAULT_TOTAL.get(terminal, 8)))
    queued_pos = 0 if pool.available > 0 else len(pool.queue) + 1
    a = _Assignment(
        id=str(uuid.uuid4()),
        passenger_id=passenger_id,
        terminal=terminal,
        flight_id=flight_id,
        scheduled_dep_iso=scheduled_dep_iso,
        requested_at=sim_time,
        queued_position=queued_pos,
    )
    _assignments[passenger_id] = a

    if pool.available > 0:
        pool.in_use += 1
        a.dispatched_at = sim_time
        await _persist(a)
        await _emit_dispatched(a, sim_time, name)
        await _persist_pool(pool)
    else:
        pool.queue.append(passenger_id)
        await _persist(a)
        # No event yet — emitted only when actually dispatched.

    return a.to_record()


async def tick(sim_time: datetime) -> None:
    """Drain waiting queues at each clock tick.

    Should be called once per ``SimClockTick`` from the passenger consumer.
    Also rolls over completed-record buffer at midnight (sim day change).
    """
    global _last_sim_day
    if _last_sim_day is None:
        _last_sim_day = sim_time.day
    elif sim_time.day != _last_sim_day:
        # Keep last 24 h only; older records are dropped to bound memory.
        cutoff = sim_time - timedelta(hours=24)
        _completed[:] = [c for c in _completed if c.released_at and c.released_at >= cutoff]
        _last_sim_day = sim_time.day

    # Drain queues
    for pool in _pools.values():
        while pool.queue and pool.available > 0:
            pid = pool.queue.pop(0)
            a = _assignments.get(pid)
            if a is None or a.dispatched_at is not None:
                continue
            pool.in_use += 1
            a.dispatched_at = sim_time
            await _persist(a)
            await _emit_dispatched(a, sim_time, None)
        await _persist_pool(pool)


async def mark_at_gate(passenger_id: str, sim_time: datetime) -> None:
    """Record that a SA passenger reached the gate (for SLA computation)."""
    a = _assignments.get(passenger_id)
    if a is None or a.arrived_at_gate_at is not None:
        return
    a.arrived_at_gate_at = sim_time
    a.sla_met = _evaluate_sla(a)
    await _persist(a)


async def release(passenger_id: str, sim_time: datetime) -> None:
    """Free a passenger's wheelchair and emit ``WheelchairReturned``."""
    a = _assignments.pop(passenger_id, None)
    if a is None:
        return
    pool = _pools.get(a.terminal)
    if pool and a.dispatched_at is not None:
        pool.in_use = max(0, pool.in_use - 1)
        await _persist_pool(pool)
    a.released_at = sim_time
    if a.sla_met is None and a.arrived_at_gate_at is not None:
        a.sla_met = _evaluate_sla(a)
    _completed.append(a)
    await _persist(a)
    await _emit_returned(a, sim_time)


# ── SLA / staffing analytics ──────────────────────────────────────────────

def sla_summary(sim_time: datetime | None = None) -> dict:
    """ECAC Doc 30 SLA: % of SA pax reaching the gate before the boarding cutoff.

    ``sim_time`` is unused today (records are already filtered to the rolling
    24 h window), but reserved for future per-period filtering.
    """
    records = list(_completed) + [a for a in _assignments.values() if a.arrived_at_gate_at]
    total = len(records)
    if total == 0:
        return {
            "target_pct": _target_pct,
            "actual_pct": None,
            "compliant": None,
            "boarding_cutoff_minutes": _boarding_cutoff_min,
            "samples": 0,
            "by_terminal": {},
        }
    met = sum(1 for r in records if r.sla_met)
    by_term: dict[str, dict] = {}
    for r in records:
        bucket = by_term.setdefault(r.terminal, {"samples": 0, "met": 0})
        bucket["samples"] += 1
        if r.sla_met:
            bucket["met"] += 1
    for t, b in by_term.items():
        b["actual_pct"] = round(100 * b["met"] / b["samples"], 2) if b["samples"] else None
    actual = round(100 * met / total, 2)
    waits = [
        (r.dispatched_at - r.requested_at).total_seconds() / 60.0
        for r in records
        if r.dispatched_at is not None
    ]
    mean_wait = round(sum(waits) / len(waits), 2) if waits else 0.0
    return {
        "target_pct": _target_pct,
        "actual_pct": actual,
        "compliant": actual >= _target_pct,
        "boarding_cutoff_minutes": _boarding_cutoff_min,
        "mean_dispatch_wait_minutes": mean_wait,
        "samples": total,
        "by_terminal": by_term,
    }


def staffing_recommendation() -> dict:
    """Hourly staffing recommendation per terminal.

    Uses the rolling-window assignment counts to project the next-hour demand,
    then recommends agents = ceil(peak concurrent SA pax / agents_per_chair=1).
    A simple p95 over recent hourly buckets is used as the headroom target.
    """
    from math import ceil

    by_term_hour: dict[tuple[str, int], int] = {}
    records = list(_completed) + list(_assignments.values())
    for r in records:
        hour = r.requested_at.hour
        by_term_hour[(r.terminal, hour)] = by_term_hour.get((r.terminal, hour), 0) + 1

    recommendations: dict[str, dict] = {}
    for terminal, pool in _pools.items():
        # peak hour count over rolling window
        hour_counts = [v for (t, _h), v in by_term_hour.items() if t == terminal]
        peak = max(hour_counts) if hour_counts else 0
        # 1 agent per concurrent chair, +20% headroom, never below pool/4 minimum
        recommended = max(ceil(pool.total / 4), ceil(peak * 1.2))
        recommendations[terminal] = {
            "current_pool_size": pool.total,
            "current_in_use": pool.in_use,
            "queue_depth": len(pool.queue),
            "recent_peak_hourly_requests": peak,
            "recommended_agents": recommended,
        }
    return {
        "method": "p100 of last 24h hourly demand × 1.2 headroom, floored at pool/4",
        "by_terminal": recommendations,
    }


def resources_snapshot() -> dict:
    """Pool snapshot used by the dashboard accessibility card."""
    return {
        "by_terminal": {
            t: {
                "total": p.total,
                "available": p.available,
                "in_use": p.in_use,
                "queue_depth": len(p.queue),
            }
            for t, p in _pools.items()
        },
    }


# ── Internal helpers ──────────────────────────────────────────────────────

def _evaluate_sla(a: _Assignment) -> bool:
    """SLA met if pax reached the gate ≥ boarding_cutoff_min before scheduled dep."""
    if not a.scheduled_dep_iso or a.arrived_at_gate_at is None:
        return False
    try:
        sched = datetime.fromisoformat(a.scheduled_dep_iso).replace(tzinfo=None)
    except (TypeError, ValueError):
        return False
    deadline = sched - timedelta(minutes=_boarding_cutoff_min)
    return a.arrived_at_gate_at <= deadline


async def _persist(a: _Assignment) -> None:
    try:
        from db.neo4j import write_wheelchair_assignment

        await write_wheelchair_assignment(a.to_record())
    except Exception as exc:  # don't block the hot path
        logger.warning("wheelchair: failed to persist assignment %s: %s", a.id, exc)


async def _persist_pool(pool: _Pool) -> None:
    try:
        from db.neo4j import upsert_wheelchair_resource

        await upsert_wheelchair_resource(pool.terminal, pool.total, pool.available)
    except Exception as exc:
        logger.debug("wheelchair: failed to persist pool %s: %s", pool.terminal, exc)


async def _emit_dispatched(a: _Assignment, sim_time: datetime, name: str | None) -> None:
    try:
        from kafka.producer import emit_wheelchair_dispatched

        wait_min = (
            (a.dispatched_at - a.requested_at).total_seconds() / 60.0
            if a.dispatched_at
            else 0.0
        )
        await _maybe_await(
            emit_wheelchair_dispatched(
                assignment_id=a.id,
                passenger_id=a.passenger_id,
                terminal=a.terminal,
                flight_id=a.flight_id,
                wait_minutes=round(wait_min, 2),
                sim_time=sim_time,
            )
        )
    except Exception as exc:
        logger.warning("wheelchair: failed to emit dispatched event: %s", exc)


async def _emit_returned(a: _Assignment, sim_time: datetime) -> None:
    try:
        from kafka.producer import emit_wheelchair_returned

        await _maybe_await(
            emit_wheelchair_returned(
                assignment_id=a.id,
                passenger_id=a.passenger_id,
                terminal=a.terminal,
                sla_met=bool(a.sla_met),
                sim_time=sim_time,
            )
        )
    except Exception as exc:
        logger.warning("wheelchair: failed to emit returned event: %s", exc)


async def _maybe_await(value):
    if asyncio.iscoroutine(value):
        await value

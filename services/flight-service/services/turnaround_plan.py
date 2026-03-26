"""Turnaround task graph — sequenced parallel tasks with hard dependencies.

Replaces the flat 30/45-min turnaround buffer with a realistic task DAG.
Each task has dependencies (must complete before this task starts) and a
duration in minutes.  The critical path determines the minimum turnaround.

Usage:
    plan = create_turnaround_plan("N12345", "FL-001", "B738")
    plan.start(sim_time)
    ...
    changed = plan.advance(sim_time)  # returns tasks that changed state
"""

from __future__ import annotations

import logging
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Sequence

logger = logging.getLogger(__name__)

WIDE_BODY_TYPES = {"B77W", "A333", "A332", "B748", "A380"}


# ── Task status enum ────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


# ── Dataclasses ─────────────────────────────────────────────

@dataclass
class TurnaroundTask:
    """A single turnaround sub-task."""
    name: str
    starts_after: list[str]       # names of prerequisite tasks
    duration_min: int
    status: TaskStatus = TaskStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "starts_after": self.starts_after,
            "duration_min": self.duration_min,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class TurnaroundPlan:
    """Container for a set of turnaround tasks with dependency edges."""
    aircraft_registration: str
    arrival_flight_id: str
    paired_departure_id: str | None = None
    aircraft_type: str = ""
    started_at: datetime | None = None
    tasks: dict[str, TurnaroundTask] = field(default_factory=dict)

    # ── Queries ──

    @property
    def is_complete(self) -> bool:
        return all(t.status == TaskStatus.COMPLETED for t in self.tasks.values())

    @property
    def deplaning_done(self) -> bool:
        t = self.tasks.get("deplaning")
        return t is not None and t.status == TaskStatus.COMPLETED

    @property
    def ready_for_boarding(self) -> bool:
        """True when cleaning + deplaning are complete (aircraft ready for new pax)."""
        for name in ("deplaning", "cleaning"):
            t = self.tasks.get(name)
            if t and t.status != TaskStatus.COMPLETED:
                return False
        return True

    @property
    def door_close_done(self) -> bool:
        t = self.tasks.get("door_close")
        return t is not None and t.status == TaskStatus.COMPLETED

    @property
    def pushback_done(self) -> bool:
        t = self.tasks.get("pushback")
        return t is not None and t.status == TaskStatus.COMPLETED

    def estimated_completion(self) -> datetime | None:
        """Estimate when the plan will complete based on the critical path."""
        if self.started_at is None:
            return None
        cp = compute_critical_path(list(self.tasks.values()))
        return self.started_at + timedelta(minutes=cp)

    def critical_path_minutes(self) -> int:
        return compute_critical_path(list(self.tasks.values()))

    def critical_path_slack(self, scheduled_departure: datetime | None) -> int:
        """Minutes of slack between critical-path completion and scheduled departure."""
        if scheduled_departure is None or self.started_at is None:
            return 0
        est = self.estimated_completion()
        if est is None:
            return 0
        return max(0, int((scheduled_departure - est).total_seconds() / 60))

    # ── Lifecycle ──

    def start(self, sim_time: datetime) -> list[TurnaroundTask]:
        """Mark the plan as started and kick off tasks with no dependencies."""
        self.started_at = sim_time
        return self._start_ready_tasks(sim_time)

    def advance(self, sim_time: datetime) -> list[TurnaroundTask]:
        """Advance all tasks one tick.  Returns tasks whose status changed."""
        if self.started_at is None or self.is_complete:
            return []

        changed: list[TurnaroundTask] = []

        # Complete in-progress tasks whose duration has elapsed
        for task in self.tasks.values():
            if task.status == TaskStatus.IN_PROGRESS and task.started_at:
                finish_at = task.started_at + timedelta(minutes=task.duration_min)
                if sim_time >= finish_at:
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = sim_time
                    changed.append(task)
                    logger.debug("Turnaround task completed: %s (reg=%s)",
                                 task.name, self.aircraft_registration)

        # Start tasks whose deps are now met
        newly_started = self._start_ready_tasks(sim_time)
        changed.extend(newly_started)

        return changed

    def extend_task(self, task_name: str, extra_minutes: int) -> bool:
        """Extend the duration of a task (e.g. baggage delay).  Returns True if found."""
        task = self.tasks.get(task_name)
        if task is None:
            return False
        task.duration_min += extra_minutes
        logger.info("Turnaround task %s extended by %d min (new dur=%d, reg=%s)",
                     task_name, extra_minutes, task.duration_min, self.aircraft_registration)
        return True

    def to_dict(self) -> dict:
        return {
            "aircraft_registration": self.aircraft_registration,
            "arrival_flight_id": self.arrival_flight_id,
            "paired_departure_id": self.paired_departure_id,
            "aircraft_type": self.aircraft_type,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "is_complete": self.is_complete,
            "ready_for_boarding": self.ready_for_boarding,
            "critical_path_minutes": self.critical_path_minutes(),
            "tasks": [t.to_dict() for t in self.tasks.values()],
        }

    # ── Internal ──

    def _start_ready_tasks(self, sim_time: datetime) -> list[TurnaroundTask]:
        """Start all PENDING tasks whose dependencies are all COMPLETED."""
        started: list[TurnaroundTask] = []
        for task in self.tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            deps_met = all(
                self.tasks[dep].status == TaskStatus.COMPLETED
                for dep in task.starts_after
                if dep in self.tasks
            )
            if deps_met:
                task.status = TaskStatus.IN_PROGRESS
                task.started_at = sim_time
                started.append(task)
                logger.debug("Turnaround task started: %s (reg=%s)",
                             task.name, self.aircraft_registration)
        return started


# ── Task templates ──────────────────────────────────────────

def _make_tasks(specs: list[tuple[str, list[str], int]]) -> dict[str, TurnaroundTask]:
    """Build a task dict from (name, starts_after, duration_min) tuples."""
    return {
        name: TurnaroundTask(name=name, starts_after=list(deps), duration_min=dur)
        for name, deps, dur in specs
    }


NARROW_BODY_TASKS: list[tuple[str, list[str], int]] = [
    # name                deps                              dur(min)
    ("jetbridge_connect",  [],                               2),
    ("deplaning",          ["jetbridge_connect"],            12),
    ("baggage_offload",    ["jetbridge_connect"],            10),
    ("fueling",            [],                               18),
    ("catering",           ["jetbridge_connect"],            22),
    ("cleaning",           ["deplaning"],                     6),
    ("baggage_loading",    ["baggage_offload"],              10),
    ("boarding",           ["cleaning", "deplaning"],        12),
    ("door_close",         ["boarding", "baggage_loading",
                            "fueling", "catering"],           2),
    ("pushback",           ["door_close"],                    1),
]

WIDE_BODY_TASKS: list[tuple[str, list[str], int]] = [
    ("jetbridge_connect",  [],                               3),
    ("deplaning",          ["jetbridge_connect"],            18),
    ("baggage_offload",    ["jetbridge_connect"],            14),
    ("fueling",            [],                               28),
    ("catering",           ["jetbridge_connect"],            32),
    ("cleaning",           ["deplaning"],                     8),
    ("baggage_loading",    ["baggage_offload"],              14),
    ("boarding",           ["cleaning", "deplaning"],        18),
    ("door_close",         ["boarding", "baggage_loading",
                            "fueling", "catering"],           2),
    ("pushback",           ["door_close"],                    1),
]

# Pre-computed nominal turnaround times (for delay-propagation math)
_NOMINAL_CACHE: dict[str, int] = {}


def _nominal_turnaround(specs: list[tuple[str, list[str], int]]) -> int:
    tasks = [TurnaroundTask(name=n, starts_after=list(d), duration_min=dur)
             for n, d, dur in specs]
    return compute_critical_path(tasks)


# Map flight_type -> task template
FLIGHT_TYPE_TASKS: dict[str, list[tuple[str, list[str], int]]] = {
    "domestic": NARROW_BODY_TASKS,
    "international_short": NARROW_BODY_TASKS,  # same tasks, slightly longer via wide body if applicable
    "international_long": WIDE_BODY_TASKS,
    "cargo": WIDE_BODY_TASKS,
    "charter": NARROW_BODY_TASKS,
}


def _select_tasks(aircraft_type: str, flight_type: str | None = None) -> list[tuple[str, list[str], int]]:
    """Select the appropriate task template based on flight_type and aircraft_type."""
    if flight_type and flight_type in FLIGHT_TYPE_TASKS:
        return FLIGHT_TYPE_TASKS[flight_type]
    # Fallback: use aircraft type (wide/narrow)
    return WIDE_BODY_TASKS if aircraft_type in WIDE_BODY_TYPES else NARROW_BODY_TASKS


def nominal_turnaround_minutes(aircraft_type: str, flight_type: str | None = None) -> int:
    """Return the pre-computed nominal turnaround time for delay math."""
    key = flight_type or ("wide" if aircraft_type in WIDE_BODY_TYPES else "narrow")
    if key not in _NOMINAL_CACHE:
        specs = _select_tasks(aircraft_type, flight_type)
        _NOMINAL_CACHE[key] = _nominal_turnaround(specs)
    return _NOMINAL_CACHE[key]


# ── Scheduler / critical-path ───────────────────────────────

def compute_critical_path(tasks: Sequence[TurnaroundTask]) -> int:
    """Compute the minimum turnaround time (critical-path length) in minutes.

    Uses longest-path on the task DAG via topological sort.
    """
    by_name: dict[str, TurnaroundTask] = {t.name: t for t in tasks}

    # Kahn's algorithm for topological sort
    in_degree: dict[str, int] = {t.name: 0 for t in tasks}
    adj: dict[str, list[str]] = {t.name: [] for t in tasks}
    for t in tasks:
        for dep in t.starts_after:
            if dep in by_name:
                adj[dep].append(t.name)
                in_degree[t.name] += 1

    queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
    earliest_finish: dict[str, int] = {t.name: 0 for t in tasks}

    while queue:
        name = queue.popleft()
        task = by_name[name]
        start = earliest_finish[name]
        finish = start + task.duration_min
        for succ in adj[name]:
            if finish > earliest_finish[succ]:
                earliest_finish[succ] = finish
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    # Critical path = max earliest_finish + that task's duration
    # Actually earliest_finish already stores the earliest START for successors.
    # We need earliest_finish of each task = earliest_start + duration
    return max(
        earliest_finish[t.name] + t.duration_min
        for t in tasks
    )


def topological_order(tasks: Sequence[TurnaroundTask]) -> list[str]:
    """Return task names in topological (dependency) order."""
    by_name = {t.name: t for t in tasks}
    in_degree: dict[str, int] = {t.name: 0 for t in tasks}
    adj: dict[str, list[str]] = {t.name: [] for t in tasks}
    for t in tasks:
        for dep in t.starts_after:
            if dep in by_name:
                adj[dep].append(t.name)
                in_degree[t.name] += 1

    result: list[str] = []
    queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
    while queue:
        name = queue.popleft()
        result.append(name)
        for succ in adj[name]:
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)
    return result


# ── Factory ─────────────────────────────────────────────────

def create_turnaround_plan(
    aircraft_registration: str,
    arrival_flight_id: str,
    aircraft_type: str,
    paired_departure_id: str | None = None,
    flight_type: str | None = None,
) -> TurnaroundPlan:
    """Create a new TurnaroundPlan with the correct task template."""
    specs = _select_tasks(aircraft_type, flight_type)
    return TurnaroundPlan(
        aircraft_registration=aircraft_registration,
        arrival_flight_id=arrival_flight_id,
        paired_departure_id=paired_departure_id,
        aircraft_type=aircraft_type,
        tasks=_make_tasks(specs),
    )

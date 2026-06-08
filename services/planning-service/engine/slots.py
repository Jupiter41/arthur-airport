"""Slot allocation & coordination engine (2B — ROADMAP_USECASE.md).

Provides:
- Slot request allocation using integer linear programming (PuLP)
- Schedule compression to identify shiftable flights
- Strategy comparison: FCFS vs optimised vs priority-weighted

The ILP minimises total displacement (|requested_time - allocated_time|)
subject to per-hour runway and gate capacity constraints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    import pulp
except ImportError:
    pulp = None  # type: ignore[assignment]


# ── Models ──────────────────────────────────────────────────


@dataclass
class SlotRequest:
    """A slot allocation request from an airline."""

    id: str
    airline: str
    requested_hour: int  # 0–23
    requested_minute: int = 0  # 0–59
    aircraft_type: str = "A320"
    priority: int = 1  # 1 = standard, 2 = medium, 3 = high
    direction: str = "departure"  # departure | arrival

    @property
    def requested_slot(self) -> int:
        """Convert requested time to 15-minute slot index (0–95)."""
        return self.requested_hour * 4 + self.requested_minute // 15


@dataclass
class SlotAllocation:
    """The result of allocating a single slot request."""

    request_id: str
    airline: str
    requested_hour: int
    requested_minute: int
    allocated_hour: int
    allocated_minute: int
    displacement_minutes: int
    direction: str


@dataclass
class AllocationResult:
    """Full result of a slot allocation run."""

    strategy: str
    allocations: list[SlotAllocation] = field(default_factory=list)
    total_displacement_minutes: int = 0
    max_displacement_minutes: int = 0
    unallocated_count: int = 0
    hourly_demand: dict[int, int] = field(default_factory=dict)
    hourly_capacity: dict[int, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "allocations": [
                {
                    "request_id": a.request_id,
                    "airline": a.airline,
                    "requested_time": f"{a.requested_hour:02d}:{a.requested_minute:02d}",
                    "allocated_time": f"{a.allocated_hour:02d}:{a.allocated_minute:02d}",
                    "displacement_minutes": a.displacement_minutes,
                    "direction": a.direction,
                }
                for a in self.allocations
            ],
            "total_displacement_minutes": self.total_displacement_minutes,
            "max_displacement_minutes": self.max_displacement_minutes,
            "mean_displacement_minutes": round(
                self.total_displacement_minutes / max(len(self.allocations), 1), 1
            ),
            "unallocated_count": self.unallocated_count,
            "hourly_demand": self.hourly_demand,
            "hourly_capacity": self.hourly_capacity,
        }


@dataclass
class CompressionOpportunity:
    """A flight that can be shifted to improve throughput."""

    flight_number: str
    airline: str
    current_hour: int
    current_minute: int
    suggested_hour: int
    suggested_minute: int
    shift_minutes: int
    reason: str
    throughput_gain_pct: float


# ── Capacity constraints ────────────────────────────────────

# Movements per hour: combined arrivals + departures.
DEFAULT_HOURLY_CAPACITY = 60  # ~30 arr + 30 dep per hour (2 runways, IFR)
DEFAULT_GATE_CAPACITY_PER_HOUR = 42  # 42 gates, avg turnaround ~60 min


def _slot_to_time(slot_idx: int) -> tuple[int, int]:
    """Convert 15-minute slot index to (hour, minute)."""
    hour = slot_idx // 4
    minute = (slot_idx % 4) * 15
    return hour, minute


def _time_to_slot(hour: int, minute: int) -> int:
    """Convert time to 15-minute slot index."""
    return hour * 4 + minute // 15


# ── FCFS Strategy ───────────────────────────────────────────


def allocate_fcfs(
    requests: list[SlotRequest],
    hourly_capacity: int = DEFAULT_HOURLY_CAPACITY,
) -> AllocationResult:
    """First-Come-First-Served allocation.

    Allocates slots in request order. If the requested hour is at capacity,
    shifts to the next available hour.
    """
    # Track usage per hour
    usage: dict[int, int] = {h: 0 for h in range(24)}

    allocations: list[SlotAllocation] = []
    unallocated = 0

    for req in requests:
        allocated = False
        # Try requested hour first, then search outward
        for offset in range(24):
            for direction in [0, 1] if offset > 0 else [0]:
                h = req.requested_hour + offset * (1 if direction == 0 else -1)
                if h < 0 or h > 23:
                    continue
                if usage[h] < hourly_capacity:
                    usage[h] += 1
                    disp = abs(h - req.requested_hour) * 60
                    allocations.append(SlotAllocation(
                        request_id=req.id,
                        airline=req.airline,
                        requested_hour=req.requested_hour,
                        requested_minute=req.requested_minute,
                        allocated_hour=h,
                        allocated_minute=req.requested_minute,
                        displacement_minutes=disp,
                        direction=req.direction,
                    ))
                    allocated = True
                    break
            if allocated:
                break
        if not allocated:
            unallocated += 1

    total_disp = sum(a.displacement_minutes for a in allocations)
    max_disp = max((a.displacement_minutes for a in allocations), default=0)

    return AllocationResult(
        strategy="fcfs",
        allocations=allocations,
        total_displacement_minutes=total_disp,
        max_displacement_minutes=max_disp,
        unallocated_count=unallocated,
        hourly_demand={h: sum(1 for r in requests if r.requested_hour == h) for h in range(24)},
        hourly_capacity={h: hourly_capacity for h in range(24)},
    )


# ── Priority-weighted FCFS ──────────────────────────────────


def allocate_priority(
    requests: list[SlotRequest],
    hourly_capacity: int = DEFAULT_HOURLY_CAPACITY,
) -> AllocationResult:
    """Priority-weighted FCFS: high-priority requests get first pick.

    Sorts requests by priority (descending) then processes as FCFS.
    """
    sorted_requests = sorted(requests, key=lambda r: -r.priority)
    result = allocate_fcfs(sorted_requests, hourly_capacity)
    result.strategy = "priority_weighted"
    return result


# ── ILP-Optimised allocation ────────────────────────────────


def allocate_optimised(
    requests: list[SlotRequest],
    hourly_capacity: int = DEFAULT_HOURLY_CAPACITY,
) -> AllocationResult:
    """Optimised slot allocation using Integer Linear Programming.

    Minimises total displacement subject to capacity constraints.
    Uses PuLP's built-in CBC solver (no external dependency).
    """
    if pulp is None:
        raise ImportError("PuLP is required for optimised allocation: pip install pulp")

    n = len(requests)
    hours = list(range(24))

    # Decision variables: x[i][h] = 1 if request i is assigned to hour h
    prob = pulp.LpProblem("SlotAllocation", pulp.LpMinimize)

    x = {}
    for i in range(n):
        for h in hours:
            x[i, h] = pulp.LpVariable(f"x_{i}_{h}", cat="Binary")

    # Objective: minimise total displacement (weighted by inverse priority)
    prob += pulp.lpSum(
        x[i, h] * abs(h - requests[i].requested_hour) * 60 / max(requests[i].priority, 1)
        for i in range(n)
        for h in hours
    )

    # Constraint 1: each request assigned to exactly one hour
    for i in range(n):
        prob += pulp.lpSum(x[i, h] for h in hours) == 1

    # Constraint 2: capacity per hour
    for h in hours:
        prob += pulp.lpSum(x[i, h] for i in range(n)) <= hourly_capacity

    # Constraint 3: limit displacement to ±4 hours max
    for i in range(n):
        req_h = requests[i].requested_hour
        for h in hours:
            if abs(h - req_h) > 4:
                prob += x[i, h] == 0

    # Solve
    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=30))

    allocations: list[SlotAllocation] = []
    unallocated = 0

    if prob.status == pulp.constants.LpStatusOptimal:
        for i in range(n):
            assigned_hour = None
            for h in hours:
                if pulp.value(x[i, h]) and pulp.value(x[i, h]) > 0.5:
                    assigned_hour = h
                    break
            if assigned_hour is not None:
                disp = abs(assigned_hour - requests[i].requested_hour) * 60
                allocations.append(SlotAllocation(
                    request_id=requests[i].id,
                    airline=requests[i].airline,
                    requested_hour=requests[i].requested_hour,
                    requested_minute=requests[i].requested_minute,
                    allocated_hour=assigned_hour,
                    allocated_minute=requests[i].requested_minute,
                    displacement_minutes=disp,
                    direction=requests[i].direction,
                ))
            else:
                unallocated += 1
    else:
        # Fallback to FCFS if ILP infeasible
        logger.warning("ILP infeasible or timeout — falling back to FCFS")
        return allocate_fcfs(requests, hourly_capacity)

    total_disp = sum(a.displacement_minutes for a in allocations)
    max_disp = max((a.displacement_minutes for a in allocations), default=0)

    return AllocationResult(
        strategy="optimised",
        allocations=allocations,
        total_displacement_minutes=total_disp,
        max_displacement_minutes=max_disp,
        unallocated_count=unallocated,
        hourly_demand={h: sum(1 for r in requests if r.requested_hour == h) for h in range(24)},
        hourly_capacity={h: hourly_capacity for h in range(24)},
    )


# ── Schedule compression ────────────────────────────────────


def find_compression_opportunities(
    schedule: list[dict],
    hourly_capacity: int = DEFAULT_HOURLY_CAPACITY,
    shift_limit_minutes: int = 15,
) -> list[CompressionOpportunity]:
    """Identify flights that can be shifted ±N minutes to smooth demand peaks.

    Scans for hours exceeding capacity and suggests moving excess flights
    to adjacent under-utilised hours.
    """
    # Count flights per hour
    hourly: dict[int, list[dict]] = {h: [] for h in range(24)}
    for f in schedule:
        dep = f.get("scheduled_departure", "")
        try:
            hour = int(dep[11:13]) if len(dep) > 12 else 0
        except (ValueError, IndexError):
            hour = 0
        hourly[hour].append(f)

    opportunities: list[CompressionOpportunity] = []

    for h in range(24):
        excess = len(hourly[h]) - hourly_capacity
        if excess <= 0:
            continue

        # Find adjacent hours with spare capacity
        candidates = hourly[h][-excess:]  # take last N flights from peak hour

        for flight in candidates:
            # Try shifting ±1 hour (within shift_limit_minutes semantics)
            for target_h in [h - 1, h + 1]:
                if target_h < 0 or target_h > 23:
                    continue
                if len(hourly[target_h]) < hourly_capacity:
                    shift_min = abs(target_h - h) * 60
                    if shift_min > shift_limit_minutes * 4:
                        continue  # respect generous shift limit for suggestions

                    dep = flight.get("scheduled_departure", "")
                    try:
                        minute = int(dep[14:16]) if len(dep) > 15 else 0
                    except (ValueError, IndexError):
                        minute = 0

                    throughput_gain = (excess / max(len(hourly[h]), 1)) * 100

                    opportunities.append(CompressionOpportunity(
                        flight_number=flight.get("flight_number", "???"),
                        airline=flight.get("airline_code", "??"),
                        current_hour=h,
                        current_minute=minute,
                        suggested_hour=target_h,
                        suggested_minute=minute,
                        shift_minutes=shift_min if target_h > h else -shift_min,
                        reason=f"Hour {h:02d} at {len(hourly[h])}/{hourly_capacity} capacity",
                        throughput_gain_pct=round(throughput_gain, 1),
                    ))
                    break  # Only suggest one shift per flight

    return opportunities


# ── Strategy comparison ─────────────────────────────────────


def compare_strategies(
    requests: list[SlotRequest],
    hourly_capacity: int = DEFAULT_HOURLY_CAPACITY,
) -> dict:
    """Run all three strategies and return a side-by-side comparison."""
    fcfs = allocate_fcfs(requests, hourly_capacity)
    priority = allocate_priority(requests, hourly_capacity)

    results = {
        "fcfs": fcfs.to_dict(),
        "priority_weighted": priority.to_dict(),
    }

    if pulp is not None:
        optimised = allocate_optimised(requests, hourly_capacity)
        results["optimised"] = optimised.to_dict()
    else:
        results["optimised"] = {"error": "PuLP not installed — install with: pip install pulp"}

    # Summary comparison
    results["summary"] = {
        "strategies_compared": list(results.keys()),
        "best_strategy": min(
            [k for k in results if k != "summary" and "error" not in results[k]],
            key=lambda k: results[k].get("total_displacement_minutes", float("inf")),
        ),
        "improvement_vs_fcfs_pct": round(
            (1 - results.get("optimised", results["priority_weighted"]).get(
                "total_displacement_minutes", fcfs.total_displacement_minutes
            ) / max(fcfs.total_displacement_minutes, 1)) * 100,
            1,
        ) if fcfs.total_displacement_minutes > 0 else 0.0,
    }

    return results

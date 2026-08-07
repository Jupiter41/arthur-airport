"""Runway queue — priority heap for runway slot assignment.

Maintains separate arrival and departure queues. On each tick, assigns
runway slots based on current capacity (weather-dependent).

Priority: emergency/incident flights first, then by estimated time ASC.
Arrivals take priority over departures during IMC/LIFR.

Phase 1.4 enhancements:
  - P1-4-1: Wake turbulence separation matrix
  - P1-4-2: Runway alternation in IMC (interleave arr/dep)
  - P1-4-3: Runway occupancy time (ROT) enforcement
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from heapq import heappush, heappop

from _common.airport_config import load_airport_runtime_config

logger = logging.getLogger(__name__)

_cavok_capacity = load_airport_runtime_config().operations.weather_capacity["CAVOK"]

# ── Wake turbulence separation (P1-4-1) ─────────────────────

# Aircraft weight categories based on ICAO type designator
WEIGHT_CATEGORY: dict[str, str] = {
    # SUPER
    "A380": "SUPER",
    # HEAVY
    "B77W": "HEAVY", "B744": "HEAVY", "B748": "HEAVY", "B77F": "HEAVY",
    "A333": "HEAVY", "A332": "HEAVY", "A359": "HEAVY", "A346": "HEAVY",
    # MEDIUM
    "A320": "MEDIUM", "A321": "MEDIUM", "A319": "MEDIUM",
    "B738": "MEDIUM", "B739": "MEDIUM", "B737": "MEDIUM",
    "E195": "MEDIUM", "E190": "MEDIUM",
    # LIGHT
    "DH8D": "LIGHT", "AT75": "LIGHT", "AT76": "LIGHT",
    "C208": "LIGHT", "BE20": "LIGHT",
}

# Minimum separation in NM: SEPARATION_NM[leader_cat][follower_cat]
# Based on ICAO Doc 4444 wake turbulence separation minima
SEPARATION_NM: dict[str, dict[str, float]] = {
    "SUPER":  {"SUPER": 4.0, "HEAVY": 6.0, "MEDIUM": 7.0, "LIGHT": 8.0},
    "HEAVY":  {"SUPER": 4.0, "HEAVY": 4.0, "MEDIUM": 5.0, "LIGHT": 6.0},
    "MEDIUM": {"SUPER": 3.0, "HEAVY": 3.0, "MEDIUM": 3.0, "LIGHT": 5.0},
    "LIGHT":  {"SUPER": 3.0, "HEAVY": 3.0, "MEDIUM": 3.0, "LIGHT": 3.0},
}

# Approach speed by weight category (knots) for time conversion
APPROACH_SPEED_KT: dict[str, int] = {
    "SUPER": 150, "HEAVY": 140, "MEDIUM": 130, "LIGHT": 110,
}

# Runway occupancy time in seconds by weight category (P1-4-3)
ROT_SECONDS: dict[str, tuple[int, int]] = {
    "SUPER": (70, 90),
    "HEAVY": (55, 75),
    "MEDIUM": (40, 60),
    "LIGHT": (35, 50),
}


def get_weight_category(aircraft_type: str) -> str:
    """Get ICAO weight category for an aircraft type."""
    return WEIGHT_CATEGORY.get(aircraft_type, "MEDIUM")


def separation_seconds(leader_type: str, follower_type: str) -> int:
    """Compute minimum separation in seconds between two aircraft.

    Converts NM separation to seconds using the follower's approach speed.
    """
    leader_cat = get_weight_category(leader_type)
    follower_cat = get_weight_category(follower_type)
    nm = SEPARATION_NM.get(leader_cat, {}).get(follower_cat, 3.0)
    speed_kt = APPROACH_SPEED_KT.get(follower_cat, 130)
    # time = distance / speed, convert NM/kt to seconds
    return int(nm / speed_kt * 3600)


def rot_seconds(aircraft_type: str) -> int:
    """Runway occupancy time in seconds for a given aircraft type."""
    cat = get_weight_category(aircraft_type)
    lo, hi = ROT_SECONDS.get(cat, (40, 60))
    return (lo + hi) // 2


@dataclass(order=True)
class RunwayQueueItem:
    priority: tuple  # (is_not_emergency, estimated_time_iso, flight_id)
    flight_id: str = field(compare=False)
    operation: str = field(compare=False)  # "landing" or "takeoff"
    estimated_time: str = field(compare=False)
    aircraft_type: str = field(compare=False, default="A320")


class RunwayQueue:
    """Manages runway slot assignments with priority-based scheduling.

    Phase 1.4 additions:
      - Wake turbulence separation matrix (P1-4-1)
      - Runway alternation in IMC — interleave arr/dep (P1-4-2)
      - Runway occupancy time enforcement (P1-4-3)
    """

    def __init__(self):
        self._arrival_queue: list[RunwayQueueItem] = []
        self._departure_queue: list[RunwayQueueItem] = []
        self._queued_flights: set[str] = set()  # prevent duplicates

        # Capacity from weather — updated by WeatherStateChanged events
        self._arrival_rate: int = _cavok_capacity.arrival  # movements/hour (CAVOK default)
        self._departure_rate: int = _cavok_capacity.departure
        self._weather_category: str = "CAVOK"
        self._ils_required: bool = False

        # Track recent assignments for current_rate calculation
        self._recent_assignments: list[str] = []  # ISO timestamps
        self._rate_window_minutes: int = 60

        # Phase 1.4: Last assigned aircraft type for wake separation
        self._last_arrival_type: str = ""
        self._last_departure_type: str = ""
        # Phase 1.4: Runway occupancy cooldown (sim_time when runway is free)
        self._runway_free_at: datetime | None = None

    def update_capacity(self, arrival_rate: int, departure_rate: int,
                        weather_category: str) -> None:
        """Update runway capacity based on weather conditions."""
        self._arrival_rate = arrival_rate
        self._departure_rate = departure_rate
        self._weather_category = weather_category
        self._ils_required = weather_category in ("IMC", "LIFR")
        logger.info(
            "Runway capacity updated: arr=%d/hr dep=%d/hr weather=%s",
            arrival_rate, departure_rate, weather_category,
        )

    def enqueue_arrival(self, flight_id: str, estimated_time: str,
                        is_emergency: bool = False,
                        aircraft_type: str = "A320") -> None:
        """Add a flight to the arrival queue."""
        if flight_id in self._queued_flights:
            return
        self._queued_flights.add(flight_id)
        priority = (0 if is_emergency else 1, estimated_time, flight_id)
        item = RunwayQueueItem(
            priority=priority,
            flight_id=flight_id,
            operation="landing",
            estimated_time=estimated_time,
            aircraft_type=aircraft_type,
        )
        heappush(self._arrival_queue, item)

    def enqueue_departure(self, flight_id: str, estimated_time: str,
                          is_emergency: bool = False,
                          aircraft_type: str = "A320") -> None:
        """Add a flight to the departure queue."""
        if flight_id in self._queued_flights:
            return
        self._queued_flights.add(flight_id)
        priority = (0 if is_emergency else 1, estimated_time, flight_id)
        item = RunwayQueueItem(
            priority=priority,
            flight_id=flight_id,
            operation="takeoff",
            estimated_time=estimated_time,
            aircraft_type=aircraft_type,
        )
        heappush(self._departure_queue, item)

    def remove(self, flight_id: str) -> None:
        """Remove a flight from queues (e.g. on cancellation)."""
        self._queued_flights.discard(flight_id)
        # Lazy removal — items stay in heap but won't match on dequeue

    def _runway_occupied(self, sim_time: datetime) -> bool:
        """P1-4-3: Check if runway is still occupied from last landing/takeoff."""
        if self._runway_free_at is None:
            return False
        return sim_time < self._runway_free_at

    def _record_runway_use(self, sim_time: datetime, aircraft_type: str) -> None:
        """P1-4-3: Record a runway use, blocking it for ROT duration."""
        rot = rot_seconds(aircraft_type)
        self._runway_free_at = sim_time + timedelta(seconds=rot)

    def assign_slots(self, sim_time: datetime) -> list[dict]:
        """Assign runway slots for this tick.

        Returns list of {flight_id, operation, aircraft_type} assignments.
        Capacity is per hour, so per minute = rate / 60.

        Phase 1.4 enhancements:
          - ROT: skip if runway still occupied from last assignment
          - Wake separation: check timing against last same-type assignment
          - IMC alternation: interleave arrivals and departures
        """
        # P1-4-3: If runway still occupied, no assignments this tick
        if self._runway_occupied(sim_time):
            return []

        arrival_slots = max(1, self._arrival_rate // 60)
        departure_slots = max(1, self._departure_rate // 60)

        assigned: list[dict] = []

        # P1-4-2: In IMC/LIFR single-runway ops, interleave arr/dep
        if self._weather_category in ("IMC", "LIFR"):
            assigned = self._assign_alternating(sim_time, arrival_slots + departure_slots)
        else:
            # Normal mode: arrivals first, then departures
            assigned.extend(self._assign_from_queue(
                self._arrival_queue, "landing", arrival_slots, sim_time,
            ))
            assigned.extend(self._assign_from_queue(
                self._departure_queue, "takeoff", departure_slots, sim_time,
            ))

        # Track assignments for current_rate and ROT
        sim_iso = sim_time.isoformat()
        for a in assigned:
            self._recent_assignments.append(sim_iso)
            self._record_runway_use(sim_time, a.get("aircraft_type", "A320"))
            # Track last aircraft type for wake separation
            if a["operation"] == "landing":
                self._last_arrival_type = a.get("aircraft_type", "A320")
            else:
                self._last_departure_type = a.get("aircraft_type", "A320")

        # Prune old assignments outside the window
        cutoff = (sim_time - timedelta(minutes=self._rate_window_minutes)).isoformat()
        self._recent_assignments = [
            t for t in self._recent_assignments if t >= cutoff
        ]

        return assigned

    def _assign_from_queue(
        self,
        queue: list[RunwayQueueItem],
        operation: str,
        max_slots: int,
        sim_time: datetime,
    ) -> list[dict]:
        """Assign slots from a single queue, respecting wake separation."""
        assigned = []
        count = 0
        last_type = self._last_arrival_type if operation == "landing" else self._last_departure_type

        while queue and count < max_slots:
            item = heappop(queue)
            if item.flight_id not in self._queued_flights:
                continue  # lazy removal — skip cancelled flights

            # P1-4-1: Wake turbulence separation check
            if last_type and assigned:
                # We already assigned one this tick — enforce separation
                sep = separation_seconds(last_type, item.aircraft_type)
                # At 1-minute tick resolution, we can only enforce >= 60s separation
                if sep > 60:
                    # Put it back and stop — need to wait
                    heappush(queue, item)
                    break

            self._queued_flights.discard(item.flight_id)
            assigned.append({
                "flight_id": item.flight_id,
                "operation": operation,
                "aircraft_type": item.aircraft_type,
            })
            last_type = item.aircraft_type
            count += 1

        return assigned

    def _assign_alternating(
        self,
        sim_time: datetime,
        max_total: int,
    ) -> list[dict]:
        """P1-4-2: Interleave arrivals and departures for IMC single-runway ops.

        Pattern: arrival, departure, arrival, departure...
        Arrivals still get priority (start with arrival).
        """
        assigned: list[dict] = []
        arr_turn = True  # start with arrival
        attempts = 0
        max_attempts = max_total * 2  # prevent infinite loop

        while len(assigned) < max_total and attempts < max_attempts:
            attempts += 1
            if arr_turn:
                items = self._assign_from_queue(
                    self._arrival_queue, "landing", 1, sim_time,
                )
                if items:
                    assigned.extend(items)
                    arr_turn = False
                else:
                    # No arrivals — try a departure instead
                    items = self._assign_from_queue(
                        self._departure_queue, "takeoff", 1, sim_time,
                    )
                    if items:
                        assigned.extend(items)
                    arr_turn = True
            else:
                items = self._assign_from_queue(
                    self._departure_queue, "takeoff", 1, sim_time,
                )
                if items:
                    assigned.extend(items)
                    arr_turn = True
                else:
                    # No departures — try an arrival instead
                    items = self._assign_from_queue(
                        self._arrival_queue, "landing", 1, sim_time,
                    )
                    if items:
                        assigned.extend(items)
                    arr_turn = False

            # Safety: if both queues empty, stop
            arr_avail = any(i.flight_id in self._queued_flights for i in self._arrival_queue)
            dep_avail = any(i.flight_id in self._queued_flights for i in self._departure_queue)
            if not arr_avail and not dep_avail:
                break

        return assigned

        # Track assignments for current_rate
        sim_iso = sim_time.isoformat()
        for _ in assigned:
            self._recent_assignments.append(sim_iso)
        # Prune old assignments outside the window
        cutoff = (sim_time - timedelta(minutes=self._rate_window_minutes)).isoformat()
        self._recent_assignments = [
            t for t in self._recent_assignments if t >= cutoff
        ]

        return assigned

    @property
    def arrivals_queued(self) -> int:
        return len([i for i in self._arrival_queue if i.flight_id in self._queued_flights])

    @property
    def departures_queued(self) -> int:
        return len([i for i in self._departure_queue if i.flight_id in self._queued_flights])

    @property
    def ils_required(self) -> bool:
        return self._ils_required

    @property
    def weather_category(self) -> str:
        return self._weather_category

    @property
    def arrival_rate(self) -> int:
        return self._arrival_rate

    @property
    def departure_rate(self) -> int:
        return self._departure_rate

    @property
    def capacity_per_hour(self) -> int:
        """Total capacity (arrivals + departures) per hour."""
        return self._arrival_rate + self._departure_rate

    @property
    def current_rate(self) -> int:
        """Actual movements in the last 60 sim-minutes."""
        return len(self._recent_assignments)

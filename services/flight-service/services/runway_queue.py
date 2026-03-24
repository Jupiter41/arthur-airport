"""Runway queue — priority heap for runway slot assignment.

Maintains separate arrival and departure queues. On each tick, assigns
runway slots based on current capacity (weather-dependent).

Priority: emergency/incident flights first, then by estimated time ASC.
Arrivals take priority over departures during IMC/LIFR.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from heapq import heappush, heappop

logger = logging.getLogger(__name__)


@dataclass(order=True)
class RunwayQueueItem:
    priority: tuple  # (is_not_emergency, estimated_time_iso, flight_id)
    flight_id: str = field(compare=False)
    operation: str = field(compare=False)  # "landing" or "takeoff"
    estimated_time: str = field(compare=False)


class RunwayQueue:
    """Manages runway slot assignments with priority-based scheduling."""

    def __init__(self):
        self._arrival_queue: list[RunwayQueueItem] = []
        self._departure_queue: list[RunwayQueueItem] = []
        self._queued_flights: set[str] = set()  # prevent duplicates

        # Capacity from weather — updated by WeatherStateChanged events
        self._arrival_rate: int = 32   # movements/hour (CAVOK default)
        self._departure_rate: int = 32
        self._weather_category: str = "CAVOK"
        self._ils_required: bool = False

        # Track recent assignments for current_rate calculation
        self._recent_assignments: list[str] = []  # ISO timestamps
        self._rate_window_minutes: int = 60

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
                        is_emergency: bool = False) -> None:
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
        )
        heappush(self._arrival_queue, item)

    def enqueue_departure(self, flight_id: str, estimated_time: str,
                          is_emergency: bool = False) -> None:
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
        )
        heappush(self._departure_queue, item)

    def remove(self, flight_id: str) -> None:
        """Remove a flight from queues (e.g. on cancellation)."""
        self._queued_flights.discard(flight_id)
        # Lazy removal — items stay in heap but won't match on dequeue

    def assign_slots(self, sim_time: datetime) -> list[dict]:
        """Assign runway slots for this tick.

        Returns list of {flight_id, operation, runway_id} assignments.
        Capacity is per hour, so per minute = rate / 60.
        """
        arrival_slots = max(1, self._arrival_rate // 60)
        departure_slots = max(1, self._departure_rate // 60)

        # In IMC/LIFR, arrivals take priority
        if self._weather_category in ("IMC", "LIFR"):
            arrival_slots = min(arrival_slots + 1, len(self._arrival_queue))

        assigned = []

        # Assign arrival slots
        arr_assigned = 0
        while self._arrival_queue and arr_assigned < arrival_slots:
            item = heappop(self._arrival_queue)
            if item.flight_id not in self._queued_flights:
                continue  # lazy removal — skip cancelled flights
            self._queued_flights.discard(item.flight_id)
            assigned.append({
                "flight_id": item.flight_id,
                "operation": "landing",
            })
            arr_assigned += 1

        # Assign departure slots
        dep_assigned = 0
        while self._departure_queue and dep_assigned < departure_slots:
            item = heappop(self._departure_queue)
            if item.flight_id not in self._queued_flights:
                continue
            self._queued_flights.discard(item.flight_id)
            assigned.append({
                "flight_id": item.flight_id,
                "operation": "takeoff",
            })
            dep_assigned += 1

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

"""Conveyor pipeline — in-memory zone state + per-tick throughput drain.

Models the baggage handling system as a series of zones with throughput constraints.
Items flow: induction → screening → sorting → make-up (loading) → arrival-belt.
"""

import logging
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BagInZone:
    """A baggage item currently queued in a conveyor zone."""
    baggage_id: str
    tag: str
    flight_id: str
    is_dg: bool
    dg_class: str | None
    passenger_id: str | None
    terminal: str  # A, B, or C
    entered_at: str  # ISO timestamp when entered this zone


@dataclass
class ZoneState:
    zone_id: str
    status: str = "normal"  # normal | degraded | offline
    throughput_per_hr: int = 0
    queue: deque[BagInZone] = field(default_factory=deque)

    @property
    def items(self) -> int:
        return len(self.queue)


# Zone throughput capacities from SPEC.md §3
# Arrival belts increased from 200→600 to handle peak arrival volumes
# (210 arrivals/day × ~150 bags/flight requires ~1300 bags/hr across 6 belts)
ZONE_THROUGHPUT: dict[str, int] = {
    "induction-A": 600, "induction-B": 600, "induction-C": 600,
    "screening-unit-1": 300, "screening-unit-2": 300,
    "screening-unit-3": 300, "screening-unit-4": 300,
    "screening-unit-5": 300, "screening-unit-6": 300,
    "sorting-matrix": 1800,
    **{f"make-up-{t}-{n}": 150 for t in "ABC" for n in range(1, 6)},
    **{f"arrival-belt-{n}": 600 for n in range(1, 7)},
}

# Mapping terminals to screening units (2 per terminal)
TERMINAL_SCREENING: dict[str, list[str]] = {
    "A": ["screening-unit-1", "screening-unit-2"],
    "B": ["screening-unit-3", "screening-unit-4"],
    "C": ["screening-unit-5", "screening-unit-6"],
}

# Mapping terminals to make-up areas
TERMINAL_MAKEUP: dict[str, list[str]] = {
    t: [f"make-up-{t}-{n}" for n in range(1, 6)]
    for t in "ABC"
}

# Pipeline order for status progression
ZONE_TO_STATUS: dict[str, str] = {}
for z in ZONE_THROUGHPUT:
    if z.startswith("induction"):
        ZONE_TO_STATUS[z] = "inducted"
    elif z.startswith("screening"):
        ZONE_TO_STATUS[z] = "screening"
    elif z == "sorting-matrix":
        ZONE_TO_STATUS[z] = "sorting"
    elif z.startswith("make-up"):
        ZONE_TO_STATUS[z] = "loaded"
    elif z.startswith("arrival-belt"):
        ZONE_TO_STATUS[z] = "on_carousel"


class ConveyorSystem:
    """In-memory conveyor pipeline modelling the baggage handling system.

    Items flow through zones in order:
    induction → screening → sorting-matrix → make-up (loading).
    Arrival belts handle incoming baggage for passenger collection.
    Each zone has a throughput cap (items/hr) and can be degraded or offline.
    """

    def __init__(self) -> None:
        self._zones: dict[str, ZoneState] = {}
        self._screening_round_robin: dict[str, int] = {"A": 0, "B": 0, "C": 0}
        self._makeup_round_robin: dict[str, int] = {"A": 0, "B": 0, "C": 0}
        self._initialize_zones()

    def _initialize_zones(self) -> None:
        for zone_id, throughput in ZONE_THROUGHPUT.items():
            self._zones[zone_id] = ZoneState(
                zone_id=zone_id,
                throughput_per_hr=throughput,
            )

    def get_zone(self, zone_id: str) -> ZoneState | None:
        return self._zones.get(zone_id)

    def get_all_zones(self) -> dict[str, ZoneState]:
        return self._zones

    def set_zone_status(self, zone_id: str, status: str) -> None:
        if zone_id in self._zones:
            self._zones[zone_id].status = status
            logger.info("Zone %s status changed to %s", zone_id, status)

    def induct_bag(self, bag: BagInZone, sim_time: str) -> str:
        """Add a bag to the appropriate induction zone based on terminal."""
        zone_id = f"induction-{bag.terminal}"
        zone = self._zones.get(zone_id)
        if not zone:
            # Fallback to induction-A
            zone_id = "induction-A"
            zone = self._zones[zone_id]
        bag.entered_at = sim_time
        zone.queue.append(bag)
        return zone_id

    def remove_bag_from_all_zones(self, baggage_id: str) -> BagInZone | None:
        """Remove a bag from whatever zone it's in. Used for offloading."""
        for zone in self._zones.values():
            for i, bag in enumerate(zone.queue):
                if bag.baggage_id == baggage_id:
                    del zone.queue[i]
                    return bag
        return None

    def drain_zone(self, zone: ZoneState, delta_minutes: int = 1) -> list[BagInZone]:
        """Drain items from a zone based on its throughput capacity.

        ``delta_minutes`` scales throughput for multi-minute ticks at high
        sim speeds so that tick-skipping doesn't reduce conveyor capacity.
        Returns list of bags moved out of this zone.
        """
        if zone.status == "offline":
            return []

        capacity = zone.throughput_per_hr
        if zone.status == "degraded":
            capacity = int(capacity * 0.5)

        # items_to_advance per tick covering `delta_minutes` sim-minutes
        items_to_advance = min(zone.items, max(1, capacity * delta_minutes // 60))
        advanced: list[BagInZone] = []
        for _ in range(items_to_advance):
            if zone.queue:
                advanced.append(zone.queue.popleft())
        return advanced

    def advance_tick(self, sim_time: str, delta_minutes: int = 1) -> dict[str, list[BagInZone]]:
        """Advance all zones by one tick. Returns dict of zone_id -> bags that
        exited that zone and need to move to the next stage.

        Pipeline flow:
        induction-{T} → screening-unit-{N} → sorting-matrix → make-up-{T}-{N}

        Arrival belts are terminal — bags that exit make-up are "loaded".
        Arrival belts drain to "collected" (handled separately by flight events).
        """
        # Process zones in reverse pipeline order to prevent double-advancing
        # in a single tick. Process downstream first.
        outputs: dict[str, list[BagInZone]] = {}

        # 1. Drain arrival belts (terminal zone — bags exit system)
        for n in range(1, 7):
            zone_id = f"arrival-belt-{n}"
            zone = self._zones[zone_id]
            exited = self.drain_zone(zone, delta_minutes)
            if exited:
                outputs[zone_id] = exited

        # 2. Drain make-up zones → bags become "loaded"
        for t in "ABC":
            for n in range(1, 6):
                zone_id = f"make-up-{t}-{n}"
                zone = self._zones[zone_id]
                exited = self.drain_zone(zone, delta_minutes)
                if exited:
                    outputs[zone_id] = exited

        # 3. Drain sorting-matrix → route to make-up zones by terminal
        zone = self._zones["sorting-matrix"]
        sorted_bags = self.drain_zone(zone, delta_minutes)
        if sorted_bags:
            outputs["sorting-matrix"] = []
            for bag in sorted_bags:
                makeup_zone = self._pick_makeup_zone(bag.terminal)
                bag.entered_at = sim_time
                self._zones[makeup_zone].queue.append(bag)
            outputs["sorting-matrix"] = sorted_bags

        # 4. Drain screening zones → send to sorting-matrix
        for unit_n in range(1, 7):
            zone_id = f"screening-unit-{unit_n}"
            zone = self._zones[zone_id]
            screened = self.drain_zone(zone, delta_minutes)
            if screened:
                outputs[zone_id] = screened
                for bag in screened:
                    bag.entered_at = sim_time
                    self._zones["sorting-matrix"].queue.append(bag)

        # 5. Drain induction zones → send to screening
        for t in "ABC":
            zone_id = f"induction-{t}"
            zone = self._zones[zone_id]
            inducted = self.drain_zone(zone, delta_minutes)
            if inducted:
                outputs[zone_id] = inducted
                for bag in inducted:
                    screening_zone = self._pick_screening_zone(t)
                    bag.entered_at = sim_time
                    self._zones[screening_zone].queue.append(bag)

        return outputs

    def _pick_screening_zone(self, terminal: str) -> str:
        """Round-robin select a screening unit for a terminal, respecting status."""
        units = TERMINAL_SCREENING.get(terminal, ["screening-unit-1", "screening-unit-2"])
        available = [u for u in units if self._zones[u].status != "offline"]
        if not available:
            # All offline — queue in first unit anyway (will be stuck)
            return units[0]
        idx = self._screening_round_robin.get(terminal, 0) % len(available)
        self._screening_round_robin[terminal] = idx + 1
        return available[idx]

    def _pick_makeup_zone(self, terminal: str) -> str:
        """Round-robin select a make-up carousel for a terminal."""
        carousels = TERMINAL_MAKEUP.get(terminal, TERMINAL_MAKEUP["A"])
        available = [c for c in carousels if self._zones[c].status != "offline"]
        if not available:
            return carousels[0]
        idx = self._makeup_round_robin.get(terminal, 0) % len(available)
        self._makeup_round_robin[terminal] = idx + 1
        return available[idx]

    def get_zone_summary(self) -> list[dict]:
        """Get summary of all zones for the flow map."""
        result = []
        for zone_id in sorted(self._zones.keys()):
            zone = self._zones[zone_id]
            utilisation = 0
            if zone.throughput_per_hr > 0:
                # Queue capacity = 5 minutes of throughput (reasonable buffer)
                queue_capacity = max(1, (zone.throughput_per_hr * 5) // 60)
                utilisation = min(100, int(zone.items / queue_capacity * 100)) if zone.items > 0 else 0
            result.append({
                "zone_id": zone_id,
                "items": zone.items,
                "status": zone.status,
                "throughput_per_hour": zone.throughput_per_hr,
                "utilisation_pct": utilisation,
            })
        return result

    def get_system_failures_count(self) -> int:
        """Count zones currently offline."""
        return sum(1 for z in self._zones.values() if z.status == "offline")

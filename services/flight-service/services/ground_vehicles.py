"""Ground vehicle pool — dispatch, contention, and lifecycle tracking.

Manages a fleet of ground vehicles (fuel trucks, catering trucks, pushback tugs,
baggage loaders, stairs) that are dispatched to gates for turnaround tasks.
Vehicles have spatial positions and transit times computed from the airport layout.

Vehicle lifecycle:  available → dispatched → at_gate → returning → available
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from _common.airport_config import load_airport_runtime_config

logger = logging.getLogger(__name__)

# Vehicle types and the turnaround tasks they serve
VEHICLE_TASK_MAP: dict[str, str] = {
    "fueling": "fuel_truck",
    "catering": "catering_truck",
    "pushback": "pushback_tug",
    "baggage_offload": "baggage_loader",
    "baggage_loading": "baggage_loader",
}

# Fleet size per type (sized for 420 flights/day with ~20 concurrent turnarounds)
FLEET_SIZE: dict[str, int] = {
    "fuel_truck": 8,
    "catering_truck": 6,
    "pushback_tug": 10,
    "baggage_loader": 8,
    "stairs": 4,
}

# Depot positions on the 0-1000 grid (central apron area)
DEPOT_POSITION: dict[str, float] = {"x": 500.0, "y": 300.0}

# Vehicle speed on apron in metres per minute (same as spatial.APRON_SPEED)
VEHICLE_SPEED_M_PER_MIN = load_airport_runtime_config().operations.apron_speed_m_min


@dataclass
class GroundVehicle:
    """In-memory representation of a ground vehicle."""
    id: str
    vehicle_type: str
    status: str = "available"       # available | dispatched | at_gate | returning
    current_gate: str | None = None
    position_x: float = 0.0
    position_y: float = 0.0
    dispatched_at: datetime | None = None
    arrives_at: datetime | None = None    # when vehicle reaches gate / depot
    task_name: str | None = None          # which turnaround task it's serving
    flight_id: str | None = None          # which flight it's serving

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.vehicle_type,
            "status": self.status,
            "current_gate": self.current_gate,
            "position_x": self.position_x,
            "position_y": self.position_y,
            "task_name": self.task_name,
            "flight_id": self.flight_id,
        }


@dataclass
class GroundVehiclePool:
    """Manages the ground vehicle fleet."""
    vehicles: dict[str, GroundVehicle] = field(default_factory=dict)
    # gate_id → {x, y} positions (set from spatial data at startup)
    gate_positions: dict[str, dict] = field(default_factory=dict)
    # Pending requests: (task_name, gate_id, flight_id) waiting for a vehicle
    pending_requests: list[tuple[str, str, str]] = field(default_factory=list)

    def initialize_fleet(self) -> list[GroundVehicle]:
        """Create the initial vehicle fleet and return all vehicles."""
        vehicles: list[GroundVehicle] = []
        for vtype, count in FLEET_SIZE.items():
            for i in range(count):
                vid = f"GV-{vtype[:3].upper()}-{i+1:03d}"
                v = GroundVehicle(
                    id=vid,
                    vehicle_type=vtype,
                    position_x=DEPOT_POSITION["x"],
                    position_y=DEPOT_POSITION["y"],
                )
                self.vehicles[vid] = v
                vehicles.append(v)
        logger.info(
            "Ground vehicle pool initialized: %s",
            {t: c for t, c in FLEET_SIZE.items()},
        )
        return vehicles

    def set_gate_positions(self, positions: dict[str, dict]) -> None:
        """Set gate spatial positions for transit time computation."""
        self.gate_positions = positions

    def _transit_minutes(self, from_x: float, from_y: float,
                         to_x: float, to_y: float) -> int:
        """Compute transit time in minutes between two grid positions."""
        dist = math.hypot(to_x - from_x, to_y - from_y)
        minutes = dist / VEHICLE_SPEED_M_PER_MIN
        return max(1, round(minutes))  # minimum 1 minute transit

    def _find_nearest_available(self, vehicle_type: str,
                                gate_x: float, gate_y: float) -> GroundVehicle | None:
        """Find the nearest available vehicle of the given type."""
        best: GroundVehicle | None = None
        best_dist = float("inf")
        for v in self.vehicles.values():
            if v.vehicle_type == vehicle_type and v.status == "available":
                dist = math.hypot(gate_x - v.position_x, gate_y - v.position_y)
                if dist < best_dist:
                    best_dist = dist
                    best = v
        return best

    def request_vehicle(
        self,
        task_name: str,
        gate_id: str,
        flight_id: str,
        sim_time: datetime,
    ) -> tuple[GroundVehicle | None, int]:
        """Request a vehicle for a turnaround task.

        Returns (vehicle, transit_minutes) if available, or (None, 0) if
        no vehicle of the required type is free. When None is returned,
        the request is queued for later dispatch.
        """
        vehicle_type = VEHICLE_TASK_MAP.get(task_name)
        if vehicle_type is None:
            return None, 0  # task doesn't need a vehicle

        gate_pos = self.gate_positions.get(gate_id, {})
        gate_x = gate_pos.get("position_x", DEPOT_POSITION["x"])
        gate_y = gate_pos.get("position_y", DEPOT_POSITION["y"])

        vehicle = self._find_nearest_available(vehicle_type, gate_x, gate_y)
        if vehicle is None:
            # No vehicle available — queue the request
            self.pending_requests.append((task_name, gate_id, flight_id))
            logger.info(
                "Vehicle contention: no %s available for %s at gate %s",
                vehicle_type, flight_id, gate_id,
            )
            return None, 0

        transit = self._transit_minutes(
            vehicle.position_x, vehicle.position_y, gate_x, gate_y,
        )
        vehicle.status = "dispatched"
        vehicle.current_gate = gate_id
        vehicle.dispatched_at = sim_time
        vehicle.arrives_at = sim_time + timedelta(minutes=transit)
        vehicle.task_name = task_name
        vehicle.flight_id = flight_id
        vehicle.position_x = gate_x  # will be at gate after transit
        vehicle.position_y = gate_y

        logger.info(
            "Dispatched %s (%s) to gate %s for %s, transit %d min",
            vehicle.id, vehicle_type, gate_id, flight_id, transit,
        )
        return vehicle, transit

    def arrive_at_gate(self, vehicle_id: str, sim_time: datetime) -> bool:
        """Mark a dispatched vehicle as arrived at gate."""
        v = self.vehicles.get(vehicle_id)
        if v is None or v.status != "dispatched":
            return False
        v.status = "at_gate"
        return True

    def release_vehicle(
        self,
        vehicle_id: str,
        sim_time: datetime,
    ) -> tuple[bool, int]:
        """Release a vehicle back to depot after task completion.

        Returns (success, return_transit_minutes).
        """
        v = self.vehicles.get(vehicle_id)
        if v is None or v.status not in ("at_gate", "dispatched"):
            return False, 0

        transit = self._transit_minutes(
            v.position_x, v.position_y,
            DEPOT_POSITION["x"], DEPOT_POSITION["y"],
        )
        v.status = "returning"
        v.dispatched_at = sim_time
        v.arrives_at = sim_time + timedelta(minutes=transit)
        v.task_name = None
        v.flight_id = None
        v.current_gate = None
        return True, transit

    def advance(self, sim_time: datetime) -> list[tuple[str, GroundVehicle]]:
        """Advance vehicle states. Returns list of (event_type, vehicle) for changed vehicles."""
        events: list[tuple[str, GroundVehicle]] = []

        for v in self.vehicles.values():
            if v.status == "dispatched" and v.arrives_at and sim_time >= v.arrives_at:
                v.status = "at_gate"
                v.arrives_at = None
                events.append(("arrived_at_gate", v))

            elif v.status == "returning" and v.arrives_at and sim_time >= v.arrives_at:
                v.status = "available"
                v.position_x = DEPOT_POSITION["x"]
                v.position_y = DEPOT_POSITION["y"]
                v.arrives_at = None
                events.append(("returned", v))

        # Try to fulfill pending requests with newly available vehicles
        still_pending: list[tuple[str, str, str]] = []
        for task_name, gate_id, flight_id in self.pending_requests:
            vehicle_type = VEHICLE_TASK_MAP.get(task_name)
            if vehicle_type is None:
                continue
            gate_pos = self.gate_positions.get(gate_id, {})
            gate_x = gate_pos.get("position_x", DEPOT_POSITION["x"])
            gate_y = gate_pos.get("position_y", DEPOT_POSITION["y"])

            vehicle = self._find_nearest_available(vehicle_type, gate_x, gate_y)
            if vehicle is None:
                still_pending.append((task_name, gate_id, flight_id))
                continue

            transit = self._transit_minutes(
                vehicle.position_x, vehicle.position_y, gate_x, gate_y,
            )
            vehicle.status = "dispatched"
            vehicle.current_gate = gate_id
            vehicle.dispatched_at = sim_time
            vehicle.arrives_at = sim_time + timedelta(minutes=transit)
            vehicle.task_name = task_name
            vehicle.flight_id = flight_id
            vehicle.position_x = gate_x
            vehicle.position_y = gate_y
            events.append(("dispatched", vehicle))
            logger.info(
                "Dispatched %s (%s) to gate %s for %s (from queue), transit %d min",
                vehicle.id, vehicle_type, gate_id, flight_id, transit,
            )

        self.pending_requests = still_pending
        return events

    def utilisation_by_type(self) -> dict[str, float]:
        """Return utilisation percentage per vehicle type."""
        type_counts: dict[str, int] = {}
        type_busy: dict[str, int] = {}
        for v in self.vehicles.values():
            type_counts[v.vehicle_type] = type_counts.get(v.vehicle_type, 0) + 1
            if v.status != "available":
                type_busy[v.vehicle_type] = type_busy.get(v.vehicle_type, 0) + 1
        return {
            vtype: (type_busy.get(vtype, 0) / count * 100) if count > 0 else 0.0
            for vtype, count in type_counts.items()
        }

    def vehicles_for_flight(self, flight_id: str) -> list[GroundVehicle]:
        """Return all vehicles currently assigned to a flight."""
        return [v for v in self.vehicles.values() if v.flight_id == flight_id]

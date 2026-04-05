"""In-memory operational state aggregated from Kafka events.

This module maintains a live view of the airport's operational state derived purely
from consumed Kafka events. It is the primary data source for bottleneck detection
and recommendation generation — no direct service-to-service HTTP calls.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class FlightState:
    """Lightweight in-memory flight record."""
    flight_id: str
    status: str = "scheduled"
    flight_type: str = "departure"  # departure | arrival
    gate: str | None = None
    runway: str | None = None
    terminal: str | None = None
    delay_minutes: float = 0.0
    scheduled_departure: datetime | None = None
    scheduled_arrival: datetime | None = None
    passenger_count: int = 0
    aircraft_type: str = ""


@dataclass
class SecurityState:
    """Security queue state per terminal."""
    terminal: str
    queue_depth: int = 0
    open_lanes: int = 4
    forecast_wait_minutes: float = 0.0
    forecast_confidence: float = 0.0
    last_updated: datetime | None = None


@dataclass
class BaggageZoneState:
    """Baggage conveyor zone utilisation."""
    zone: str
    capacity: int = 0
    current_count: int = 0
    utilisation_pct: float = 0.0
    overloaded_since: datetime | None = None


@dataclass
class VehicleTypeState:
    """Ground vehicle utilisation per type."""
    vehicle_type: str
    total: int = 0
    dispatched: int = 0
    utilisation_pct: float = 0.0


@dataclass
class WeatherSnapshot:
    """Latest weather conditions."""
    category: str = "CAVOK"
    visibility_m: float = 9999.0
    wind_speed_kt: float = 5.0
    ceiling_ft: float | None = None
    runway_capacity_pct: float = 100.0
    updated_at: datetime | None = None


class OperationalState:
    """Aggregated operational state rebuilt from Kafka events.

    Thread-safe for single-writer (consumer) / multi-reader (endpoints) use
    since Python's GIL protects dict mutations for simple types.
    """

    def __init__(self) -> None:
        # Current sim time
        self.sim_time: datetime | None = None
        self.speed_multiplier: float = 1.0
        self.tick_number: int = 0

        # Flight state
        self.flights: dict[str, FlightState] = {}

        # Security queues per terminal
        self.security: dict[str, SecurityState] = {
            t: SecurityState(terminal=t)
            for t in ("Terminal A", "Terminal B", "Terminal C")
        }

        # Baggage zone utilisation
        self.baggage_zones: dict[str, BaggageZoneState] = {}
        # Per-terminal make-up carousel tracking
        self.makeup_utilisation: dict[str, float] = defaultdict(float)
        # Time spent over threshold per zone (for 5-min rule)
        self.makeup_over_threshold_since: dict[str, datetime | None] = defaultdict(lambda: None)

        # Ground vehicles
        self.vehicles: dict[str, VehicleTypeState] = {}

        # Weather
        self.weather: WeatherSnapshot = WeatherSnapshot()

        # Active incidents
        self.active_incidents: dict[str, dict] = {}

        # Passenger forecasts (from passenger-service events)
        self.forecasts: dict[str, dict] = {}

        # Connection risk data
        self.connection_clusters: list[dict] = []

        # Recent security congestion events
        self.security_congestion_events: deque = deque(maxlen=100)

    # ── Event handlers ───────────────────────────────────────

    def on_clock_tick(self, payload: dict) -> None:
        """Process SimClockTick."""
        self.sim_time = _parse_dt(payload.get("sim_time"))
        self.speed_multiplier = payload.get("speed_multiplier", 1.0)
        self.tick_number = payload.get("tick_number", 0)

    def on_flight_status_changed(self, payload: dict) -> None:
        """Process FlightStatusChanged."""
        fid = payload.get("flight_id", "")
        if fid not in self.flights:
            self.flights[fid] = FlightState(flight_id=fid)
        f = self.flights[fid]
        f.status = payload.get("new_status", f.status)
        f.delay_minutes = payload.get("delay_minutes", f.delay_minutes)
        f.flight_type = payload.get("flight_type", f.flight_type)
        f.terminal = payload.get("terminal", f.terminal)
        f.passenger_count = payload.get("passenger_count", f.passenger_count)
        f.aircraft_type = payload.get("aircraft_type", f.aircraft_type)

    def on_flight_gate_assigned(self, payload: dict) -> None:
        """Process FlightGateAssigned."""
        fid = payload.get("flight_id", "")
        if fid not in self.flights:
            self.flights[fid] = FlightState(flight_id=fid)
        self.flights[fid].gate = payload.get("gate_id")
        self.flights[fid].terminal = payload.get("terminal")

    def on_flight_cancelled(self, payload: dict) -> None:
        """Process FlightCancelled."""
        fid = payload.get("flight_id", "")
        if fid in self.flights:
            self.flights[fid].status = "cancelled"

    def on_passenger_status_changed(self, payload: dict) -> None:
        """Process PassengerStatusChanged — track queue depths."""
        zone = payload.get("new_zone", "")
        terminal = payload.get("terminal", "")
        if "security" in zone.lower() and terminal in self.security:
            # Increment direction based on transition
            old_zone = payload.get("old_zone", "")
            if "security" not in old_zone.lower():
                self.security[terminal].queue_depth += 1
            elif "security" in old_zone.lower() and "security" not in zone.lower():
                self.security[terminal].queue_depth = max(
                    0, self.security[terminal].queue_depth - 1
                )
            self.security[terminal].last_updated = self.sim_time

    def on_security_congestion_detected(self, payload: dict) -> None:
        """Process SecurityCongestionDetected."""
        self.security_congestion_events.append({
            "terminal": payload.get("terminal", ""),
            "queue_depth": payload.get("queue_depth", 0),
            "forecast_wait_minutes": payload.get("forecast_wait_minutes", 0),
            "confidence": payload.get("confidence", 0),
            "sim_time": self.sim_time,
        })
        terminal = payload.get("terminal", "")
        if terminal in self.security:
            self.security[terminal].queue_depth = payload.get("queue_depth", 0)
            self.security[terminal].forecast_wait_minutes = payload.get(
                "forecast_wait_minutes", 0
            )
            self.security[terminal].forecast_confidence = payload.get(
                "confidence", 0
            )

    def on_baggage_status_changed(self, payload: dict) -> None:
        """Process BaggageStatusChanged — track zone occupancy."""
        new_zone = payload.get("new_zone", "")
        old_zone = payload.get("old_zone", "")

        # Track make-up carousel utilisation
        if new_zone.startswith("make_up") or new_zone.startswith("MU-"):
            if new_zone not in self.baggage_zones:
                self.baggage_zones[new_zone] = BaggageZoneState(
                    zone=new_zone, capacity=150,
                )
            z = self.baggage_zones[new_zone]
            z.current_count += 1
            z.utilisation_pct = (z.current_count / z.capacity * 100) if z.capacity else 0

        if old_zone.startswith("make_up") or old_zone.startswith("MU-"):
            if old_zone in self.baggage_zones:
                z = self.baggage_zones[old_zone]
                z.current_count = max(0, z.current_count - 1)
                z.utilisation_pct = (z.current_count / z.capacity * 100) if z.capacity else 0

    def on_weather_state_changed(self, payload: dict) -> None:
        """Process WeatherStateChanged."""
        self.weather.category = payload.get("category", self.weather.category)
        self.weather.visibility_m = payload.get("visibility_m", self.weather.visibility_m)
        self.weather.wind_speed_kt = payload.get("wind_speed_kt", self.weather.wind_speed_kt)
        self.weather.ceiling_ft = payload.get("ceiling_ft", self.weather.ceiling_ft)
        self.weather.runway_capacity_pct = payload.get(
            "runway_capacity_pct", self.weather.runway_capacity_pct
        )
        self.weather.updated_at = self.sim_time

    def on_incident_created(self, payload: dict) -> None:
        """Process IncidentCreated."""
        iid = payload.get("incident_id", "")
        self.active_incidents[iid] = {
            "id": iid,
            "type": payload.get("type", ""),
            "severity": payload.get("severity", ""),
            "status": "active",
            "location": payload.get("location", ""),
            "created_at": self.sim_time,
        }

    def on_incident_status_changed(self, payload: dict) -> None:
        """Process IncidentStatusChanged."""
        iid = payload.get("incident_id", "")
        new_status = payload.get("new_status", "")
        if iid in self.active_incidents:
            if new_status == "resolved":
                del self.active_incidents[iid]
            else:
                self.active_incidents[iid]["status"] = new_status

    def on_ground_vehicle_dispatched(self, payload: dict) -> None:
        """Process GroundVehicleDispatched."""
        vtype = payload.get("vehicle_type", "")
        if vtype not in self.vehicles:
            self.vehicles[vtype] = VehicleTypeState(vehicle_type=vtype)
        v = self.vehicles[vtype]
        v.dispatched += 1
        v.total = max(v.total, payload.get("fleet_total", v.total))
        v.utilisation_pct = (v.dispatched / v.total * 100) if v.total else 0

    def on_ground_vehicle_returned(self, payload: dict) -> None:
        """Process GroundVehicleReturned."""
        vtype = payload.get("vehicle_type", "")
        if vtype in self.vehicles:
            v = self.vehicles[vtype]
            v.dispatched = max(0, v.dispatched - 1)
            v.utilisation_pct = (v.dispatched / v.total * 100) if v.total else 0

    # ── Convenience queries ──────────────────────────────────

    def get_free_gates_by_terminal(self) -> dict[str, int]:
        """Count gates not assigned to active flights, per terminal."""
        # Gate counts from known terminal structure
        terminal_gates: dict[str, int] = {
            "Terminal A": 14, "Terminal B": 14, "Terminal C": 14,
        }
        occupied: dict[str, int] = defaultdict(int)
        for f in self.flights.values():
            if f.gate and f.terminal and f.status not in (
                "completed", "cancelled", "departed", "airborne",
            ):
                occupied[f.terminal] += 1
        return {
            t: max(0, total - occupied.get(t, 0))
            for t, total in terminal_gates.items()
        }

    def get_flights_needing_gate(self) -> list[FlightState]:
        """Flights that need a gate but don't have one."""
        return [
            f for f in self.flights.values()
            if f.status in ("approaching", "holding", "landed") and not f.gate
        ]

    def get_delayed_arrivals(self) -> list[FlightState]:
        """Inbound flights currently delayed."""
        return [
            f for f in self.flights.values()
            if f.flight_type == "arrival" and f.delay_minutes > 0
            and f.status not in ("completed", "cancelled")
        ]

    def get_makeup_utilisation_by_terminal(self) -> dict[str, float]:
        """Average make-up carousel utilisation per terminal."""
        terminal_utils: dict[str, list[float]] = defaultdict(list)
        for zone_name, zone in self.baggage_zones.items():
            # Identify terminal from zone name (e.g., "MU-A-1" → Terminal A)
            for prefix, terminal in [
                ("MU-A", "Terminal A"), ("MU-B", "Terminal B"),
                ("MU-C", "Terminal C"), ("make_up_a", "Terminal A"),
                ("make_up_b", "Terminal B"), ("make_up_c", "Terminal C"),
            ]:
                if zone_name.lower().startswith(prefix.lower()):
                    terminal_utils[terminal].append(zone.utilisation_pct)
                    break
        return {
            t: sum(vals) / len(vals) if vals else 0.0
            for t, vals in terminal_utils.items()
        }


def _parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None

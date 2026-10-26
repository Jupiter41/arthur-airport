"""In-memory operational state aggregated from Kafka events.

This module maintains a live view of the airport's operational state derived purely
from consumed Kafka events. It is the primary data source for bottleneck detection
and recommendation generation — no direct service-to-service HTTP calls.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone

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
    observed_wait_minutes: float = 0.0
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
        self.gates: dict[str, dict] = {}
        self.graph_loaded: bool = False
        self.baggage_snapshot_at: datetime | None = None

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

    def restore_graph(self, snapshot: dict) -> None:
        """Build replacement dictionaries before swapping the visible cache."""
        import json

        flights = {}
        for row in snapshot["flights"]:
            raw = row["flight"]
            gate = row.get("gate_id")
            terminal = str(row.get("terminal_id") or "").rsplit("-", 1)[-1]
            direction = raw.get("direction", "departure")
            scheduled = _parse_dt(raw.get("scheduled_time"))
            flights[raw["id"]] = FlightState(
                flight_id=raw["id"], status=raw["status"], flight_type=direction,
                gate=gate, terminal=f"Terminal {terminal}" if terminal else None,
                delay_minutes=raw.get("delay_minutes") or 0,
                scheduled_departure=scheduled if direction == "departure" else None,
                scheduled_arrival=scheduled if direction == "arrival" else None,
                passenger_count=raw.get("pax_count") or 0,
                aircraft_type=raw.get("aircraft_type") or "",
            )
        gates = {}
        for row in snapshot["gates"]:
            gate = dict(row["gate"])
            terminal = str(gate.get("terminal_id") or "").rsplit("-", 1)[-1]
            gate["terminal"] = f"Terminal {terminal}"
            gates[gate["id"]] = gate
        incidents = {row["incident"]["id"]: dict(row["incident"]) for row in snapshot["incidents"]}
        self.flights, self.gates, self.active_incidents = flights, gates, incidents
        self.graph_loaded = True
        if snapshot["weather"]:
            weather = dict(snapshot["weather"][0]["weather"])
            if weather.get("recommended_arrival_rate") is None:
                from _common.airport_config import load_airport_runtime_config
                base = load_airport_runtime_config().operations.weather_capacity[weather["category"]]
                weather.update(recommended_arrival_rate=base.arrival, recommended_departure_rate=base.departure)
            self.on_weather_state_changed(weather)
            self.weather.updated_at = _parse_dt(weather.get("timestamp"))
        for row in snapshot["baggage"]:
            self.on_baggage_zone_snapshot(json.loads(row["document"]))

    def on_clock_tick(self, payload: dict) -> None:
        """Process SimClockTick."""
        clock = _parse_dt(payload.get("sim_time"))
        if clock and self.sim_time and _utc(clock) < _utc(self.sim_time):
            # A simulation rewind must not pin aggregates to a future timestamp.
            self.baggage_zones.clear()
            self.baggage_snapshot_at = None
            self.makeup_over_threshold_since.clear()
        self.sim_time = clock
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
        f.flight_type = payload.get("direction") or payload.get("flight_type", f.flight_type)
        f.terminal = payload.get("terminal", f.terminal)
        if payload.get("gate_id"):
            f.gate = payload["gate_id"]
            f.terminal = f.terminal or f"Terminal {f.gate[0]}"
        f.passenger_count = payload.get("passenger_count", f.passenger_count)
        f.aircraft_type = payload.get("aircraft_type", f.aircraft_type)

    def on_flight_gate_assigned(self, payload: dict) -> None:
        """Process FlightGateAssigned."""
        fid = payload.get("flight_id", "")
        if fid not in self.flights:
            self.flights[fid] = FlightState(flight_id=fid)
        self.flights[fid].gate = payload.get("gate_id")
        self.flights[fid].terminal = payload.get("terminal") or (f"Terminal {payload['gate_id'][0]}" if payload.get("gate_id") else None)

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
        if terminal in {"A", "B", "C"}:
            terminal = f"Terminal {terminal}"
        if terminal in self.security:
            self.security[terminal].queue_depth = payload.get("queue_depth", 0)
            self.security[terminal].observed_wait_minutes = payload.get("wait_minutes", 0)
            self.security[terminal].forecast_wait_minutes = payload.get(
                "forecast_wait_minutes", 0
            )
            self.security[terminal].forecast_confidence = payload.get(
                "confidence", 0
            )

    def on_security_queue_updated(self, payload: dict) -> None:
        terminal = payload.get("terminal", "")
        if terminal in {"A", "B", "C"}:
            terminal = f"Terminal {terminal}"
        sec = self.security.get(terminal)
        if sec is None:
            return
        sec.queue_depth = payload["queue_depth"]
        sec.open_lanes = payload["lanes_open"]
        sec.observed_wait_minutes = payload["wait_minutes"]
        sec.last_updated = self.sim_time

    def on_baggage_status_changed(self, payload: dict) -> None:
        """Process BaggageStatusChanged — track zone occupancy."""
        new_zone = payload.get("new_zone", "")
        old_zone = payload.get("old_zone", "")

        # Owner aggregates supersede incremental estimates. Real producers use
        # scan_zone and may suppress individual events in BULK mode.
        if self.baggage_snapshot_at is not None or "scan_zone" in payload:
            return

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

    def on_baggage_zone_snapshot(self, payload: dict) -> None:
        at = _parse_dt(payload.get("at"))
        if at is None or (self.baggage_snapshot_at and _utc(at) < _utc(self.baggage_snapshot_at)):
            return
        zones = {}
        for row in payload["zones"]:
            zone_id = row["zone_id"]
            if not zone_id.startswith("make-up-"):
                continue
            capacity = max(1, int(row["throughput_per_hour"] * 5 / 60))
            zones[zone_id] = BaggageZoneState(
                zone=zone_id, capacity=capacity, current_count=row["items"],
                utilisation_pct=row["utilisation_pct"],
            )
        self.baggage_zones = zones
        self.baggage_snapshot_at = at

    def on_weather_state_changed(self, payload: dict) -> None:
        """Process WeatherStateChanged."""
        self.weather.category = payload.get("new_category") or payload.get("category", self.weather.category)
        self.weather.visibility_m = payload.get("visibility_m", self.weather.visibility_m)
        self.weather.wind_speed_kt = payload.get("wind_speed_kt", self.weather.wind_speed_kt)
        self.weather.ceiling_ft = payload.get("ceiling_ft", self.weather.ceiling_ft)
        self.weather.runway_capacity_pct = payload.get(
            "runway_capacity_pct", self.weather.runway_capacity_pct
        )
        if "recommended_arrival_rate" in payload and "recommended_departure_rate" in payload:
            from _common.airport_config import load_airport_runtime_config
            base = load_airport_runtime_config().operations.weather_capacity["CAVOK"]
            self.weather.runway_capacity_pct = 100 * (
                payload["recommended_arrival_rate"] + payload["recommended_departure_rate"]
            ) / max(1, base.arrival + base.departure)
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
        if self.graph_loaded:
            occupied = {
                f.gate for f in self.flights.values()
                if f.status in {"boarding", "delayed", "scheduled", "landed", "taxiing", "at_gate"}
            }
            counts: dict[str, int] = defaultdict(int)
            for gate_id, gate in self.gates.items():
                terminal = gate["terminal"]
                counts.setdefault(terminal, 0)
                if gate_id not in occupied and gate.get("status") not in {"closed", "maintenance", "offline"}:
                    counts[terminal] += 1
            return dict(counts)
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

    def get_free_gate_ids_by_terminal(self) -> dict[str, list[str]]:
        """Actual free gate IDs per terminal (only when the graph is loaded).

        Unlike :meth:`get_free_gates_by_terminal` (counts), this returns concrete
        gate IDs so a recommendation can name a real reassignment target. Returns
        ``{}`` before the operational graph has been loaded (no gate identities
        are known yet).
        """
        if not self.graph_loaded:
            return {}
        occupied = {
            f.gate for f in self.flights.values()
            if f.status in {"boarding", "delayed", "scheduled", "landed", "taxiing", "at_gate"}
        }
        free: dict[str, list[str]] = defaultdict(list)
        for gate_id, gate in self.gates.items():
            if gate_id not in occupied and gate.get("status") not in {"closed", "maintenance", "offline"}:
                free[gate["terminal"]].append(gate_id)
        return {t: sorted(ids) for t, ids in free.items()}

    def get_flights_needing_gate(self) -> list[FlightState]:
        """Flights that need a gate but don't have one."""
        return [
            f for f in self.flights.values()
            if f.status in ("approach", "approaching", "holding", "landed", "delayed") and not f.gate
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
                ("make-up-A", "Terminal A"), ("make-up-B", "Terminal B"),
                ("make-up-C", "Terminal C"),
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
    if hasattr(value, "to_native"):
        return value.to_native()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _utc(value: datetime) -> datetime:
    """Legacy naive simulation timestamps represent UTC too."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

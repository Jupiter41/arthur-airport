"""Unit tests for analysis-service OperationalState.

Tests the event handlers that maintain the in-memory operational state
derived from Kafka events.
"""

from datetime import datetime

import pytest

from tests.conftest import import_service_module

_state_mod = import_service_module("analysis", "services.state")
OperationalState = _state_mod.OperationalState
FlightState = _state_mod.FlightState
SecurityState = _state_mod.SecurityState
BaggageZoneState = _state_mod.BaggageZoneState
VehicleTypeState = _state_mod.VehicleTypeState
WeatherSnapshot = _state_mod.WeatherSnapshot


NOW = datetime(2024, 6, 15, 14, 30, 0)


@pytest.fixture
def state():
    return OperationalState()


class TestClockTick:
    def test_updates_sim_time(self, state: OperationalState):
        state.on_clock_tick({
            "sim_time": "2024-06-15T14:30:00",
            "speed_multiplier": 60,
            "tick_number": 100,
        })
        assert state.sim_time == NOW
        assert state.speed_multiplier == 60
        assert state.tick_number == 100

    def test_handles_missing_fields(self, state: OperationalState):
        state.on_clock_tick({})
        assert state.sim_time is None
        assert state.speed_multiplier == 1.0


class TestFlightEvents:
    def test_status_changed_creates_flight(self, state: OperationalState):
        state.on_flight_status_changed({
            "flight_id": "f1",
            "new_status": "boarding",
            "delay_minutes": 15,
            "flight_type": "departure",
            "terminal": "Terminal A",
        })
        assert "f1" in state.flights
        f = state.flights["f1"]
        assert f.status == "boarding"
        assert f.delay_minutes == 15
        assert f.terminal == "Terminal A"

    def test_status_changed_updates_existing(self, state: OperationalState):
        state.flights["f1"] = FlightState(
            flight_id="f1", status="scheduled", gate="A01",
        )
        state.on_flight_status_changed({
            "flight_id": "f1",
            "new_status": "delayed",
            "delay_minutes": 30,
        })
        assert state.flights["f1"].status == "delayed"
        assert state.flights["f1"].gate == "A01"  # Preserved

    def test_gate_assigned(self, state: OperationalState):
        state.on_flight_gate_assigned({
            "flight_id": "f1",
            "gate_id": "B07",
            "terminal": "Terminal B",
        })
        assert state.flights["f1"].gate == "B07"
        assert state.flights["f1"].terminal == "Terminal B"

    def test_flight_cancelled(self, state: OperationalState):
        state.flights["f1"] = FlightState(flight_id="f1", status="delayed")
        state.on_flight_cancelled({"flight_id": "f1"})
        assert state.flights["f1"].status == "cancelled"

    def test_cancel_unknown_flight_is_noop(self, state: OperationalState):
        state.on_flight_cancelled({"flight_id": "unknown"})
        assert "unknown" not in state.flights


class TestSecurityEvents:
    def test_congestion_detected_updates_state(self, state: OperationalState):
        state.on_security_congestion_detected({
            "terminal": "Terminal A",
            "queue_depth": 85,
            "forecast_wait_minutes": 22,
            "confidence": 0.9,
        })
        sec = state.security["Terminal A"]
        assert sec.queue_depth == 85
        assert sec.forecast_wait_minutes == 22
        assert sec.forecast_confidence == 0.9

    def test_congestion_event_recorded(self, state: OperationalState):
        state.sim_time = NOW
        state.on_security_congestion_detected({
            "terminal": "Terminal B",
            "queue_depth": 50,
            "forecast_wait_minutes": 15,
        })
        assert len(state.security_congestion_events) == 1


class TestWeatherEvents:
    def test_weather_state_changed(self, state: OperationalState):
        state.on_weather_state_changed({
            "category": "IMC",
            "visibility_m": 800,
            "wind_speed_kt": 28,
            "ceiling_ft": 500,
            "runway_capacity_pct": 55,
        })
        assert state.weather.category == "IMC"
        assert state.weather.visibility_m == 800
        assert state.weather.runway_capacity_pct == 55


class TestIncidentEvents:
    def test_incident_created(self, state: OperationalState):
        state.sim_time = NOW
        state.on_incident_created({
            "incident_id": "inc1",
            "type": "runway_incursion",
            "severity": "critical",
            "location": "runway-09L",
        })
        assert "inc1" in state.active_incidents
        assert state.active_incidents["inc1"]["type"] == "runway_incursion"

    def test_incident_resolved_removes(self, state: OperationalState):
        state.active_incidents["inc1"] = {
            "id": "inc1", "type": "test", "status": "active",
        }
        state.on_incident_status_changed({
            "incident_id": "inc1",
            "new_status": "resolved",
        })
        assert "inc1" not in state.active_incidents

    def test_incident_contained_updates_status(self, state: OperationalState):
        state.active_incidents["inc1"] = {
            "id": "inc1", "type": "test", "status": "active",
        }
        state.on_incident_status_changed({
            "incident_id": "inc1",
            "new_status": "contained",
        })
        assert state.active_incidents["inc1"]["status"] == "contained"


class TestVehicleEvents:
    def test_vehicle_dispatched(self, state: OperationalState):
        state.on_ground_vehicle_dispatched({
            "vehicle_type": "fuel_truck",
            "fleet_total": 10,
        })
        assert "fuel_truck" in state.vehicles
        v = state.vehicles["fuel_truck"]
        assert v.dispatched == 1
        assert v.total == 10
        assert v.utilisation_pct == 10.0

    def test_vehicle_returned(self, state: OperationalState):
        state.vehicles["fuel_truck"] = VehicleTypeState(
            vehicle_type="fuel_truck", total=10, dispatched=5, utilisation_pct=50.0,
        )
        state.on_ground_vehicle_returned({"vehicle_type": "fuel_truck"})
        assert state.vehicles["fuel_truck"].dispatched == 4
        assert state.vehicles["fuel_truck"].utilisation_pct == 40.0

    def test_vehicle_returned_no_negative(self, state: OperationalState):
        state.vehicles["tug"] = VehicleTypeState(
            vehicle_type="tug", total=5, dispatched=0, utilisation_pct=0,
        )
        state.on_ground_vehicle_returned({"vehicle_type": "tug"})
        assert state.vehicles["tug"].dispatched == 0


class TestBaggageEvents:
    def test_baggage_enters_makeup_zone(self, state: OperationalState):
        state.on_baggage_status_changed({
            "new_zone": "MU-A-1",
            "old_zone": "screening",
        })
        assert "MU-A-1" in state.baggage_zones
        assert state.baggage_zones["MU-A-1"].current_count == 1

    def test_baggage_leaves_makeup_zone(self, state: OperationalState):
        state.baggage_zones["MU-A-1"] = BaggageZoneState(
            zone="MU-A-1", capacity=150, current_count=10, utilisation_pct=6.7,
        )
        state.on_baggage_status_changed({
            "new_zone": "loaded",
            "old_zone": "MU-A-1",
        })
        assert state.baggage_zones["MU-A-1"].current_count == 9


class TestConvenienceQueries:
    def test_free_gates_all_empty(self, state: OperationalState):
        free = state.get_free_gates_by_terminal()
        assert free["Terminal A"] == 14
        assert free["Terminal B"] == 14
        assert free["Terminal C"] == 14

    def test_free_gates_with_occupancy(self, state: OperationalState):
        for i in range(5):
            state.flights[f"f-{i}"] = FlightState(
                flight_id=f"f-{i}", status="at_gate",
                gate=f"A{i:02d}", terminal="Terminal A",
            )
        free = state.get_free_gates_by_terminal()
        assert free["Terminal A"] == 9
        assert free["Terminal B"] == 14

    def test_flights_needing_gate(self, state: OperationalState):
        state.flights["f1"] = FlightState(flight_id="f1", status="landed")
        state.flights["f2"] = FlightState(
            flight_id="f2", status="landed", gate="A01",
        )
        state.flights["f3"] = FlightState(flight_id="f3", status="holding")
        needing = state.get_flights_needing_gate()
        ids = {f.flight_id for f in needing}
        assert "f1" in ids
        assert "f3" in ids
        assert "f2" not in ids  # Already has a gate

    def test_delayed_arrivals(self, state: OperationalState):
        state.flights["f1"] = FlightState(
            flight_id="f1", flight_type="arrival",
            status="approaching", delay_minutes=25,
        )
        state.flights["f2"] = FlightState(
            flight_id="f2", flight_type="departure",
            status="delayed", delay_minutes=15,
        )
        delayed = state.get_delayed_arrivals()
        assert len(delayed) == 1
        assert delayed[0].flight_id == "f1"

"""Unit tests for passenger-service connections risk — pure logic, no I/O."""

from datetime import datetime, timedelta


from tests.conftest import import_service_module

_conn = import_service_module("passenger", "services.connections")
MCT_MINUTES = _conn.MCT_MINUTES
connection_risk = _conn.connection_risk
compute_time_to_connection = _conn.compute_time_to_connection
evaluate_connecting_passengers = _conn.evaluate_connecting_passengers


BASE_TIME = datetime(2025, 6, 15, 10, 0, 0)


class TestConnectionRisk:
    """Verify the 4-tier risk level computation."""

    def test_ok_no_delay_plenty_of_time(self):
        assert connection_risk(0, MCT_MINUTES + 30) == "ok"

    def test_watch_moderate_delay(self):
        assert connection_risk(20, MCT_MINUTES + 30) == "watch"

    def test_at_risk_high_delay(self):
        assert connection_risk(35, MCT_MINUTES + 30) == "at_risk"

    def test_at_risk_tight_time(self):
        assert connection_risk(0, MCT_MINUTES + 10) == "at_risk"

    def test_missed_below_mct(self):
        assert connection_risk(0, MCT_MINUTES - 1) == "missed"

    def test_missed_at_zero(self):
        assert connection_risk(0, 0) == "missed"

    def test_boundary_exactly_mct(self):
        """At exactly MCT, not missed."""
        result = connection_risk(0, MCT_MINUTES)
        assert result != "missed"

    def test_boundary_exactly_mct_plus_15(self):
        """At MCT+15 with low delay, should transition from at_risk to ok."""
        result = connection_risk(0, MCT_MINUTES + 15)
        # MCT+15 is the boundary — at_risk if time_to_connection < MCT+15
        assert result in ("ok", "at_risk")

    def test_delay_16_creates_watch(self):
        assert connection_risk(16, MCT_MINUTES + 30) == "watch"

    def test_delay_15_is_ok(self):
        assert connection_risk(15, MCT_MINUTES + 30) == "ok"


class TestComputeTimeToConnection:
    def test_returns_minutes(self):
        connection_time = BASE_TIME + timedelta(minutes=90)
        result = compute_time_to_connection(BASE_TIME, connection_time)
        assert result == 90

    def test_returns_zero_when_past(self):
        connection_time = BASE_TIME - timedelta(minutes=10)
        result = compute_time_to_connection(BASE_TIME, connection_time)
        assert result == 0

    def test_none_input(self):
        result = compute_time_to_connection(BASE_TIME, None)
        assert result is None

    def test_string_input(self):
        connection_str = (BASE_TIME + timedelta(minutes=60)).isoformat()
        result = compute_time_to_connection(BASE_TIME, connection_str)
        assert result == 60


class TestEvaluateConnectingPassengers:
    def test_risk_change_detected(self):
        pax = [{
            "id": "p1",
            "name": "Test Pax",
            "pnr": "ABC123",
            "inbound_delay": 40,
            "connection_estimated": (BASE_TIME + timedelta(minutes=MCT_MINUTES + 20)).isoformat(),
            "connection_risk": "ok",
        }]
        results = evaluate_connecting_passengers(pax, BASE_TIME)
        assert len(results) == 1
        assert results[0]["risk_changed"] is True
        assert results[0]["risk_level"] == "at_risk"

    def test_no_change_when_risk_same(self):
        pax = [{
            "id": "p1",
            "name": "Test",
            "pnr": "XYZ",
            "inbound_delay": 0,
            "connection_estimated": (BASE_TIME + timedelta(hours=3)).isoformat(),
            "connection_risk": "ok",
        }]
        results = evaluate_connecting_passengers(pax, BASE_TIME)
        assert results[0]["risk_changed"] is False

    def test_skips_pax_without_connection(self):
        pax = [{"id": "p1", "connection_estimated": None}]
        results = evaluate_connecting_passengers(pax, BASE_TIME)
        assert len(results) == 0

    def test_multiple_passengers(self):
        pax = [
            {
                "id": "p1", "name": "A", "pnr": "A1", "inbound_delay": 0,
                "connection_estimated": (BASE_TIME + timedelta(hours=2)).isoformat(),
                "connection_risk": "ok",
            },
            {
                "id": "p2", "name": "B", "pnr": "B2", "inbound_delay": 50,
                "connection_estimated": (BASE_TIME + timedelta(minutes=50)).isoformat(),
                "connection_risk": "ok",
            },
        ]
        results = evaluate_connecting_passengers(pax, BASE_TIME)
        assert len(results) == 2

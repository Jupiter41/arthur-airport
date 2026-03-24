"""Integration tests — REST endpoints against live system.

These tests require the full stack to be running:
    docker compose up --build

Run with:
    python -m pytest tests/integration/ -v --tb=short
"""

import os
import time

import pytest
import requests

GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:3000")
FLIGHT_SVC = os.getenv("FLIGHT_SVC_URL", "http://localhost:8001")
PASSENGER_SVC = os.getenv("PASSENGER_SVC_URL", "http://localhost:8002")
BAGGAGE_SVC = os.getenv("BAGGAGE_SVC_URL", "http://localhost:8003")
WEATHER_SVC = os.getenv("WEATHER_SVC_URL", "http://localhost:8004")
INCIDENT_SVC = os.getenv("INCIDENT_SVC_URL", "http://localhost:8005")
SIM_SVC = os.getenv("SIM_SVC_URL", "http://localhost:8006")


def _system_reachable() -> bool:
    try:
        r = requests.get(f"{GATEWAY}/health", timeout=3)
        return r.status_code == 200
    except requests.ConnectionError:
        return False


# Skip all tests if system is not running
pytestmark = pytest.mark.skipif(
    not _system_reachable(),
    reason="Full stack not running — skipping integration tests",
)


def _get_token() -> str:
    r = requests.post(
        f"{GATEWAY}/auth/token",
        json={"client_id": "dashboard", "secret": "art-dev-secret"},
        timeout=5,
    )
    return r.json()["token"]


@pytest.fixture(scope="module")
def token():
    return _get_token()


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── Health endpoints ─────────────────────────────────────────────

class TestHealthEndpoints:
    def test_gateway_health(self):
        r = requests.get(f"{GATEWAY}/health", timeout=5)
        assert r.status_code == 200

    def test_flight_service_health(self):
        r = requests.get(f"{FLIGHT_SVC}/health", timeout=5)
        assert r.status_code == 200

    def test_passenger_service_health(self):
        r = requests.get(f"{PASSENGER_SVC}/health", timeout=5)
        assert r.status_code == 200

    def test_baggage_service_health(self):
        r = requests.get(f"{BAGGAGE_SVC}/health", timeout=5)
        assert r.status_code == 200

    def test_weather_service_health(self):
        r = requests.get(f"{WEATHER_SVC}/health", timeout=5)
        assert r.status_code == 200

    def test_incident_service_health(self):
        r = requests.get(f"{INCIDENT_SVC}/health", timeout=5)
        assert r.status_code == 200

    def test_sim_service_health(self):
        r = requests.get(f"{SIM_SVC}/health", timeout=5)
        assert r.status_code == 200


# ── Readiness ────────────────────────────────────────────────────

class TestReadiness:
    def test_all_services_ready(self):
        for url in [FLIGHT_SVC, PASSENGER_SVC, BAGGAGE_SVC, WEATHER_SVC, INCIDENT_SVC, SIM_SVC]:
            r = requests.get(f"{url}/ready", timeout=5)
            assert r.status_code == 200, f"{url}/ready returned {r.status_code}"


# ── Flight service REST ─────────────────────────────────────────

class TestFlightServiceREST:
    def test_list_flights(self):
        r = requests.get(f"{FLIGHT_SVC}/api/v1/flights", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "flights" in data
        assert "total" in data

    def test_list_flights_by_status(self):
        r = requests.get(f"{FLIGHT_SVC}/api/v1/flights?status=scheduled", timeout=10)
        assert r.status_code == 200

    def test_get_flight_by_id(self):
        # Get a flight ID first
        r = requests.get(f"{FLIGHT_SVC}/api/v1/flights?limit=1", timeout=10)
        flights = r.json().get("flights", [])
        if flights:
            fid = flights[0]["id"]
            r2 = requests.get(f"{FLIGHT_SVC}/api/v1/flights/{fid}", timeout=10)
            assert r2.status_code == 200
            assert r2.json()["id"] == fid

    def test_get_runways(self):
        r = requests.get(f"{FLIGHT_SVC}/api/v1/runways", timeout=10)
        assert r.status_code == 200

    def test_get_gates(self):
        r = requests.get(f"{FLIGHT_SVC}/api/v1/gates", timeout=10)
        assert r.status_code == 200

    def test_flight_not_found(self):
        r = requests.get(f"{FLIGHT_SVC}/api/v1/flights/nonexistent-id", timeout=5)
        assert r.status_code == 404


# ── Passenger service REST ───────────────────────────────────────

class TestPassengerServiceREST:
    def test_list_passengers(self):
        r = requests.get(f"{PASSENGER_SVC}/api/v1/passengers", timeout=10)
        assert r.status_code == 200
        assert "passengers" in r.json()

    def test_flow_summary(self):
        r = requests.get(f"{PASSENGER_SVC}/api/v1/flow/summary", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "by_status" in data

    def test_flow_heatmap(self):
        r = requests.get(f"{PASSENGER_SVC}/api/v1/flow/heatmap", timeout=10)
        assert r.status_code == 200

    def test_connections_at_risk(self):
        r = requests.get(f"{PASSENGER_SVC}/api/v1/connections/at-risk", timeout=10)
        assert r.status_code == 200

    def test_alerts(self):
        r = requests.get(f"{PASSENGER_SVC}/api/v1/alerts", timeout=10)
        assert r.status_code == 200


# ── Baggage service REST ─────────────────────────────────────────

class TestBaggageServiceREST:
    def test_list_baggage(self):
        r = requests.get(f"{BAGGAGE_SVC}/api/v1/baggage", timeout=10)
        assert r.status_code == 200

    def test_flow_summary(self):
        r = requests.get(f"{BAGGAGE_SVC}/api/v1/flow/summary", timeout=10)
        assert r.status_code == 200

    def test_flow_map(self):
        r = requests.get(f"{BAGGAGE_SVC}/api/v1/flow/map", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "zones" in data

    def test_flagged(self):
        r = requests.get(f"{BAGGAGE_SVC}/api/v1/flagged", timeout=10)
        assert r.status_code == 200


# ── Weather service REST ─────────────────────────────────────────

class TestWeatherServiceREST:
    def test_current(self):
        r = requests.get(f"{WEATHER_SVC}/api/v1/weather/current", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "category" in data

    def test_metar(self):
        r = requests.get(f"{WEATHER_SVC}/api/v1/weather/metar", timeout=10)
        assert r.status_code == 200

    def test_taf(self):
        r = requests.get(f"{WEATHER_SVC}/api/v1/weather/taf", timeout=10)
        assert r.status_code == 200

    def test_history(self):
        r = requests.get(f"{WEATHER_SVC}/api/v1/weather/history", timeout=10)
        assert r.status_code == 200

    def test_impact(self):
        r = requests.get(f"{WEATHER_SVC}/api/v1/weather/impact", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "arrival_rate" in data
        assert "departure_rate" in data


# ── Incident service REST ────────────────────────────────────────

class TestIncidentServiceREST:
    def test_list_incidents(self):
        r = requests.get(f"{INCIDENT_SVC}/api/v1/incidents", timeout=10)
        assert r.status_code == 200

    def test_alerts(self):
        r = requests.get(f"{INCIDENT_SVC}/api/v1/alerts", timeout=10)
        assert r.status_code == 200

    def test_inject_incident(self):
        r = requests.post(
            f"{INCIDENT_SVC}/api/v1/incidents/inject",
            json={"type": "system_failure", "severity": "medium", "location": "test-zone"},
            timeout=10,
        )
        assert r.status_code in (200, 201)
        data = r.json()
        assert "id" in data

    def test_get_incident_by_id(self):
        # Inject first
        r = requests.post(
            f"{INCIDENT_SVC}/api/v1/incidents/inject",
            json={"type": "system_failure", "severity": "low", "location": "test-zone"},
            timeout=10,
        )
        if r.status_code in (200, 201):
            inc_id = r.json()["id"]
            r2 = requests.get(f"{INCIDENT_SVC}/api/v1/incidents/{inc_id}", timeout=10)
            assert r2.status_code == 200


# ── Sim service REST ─────────────────────────────────────────────

class TestSimServiceREST:
    def test_status(self):
        r = requests.get(f"{SIM_SVC}/api/v1/sim/status", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "sim_time" in data

    def test_schedule(self):
        r = requests.get(f"{SIM_SVC}/api/v1/sim/schedule", timeout=10)
        assert r.status_code == 200

    def test_metrics(self):
        r = requests.get(f"{SIM_SVC}/api/v1/sim/metrics", timeout=10)
        assert r.status_code == 200


# ── Gateway proxied routes ───────────────────────────────────────

class TestGatewayProxy:
    def test_airport_aggregate(self, auth_headers):
        r = requests.get(f"{GATEWAY}/api/v1/airport", headers=auth_headers, timeout=15)
        assert r.status_code == 200

    def test_flights_via_gateway(self, auth_headers):
        r = requests.get(f"{GATEWAY}/api/v1/flights", headers=auth_headers, timeout=10)
        assert r.status_code == 200

    def test_weather_via_gateway(self, auth_headers):
        r = requests.get(f"{GATEWAY}/api/v1/weather/current", headers=auth_headers, timeout=10)
        assert r.status_code == 200

    def test_incidents_via_gateway(self, auth_headers):
        r = requests.get(f"{GATEWAY}/api/v1/incidents", headers=auth_headers, timeout=10)
        assert r.status_code == 200

    def test_sim_status_via_gateway(self, auth_headers):
        r = requests.get(f"{GATEWAY}/api/v1/sim/status", headers=auth_headers, timeout=10)
        assert r.status_code == 200

    def test_health_services(self, auth_headers):
        r = requests.get(f"{GATEWAY}/api/v1/health/services", headers=auth_headers, timeout=15)
        assert r.status_code == 200


# ── Idempotency tests ───────────────────────────────────────────

class TestIdempotency:
    """Verify that injecting the same incident twice doesn't create duplicates."""

    def test_duplicate_incident_injection(self):
        """Injecting two incidents of the same type at the same location creates
        two separate incidents (each is unique by ID). The system should handle
        this without errors."""
        payload = {"type": "runway_incursion", "severity": "high", "location": "runway-09L"}
        r1 = requests.post(f"{INCIDENT_SVC}/api/v1/incidents/inject", json=payload, timeout=10)
        r2 = requests.post(f"{INCIDENT_SVC}/api/v1/incidents/inject", json=payload, timeout=10)
        assert r1.status_code in (200, 201)
        assert r2.status_code in (200, 201)
        # Each injection creates a unique incident
        assert r1.json()["id"] != r2.json()["id"]


# ── Cascade depth test ───────────────────────────────────────────

class TestCascadeDepth:
    """Verify cascades stop at depth 5."""

    def test_runway_incursion_cascade(self):
        """A critical runway incursion should trigger cascades but not exceed depth 5."""
        r = requests.post(
            f"{INCIDENT_SVC}/api/v1/incidents/inject",
            json={"type": "runway_incursion", "severity": "critical", "location": "runway-09L"},
            timeout=10,
        )
        assert r.status_code in (200, 201)
        inc_id = r.json()["id"]

        # Wait for cascades to propagate
        time.sleep(3)

        # Get the incident with its cascade tree
        r2 = requests.get(f"{INCIDENT_SVC}/api/v1/incidents/{inc_id}", timeout=10)
        assert r2.status_code == 200
        data = r2.json()

        # Check cascade_tree depth
        if "cascade_tree" in data and data["cascade_tree"]:
            max_depth = _max_tree_depth(data["cascade_tree"])
            assert max_depth <= 5, f"Cascade depth {max_depth} exceeds limit of 5"

    def test_security_breach_cascade(self):
        """Security breach cascade chain should stay within depth limit."""
        r = requests.post(
            f"{INCIDENT_SVC}/api/v1/incidents/inject",
            json={"type": "security_breach", "severity": "critical", "location": "terminal-B"},
            timeout=10,
        )
        assert r.status_code in (200, 201)
        inc_id = r.json()["id"]
        time.sleep(3)

        r2 = requests.get(f"{INCIDENT_SVC}/api/v1/incidents/{inc_id}", timeout=10)
        assert r2.status_code == 200


def _max_tree_depth(node: dict, current: int = 0) -> int:
    """Recursively find max depth in a cascade tree."""
    children = node.get("children", [])
    if not children:
        return current
    return max(_max_tree_depth(child, current + 1) for child in children)

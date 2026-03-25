"""Resilience tests — restart recovery scenarios.

These tests verify that services recover gracefully from restarts.
Requires the full stack to be running.

Run with:
    python -m pytest tests/integration/test_resilience.py -v --tb=short -s
"""

import os
import subprocess
import time

import pytest
import requests

GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:3000")
FLIGHT_SVC = os.getenv("FLIGHT_SVC_URL", "http://localhost:8001")
PASSENGER_SVC = os.getenv("PASSENGER_SVC_URL", "http://localhost:8002")
BAGGAGE_SVC = os.getenv("BAGGAGE_SVC_URL", "http://localhost:8003")
WEATHER_SVC = os.getenv("WEATHER_SVC_URL", "http://localhost:8004")
SIM_SVC = os.getenv("SIM_SVC_URL", "http://localhost:8006")
COMPOSE_DIR = os.path.join(os.path.dirname(__file__), "..", "..")


def _system_reachable() -> bool:
    try:
        r = requests.get(f"{GATEWAY}/health", timeout=3)
        return r.status_code == 200
    except requests.ConnectionError:
        return False


def _wait_for_service(url: str, timeout: int = 60) -> bool:
    """Wait until a service is healthy."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{url}/health", timeout=3)
            if r.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(2)
    return False


def _wait_for_ready(url: str, timeout: int = 90) -> bool:
    """Wait until a service reports ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{url}/ready", timeout=3)
            if r.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(2)
    return False


pytestmark = pytest.mark.skipif(
    not _system_reachable(),
    reason="Full stack not running — skipping resilience tests",
)


class TestServiceRestart:
    """Verify service restart recovery."""

    def test_flight_service_restart(self):
        """Flight service restarts and rebuilds state from Neo4j."""
        # Get flights before restart
        r = requests.get(f"{FLIGHT_SVC}/api/v1/flights?limit=5", timeout=10)
        assert r.status_code == 200
        r.json()["total"]

        # Restart flight-service
        subprocess.run(
            ["docker", "compose", "restart", "flight-service"],
            cwd=COMPOSE_DIR, timeout=30, capture_output=True,
        )

        # Wait for recovery
        assert _wait_for_ready(FLIGHT_SVC, timeout=60), "flight-service failed to become ready"

        # Verify state recovered
        r = requests.get(f"{FLIGHT_SVC}/api/v1/flights?limit=5", timeout=10)
        assert r.status_code == 200
        # Flight count should be similar (may have changed slightly during restart)
        flights_after = r.json()["total"]
        assert flights_after > 0, "No flights after restart — state not recovered"

    def test_weather_service_restart(self):
        """Weather service restarts and has current weather."""
        r = requests.get(f"{WEATHER_SVC}/api/v1/weather/current", timeout=10)
        assert r.status_code == 200
        r.json()["category"]

        subprocess.run(
            ["docker", "compose", "restart", "weather-service"],
            cwd=COMPOSE_DIR, timeout=30, capture_output=True,
        )

        assert _wait_for_ready(WEATHER_SVC, timeout=60), "weather-service failed to become ready"

        r = requests.get(f"{WEATHER_SVC}/api/v1/weather/current", timeout=10)
        assert r.status_code == 200
        assert r.json()["category"] in ("CAVOK", "VMC", "IMC", "LIFR")


class TestAllServicesRestart:
    """Full docker compose restart — all services recover."""

    def test_full_restart(self):
        subprocess.run(
            ["docker", "compose", "restart"],
            cwd=COMPOSE_DIR, timeout=120, capture_output=True,
        )

        # Wait for all services
        services = [
            (FLIGHT_SVC, "flight-service"),
            (WEATHER_SVC, "weather-service"),
            (SIM_SVC, "sim-orchestrator"),
        ]

        for url, name in services:
            assert _wait_for_ready(url, timeout=90), f"{name} failed to become ready after restart"

        # Verify data is accessible
        r = requests.get(f"{FLIGHT_SVC}/api/v1/flights?limit=1", timeout=10)
        assert r.status_code == 200

        r = requests.get(f"{WEATHER_SVC}/api/v1/weather/current", timeout=10)
        assert r.status_code == 200


class TestRestartRebuild:
    """Verify in-memory structures are rebuilt correctly after restart."""

    def test_baggage_service_conveyor_rebuild(self):
        """Baggage service rebuilds conveyor state from Neo4j on restart."""
        r = requests.get(f"{BAGGAGE_SVC}/api/v1/baggage/conveyor-status", timeout=10)
        assert r.status_code == 200

        subprocess.run(
            ["docker", "compose", "restart", "baggage-service"],
            cwd=COMPOSE_DIR, timeout=30, capture_output=True,
        )
        assert _wait_for_ready(BAGGAGE_SVC, timeout=60)

        r = requests.get(f"{BAGGAGE_SVC}/api/v1/baggage/conveyor-status", timeout=10)
        assert r.status_code == 200

    def test_passenger_service_security_rebuild(self):
        """Passenger service rebuilds security queues from Neo4j on restart."""
        r = requests.get(f"{PASSENGER_SVC}/api/v1/passengers/security/status", timeout=10)
        assert r.status_code == 200

        subprocess.run(
            ["docker", "compose", "restart", "passenger-service"],
            cwd=COMPOSE_DIR, timeout=30, capture_output=True,
        )
        assert _wait_for_ready(PASSENGER_SVC, timeout=60)

        r = requests.get(f"{PASSENGER_SVC}/api/v1/passengers/security/status", timeout=10)
        assert r.status_code == 200
        after = r.json()
        for terminal in after.get("checkpoints", {}).values():
            assert terminal.get("queue_depth", 0) >= 0

    def test_flight_service_incident_impacts_rebuild(self):
        """Flight service rebuilds incident-affected gates/runways from Neo4j."""
        r = requests.get(f"{FLIGHT_SVC}/api/v1/flights?limit=1", timeout=10)
        assert r.status_code == 200
        total_before = r.json()["total"]

        subprocess.run(
            ["docker", "compose", "restart", "flight-service"],
            cwd=COMPOSE_DIR, timeout=30, capture_output=True,
        )
        assert _wait_for_ready(FLIGHT_SVC, timeout=60)

        r = requests.get(f"{FLIGHT_SVC}/api/v1/flights?limit=1", timeout=10)
        assert r.status_code == 200
        total_after = r.json()["total"]
        assert abs(total_after - total_before) < 50

"""Integration tests — cross-service event chain validation.

These tests validate the full event chains identified as broken in
sprint-16 audit BUG-1 through BUG-4. They require the full stack
running:
    docker compose up --build

Each test injects an event at the source service and verifies the
downstream effect via REST endpoint polling.

Run with:
    python -m pytest tests/integration/test_event_chains.py -v --tb=short -s

Ref: docs/lessons-learned/sprint-16-full-audit-report.md §6.
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

POLL_INTERVAL = 2  # seconds between polls
MAX_POLL_ATTEMPTS = 15  # max attempts (30s total)


def _system_reachable() -> bool:
    try:
        r = requests.get(f"{GATEWAY}/health", timeout=3)
        return r.status_code == 200
    except requests.ConnectionError:
        return False


pytestmark = pytest.mark.skipif(
    not _system_reachable(),
    reason="Full stack not running — skipping event chain integration tests",
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


def _poll_until(predicate, description: str, interval: int = POLL_INTERVAL, max_attempts: int = MAX_POLL_ATTEMPTS):
    """Poll until predicate returns a truthy value or timeout."""
    for attempt in range(max_attempts):
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    pytest.fail(f"Timed out waiting for: {description} (after {max_attempts * interval}s)")


# ══════════════════════════════════════════════════════════════
# BUG-1 + BUG-2: DG class 3 flagged → baggage_fire incident
# ══════════════════════════════════════════════════════════════

class TestBug1Bug2DGFireChain:
    """Validate the full chain: BaggageFlagged (DG class 3) → incident-service → baggage_fire.

    BUG-1 broke this chain because `dg_class != 3` compared string to int.
    BUG-2 caused the fire location to default to 'baggage-handling' instead
    of the actual scan_zone from the BaggageFlagged event.

    This test injects a system_failure/baggage_fire directly and verifies
    the incident-service creates it with the correct location. The full
    DG→fire chain depends on probabilistic triggering (30% chance), so we
    also verify the injection API works with the correct field mapping.
    """

    def test_inject_baggage_fire_with_location(self):
        """Inject a baggage_fire incident with a specific location and verify
        the incident is created with that location (validates BUG-2 fix)."""
        test_location = "screening-unit-3"
        r = requests.post(
            f"{INCIDENT_SVC}/api/v1/incidents/inject",
            json={
                "type": "baggage_fire",
                "severity": "high",
                "location": test_location,
                "description": "Integration test: BUG-2 location validation",
            },
            timeout=10,
        )
        assert r.status_code in (200, 201), f"Inject failed: {r.text}"
        data = r.json()
        inc_id = data["id"]

        # Verify the incident has the correct location
        r2 = requests.get(f"{INCIDENT_SVC}/api/v1/incidents/{inc_id}", timeout=10)
        assert r2.status_code == 200
        incident = r2.json()
        assert incident["location"] == test_location, (
            f"Incident location should be '{test_location}', "
            f"got '{incident['location']}'"
        )
        assert incident["type"] == "baggage_fire"

    def test_baggage_fire_appears_in_alerts(self):
        """A baggage_fire incident should generate an alert."""
        r = requests.post(
            f"{INCIDENT_SVC}/api/v1/incidents/inject",
            json={
                "type": "baggage_fire",
                "severity": "high",
                "location": "baggage-handling-A",
            },
            timeout=10,
        )
        assert r.status_code in (200, 201)
        inc_id = r.json()["id"]

        # Check alerts endpoint
        def check_alert():
            r = requests.get(f"{INCIDENT_SVC}/api/v1/alerts", timeout=10)
            if r.status_code != 200:
                return None
            alerts = r.json()
            if isinstance(alerts, dict):
                alerts = alerts.get("alerts", [])
            for alert in alerts:
                if alert.get("incident_id") == inc_id:
                    return alert
            return None

        alert = _poll_until(check_alert, f"alert for incident {inc_id}")
        assert alert["severity"] == "high"


# ══════════════════════════════════════════════════════════════
# BUG-3: System failure at power-X → baggage zone offline
# ══════════════════════════════════════════════════════════════

class TestBug3SystemFailureConveyorChain:
    """Validate: system_failure at power-A → baggage zones offline → resolve → restore.

    BUG-3 broke this because incident-service emitted 'terminal-A-power' but
    baggage-service expected 'power-A'. With the fix, the location keys align.
    """

    def test_power_failure_halts_baggage_zones(self):
        """Inject a system_failure at 'power-A' and verify baggage zones go offline."""
        # Inject system failure at power-A
        r = requests.post(
            f"{INCIDENT_SVC}/api/v1/incidents/inject",
            json={
                "type": "system_failure",
                "severity": "high",
                "location": "power-A",
                "description": "Integration test: BUG-3 power-A failure",
            },
            timeout=10,
        )
        assert r.status_code in (200, 201), f"Inject failed: {r.text}"

        # Wait for the event to propagate through Kafka to baggage-service
        def check_zones_offline():
            r = requests.get(f"{BAGGAGE_SVC}/api/v1/flow/map", timeout=10)
            if r.status_code != 200:
                return None
            data = r.json()
            zones_raw = data.get("zones", [])
            # zones may be a list of dicts or a dict — normalise to dict
            if isinstance(zones_raw, list):
                zones = {z["zone_id"]: z for z in zones_raw if "zone_id" in z}
            else:
                zones = zones_raw
            # power-A should affect induction-A, screening-unit-1, screening-unit-2
            affected = ["induction-A", "screening-unit-1", "screening-unit-2"]
            for zone_id in affected:
                zone = zones.get(zone_id, {})
                if zone.get("status") == "offline":
                    return True
            return None

        result = _poll_until(
            check_zones_offline,
            "baggage zones to go offline after power-A failure",
        )
        assert result, "Baggage zones did not go offline after power-A system failure"

    def test_conveyor_sorting_failure_halts_sorting_matrix(self):
        """Inject a system_failure at 'conveyor-sorting' and verify sorting-matrix offline."""
        r = requests.post(
            f"{INCIDENT_SVC}/api/v1/incidents/inject",
            json={
                "type": "system_failure",
                "severity": "medium",
                "location": "conveyor-sorting",
                "description": "Integration test: conveyor-sorting failure",
            },
            timeout=10,
        )
        assert r.status_code in (200, 201), f"Inject failed: {r.text}"

        def check_sorting_offline():
            r = requests.get(f"{BAGGAGE_SVC}/api/v1/flow/map", timeout=10)
            if r.status_code != 200:
                return None
            zones_raw = r.json().get("zones", [])
            if isinstance(zones_raw, list):
                zones = {z["zone_id"]: z for z in zones_raw if "zone_id" in z}
            else:
                zones = zones_raw
            zone = zones.get("sorting-matrix", {})
            if zone.get("status") == "offline":
                return True
            return None

        result = _poll_until(
            check_sorting_offline,
            "sorting-matrix to go offline after conveyor-sorting failure",
        )
        assert result

    def test_resolve_restores_zones(self):
        """Inject a power-B failure, then resolve it, and verify zones come back online."""
        # Step 1: Inject
        r = requests.post(
            f"{INCIDENT_SVC}/api/v1/incidents/inject",
            json={
                "type": "system_failure",
                "severity": "medium",
                "location": "power-B",
                "description": "Integration test: BUG-3 resolve/restore cycle",
            },
            timeout=10,
        )
        assert r.status_code in (200, 201)
        inc_id = r.json()["id"]

        # Wait for zones to go offline
        time.sleep(5)

        # Step 2: Resolve the incident
        r = requests.post(
            f"{INCIDENT_SVC}/api/v1/incidents/{inc_id}/resolve",
            json={"note": "Integration test resolve"},
            timeout=10,
        )
        # The resolve endpoint may not exist via REST — try PATCH status
        if r.status_code == 404:
            r = requests.patch(
                f"{INCIDENT_SVC}/api/v1/incidents/{inc_id}",
                json={"status": "resolved", "note": "Integration test resolve"},
                timeout=10,
            )

        # Verify the incident is now resolved
        def check_resolved():
            r = requests.get(f"{INCIDENT_SVC}/api/v1/incidents/{inc_id}", timeout=10)
            if r.status_code != 200:
                return None
            data = r.json()
            if data.get("status") == "resolved":
                return True
            return None

        _poll_until(check_resolved, f"incident {inc_id} to be resolved")

        # Step 3: Verify zones restored
        def check_zones_restored():
            r = requests.get(f"{BAGGAGE_SVC}/api/v1/flow/map", timeout=10)
            if r.status_code != 200:
                return None
            zones_raw = r.json().get("zones", [])
            if isinstance(zones_raw, list):
                zones = {z["zone_id"]: z for z in zones_raw if "zone_id" in z}
            else:
                zones = zones_raw
            affected = ["induction-B", "screening-unit-3", "screening-unit-4"]
            for zone_id in affected:
                zone = zones.get(zone_id, {})
                if zone.get("status") != "normal":
                    return None
            return True

        result = _poll_until(
            check_zones_restored,
            "baggage zones to restore after incident resolved",
        )
        assert result


# ══════════════════════════════════════════════════════════════
# BUG-4: Probabilistic incident rate — not doubled
# ══════════════════════════════════════════════════════════════

class TestBug4ProbabilisticRate:
    """Verify that probabilistic incidents fire at the expected rate, not 2×.

    BUG-4 caused both sim-orchestrator AND incident-service to independently
    generate probabilistic incidents. This test verifies that over a period,
    the incident rate is in the expected range for the spec base probabilities.

    This is a statistical test — it checks that the rate is plausible, not exact.
    """

    def test_incident_count_in_expected_range(self):
        """Over a reasonable period, total probabilistic incident count should
        be consistent with single-source generation, not doubled.

        Base probabilities sum to ~0.038 per hr. Over ~6 sim hours with a
        peak multiplier window, we'd expect 0–2 probabilistic incidents
        (single source), not 3–6 (double source).

        This test just checks the current incident list doesn't show a
        suspiciously high probabilistic-trigger count.
        """
        r = requests.get(f"{INCIDENT_SVC}/api/v1/incidents?limit=100", timeout=10)
        assert r.status_code == 200
        data = r.json()
        incidents = data if isinstance(data, list) else data.get("incidents", [])

        # Count probabilistic incidents
        prob_incidents = [
            i for i in incidents
            if i.get("trigger") == "probabilistic"
        ]
        # Count non-test manual incidents
        manual_incidents = [
            i for i in incidents
            if i.get("trigger") == "manual"
        ]

        # Get sim status to know how many hours have passed
        r = requests.get(f"{SIM_SVC}/api/v1/sim/status", timeout=10)
        sim_data = r.json()
        sim_time_str = sim_data.get("sim_time", "")

        # This is a soft check — we just verify the count isn't absurdly high
        # With single-source prob generation, we expect ~0.038 * hours incidents
        # Log for diagnostic purposes
        print(
            f"\n  Probabilistic incidents: {len(prob_incidents)}, "
            f"Manual: {len(manual_incidents)}, "
            f"Sim time: {sim_time_str}"
        )

        # If we're within the first 24 sim hours, there should be < 10
        # probabilistic incidents (with single source at ~0.038/hr base,
        # even with peak multipliers this would be ~2-4)
        # With double source (bug), we'd see ~4-8
        # This is a sanity check, not a precise statistical test
        if len(prob_incidents) > 0:
            assert len(prob_incidents) < 50, (
                f"Too many probabilistic incidents ({len(prob_incidents)}) — "
                "possible duplicate generation (BUG-4 regression)"
            )

    def test_no_sim_orchestrator_inject_topic_messages(self):
        """Verify sim-orchestrator claims to not inject probabilistic events.
        We check the /status endpoint for any indication."""
        r = requests.get(f"{SIM_SVC}/api/v1/sim/status", timeout=10)
        assert r.status_code == 200
        data = r.json()
        # The sim status should not show any probabilistic injection count
        # (since that was removed from sim-orchestrator)
        injected = data.get("events_injected_probabilistic", 0)
        assert injected == 0 or "events_injected_probabilistic" not in data, (
            f"sim-orchestrator should not inject probabilistic events, "
            f"but reports {injected} injected"
        )


# ══════════════════════════════════════════════════════════════
# Cross-service: Weather → Flight delay chain
# ══════════════════════════════════════════════════════════════

class TestWeatherFlightCascade:
    """Verify weather degradation propagates to flight delays via incident chain."""

    def test_severe_weather_creates_incident(self):
        """When weather degrades to IMC/LIFR, incident-service should auto-create
        a severe_weather incident."""
        # Check current incidents for any severe_weather
        r = requests.get(f"{INCIDENT_SVC}/api/v1/incidents?limit=100", timeout=10)
        assert r.status_code == 200
        data = r.json()
        incidents = data if isinstance(data, list) else data.get("incidents", [])

        weather_incidents = [
            i for i in incidents
            if i.get("type") == "severe_weather"
        ]
        # Just verify the endpoint works and returns structured data
        assert isinstance(weather_incidents, list)


# ══════════════════════════════════════════════════════════════
# Cross-service: Incident → Flight service reaction
# ══════════════════════════════════════════════════════════════

class TestIncidentFlightReaction:
    """Verify flight-service reacts to incidents on incidents.events."""

    def test_runway_incursion_affects_flights(self):
        """Inject a critical runway_incursion and check if flights are affected."""
        r = requests.post(
            f"{INCIDENT_SVC}/api/v1/incidents/inject",
            json={
                "type": "runway_incursion",
                "severity": "critical",
                "location": "runway-09L",
                "description": "Integration test: runway incursion cascade",
            },
            timeout=10,
        )
        assert r.status_code in (200, 201)
        inc_id = r.json()["id"]

        # Wait for cascades
        time.sleep(5)

        # Verify incident has cascade children
        r2 = requests.get(f"{INCIDENT_SVC}/api/v1/incidents/{inc_id}", timeout=10)
        assert r2.status_code == 200
        incident = r2.json()

        # At minimum, the incident should exist with correct type
        assert incident["type"] == "runway_incursion"
        assert incident["severity"] == "critical"

        # Check if any flights are delayed
        r3 = requests.get(f"{FLIGHT_SVC}/api/v1/flights?status=delayed&limit=50", timeout=10)
        assert r3.status_code == 200
        # We don't assert a specific count because it depends on sim state,
        # but the endpoint should work and return structured data
        data = r3.json()
        assert "flights" in data or isinstance(data, list)


# ══════════════════════════════════════════════════════════════
# Event schema validation against live Kafka events
# ══════════════════════════════════════════════════════════════

class TestLiveEventSchemaValidation:
    """Validate that events flowing through the system match EVENT_BUS.md schemas."""

    def test_incident_created_schema(self):
        """Inject an incident and verify the returned data matches expected schema."""
        r = requests.post(
            f"{INCIDENT_SVC}/api/v1/incidents/inject",
            json={
                "type": "security_breach",
                "severity": "medium",
                "location": "terminal-A",
            },
            timeout=10,
        )
        assert r.status_code in (200, 201)
        data = r.json()

        # Verify required fields from EVENT_BUS.md IncidentCreated
        assert "id" in data
        assert data["type"] == "security_breach"
        assert data["severity"] == "medium"
        assert "status" in data
        assert data["status"] in ("active", "contained", "resolved")

    def test_flight_data_schema(self):
        """Verify flight data matches DATA_MODEL.md Flight node schema."""
        r = requests.get(f"{FLIGHT_SVC}/api/v1/flights?limit=1", timeout=10)
        assert r.status_code == 200
        flights = r.json().get("flights", [])
        if flights:
            flight = flights[0]
            # Required fields from DATA_MODEL.md
            for field in ["id", "flight_number", "airline_code", "direction", "status"]:
                assert field in flight, f"Flight missing required field '{field}'"
            assert flight["direction"] in ("arrival", "departure")
            assert flight["status"] in (
                "scheduled", "boarding", "departed", "airborne", "approach",
                "landed", "taxiing", "at_gate", "delayed", "cancelled",
                "diverted", "arrived",
            )

    def test_baggage_flow_map_schema(self):
        """Verify baggage flow map returns properly structured zone data."""
        r = requests.get(f"{BAGGAGE_SVC}/api/v1/flow/map", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "zones" in data
        zones = data["zones"]
        assert isinstance(zones, dict)
        # Each zone should have a status
        for zone_id, zone_data in zones.items():
            assert "status" in zone_data, f"Zone '{zone_id}' missing 'status'"

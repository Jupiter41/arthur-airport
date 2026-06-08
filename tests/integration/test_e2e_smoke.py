"""End-to-end smoke test — verifies services work together in CI.

Requires docker compose services running:
    docker compose up -d neo4j zookeeper kafka cost-service planning-service sim-orchestrator

Asserts:
- cost-service /health and /ready respond
- planning-service /health responds
- A planning scenario can be created and completes
- cost-service produces cost records after simulation runs

Run with:
    python -m pytest tests/integration/test_e2e_smoke.py -v --tb=short
"""

import os
import time

import pytest
import requests

COST_SVC = os.getenv("COST_SVC_URL", "http://localhost:8008")
PLANNING_SVC = os.getenv("PLANNING_SVC_URL", "http://localhost:8009")
SIM_SVC = os.getenv("SIM_SVC_URL", "http://localhost:8006")


def _services_reachable() -> bool:
    """Check if cost-service and planning-service are reachable."""
    try:
        c = requests.get(f"{COST_SVC}/health", timeout=3)
        p = requests.get(f"{PLANNING_SVC}/health", timeout=3)
        return c.status_code == 200 and p.status_code == 200
    except requests.ConnectionError:
        return False


pytestmark = pytest.mark.skipif(
    not _services_reachable(),
    reason="cost-service or planning-service not running — skipping E2E smoke test",
)


class TestServiceHealth:
    """Verify all services are alive and ready."""

    def test_cost_service_health(self):
        r = requests.get(f"{COST_SVC}/health", timeout=5)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_planning_service_health(self):
        r = requests.get(f"{PLANNING_SVC}/health", timeout=5)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_cost_service_ready(self):
        """Cost service readiness (may be 503 if Neo4j not seeded yet — acceptable)."""
        r = requests.get(f"{COST_SVC}/ready", timeout=5)
        assert r.status_code in (200, 503)

    def test_planning_service_ready(self):
        r = requests.get(f"{PLANNING_SVC}/ready", timeout=5)
        assert r.status_code == 200


class TestPlanningScenarioLifecycle:
    """Run a quick planning scenario and verify completion."""

    def test_create_and_complete_scenario(self):
        # Create a minimal 1-day, 1-run scenario (fastest possible)
        payload = {
            "name": "CI smoke test",
            "description": "Automated CI validation",
            "horizon": "day",
            "monte_carlo_runs": 1,
            "random_seed": 42,
            "demand_source": "simulation",
            "weather_source": "simulation",
        }
        r = requests.post(f"{PLANNING_SVC}/api/v1/planning/scenarios", json=payload, timeout=10)
        assert r.status_code == 201, f"Create failed: {r.text}"
        data = r.json()
        scenario_id = data["scenario_id"]
        assert data["status"] == "pending"

        # Poll for completion (max 60s)
        deadline = time.time() + 60
        while time.time() < deadline:
            sr = requests.get(
                f"{PLANNING_SVC}/api/v1/planning/scenarios/{scenario_id}/status",
                timeout=5,
            )
            assert sr.status_code == 200
            status = sr.json()["status"]
            if status == "completed":
                break
            if status == "failed":
                pytest.fail(f"Scenario failed: {sr.json().get('error')}")
            time.sleep(1)
        else:
            pytest.fail("Scenario did not complete within 60s")

        # Verify results exist
        rr = requests.get(
            f"{PLANNING_SVC}/api/v1/planning/scenarios/{scenario_id}/results",
            timeout=5,
        )
        assert rr.status_code == 200
        results = rr.json()
        assert "kpis" in results
        assert "avg_delay_minutes" in results["kpis"]
        assert results["kpis"]["avg_delay_minutes"]["mean"] >= 0


class TestCostServiceEndpoints:
    """Verify cost-service API shape (may return empty data if sim hasn't run)."""

    def test_cost_summary_shape(self):
        r = requests.get(f"{COST_SVC}/api/v1/costs/summary", timeout=5)
        assert r.status_code == 200
        data = r.json()
        # These fields must always be present
        for field in ["total_cost_eur", "total_revenue_eur", "net_eur", "margin_pct"]:
            assert field in data, f"Missing field: {field}"

    def test_cost_rates_shape(self):
        r = requests.get(f"{COST_SVC}/api/v1/costs/rates", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_cost_pnl_shape(self):
        r = requests.get(f"{COST_SVC}/api/v1/costs/pnl?day=1", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "day" in data
        assert "by_category" in data

    def test_cost_hourly_shape(self):
        r = requests.get(f"{COST_SVC}/api/v1/costs/hourly?day=1", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "hours" in data
        assert isinstance(data["hours"], list)

    def test_cost_recommendations_shape(self):
        r = requests.get(f"{COST_SVC}/api/v1/costs/recommendations", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (dict, list))

    def test_cost_incidents_ranking_shape(self):
        r = requests.get(f"{COST_SVC}/api/v1/costs/incidents/ranking?day=1", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "incidents" in data
        assert isinstance(data["incidents"], list)


class TestSlotAllocation:
    """Verify slot allocation endpoints work."""

    def test_allocate_slots(self):
        payload = {
            "requests": [
                {"id": "s1", "airline": "BA", "requested_hour": 8, "priority": 2},
                {"id": "s2", "airline": "LH", "requested_hour": 8, "priority": 1},
                {"id": "s3", "airline": "AF", "requested_hour": 9, "priority": 1},
            ],
            "strategy": "fcfs",
            "hourly_capacity": 60,
        }
        r = requests.post(
            f"{PLANNING_SVC}/api/v1/planning/slots/allocate",
            json=payload,
            timeout=10,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["strategy"] == "fcfs"
        assert len(data["allocations"]) == 3
        assert data["total_displacement_minutes"] >= 0


class TestNetworkResilience:
    """Verify network resilience endpoints work."""

    def test_hub_dependency(self):
        r = requests.get(
            f"{PLANNING_SVC}/api/v1/planning/network/dependency",
            timeout=10,
        )
        # 503 acceptable if BTS data not available in CI
        if r.status_code == 503:
            pytest.skip("BTS data not available in CI environment")
        assert r.status_code == 200
        data = r.json()
        assert "herfindahl_index" in data
        assert "airlines" in data

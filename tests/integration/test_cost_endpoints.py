"""Integration test — cost-service REST endpoint response shapes.

Promoted from ``scripts/helper_test_cost_endpoints.sh`` to a proper pytest suite.
Tests the same assertions as the shell script but with structured error reporting
and CI integration.

Requires the stack running (at minimum: cost-service, api-gateway, neo4j, kafka):
    docker compose up --build

Run with:
    python -m pytest tests/integration/test_cost_endpoints.py -v --tb=short
"""

import os

import pytest
import requests

COST_SVC = os.getenv("COST_SVC_URL", "http://localhost:8008")
GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:3000")

# Try direct cost-service access first, fall back to gateway
BASE = COST_SVC


def _service_reachable() -> bool:
    try:
        r = requests.get(f"{BASE}/health", timeout=3)
        return r.status_code == 200
    except requests.ConnectionError:
        return False


pytestmark = pytest.mark.skipif(
    not _service_reachable(),
    reason="cost-service not running — skipping cost endpoint tests",
)


@pytest.fixture(scope="module")
def api_base():
    """Return the base URL for cost-service API."""
    return f"{BASE}/api/v1"


# ── Summary endpoint ─────────────────────────────────────────


class TestCostSummary:
    def test_returns_200(self, api_base):
        r = requests.get(f"{api_base}/costs/summary", timeout=5)
        assert r.status_code == 200

    def test_has_required_fields(self, api_base):
        r = requests.get(f"{api_base}/costs/summary", timeout=5)
        data = r.json()
        required = [
            "total_cost_eur", "total_revenue_eur", "net_eur",
            "margin_pct", "by_category", "eu261_exposure_eur",
        ]
        for field in required:
            assert field in data, f"Summary missing field: {field}"

    def test_numeric_types(self, api_base):
        r = requests.get(f"{api_base}/costs/summary", timeout=5)
        data = r.json()
        assert isinstance(data["total_cost_eur"], (int, float))
        assert isinstance(data["total_revenue_eur"], (int, float))
        assert isinstance(data["net_eur"], (int, float))
        assert isinstance(data["margin_pct"], (int, float))


# ── P&L endpoint ────────────────────────────────────────────


class TestCostPnl:
    def test_returns_200(self, api_base):
        r = requests.get(f"{api_base}/costs/pnl?day=1", timeout=5)
        assert r.status_code == 200

    def test_has_required_fields(self, api_base):
        r = requests.get(f"{api_base}/costs/pnl?day=1", timeout=5)
        data = r.json()
        assert "day" in data
        assert "by_category" in data
        assert "cost_records" in data

    def test_by_category_is_dict(self, api_base):
        r = requests.get(f"{api_base}/costs/pnl?day=1", timeout=5)
        data = r.json()
        assert isinstance(data["by_category"], dict)


# ── Hourly endpoint ─────────────────────────────────────────


class TestCostHourly:
    def test_returns_200(self, api_base):
        r = requests.get(f"{api_base}/costs/hourly?day=1", timeout=5)
        assert r.status_code == 200

    def test_wrapped_in_hours_array(self, api_base):
        r = requests.get(f"{api_base}/costs/hourly?day=1", timeout=5)
        data = r.json()
        assert "hours" in data
        assert isinstance(data["hours"], list)

    def test_hour_item_fields(self, api_base):
        r = requests.get(f"{api_base}/costs/hourly?day=1", timeout=5)
        data = r.json()
        if data["hours"]:
            item = data["hours"][0]
            for field in ["cost_eur", "revenue_eur", "net_eur"]:
                assert field in item, f"Hourly item missing field: {field}"


# ── Incidents ranking endpoint ───────────────────────────────


class TestCostIncidents:
    def test_returns_200(self, api_base):
        r = requests.get(f"{api_base}/costs/incidents/ranking?day=1&limit=5", timeout=5)
        assert r.status_code == 200

    def test_wrapped_in_incidents_array(self, api_base):
        r = requests.get(f"{api_base}/costs/incidents/ranking?day=1&limit=5", timeout=5)
        data = r.json()
        assert "incidents" in data
        assert isinstance(data["incidents"], list)

    def test_incident_item_fields(self, api_base):
        r = requests.get(f"{api_base}/costs/incidents/ranking?day=1&limit=5", timeout=5)
        data = r.json()
        if data["incidents"]:
            item = data["incidents"][0]
            assert "incident_id" in item or "id" in item
            assert "total_eur" in item


# ── Recommendations endpoint ─────────────────────────────────


class TestCostRecommendations:
    def test_returns_200(self, api_base):
        r = requests.get(f"{api_base}/costs/recommendations", timeout=5)
        assert r.status_code == 200

    def test_is_dict_or_list(self, api_base):
        r = requests.get(f"{api_base}/costs/recommendations", timeout=5)
        data = r.json()
        assert isinstance(data, (dict, list))


# ── Rates endpoint ───────────────────────────────────────────


class TestCostRates:
    def test_returns_200(self, api_base):
        r = requests.get(f"{api_base}/costs/rates", timeout=5)
        assert r.status_code == 200

    def test_is_non_empty_dict(self, api_base):
        r = requests.get(f"{api_base}/costs/rates", timeout=5)
        data = r.json()
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_rates_patch_rejects_unknown_keys(self, api_base):
        r = requests.patch(
            f"{api_base}/costs/rates",
            json={"unknown_section": {"foo": 1}},
            timeout=5,
        )
        assert r.status_code == 400


# ── Carbon endpoints ─────────────────────────────────────────


class TestCostCarbon:
    def test_carbon_summary(self, api_base):
        r = requests.get(f"{api_base}/costs/carbon/summary", timeout=5)
        assert r.status_code == 200

    def test_carbon_by_source(self, api_base):
        r = requests.get(f"{api_base}/costs/carbon/by-source", timeout=5)
        assert r.status_code == 200

    def test_carbon_timeline(self, api_base):
        r = requests.get(f"{api_base}/costs/carbon/timeline", timeout=5)
        assert r.status_code == 200


# ── Valuation endpoints ──────────────────────────────────────


class TestCostValuation:
    def test_ebitda(self, api_base):
        r = requests.get(f"{api_base}/costs/ebitda?horizon=day", timeout=5)
        assert r.status_code == 200

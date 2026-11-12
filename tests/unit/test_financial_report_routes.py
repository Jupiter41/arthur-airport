"""Financial reports use the shared accessor and distinguish missing storage."""

import importlib
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from tests.conftest import import_service_module


@pytest.fixture
def reports():
    costs = import_service_module("cost", "routers.costs")
    carbon = importlib.import_module("routers.carbon")
    app = FastAPI()
    app.include_router(costs.router)
    app.include_router(carbon.router)
    return costs, TestClient(app)


@pytest.mark.parametrize("path", ["/pnl", "/flight/synthetic", "/incident/synthetic",
    "/incidents/ranking", "/hourly", "/terminal/A", "/ebitda",
    "/carbon/by-source", "/carbon/timeline"])
def test_uninitialized_storage_returns_503_instead_of_empty_report(reports, monkeypatch, path):
    costs, client = reports

    def unavailable():
        raise RuntimeError("Neo4j driver not initialised")

    monkeypatch.setattr(costs.db, "get_driver", unavailable)
    response = client.get(f"/api/v1/costs{path}")
    assert response.status_code == 503, response.text


@pytest.mark.parametrize("path", ["/valuation/sensitivity", "/valuation/thesis"])
def test_valuation_writes_require_initialized_storage(reports, monkeypatch, path):
    costs, client = reports

    def unavailable():
        raise RuntimeError("Neo4j driver not initialised")

    monkeypatch.setattr(costs.db, "get_driver", unavailable)
    response = client.post(f"/api/v1/costs{path}", json={"day": 1})
    assert response.status_code == 503, response.text


def test_pnl_passes_public_driver_to_aggregation(reports, monkeypatch):
    costs, client = reports
    driver = object()
    monkeypatch.setattr(costs.db, "get_driver", lambda: driver)
    query = AsyncMock(return_value={"sim_day": 3, "total_cost_eur": 12,
                                   "total_revenue_eur": 20, "net_eur": 8})
    monkeypatch.setattr(costs, "daily_pnl", query)
    response = client.get("/api/v1/costs/pnl?day=3")
    assert response.status_code == 200 and response.json()["net_eur"] == 8
    query.assert_awaited_once_with(driver, 3)

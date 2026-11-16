"""Observation metadata comes from the owner clock, including missing clocks."""
import asyncio
from datetime import datetime, timezone
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.conftest import import_service_module


@pytest.fixture(autouse=True)
def isolate_owner_models():
    # The shared import helper clears services/db/kafka, but not models. These
    # endpoint tests load incident models; do not leak them into analysis tests.
    saved = {key: value for key, value in sys.modules.items()
             if key == "models" or key.startswith("models.")}
    for key in saved:
        sys.modules.pop(key)
    yield
    for key in list(sys.modules):
        if key == "models" or key.startswith("models."):
            sys.modules.pop(key)
    sys.modules.update(saved)


@pytest.mark.parametrize("clock", [None, datetime(2026, 11, 16, tzinfo=timezone.utc)])
def test_security_rows_keep_owner_time_independent_of_count_cache(monkeypatch, clock):
    security = import_service_module("passenger", "services.security").SecuritySystem()
    monkeypatch.setitem(sys.modules, "kafka.consumer", SimpleNamespace(
        get_sim_time=lambda: clock, get_security=lambda: security,
        get_alerts=lambda: [], get_at_risk_connections=lambda: [],
        get_forecast_context=lambda: {},
        get_passenger_source_info=lambda: {"source": "simulation"},
    ))
    route = importlib.import_module("routers.passengers")
    projection = importlib.import_module("services.flow_projection")
    monkeypatch.setattr(projection, "read", AsyncMock(return_value=(
        {"airside": 12}, {"counts_observed_sim_time": "2026-11-15T00:00:00Z"},
    )))
    result = asyncio.run(route.flow_summary())
    assert result["counts_observed_sim_time"] == "2026-11-15T00:00:00Z"
    assert all(row["observed_at"] == (clock.isoformat() if clock else None)
               for row in result["security"].values())


@pytest.mark.parametrize("clock", [None, datetime(2026, 11, 16, tzinfo=timezone.utc)])
def test_zone_metadata_does_not_mutate_the_conveyor(monkeypatch, clock):
    import_service_module("baggage", "services.conveyor")
    zones = [{"zone_id": "induction-A", "items": 7}]
    monkeypatch.setitem(sys.modules, "kafka.consumer", SimpleNamespace(
        get_sim_time=lambda: clock,
        get_conveyor=lambda: SimpleNamespace(get_zone_summary=lambda: zones),
    ))
    route = importlib.import_module("routers.baggage")
    result = asyncio.run(route.flow_map())
    assert result["zones"][0]["observed_at"] == (clock.isoformat() if clock else None)
    assert zones == [{"zone_id": "induction-A", "items": 7}]


@pytest.mark.parametrize("clock", [None, datetime(2026, 11, 16, tzinfo=timezone.utc)])
def test_incident_observation_is_not_its_start_time(monkeypatch, clock):
    import_service_module("incident", "services.protocols")
    monkeypatch.setitem(sys.modules, "kafka.consumer", SimpleNamespace(
        get_sim_time=lambda: clock, get_active_alerts=lambda: [],
    ))
    route = importlib.import_module("routers.incidents")
    monkeypatch.setattr(route, "get_incidents", AsyncMock(return_value=[{
        "id": "synthetic-incident", "started_at": "2026-11-15T10:00:00Z",
    }]))
    monkeypatch.setattr(route, "count_incidents", AsyncMock(return_value=1))
    result = asyncio.run(route.list_incidents())
    assert result.incidents[0].observed_at == (clock.isoformat() if clock else None)
    assert result.incidents[0].started_at == "2026-11-15T10:00:00Z"

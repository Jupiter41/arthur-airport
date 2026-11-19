"""Explicit owner lane control uses the atomic command path and simulation time."""

import asyncio
from datetime import datetime, timezone
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.conftest import import_service_module


@pytest.fixture
def owner(monkeypatch):
    import_service_module("passenger", "services.security")
    security = importlib.import_module("services.security").SecuritySystem()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setitem(sys.modules, "kafka.consumer", SimpleNamespace(
        get_sim_time=lambda: now, get_security=lambda: security, get_alerts=lambda: [],
        get_at_risk_connections=lambda: [], get_forecast_context=lambda: {}))
    route = importlib.import_module("routers.passengers")
    db = importlib.import_module("db.neo4j")
    atomic = AsyncMock(return_value=("CommandExecuted", {"command_id": "lesson", "command_type": "OpenSecurityLane"}, True))
    monkeypatch.setattr(db, "security_lane_command_atomic", atomic)
    return route, security, atomic, now


def test_owner_lane_control_commits_once_and_replay_does_not_apply_new_parameters(owner):
    route, security, atomic, now = owner
    result = asyncio.run(route.set_security_lanes("A", route.SecurityLaneRequest(lanes_open=2, command_id="lesson")))
    assert result["event_type"] == "CommandExecuted" and security.get("A").lanes_open == 2
    atomic.assert_awaited_with("lesson", "OpenSecurityLane", "A", 2, now)
    atomic.return_value = ("CommandExecuted", result["receipt"], False)
    asyncio.run(route.set_security_lanes("A", route.SecurityLaneRequest(lanes_open=3, command_id="lesson")))
    assert security.get("A").lanes_open == 2


def test_owner_lane_control_requires_clock_and_validates_request(owner, monkeypatch):
    route, _, atomic, _ = owner
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(route.router)
    with TestClient(app) as client:
        for value in (True, 0, 21, "2"):
            assert client.post("/api/v1/flow/security/A/lanes", json={"lanes_open": value}).status_code == 422
        assert client.post("/api/v1/flow/security/D/lanes", json={"lanes_open": 2}).status_code == 422
        monkeypatch.setattr(route, "get_sim_time", lambda: None)
        assert client.post("/api/v1/flow/security/A/lanes", json={"lanes_open": 2}).status_code == 503
    atomic.assert_not_awaited()


def test_configuration_reads_durable_overrides_and_owner_defaults(owner, monkeypatch):
    route, _, _, now = owner
    db = importlib.import_module("db.neo4j")
    monkeypatch.setattr(db, "load_security_lanes", AsyncMock(return_value={"A": 2}))
    monkeypatch.setattr(importlib.import_module("services.security"), "default_lanes",
                        lambda terminal: {"A": 8, "B": 12, "C": 8}[terminal])
    response = asyncio.run(route.flow_configuration())
    assert response["sim_time"] == now.isoformat()
    assert response["values"] == {"lanes_a": 2, "lanes_b": 12, "lanes_c": 8, "mct_minutes": 45}
    monkeypatch.setattr(db, "load_security_lanes", AsyncMock(side_effect=RuntimeError("DB offline")))
    with pytest.raises(RuntimeError, match="DB offline"):
        asyncio.run(route.flow_configuration())

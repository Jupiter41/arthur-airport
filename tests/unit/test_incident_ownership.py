"""Restrictions belong to incident identities and survive independent changes."""

import asyncio
import importlib
import sys
from datetime import datetime
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import import_service_module

NOW = datetime(2026, 1, 1, 10)


def context(service, monkeypatch):
    import_service_module(service, "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    if service == "passenger":
        training = ModuleType("ml.training")
        for name in ("add_training_row", "maybe_flush", "maybe_retrain"):
            setattr(training, name, MagicMock())
        monkeypatch.setitem(sys.modules, "ml.training", training)
    consumer = importlib.import_module("kafka.consumer")
    return consumer, importlib.import_module("db.neo4j")


@pytest.mark.parametrize("location,attribute,key", [
    ("runway-09L", "incident_affected_runways", "09L"),
    ("gate-B01", "incident_affected_gates", "B01"),
])
def test_flight_child_resolution_and_containment_keep_parent_restriction(location, attribute, key, monkeypatch):
    consumer, _ = context("flight", monkeypatch)
    parent = {"incident_id": "parent", "type": "runway_incursion", "location": location}
    child = {**parent, "incident_id": "child", "type": "flight_delayed"}
    for fact in (parent, child):
        asyncio.run(consumer._on_incident_created(fact, NOW))
    asyncio.run(consumer._on_incident_status_changed({**child, "new_status": "resolved"}, NOW))
    assert key in getattr(consumer._state, attribute)
    asyncio.run(consumer._on_incident_status_changed({**parent, "new_status": "contained"}, NOW))
    assert key in getattr(consumer._state, attribute)
    asyncio.run(consumer._on_incident_status_changed({**parent, "new_status": "resolved"}, NOW))
    assert key not in getattr(consumer._state, attribute)


def test_weather_improvement_and_incident_resolution_preserve_each_others_restrictions(monkeypatch):
    consumer, _ = context("flight", monkeypatch)
    incident = {"incident_id": "parent", "type": "runway_incursion", "location": "runway-09L"}
    asyncio.run(consumer._on_incident_created(incident, NOW))
    asyncio.run(consumer._on_weather_changed({"new_category": "CAVOK", "runway_impact": "none"}, NOW))
    assert consumer._state.incident_affected_runways == {"09L"}
    asyncio.run(consumer._on_weather_changed({"new_category": "LIFR", "runway_impact": "closed"}, NOW))
    asyncio.run(consumer._on_incident_status_changed({**incident, "new_status": "resolved"}, NOW))
    assert consumer._state.incident_affected_runways == {"09L", "09R", "27L", "27R"}
    asyncio.run(consumer._on_weather_changed({"new_category": "CAVOK", "runway_impact": "none"}, NOW))
    assert consumer._state.incident_affected_runways == set()


def test_security_child_resolution_and_overlapping_breaches_do_not_unfreeze_early(monkeypatch):
    consumer, _ = context("passenger", monkeypatch)
    parent = {"incident_id": "parent", "type": "security_breach", "location": "terminal-B"}
    other = {**parent, "incident_id": "other"}
    child = {**parent, "incident_id": "child", "type": "boarding_delayed"}
    for fact in (parent, other):
        asyncio.run(consumer._on_incident_created(fact, NOW))
    for fact in (child, parent):
        asyncio.run(consumer._on_incident_status_changed({**fact, "new_status": "resolved"}, NOW))
        assert consumer._state.security.get("B").frozen is True
    asyncio.run(consumer._on_incident_status_changed({**other, "new_status": "resolved"}, NOW))
    assert consumer._state.security.get("B").frozen is False


def test_security_restart_restores_breach_and_lane_ownership(monkeypatch):
    consumer, db = context("passenger", monkeypatch)
    monkeypatch.setattr(consumer, "get_passengers_by_status", AsyncMock(return_value=[]))
    monkeypatch.setattr(db, "load_security_lanes", AsyncMock(return_value={"B": 6}))
    monkeypatch.setattr(db, "load_security_breaches", AsyncMock(return_value={"breach": "terminal-B"}))
    asyncio.run(consumer.rebuild_security_from_neo4j())
    assert consumer._state.security_breaches == {"breach": "B"}
    assert consumer._state.security.get("B").frozen is True
    assert consumer._state.security.get("B").lanes_open == 6


def test_flight_restart_restores_incident_identities(monkeypatch):
    consumer, db = context("flight", monkeypatch)
    monkeypatch.setattr(db, "get_manual_holds", AsyncMock(return_value={}))
    monkeypatch.setattr(consumer, "get_active_incident_impacts", AsyncMock(return_value={
        "parent": "runway-09L", "child": "runway-09L", "other": "gate-B01",
    }))
    monkeypatch.setattr(consumer._state, "_load_spatial_positions", AsyncMock())
    asyncio.run(consumer._state.rebuild_from_neo4j())
    assert consumer._state.incident_affected_runways == {"09L"}
    assert consumer._state.incident_affected_gates == {"B01"}
    asyncio.run(consumer._on_incident_status_changed({
        "incident_id": "child", "location": "runway-09L", "new_status": "resolved",
    }, NOW))
    assert consumer._state.incident_affected_runways == {"09L"}

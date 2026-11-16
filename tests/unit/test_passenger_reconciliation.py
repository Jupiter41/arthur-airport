"""Recovery decisions retain owner evidence and cannot invent future journeys."""
import asyncio
import importlib
import sys
from datetime import datetime
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import import_service_module

NOW = datetime(2024, 7, 6, 9)


@pytest.mark.parametrize("direction,flight,status,expected", [
    ("departure", "arrived", "at_gate", ("departed_airport", "flight-finished")),
    ("departure", "completed", "airside", ("departed_airport", "flight-finished")),
    ("departure", "airborne", "boarded", ("departed_airport", "departed")),
    ("departure", "boarding", "at_gate", None),
    ("departure", "arrived", "departed_airport", None),
    ("arrival", "arrived", "airborne", ("deplaning", "arrivals-hall")),
    ("arrival", "at_gate", "booked", ("deplaning", "arrivals-hall")),
    ("arrival", "diverted", "airborne", ("departed_airport", "diverted")),
    ("arrival", "arrived", "deplaning", None),
])
def test_recovery_disposition(direction, flight, status, expected):
    rules = import_service_module("passenger", "services.reconciliation")
    assert rules.reconciliation_transition({"direction": direction, "flight_status": flight,
        "status": status, "actual_time": "2024-07-06T08:00:00"}, NOW) == expected


def test_future_and_missing_flight_observations_are_not_reconciled():
    rules = import_service_module("passenger", "services.reconciliation")
    pax = {"direction": "departure", "flight_status": "arrived", "status": "at_gate"}
    for at in (None, "invalid", "2024-07-06T10:00:00Z"):
        assert rules.reconciliation_transition({**pax, "actual_time": at}, NOW) is None


def test_recovery_stages_facts_without_resurrecting_security_membership(monkeypatch):
    import_service_module("passenger", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    consumer = importlib.import_module("kafka.consumer")
    db = importlib.import_module("db.neo4j")
    state = consumer.PassengerConsumerState()
    state.security.get("A").enqueue("stranded")
    state.security_enqueued.add("stranded")
    monkeypatch.setattr(consumer, "_state", state)
    monkeypatch.setattr(db, "get_reconciliation_candidates", AsyncMock(return_value=[{
        "id": "stranded", "name": "Synthetic passenger", "status": "security_queue",
        "location_zone": "security-A", "direction": "departure", "flight_status": "arrived",
        "flight_id": "finished", "actual_time": "2024-07-06T08:00:00",
    }]))
    plan = asyncio.run(consumer._reconcile_flight_passengers(NOW))
    assert plan.groups == [{"ids": ["stranded"], "status": "departed_airport", "zone": "flight-finished"}]
    assert state.security.get("A").queue_depth == 0
    assert "stranded" not in state.security_enqueued
    fact = plan.facts[0]["document"]
    assert fact["payload"]["previous_status"] == "security_queue"
    assert fact["payload"]["reconciliation_reason"] == "persisted_flight_state"
    assert fact["sim_time"].startswith("2024-07-06T09:00:00")
    assert fact["payload"]["new_status"] != "boarded"


def test_physical_occupancy_excludes_future_and_inflight_records():
    rules = import_service_module("passenger", "services.reconciliation")
    assert {"customs", "deplaning", "disrupted"} <= set(rules.PHYSICAL_STATUSES)
    assert not {"booked", "airborne", "boarded", "departed_airport"} & set(rules.PHYSICAL_STATUSES)

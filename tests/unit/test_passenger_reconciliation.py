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


def test_recovery_batches_transitions_without_resurrecting_security_membership(monkeypatch):
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
    # RC3: recovery is published once, inside the tick batch, with its reason.
    assert plan.groups == [{"ids": ["stranded"], "status": "departed_airport",
                            "zone": "flight-finished",
                            "reconciliation_reason": "persisted_flight_state"}]
    assert plan.facts == []
    assert state.security.get("A").queue_depth == 0
    assert "stranded" not in state.security_enqueued
    batch = importlib.import_module("_common.outbox").transition_batch_facts(
        "PassengerStatusBatchChanged", NOW, "passenger-service",
        {"status_groups": plan.groups}, grouped_ids={"status_groups": "ids"},
    )[0]["document"]
    group = batch["payload"]["status_groups"][0]
    assert group["reconciliation_reason"] == "persisted_flight_state"
    assert group["status"] != "boarded"
    assert batch["sim_time"].startswith("2024-07-06T09:00:00")


def test_physical_occupancy_excludes_future_and_inflight_records():
    rules = import_service_module("passenger", "services.reconciliation")
    assert {"customs", "deplaning", "disrupted"} <= set(rules.PHYSICAL_STATUSES)
    assert not {"booked", "airborne", "boarded", "departed_airport"} & set(rules.PHYSICAL_STATUSES)


def test_rc3_tick_transitions_publish_only_the_batch(monkeypatch):
    """RC3: no sampled per-passenger fact rides alongside the tick batch."""
    import_service_module("passenger", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    consumer = importlib.import_module("kafka.consumer")
    monkeypatch.setattr(consumer, "_state", consumer.PassengerConsumerState())

    async def by_status(status, **kwargs):
        if status != "deplaning":
            return []
        return [{"id": f"p{i}", "name": "Synthetic", "flight_id": "F1",
                 "flight_type": "domestic", "deplaning_at": "2024-07-06T07:00:00",
                 "location_zone": "arrivals-hall"} for i in range(50)]

    monkeypatch.setattr(consumer, "get_passengers_by_status", by_status)
    plan = asyncio.run(consumer._advance_arrivals(NOW))
    assert plan.groups and len(plan.groups[0]["ids"]) == 50
    assert plan.facts == []
    assert not hasattr(consumer.TickContribution, "add_status_fact")

"""Batched owner writes retain per-bag facts and durable-before-cache ordering."""

import asyncio
import importlib
import sys
from datetime import datetime
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import import_service_module

NOW = datetime(2026, 1, 1, 10)


def context(monkeypatch):
    import_service_module("baggage", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    consumer = importlib.import_module("kafka.consumer")
    monkeypatch.setattr(consumer, "get_active_system_failures", AsyncMock(return_value={}))
    return consumer


def test_induction_persists_batch_before_queues_and_per_bag_events(monkeypatch):
    consumer = context(monkeypatch)
    consumer._state = consumer.BaggageConsumerState()
    bags = [{"id": "b1", "tag": "fake-1", "terminal_id": "T-B"},
            {"id": "b2", "tag": "fake-2", "flight_status": "departed"}]
    monkeypatch.setattr(consumer, "get_dropped_off_baggage_for_departures", AsyncMock(return_value=bags))
    emitted = []

    async def save(changes, clock):
        assert clock == NOW
        assert not consumer._state.inducted_bag_ids
        assert consumer._state.conveyor.get_zone("induction-B").items == 0
        assert not emitted
        assert changes == [{"id": "b1", "status": "inducted", "zone": "induction-B"},
                           {"id": "b2", "status": "in_hold", "zone": "aircraft-hold"}]

    async def emit(**payload):
        emitted.append(payload)
        return payload

    save_mock = AsyncMock(side_effect=save)
    monkeypatch.setattr(consumer, "update_baggage_statuses", save_mock)
    monkeypatch.setattr(consumer, "_emit_status_changed_with_metric", emit)
    asyncio.run(consumer._induct_new_bags(NOW))
    assert save_mock.await_count == 1
    assert consumer._state.inducted_bag_ids == {"b1", "b2"}
    assert consumer._state.conveyor.get_zone("induction-B").items == 1
    assert [(p["baggage_id"], p["new_status"]) for p in emitted] == [
        ("b1", "inducted"), ("b2", "in_hold")]


def test_failed_induction_write_leaves_bags_eligible_for_retry(monkeypatch):
    consumer = context(monkeypatch)
    consumer._state = consumer.BaggageConsumerState()
    monkeypatch.setattr(consumer, "get_dropped_off_baggage_for_departures", AsyncMock(
        return_value=[{"id": "b1", "tag": "fake-1", "terminal_id": "T-B"}]))
    monkeypatch.setattr(consumer, "update_baggage_statuses", AsyncMock(side_effect=RuntimeError("db offline")))
    emit = AsyncMock()
    monkeypatch.setattr(consumer, "_emit_status_changed_with_metric", emit)
    with pytest.raises(RuntimeError, match="db offline"):
        asyncio.run(consumer._induct_new_bags(NOW))
    assert not consumer._state.inducted_bag_ids
    assert consumer._state.conveyor.get_zone("induction-B").items == 0
    emit.assert_not_awaited()


def test_departure_removes_fast_tracked_bags_from_conveyor(monkeypatch):
    consumer = context(monkeypatch)
    database = sys.modules["db.neo4j"]
    consumer._state = consumer.BaggageConsumerState()
    bag = consumer.BagInZone(baggage_id="b1", tag="fake-1", flight_id="f1",
                            is_dg=False, dg_class=None, passenger_id=None,
                            terminal="B", entered_at=NOW.isoformat())
    consumer._state.conveyor.induct_bag(bag, NOW.isoformat())
    monkeypatch.setattr(database, "get_flight_baggage", AsyncMock(return_value=[
        {"id": "b1", "tag": "fake-1", "status": "inducted"}]))
    save = AsyncMock()
    emit = AsyncMock()
    monkeypatch.setattr(consumer, "update_baggage_statuses", save)
    monkeypatch.setattr(consumer, "_emit_status_changed_with_metric", emit)
    asyncio.run(consumer._on_flight_status_changed({"flight_id": "f1", "new_status": "departed"}, NOW))
    assert consumer._state.conveyor.get_zone("induction-B").items == 0
    save.assert_awaited_once_with([{"id": "b1", "status": "in_hold", "zone": "aircraft-hold"}], NOW)
    assert emit.await_args.kwargs["previous_status"] == "inducted"


def test_recovery_preserves_screening_metadata_arrivals_and_repeated_rebuild(monkeypatch):
    consumer = context(monkeypatch)
    state = consumer.BaggageConsumerState()
    bags = [
        {"id": "b1", "tag": "fake-dg", "status": "screening", "current_zone": "screening-unit-3",
         "is_dg": True, "dg_class": "3", "passenger_id": "p1", "terminal_id": "T-B",
         "gate_id": "C01", "last_scan_at": NOW.isoformat(), "flight_id": "f1"},
        {"id": "b2", "tag": "fake-arrived", "status": "arrived", "current_zone": "arrival-belt-4"},
    ]
    monkeypatch.setattr(consumer, "get_baggage_in_pipeline", AsyncMock(return_value=bags))
    for _ in range(2):
        asyncio.run(state.rebuild_from_neo4j())
    screening = state.conveyor.get_zone("screening-unit-3")
    assert screening.items == 1
    bag = screening.queue[0]
    assert (bag.tag, bag.is_dg, bag.dg_class, bag.passenger_id) == ("fake-dg", True, "3", "p1")
    assert (bag.terminal, bag.gate_terminal) == ("B", "C")
    assert state.conveyor.get_zone("arrival-belt-4").items == 1


def test_actual_child_resolution_fact_cannot_release_parent_failure(monkeypatch):
    producer = import_service_module("incident", "kafka.producer")
    facts = []
    monkeypatch.setattr(producer, "_produce_event", lambda topic, kind, clock, payload, **kw: facts.append(payload))
    parent = {"id": "failure-1", "type": "system_failure", "severity": "high",
              "status": "active", "location": "power-A"}
    child = {**parent, "id": "cascade-1", "type": "baggage_throughput_reduction"}
    producer.emit_incident_created(parent, NOW)
    producer.emit_incident_created(child, NOW)
    producer.emit_incident_status_changed(child, "resolved", NOW)
    consumer = context(monkeypatch)
    consumer._state = consumer.BaggageConsumerState()
    asyncio.run(consumer._on_incident_created(facts[0], NOW))
    asyncio.run(consumer._on_incident_created(facts[1], NOW))
    asyncio.run(consumer._on_incident_status_changed(facts[2], NOW))
    assert consumer._state.active_failures == {"failure-1": "power-A"}
    assert all(consumer._state.conveyor.get_zone(zone).status == "offline"
               for zone in consumer.FAILURE_IMPACT["power-A"])


def test_overlapping_failure_remains_offline_until_both_owners_resolve(monkeypatch):
    consumer = context(monkeypatch)
    consumer._state = consumer.BaggageConsumerState()
    failures = [
        {"incident_id": "power", "type": "system_failure", "location": "power-A"},
        {"incident_id": "scanner", "type": "system_failure", "location": "screening-unit-1"},
    ]
    for fact in failures:
        asyncio.run(consumer._on_incident_created(fact, NOW))
    asyncio.run(consumer._on_incident_status_changed({**failures[0], "new_status": "resolved"}, NOW))
    assert consumer._state.conveyor.get_zone("induction-A").status == "normal"
    assert consumer._state.conveyor.get_zone("screening-unit-1").status == "offline"
    asyncio.run(consumer._on_incident_status_changed({**failures[1], "new_status": "resolved"}, NOW))
    assert consumer._state.conveyor.get_zone("screening-unit-1").status == "normal"


def test_recovery_retains_active_failure_ownership_until_its_resolution(monkeypatch):
    consumer = context(monkeypatch)
    consumer._state = consumer.BaggageConsumerState()
    monkeypatch.setattr(consumer, "get_baggage_in_pipeline", AsyncMock(return_value=[]))
    monkeypatch.setattr(consumer, "get_active_system_failures", AsyncMock(return_value={"power": "power-B"}))
    asyncio.run(consumer._state.rebuild_from_neo4j())
    assert consumer._state.conveyor.get_zone("induction-B").status == "offline"
    asyncio.run(consumer._on_incident_status_changed({
        "incident_id": "power", "type": "system_failure", "location": "power-B", "new_status": "resolved",
    }, NOW))
    assert consumer._state.conveyor.get_zone("induction-B").status == "normal"

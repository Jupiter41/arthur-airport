"""Batched owner writes retain per-bag facts and durable-before-cache ordering."""

import asyncio
import importlib
import json
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


def test_induction_plans_batch_then_commits_atomically_with_per_bag_facts(monkeypatch):
    """G1-a: induction is planned (no write/emit), then committed in the tick tx.

    The plan carries the batch + per-bag facts; the ``inducted_bag_ids`` cache is
    updated only *after* ``_apply_tick`` commits (durable-before-cache ordering).
    """
    from tests.unit.test_baggage_outbox import Driver  # container-free fake driver

    consumer = context(monkeypatch)
    consumer._state = consumer.BaggageConsumerState()
    bags = [{"id": "b1", "tag": "fake-1", "terminal_id": "T-B"},
            {"id": "b2", "tag": "fake-2", "flight_status": "departed"}]
    monkeypatch.setattr(consumer, "get_dropped_off_baggage_for_departures", AsyncMock(return_value=bags))
    driver = Driver()
    monkeypatch.setattr(consumer, "get_driver", lambda: driver)

    plan = consumer._TickPlan()
    asyncio.run(consumer._plan_induction(plan, NOW))

    # Compute phase: statuses + per-bag facts planned; the durable cache is NOT
    # yet mutated, while the in-memory conveyor (rebuildable) is populated.
    assert plan.status_changes == [
        {"id": "b1", "status": "inducted", "zone": "induction-B"},
        {"id": "b2", "status": "in_hold", "zone": "aircraft-hold"}]
    assert plan.inducted_ids == ["b1", "b2"]
    assert consumer._state.inducted_bag_ids == set()
    assert consumer._state.conveyor.get_zone("induction-B").items == 1
    assert [(f["document"]["payload"]["baggage_id"], f["document"]["payload"]["new_status"])
            for f in plan.facts] == [("b1", "inducted"), ("b2", "in_hold")]
    for f in plan.facts:
        assert f["document"]["payload"]["previous_status"] == "dropped_off"

    # Apply phase: one transaction commits every transition + fact + checkpoint.
    assert asyncio.run(consumer._apply_tick(plan, NOW)) is True
    assert driver.db["baggage"]["b1"]["status"] == "inducted"
    assert driver.db["baggage"]["b2"]["status"] == "in_hold"
    assert len(driver.db["outbox"]) == 3  # two per-bag facts + unsampled batch
    batch = next(json.loads(r["document"]) for r in driver.db["outbox"].values()
                 if json.loads(r["document"])["event_type"] == "BaggageStatusBatchChanged")
    assert len(batch["payload"]["status_changes"]) == 2
    assert driver.db["last_tick"] == NOW.isoformat()


def test_failed_tick_write_rolls_back_and_leaves_bags_eligible_for_retry(monkeypatch):
    """A failed tick commit mutates nothing and leaves no cache/checkpoint drift."""
    from tests.unit.test_baggage_outbox import Driver

    consumer = context(monkeypatch)
    consumer._state = consumer.BaggageConsumerState()
    monkeypatch.setattr(consumer, "get_dropped_off_baggage_for_departures", AsyncMock(
        return_value=[{"id": "b1", "tag": "fake-1", "terminal_id": "T-B"}]))
    driver = Driver()
    driver.fail_on = "UNWIND $changes AS change"  # the tick's domain write fails
    from _common.transaction_scope import current, TransactionDriver
    def scoped_driver():
        return TransactionDriver(current.get()) if current.get() else driver
    monkeypatch.setattr(consumer, "get_driver", scoped_driver)
    monkeypatch.setattr(sys.modules["db.neo4j"], "get_driver", scoped_driver)
    monkeypatch.setattr(consumer, "_prepare_tick", AsyncMock())

    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(consumer._on_clock_tick({}, NOW))

    assert consumer._state.inducted_bag_ids == set()        # cache not advanced
    # Conveyor fully restored to the pre-tick snapshot (b1's induct+advance undone).
    assert sum(z.items for z in consumer._state.conveyor.get_all_zones().values()) == 0
    assert consumer._state.last_tick_sim_time is None       # checkpoint not advanced
    assert driver.db["baggage"] == {}                       # nothing committed
    assert driver.db["outbox"] == {}
    assert driver.db["last_tick"] is None


def test_departure_removes_fast_tracked_bags_from_conveyor(monkeypatch):
    """G1: departure now writes status + inbox + outbox in one tx, then clears
    the (Neo4j-derived) conveyor cache and stages facts rather than emitting."""
    from tests.unit.test_baggage_outbox import Driver  # container-free fake driver

    consumer = context(monkeypatch)
    database = sys.modules["db.neo4j"]
    consumer._state = consumer.BaggageConsumerState()
    bag = consumer.BagInZone(baggage_id="b1", tag="fake-1", flight_id="f1",
                            is_dg=False, dg_class=None, passenger_id=None,
                            terminal="B", entered_at=NOW.isoformat())
    consumer._state.conveyor.induct_bag(bag, NOW.isoformat())
    driver = Driver()
    monkeypatch.setattr(consumer, "get_driver", lambda: driver)
    monkeypatch.setattr(database, "get_flight_baggage", AsyncMock(return_value=[
        {"id": "b1", "tag": "fake-1", "status": "inducted"}]))
    asyncio.run(consumer._on_flight_status_changed(
        {"flight_id": "f1", "new_status": "departed"}, NOW, "evt-dep"))
    # Conveyor cache cleared only after the commit succeeded.
    assert consumer._state.conveyor.get_zone("induction-B").items == 0
    # Domain write + durable inbox + one staged fact all committed atomically.
    assert driver.db["baggage"]["b1"]["status"] == "in_hold"
    assert driver.db["inbox"] == {"evt-dep"}
    fact = json.loads(next(iter(driver.db["outbox"].values()))["document"])
    assert fact["payload"]["previous_status"] == "inducted"
    assert fact["payload"]["new_status"] == "in_hold"


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

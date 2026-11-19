"""Missed flight triggers converge from consumed projections, including late bags."""
import asyncio
import importlib
import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from tests.unit.test_baggage_outbox import Driver, Result, Tx, context

NOW = datetime(2024, 7, 8, 12)


def setup(monkeypatch, *, status="arrived", direction="arrival"):
    driver = Driver()
    driver.db["baggage"] = {"b1": {"id": "b1", "tag": "fake1", "flight_id": "f1",
                                    "passenger_id": "p1", "status": "in_hold", "scans": 0}}
    consumer = context(monkeypatch, driver, [])
    original = Tx.run

    async def run(tx, query, **params):
        if "MATCH (b:Baggage {status: 'in_hold'})" in query:
            return Result([dict(b) for b in tx.db["baggage"].values()
                           if b["flight_id"] == params["fid"] and b["status"] == "in_hold"])
        if "RETURN DISTINCT f.id AS id" in query:
            # A Flight property is deliberately unavailable to this query.
            assert "f.status" not in query and "f.direction" not in query
            return Result([{"id": fid} for fid in sorted({b["flight_id"] for b in tx.db["baggage"].values()
                                                          if b["status"] in params["statuses"]})])
        return await original(tx, query, **params)

    async def bags(fid, statuses):
        return [dict(b) for b in driver.db["baggage"].values()
                if b["flight_id"] == fid and b["status"] in statuses]

    monkeypatch.setattr(Tx, "run", run)
    monkeypatch.setattr(sys.modules["db.neo4j"], "get_flight_baggage", bags)
    monkeypatch.setattr(consumer, "_reconcile_cadence", {"boot_ticks": 0, "last": None})
    view = importlib.import_module("_common.flight_view").VIEW
    monkeypatch.setattr(view, "flights", {})
    view.load([{"id": "f1", "status": status, "direction": direction, "gate_id": "B07",
                "scheduled_time": "2024-06-29T12:00:00", "actual_time": "2024-06-29T12:08:00"}], [], None)
    return consumer, driver, view


@pytest.mark.parametrize("status", ["at_gate", "arrived", "completed"])
def test_startup_recovers_old_arrival_holds_once(monkeypatch, status):
    consumer, driver, _ = setup(monkeypatch, status=status)
    asyncio.run(consumer._reconcile_flight_baggage(NOW))
    assert driver.db["baggage"]["b1"]["status"] == "arrived"
    assert driver.db["baggage"]["b1"]["scans"] == 1
    facts = [json.loads(row["document"]) for row in driver.db["outbox"].values()]
    assert len(facts) == 1
    assert facts[0]["payload"]["passenger_id"] == "p1"
    assert facts[0]["sim_time"] == NOW.isoformat()
    snapshot = deepcopy(driver.db)
    asyncio.run(consumer._reconcile_flight_baggage(NOW, force=True))
    assert driver.db == snapshot


def test_hourly_sweep_recovers_bags_seeded_after_the_flight_fact(monkeypatch):
    consumer, driver, _ = setup(monkeypatch)
    asyncio.run(consumer._reconcile_flight_baggage(NOW))
    driver.db["baggage"]["late"] = {"id": "late", "tag": "fake-late", "flight_id": "f1",
                                      "passenger_id": "p2", "status": "in_hold", "scans": 0}
    consumer._reconcile_cadence["boot_ticks"] = consumer.RECONCILE_BOOT_TICKS
    asyncio.run(consumer._reconcile_flight_baggage(NOW + timedelta(minutes=59)))
    assert driver.db["baggage"]["late"]["status"] == "in_hold"
    asyncio.run(consumer._reconcile_flight_baggage(NOW + timedelta(minutes=60)))
    assert driver.db["baggage"]["late"]["status"] == "arrived"
    assert driver.db["baggage"]["b1"]["scans"] == 1


def test_sweep_never_reads_a_live_flight_state_or_runs_before_its_consumed_fact(monkeypatch):
    consumer, driver, view = setup(monkeypatch, status="scheduled")
    asyncio.run(consumer._reconcile_flight_baggage(NOW))
    assert driver.db["baggage"]["b1"]["status"] == "in_hold"
    view.apply("FlightStatusChanged", {"flight_id": "f1", "new_status": "at_gate"},
               NOW + timedelta(minutes=1))
    asyncio.run(consumer._reconcile_flight_baggage(NOW, force=True))
    assert driver.db["baggage"]["b1"]["status"] == "in_hold"
    asyncio.run(consumer._reconcile_flight_baggage(NOW + timedelta(minutes=1), force=True))
    assert driver.db["baggage"]["b1"]["status"] == "arrived"


def test_failed_recovery_rolls_back_and_does_not_consume_the_sweep(monkeypatch):
    consumer, driver, _ = setup(monkeypatch)
    before = deepcopy(driver.db)
    driver.fail_on = "CREATE (e:BaggageOutbox"
    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(consumer._reconcile_flight_baggage(NOW))
    assert driver.db == before
    assert consumer._reconcile_cadence == {"boot_ticks": 0, "last": None}
    asyncio.run(consumer._reconcile_flight_baggage(NOW))
    assert driver.db["baggage"]["b1"]["status"] == "arrived"


def test_bulk_recovery_keeps_arrival_facts_for_passenger_claim(monkeypatch):
    consumer, driver, _ = setup(monkeypatch)
    monkeypatch.setattr(consumer, "is_bulk_mode", lambda: True)
    asyncio.run(consumer._reconcile_flight_baggage(NOW))
    assert len(driver.db["outbox"]) == 1


@pytest.mark.parametrize("event_type", ["FlightDiverted", "FlightStatusChanged", "recovery"])
def test_diversion_disposes_held_arrival_bags_once_in_bulk(monkeypatch, event_type):
    consumer, driver, _ = setup(monkeypatch, status="diverted")
    monkeypatch.setattr(consumer, "is_bulk_mode", lambda: True)
    driver.db["baggage"]["unloaded"] = {"id": "unloaded", "flight_id": "f1", "status": "arrived"}
    if event_type == "recovery":
        asyncio.run(consumer._reconcile_flight_baggage(NOW))
    else:
        asyncio.run(consumer._dispatch({"event_id": "diversion", "event_type": event_type,
                    "sim_time": NOW.isoformat(),
                    "payload": {"flight_id": "f1", "new_status": "diverted"}}))
    assert driver.db["baggage"]["b1"]["status"] == "diverted"
    assert driver.db["baggage"]["b1"]["zone"] == "diverted-aircraft"
    assert driver.db["baggage"]["unloaded"]["status"] == "arrived"
    [fact] = [json.loads(row["document"]) for row in driver.db["outbox"].values()]
    assert fact["payload"]["passenger_id"] == "p1"
    assert fact["payload"]["new_status"] == "diverted"
    assert fact["sim_time"] == NOW.isoformat()
    asyncio.run(consumer._apply_arrival_diverted("f1", NOW + timedelta(hours=1), "other-diversion"))
    assert driver.db["baggage"]["b1"]["scans"] == 1
    assert len(driver.db["outbox"]) == 1


def test_diversion_failure_rolls_back_then_restart_recovers_late_bags(monkeypatch):
    consumer, driver, _ = setup(monkeypatch, status="diverted")
    before = deepcopy(driver.db)
    driver.fail_on = "CREATE (e:BaggageOutbox"
    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(consumer._reconcile_flight_baggage(NOW))
    assert driver.db == before
    asyncio.run(consumer._reconcile_flight_baggage(NOW))
    driver.db["baggage"]["late"] = {"id": "late", "tag": "late", "flight_id": "f1",
                                      "status": "in_hold", "scans": 0}
    consumer._state = consumer.BaggageConsumerState()
    consumer._reconcile_cadence = {"boot_ticks": 0, "last": None}
    asyncio.run(consumer._reconcile_flight_baggage(NOW + timedelta(minutes=1)))
    assert driver.db["baggage"]["late"]["status"] == "diverted"
    assert driver.db["baggage"]["b1"]["scans"] == 1


def test_diversion_ignores_departures_and_future_observations(monkeypatch):
    consumer, driver, view = setup(monkeypatch, status="diverted", direction="departure")
    asyncio.run(consumer._apply_arrival_diverted("f1", NOW, "diverted"))
    view.flights["f1"].update(direction="arrival", updated_at=(NOW + timedelta(minutes=1)).isoformat())
    asyncio.run(consumer._reconcile_flight_baggage(NOW))
    assert driver.db["baggage"]["b1"]["status"] == "in_hold"
    assert not driver.db["outbox"]


def test_departure_recovery_does_not_load_unscreened_bags(monkeypatch):
    consumer, driver, _ = setup(monkeypatch, status="airborne", direction="departure")
    driver.db["baggage"]["b1"]["status"] = "loaded"
    driver.db["baggage"]["b2"] = {"id": "b2", "tag": "fake2", "flight_id": "f1",
                                    "status": "screening", "scans": 0}
    asyncio.run(consumer._reconcile_flight_baggage(NOW))
    assert driver.db["baggage"]["b1"]["status"] == "in_hold"
    assert driver.db["baggage"]["b2"]["status"] == "short_shipped"


def test_cancellation_recovery_also_offloads_late_seeded_bags(monkeypatch):
    consumer, driver, _ = setup(monkeypatch, status="cancelled", direction="departure")
    offload = importlib.import_module("services.offload")
    monkeypatch.setattr(offload, "get_driver", lambda: driver)
    monkeypatch.setattr(offload, "get_flight_baggage", sys.modules["db.neo4j"].get_flight_baggage)
    asyncio.run(consumer._reconcile_flight_baggage(NOW))
    assert driver.db["baggage"]["b1"]["status"] == "offloaded"
    driver.db["baggage"]["late"] = {"id": "late", "tag": "late", "flight_id": "f1",
                                      "status": "loaded", "scans": 0}
    asyncio.run(consumer._reconcile_flight_baggage(NOW + timedelta(hours=1)))
    assert driver.db["baggage"]["late"]["status"] == "offloaded"
    assert driver.db["baggage"]["b1"]["scans"] == 1


def test_owner_consumers_default_to_earliest(monkeypatch):
    from tests.conftest import import_service_module
    from types import ModuleType
    from unittest.mock import MagicMock
    for owner in ["flight", "passenger", "baggage"]:
        import_service_module(owner, "application.commands")
        metrics = ModuleType("metrics")
        metrics.__getattr__ = lambda name: MagicMock()
        monkeypatch.setitem(sys.modules, "metrics", metrics)
        consumer = importlib.import_module("kafka.consumer")
        monkeypatch.setattr(consumer, "Consumer", lambda config: config)
        config = consumer._make_consumer()
        assert config["auto.offset.reset"] == "earliest"
        assert config["enable.auto.commit"] is False


def test_catch_up_sweeps_at_each_step_time(monkeypatch):
    consumer, _, _ = setup(monkeypatch)
    seed = importlib.import_module("_common.seed_requests")
    monkeypatch.setattr(seed, "apply_pending", AsyncMock(return_value=0))
    times = [NOW - timedelta(minutes=5), NOW]
    monkeypatch.setattr(consumer, "catch_up_times", lambda *args: times)
    recover = AsyncMock()
    monkeypatch.setattr(consumer, "_reconcile_flight_baggage", recover)
    monkeypatch.setattr(consumer, "run_tick", AsyncMock())
    monkeypatch.setattr(importlib.import_module("kafka.producer"), "emit_tick_processed", lambda *args: None)
    asyncio.run(consumer._on_clock_tick({}, NOW))
    assert [call.args[0] for call in recover.await_args_list] == times

"""G1 close-out (A41) atomicity for baggage-service — container-free.

Reuses the fake Neo4j ``Driver`` from ``test_baggage_outbox`` to prove, without
containers, that the remaining fact-emitting paths commit their domain write,
durable dedup marker / receipt and staged facts together or not at all:

* G1-c — ``at_gate`` arrivals and flight-cancellation offload.
* G1-b — the ``RedirectBaggage`` command (domain write + receipt + fact in one tx;
  redelivery re-emits the receipt without re-mutating).
* G1-a — the per-tick conveyor FSM (one ``execute_write`` per tick, idempotent
  replay via the ``BaggageOutboxSeq`` checkpoint, rollback on failure, flags).
"""

import asyncio
import importlib
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import import_service_module
from tests.unit.test_baggage_outbox import Driver

NOW = datetime(2026, 1, 1, 10)
LATER = NOW + timedelta(minutes=1)


def _ctx(monkeypatch, driver):
    """Import the baggage consumer with the fake driver wired everywhere."""
    import_service_module("baggage", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    consumer = importlib.import_module("kafka.consumer")
    consumer._state = consumer.BaggageConsumerState()
    monkeypatch.setattr(consumer, "get_driver", lambda: driver)
    # _handle_command re-imports get_driver from db.neo4j for the receipt load.
    monkeypatch.setattr(sys.modules["db.neo4j"], "get_driver", lambda: driver)
    offload = sys.modules["services.offload"]
    monkeypatch.setattr(offload, "get_driver", lambda: driver)
    return consumer


def _mock_gauges(monkeypatch, consumer):
    monkeypatch.setattr(consumer, "get_baggage_counts_by_status", AsyncMock(return_value={}))
    monkeypatch.setattr(sys.modules["db.neo4j"], "save_zone_projection", AsyncMock())
    monkeypatch.setattr(sys.modules["kafka.producer"], "emit_zone_snapshot", MagicMock())


# ════════════════════════ G1-c — at_gate arrivals ════════════════════════

AT_GATE_BAGS = [
    {"id": "b1", "tag": "t1", "passenger_id": "p1"},
    {"id": "b2", "tag": "t2", "passenger_id": None},
]
ARRIVE = {"flight_id": "f1", "new_status": "at_gate", "previous_status": "landed", "gate_id": "B05"}


def _arrival(consumer, event_id):
    return consumer._on_flight_status_changed(ARRIVE, NOW, event_id)


def test_at_gate_arrival_commits_atomically_and_dedups(monkeypatch):
    driver = Driver()
    consumer = _ctx(monkeypatch, driver)
    monkeypatch.setattr(sys.modules["db.neo4j"], "get_flight_baggage",
                        AsyncMock(return_value=AT_GATE_BAGS))
    asyncio.run(_arrival(consumer, "evt-arr"))
    assert driver.db["inbox"] == {"evt-arr"}
    assert driver.db["baggage"]["b1"]["status"] == "arrived"
    assert len(driver.db["outbox"]) == 2
    snapshot = deepcopy(driver.db)
    # Redelivery of the same input is a durable no-op.
    asyncio.run(_arrival(consumer, "evt-arr"))
    assert driver.db == snapshot


@pytest.mark.parametrize(
    "failure", ["UNWIND $changes AS change", "MERGE (i:BaggageInbox", "CREATE (e:BaggageOutbox"]
)
def test_at_gate_arrival_partial_write_rolls_back(monkeypatch, failure):
    driver = Driver()
    consumer = _ctx(monkeypatch, driver)
    monkeypatch.setattr(sys.modules["db.neo4j"], "get_flight_baggage",
                        AsyncMock(return_value=AT_GATE_BAGS))
    before = deepcopy(driver.db)
    driver.fail_on = failure
    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(_arrival(consumer, "evt-arr"))
    assert driver.db == before
    assert driver.db["inbox"] == set()
    assert driver.db["outbox"] == {}


# ════════════════════════ G1-c — cancellation offload ════════════════════════

OFFLOAD_BAGS = [
    {"id": "b1", "tag": "t1", "status": "loaded", "passenger_id": "p1"},
    {"id": "b2", "tag": "t2", "status": "in_hold", "passenger_id": None},
]


def _mock_offload_bags(monkeypatch):
    monkeypatch.setattr(sys.modules["services.offload"], "get_flight_baggage",
                        AsyncMock(return_value=OFFLOAD_BAGS))


def test_offload_commits_atomically_and_dedups_per_flight(monkeypatch):
    driver = Driver()
    consumer = _ctx(monkeypatch, driver)
    _mock_offload_bags(monkeypatch)
    asyncio.run(consumer._on_flight_cancelled({"flight_id": "f1"}, NOW))
    assert driver.db["inbox"] == {"offload:f1"}  # flight-scoped durable dedup
    assert driver.db["baggage"]["b1"]["status"] == "offloaded"
    assert len(driver.db["outbox"]) == 2
    snapshot = deepcopy(driver.db)
    # Same flight again (even if bags re-appear): deduped, no re-write.
    asyncio.run(consumer._on_flight_cancelled({"flight_id": "f1"}, NOW))
    assert driver.db == snapshot


@pytest.mark.parametrize(
    "failure", ["UNWIND $changes AS change", "MERGE (i:BaggageInbox", "CREATE (e:BaggageOutbox"]
)
def test_offload_partial_write_rolls_back(monkeypatch, failure):
    driver = Driver()
    consumer = _ctx(monkeypatch, driver)
    _mock_offload_bags(monkeypatch)
    before = deepcopy(driver.db)
    driver.fail_on = failure
    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(consumer._on_flight_cancelled({"flight_id": "f1"}, NOW))
    assert driver.db == before
    assert driver.db["inbox"] == set()


# ════════════════════════ G1-b — RedirectBaggage command ════════════════════════

def _redirect_ctx(monkeypatch, bag=None):
    driver = Driver()
    driver.db["baggage"]["BAG-1"] = {"scans": 0}
    driver.db["flights"].add("AX999")
    consumer = _ctx(monkeypatch, driver)
    consumer._state.sim_time = NOW
    bag = bag if bag is not None else {
        "id": "BAG-1", "tag": "t", "status": "loaded", "passenger": {"id": "p1"}
    }
    monkeypatch.setattr(consumer, "get_baggage_by_id", AsyncMock(return_value=bag))
    events = []
    monkeypatch.setattr(sys.modules["kafka.producer"], "_produce_event",
                        lambda kind, clock, payload, **kw: events.append((kind, payload)))
    return consumer, driver, events


CMD = {
    "command_id": "cmd-1", "command_type": "RedirectBaggage",
    "payload": {"bag_id": "BAG-1", "target_flight_id": "AX999"},
}


def test_redirect_commits_write_receipt_and_fact_in_one_tx(monkeypatch):
    consumer, driver, events = _redirect_ctx(monkeypatch)
    asyncio.run(consumer._handle_command(CMD))
    assert driver.db["baggage"]["BAG-1"]["loaded_on"] == "AX999"   # domain write
    assert driver.db["receipts"]["cmd-1"]["event_type"] == "CommandExecuted"  # receipt node
    assert len(driver.db["outbox"]) == 1                            # staged BaggageStatusChanged
    assert [k for k, _ in events] == ["CommandExecuted"]            # receipt fact emitted once


def test_redirect_redelivery_reemits_receipt_without_remutating(monkeypatch):
    consumer, driver, events = _redirect_ctx(monkeypatch)
    asyncio.run(consumer._handle_command(CMD))
    consumer._command_receipts.results.clear()  # simulate process restart
    scans = driver.db["baggage"]["BAG-1"]["scans"]
    outbox_n = len(driver.db["outbox"])
    asyncio.run(consumer._handle_command(CMD))
    assert [k for k, _ in events] == ["CommandExecuted", "CommandExecuted"]  # re-emitted
    assert driver.db["baggage"]["BAG-1"]["scans"] == scans           # no re-mutation
    assert len(driver.db["outbox"]) == outbox_n                      # no new fact staged


@pytest.mark.parametrize("failure", ["CREATE (b)-[:LOADED_ON {redirected_at", "CREATE (e:BaggageOutbox", "MERGE (r:CommandReceipt"])
def test_redirect_partial_write_rolls_back(monkeypatch, failure):
    consumer, driver, events = _redirect_ctx(monkeypatch)
    before = deepcopy(driver.db)
    driver.fail_on = failure
    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(consumer._handle_command(CMD))
    assert driver.db == before            # no write, no receipt, no fact
    assert events == []                   # nothing emitted


def test_redirect_rejected_when_target_flight_missing(monkeypatch):
    consumer, driver, events = _redirect_ctx(monkeypatch)
    driver.db["flights"].clear()          # target flight does not exist
    asyncio.run(consumer._handle_command(CMD))
    assert driver.db["receipts"]["cmd-1"]["event_type"] == "CommandRejected"
    assert [k for k, _ in events] == ["CommandRejected"]
    assert driver.db["outbox"] == {}      # no domain fact
    assert "loaded_on" not in driver.db["baggage"]["BAG-1"]


# ════════════════════════ G1-a — per-tick conveyor FSM ════════════════════════

def test_full_tick_commits_advancement_and_checkpoint_atomically(monkeypatch):
    driver = Driver()
    consumer = _ctx(monkeypatch, driver)
    _mock_gauges(monkeypatch, consumer)
    # Fast-track (departed) bag → in_hold in one tick; no conveyor drama.
    monkeypatch.setattr(consumer, "get_dropped_off_baggage_for_departures", AsyncMock(
        return_value=[{"id": "b1", "tag": "t1", "flight_status": "departed"}]))
    asyncio.run(consumer._on_clock_tick({}, NOW))
    assert driver.db["baggage"]["b1"]["status"] == "in_hold"
    assert driver.db["last_tick"] == NOW.isoformat()      # checkpoint advanced in-tx
    assert len(driver.db["outbox"]) == 1
    assert consumer._state.last_tick_sim_time == NOW      # cache advanced post-commit
    assert consumer._state.inducted_bag_ids == {"b1"}


def test_tick_replay_with_durable_checkpoint_is_noop(monkeypatch):
    driver = Driver()
    driver.db["last_tick"] = NOW.isoformat()              # tick already applied durably
    consumer = _ctx(monkeypatch, driver)
    # Bypass the in-memory guard to exercise the durable begin_tick_tx guard.
    consumer._state.last_tick_sim_time = None
    monkeypatch.setattr(consumer, "get_dropped_off_baggage_for_departures", AsyncMock(
        return_value=[{"id": "b1", "tag": "t1", "terminal_id": "T-A"}]))
    asyncio.run(consumer._on_clock_tick({}, NOW))
    assert driver.db["baggage"] == {}                     # no re-write
    assert driver.db["outbox"] == {}                      # no re-stage
    assert consumer._state.inducted_bag_ids == set()      # cache not advanced
    assert consumer._state.conveyor.get_zone("induction-A").items == 0  # rolled back


def test_tick_outbox_facts_carry_tick_scoped_stable_ids(monkeypatch):
    driver = Driver()
    consumer = _ctx(monkeypatch, driver)
    _mock_gauges(monkeypatch, consumer)
    monkeypatch.setattr(consumer, "get_dropped_off_baggage_for_departures", AsyncMock(
        return_value=[{"id": "b1", "tag": "t1", "flight_status": "departed"}]))
    asyncio.run(consumer._on_clock_tick({}, NOW))
    import json
    fact = json.loads(next(iter(driver.db["outbox"].values()))["document"])
    assert fact["event_id"] == f"{NOW.isoformat()}:b1:in_hold"   # deterministic per tick
    assert fact["payload"]["previous_status"] == "dropped_off"


def test_plan_bag_exit_flag_stages_flagged_fact_evicts_and_commits(monkeypatch):
    driver = Driver()
    consumer = _ctx(monkeypatch, driver)
    monkeypatch.setattr(consumer, "screen_item", lambda *a: "flagged")
    bag = consumer.BagInZone(
        baggage_id="b1", tag="t1", flight_id="f1", is_dg=True, dg_class="3",
        passenger_id="p1", terminal="A", entered_at=NOW.isoformat(),
    )
    consumer._state.conveyor.get_zone("screening-unit-1").queue.append(bag)
    plan = consumer._TickPlan()
    consumer._plan_bag_exit(plan, "screening-unit-1", bag, NOW)
    assert plan.flags == [
        {"baggage_id": "b1", "flag_reason": "dangerous_goods_detected",
         "scan_zone": "screening-unit-1"}]
    assert plan.status_changes == []                       # flagged, not a plain status row
    assert len(plan.facts) == 1
    assert plan.facts[0]["document"]["event_type"] == "BaggageFlagged"
    assert consumer._state.conveyor.get_zone("screening-unit-1").items == 0  # evicted
    assert ("flag_dg", "3") in plan.metrics
    # The flag commits through flag_baggage_tx in the per-tick transaction.
    assert asyncio.run(consumer._apply_tick(plan, NOW)) is True
    assert driver.db["baggage"]["b1"]["status"] == "flagged"
    assert len(driver.db["outbox"]) == 1


def test_tick_rollback_leaves_conveyor_and_checkpoint_unchanged(monkeypatch):
    driver = Driver()
    consumer = _ctx(monkeypatch, driver)
    monkeypatch.setattr(consumer, "get_dropped_off_baggage_for_departures", AsyncMock(
        return_value=[{"id": "b1", "tag": "t1", "terminal_id": "T-A"}]))
    driver.fail_on = "CREATE (e:BaggageOutbox"   # fact staging fails mid-tick
    before = deepcopy(driver.db)
    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(consumer._on_clock_tick({}, NOW))
    assert driver.db == before
    assert driver.db["last_tick"] is None
    assert consumer._state.last_tick_sim_time is None
    assert consumer._state.inducted_bag_ids == set()
    # Conveyor restored to the pre-tick snapshot: the compute-phase induct+advance
    # of b1 (into a screening zone) is fully rolled back — no cache/DB drift.
    assert sum(z.items for z in consumer._state.conveyor.get_all_zones().values()) == 0

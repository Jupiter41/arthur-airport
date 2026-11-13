"""Drive the actual owning-service handlers through their I/O boundaries."""

import asyncio
import importlib
import sys
from datetime import datetime
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import import_service_module

NOW = datetime(2024, 6, 15, 12)


def context(service, monkeypatch):
    import_service_module(service, "application.commands")
    # Metrics are an output boundary, not part of the command decision.
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    if service == "passenger":
        training = ModuleType("ml.training")
        training.add_training_row = MagicMock()
        training.maybe_flush = MagicMock()
        training.maybe_retrain = MagicMock()
        monkeypatch.setitem(sys.modules, "ml.training", training)
    consumer = importlib.import_module("kafka.consumer")
    producer = importlib.import_module("kafka.producer")
    db = importlib.import_module("db.neo4j")
    store = importlib.import_module("_common.command_store")
    documents, events = {}, []

    async def load(driver, key):
        return documents.get(key)

    async def save(driver, key, receipt):
        documents[key] = receipt

    monkeypatch.setattr(db, "get_driver", lambda: None)
    monkeypatch.setattr(store, "load_receipt", load)
    monkeypatch.setattr(store, "save_receipt", save)
    monkeypatch.setattr(
        producer,
        "_produce_event",
        lambda kind, clock, payload, **kw: events.append((kind, payload)),
    )
    consumer._state.sim_time = NOW
    return consumer, producer, db, documents, events


class _FakeResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    async def single(self):
        return self.rows[0] if self.rows else None

    async def consume(self):
        pass


class _FakeDriver:
    """Managed-transaction fake for the atomic command path (G1-b)."""

    def __init__(self, flights):
        self.db = {
            "flights": dict(flights),
            "runtime_rev": 0,
            "receipts": {},   # command_id -> (event_type, payload_json)
            "outbox": {},
            "gates": {},
            "inbox": set(),
        }
        self.fail_on = None

    def session(self):
        import copy
        driver = self

        class _S:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def execute_write(self, cb):
                candidate = copy.deepcopy(driver.db)
                res = await cb(_Tx(driver, candidate))
                driver.db = candidate
                return res

        return _S()


class _Tx:
    def __init__(self, driver, db):
        self.driver, self.db = driver, db

    async def run(self, query, **p):
        import json
        if self.driver.fail_on and self.driver.fail_on in query:
            self.driver.fail_on = None
            raise RuntimeError("Injected storage failure")
        db = self.db
        if "s:FlightRuntime" in query:
            db["runtime_rev"] += 1
            return _FakeResult([{"revision": db["runtime_rev"]}])
        if "RETURN r.event_type" in query:
            rec = db["receipts"].get(p["id"])
            return _FakeResult([{"event_type": rec[0], "payload": rec[1]}] if rec else [])
        if "MERGE (r:CommandReceipt" in query:
            db["receipts"][p["id"]] = (p["event_type"], p["payload"])
            return _FakeResult()
        if "SET f.status = 'delayed'" in query:  # set_manual_hold_in_tx
            f = db["flights"].get(p["id"])
            if f is None:
                return _FakeResult()
            f.update(status="delayed", delay_minutes=p["delay"], estimated_time=p["estimated"])
            return _FakeResult([{"flight": dict(f, id=p["id"])}])
        if "MERGE (f)-[r:ASSIGNED_TO]->(g)" in query:
            db["gates"][p["gate_id"]] = p["flight_id"]
            return _FakeResult([{"gate_id": p["gate_id"]}])
        if "i:FlightInbox" in query and "RETURN i.id" in query:
            return _FakeResult([{"id": p["id"]}] if p["id"] in db["inbox"] else [])
        if "MERGE (i:FlightInbox" in query:
            db["inbox"].add(p["id"])
            return _FakeResult()
        if "CREATE (e:FlightOutbox" in query:
            for row in p["rows"]:
                db["outbox"][row["id"]] = json.loads(row["document"])
            return _FakeResult()
        raise AssertionError(f"unexpected query: {query}")


def _outbox_types(driver):
    return [doc["event_type"] for doc in driver.db["outbox"].values()]


def test_flight_command_executes_once_and_dedupes_redelivery(monkeypatch):
    """G1-b: the hold write, its fact, the receipt and the receipt fact commit
    in one transaction; redelivery re-mutates nothing and stages nothing new."""
    consumer, _, _, _, _ = context("flight", monkeypatch)
    driver = _FakeDriver({"f1": {"status": "scheduled", "flight_number": "AX1",
                                 "estimated_time": "2024-06-15T12:10:00"}})

    async def get_flight(key):
        return {"id": key, "status": "scheduled", "flight_number": "AX1",
                "estimated_time": "2024-06-15T12:10:00"}

    monkeypatch.setattr(consumer, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_flight_by_id", get_flight)
    monkeypatch.setattr(consumer, "_state", consumer.FlightConsumerState())
    consumer._state.sim_time = NOW
    consumer._command_results.clear()

    command = {
        "command_id": "hold-1",
        "command_type": "HoldFlight",
        "payload": {"flight_id": "f1", "reason": "connections", "duration_min": 5},
    }
    asyncio.run(consumer._handle_command(command))
    assert driver.db["flights"]["f1"]["status"] == "delayed"
    assert driver.db["flights"]["f1"]["delay_minutes"] == 5
    # Domain fact + receipt fact both staged to the outbox; receipt persisted.
    assert _outbox_types(driver) == ["FlightStatusChanged", "CommandExecuted"]
    assert "hold-1" in driver.db["receipts"]
    assert "f1" in consumer._state.held_flights

    # Simulate a cross-process redelivery: clear the in-process cache so the
    # durable CommandReceipt is the only guard.
    consumer._command_results.clear()
    driver.db["flights"]["f1"]["status"] = "sentinel"   # detect any re-mutation
    outbox_before = dict(driver.db["outbox"])
    asyncio.run(consumer._handle_command(command))
    assert driver.db["flights"]["f1"]["status"] == "sentinel"   # not re-held
    assert driver.db["outbox"] == outbox_before                 # nothing re-staged


def test_flight_precondition_failure_stages_rejection_receipt(monkeypatch):
    consumer, _, _, _, _ = context("flight", monkeypatch)
    driver = _FakeDriver({"f1": {"status": "airborne", "flight_number": "AX1"}})

    async def get_flight(key):
        return {"id": key, "status": "airborne", "flight_number": "AX1"}

    monkeypatch.setattr(consumer, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_flight_by_id", get_flight)
    monkeypatch.setattr(consumer, "_state", consumer.FlightConsumerState())
    consumer._state.sim_time = NOW
    consumer._command_results.clear()

    asyncio.run(consumer._handle_command({
        "command_id": "hold-airborne",
        "command_type": "HoldFlight",
        "payload": {"flight_id": "f1", "reason": "connections", "duration_min": 5},
    }))
    # No domain mutation; a CommandRejected receipt fact is staged and persisted.
    assert driver.db["flights"]["f1"]["status"] == "airborne"
    assert _outbox_types(driver) == ["CommandRejected"]
    rec_type, rec_payload = driver.db["receipts"]["hold-airborne"]
    assert rec_type == "CommandRejected"
    assert "cannot hold" in __import__("json").loads(rec_payload)["reason"]


def test_passenger_lane_change_is_saved_emitted_and_rebuilt(monkeypatch):
    from _common import transaction_scope
    monkeypatch.setattr(transaction_scope, "restore_owner_checkpoint", AsyncMock(return_value=False))
    consumer, _, db, _, events = context("passenger", monkeypatch)
    saved = {}

    async def save_lanes(terminal, lanes, clock):
        saved[terminal] = lanes

    async def load_lanes():
        return saved

    async def load_breaches():
        return {}

    async def passengers(status):
        return []

    async def atomic(command_id, command_type, terminal, lanes, clock, rejection):
        assert rejection is None
        await save_lanes(terminal, lanes, clock)
        return "CommandExecuted", {}, True

    monkeypatch.setattr(db, "security_lane_command_atomic", atomic)
    monkeypatch.setattr(db, "load_security_lanes", load_lanes)
    monkeypatch.setattr(db, "load_security_breaches", load_breaches)
    monkeypatch.setattr(consumer, "get_passengers_by_status", passengers)
    asyncio.run(
        consumer._handle_command(
            {
                "command_id": "lane-1",
                "command_type": "OpenSecurityLane",
                "payload": {"terminal": "B", "lanes_open": 7},
            }
        )
    )
    assert saved == {"B": 7}
    assert consumer._state.security.checkpoints["B"].lanes_open == 7
    assert events == []  # The transaction stages both facts for outbox delivery
    consumer._state.security.checkpoints["B"].lanes_open = 1
    asyncio.run(consumer.rebuild_security_from_neo4j())
    assert consumer._state.security.checkpoints["B"].lanes_open == 7


def test_reassign_gate_command_stages_gate_fact_and_receipt(monkeypatch):
    consumer, _, _, _, _ = context("flight", monkeypatch)
    driver = _FakeDriver({"f1": {"status": "scheduled", "flight_number": "AX1"}})

    async def get_flight(key):
        return {"id": key, "status": "scheduled", "flight_number": "AX1"}

    async def unoccupied(*a, **k):
        return False

    monkeypatch.setattr(consumer, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_flight_by_id", get_flight)
    monkeypatch.setattr(consumer, "is_gate_occupied", unoccupied)
    monkeypatch.setattr(consumer, "_state", consumer.FlightConsumerState())
    consumer._state.sim_time = NOW
    consumer._command_results.clear()

    asyncio.run(consumer._handle_command({
        "command_id": "rg-1",
        "command_type": "ReassignGate",
        "payload": {"flight_id": "f1", "gate_id": "B07"},
    }))
    assert driver.db["gates"]["B07"] == "f1"
    assert _outbox_types(driver) == ["FlightGateAssigned", "CommandExecuted"]
    assert "rg-1" in driver.db["receipts"]


def test_command_partial_write_rolls_back_everything(monkeypatch):
    """A storage failure mid-transaction leaves no receipt, no outbox row and no
    domain mutation — the whole command transaction rolls back atomically."""
    consumer, _, _, _, _ = context("flight", monkeypatch)
    driver = _FakeDriver({"f1": {"status": "scheduled", "flight_number": "AX1",
                                 "estimated_time": "2024-06-15T12:10:00"}})

    async def get_flight(key):
        return {"id": key, "status": "scheduled", "flight_number": "AX1",
                "estimated_time": "2024-06-15T12:10:00"}

    monkeypatch.setattr(consumer, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_flight_by_id", get_flight)
    monkeypatch.setattr(consumer, "_state", consumer.FlightConsumerState())
    consumer._state.sim_time = NOW
    consumer._command_results.clear()
    driver.fail_on = "CREATE (e:FlightOutbox"   # fail when staging facts

    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(consumer._handle_command({
            "command_id": "hold-x",
            "command_type": "HoldFlight",
            "payload": {"flight_id": "f1", "reason": "connections", "duration_min": 5},
        }))
    assert driver.db["flights"]["f1"]["status"] == "scheduled"   # not mutated
    assert driver.db["receipts"] == {}                           # no receipt
    assert driver.db["outbox"] == {}                             # no facts
    assert "hold-x" not in consumer._command_results             # not cached
    assert "f1" not in consumer._state.held_flights


def test_manual_hold_is_persisted_before_cache_and_preserves_existing_delay(
    monkeypatch,
):
    """G1-b: the hold write + its FlightStatusChanged fact commit atomically; the
    in-memory held_flights cache is only populated after the commit."""
    consumer, _, _, _, _ = context("flight", monkeypatch)
    import json
    driver = _FakeDriver({"f1": {"status": "boarding", "direction": "departure",
                                 "estimated_time": "2024-06-15T12:10:00",
                                 "delay_minutes": 10, "flight_number": "AX100"}})

    async def get_flight(key):
        return {"id": key, "status": "boarding", "direction": "departure",
                "estimated_time": "2024-06-15T12:10:00", "delay_minutes": 10}

    monkeypatch.setattr(consumer, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_flight_by_id", get_flight)
    monkeypatch.setattr(consumer, "_state", consumer.FlightConsumerState())
    # The cache is empty until the transaction commits.
    assert "f1" not in consumer._state.held_flights
    asyncio.run(consumer.hold_flight("f1", "connections", 5, NOW))
    # Existing 10 min delay preserved + 5 min hold; estimated pushed 5 min.
    assert driver.db["flights"]["f1"]["delay_minutes"] == 15
    assert driver.db["flights"]["f1"]["estimated_time"] == "2024-06-15T12:15:00"
    assert consumer._state.held_flights["f1"]["reason"] == "connections"
    fact = next(iter(driver.db["outbox"].values()))
    assert fact["event_type"] == "FlightStatusChanged"
    assert fact["payload"]["delay_minutes"] == 15
    json.dumps(fact)  # fact is JSON-serialisable


def test_failed_hold_save_does_not_mutate_cache_or_stage_fact(monkeypatch):
    consumer, _, _, _, _ = context("flight", monkeypatch)
    # Driver has no 'f1' row, so set_manual_hold_in_tx returns no record (save fails).
    driver = _FakeDriver({})

    async def get_flight(key):
        return {"id": key, "estimated_time": "2024-06-15T12:00:00"}

    monkeypatch.setattr(consumer, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_flight_by_id", get_flight)
    monkeypatch.setattr(consumer, "_state", consumer.FlightConsumerState())
    assert asyncio.run(consumer.hold_flight("f1", "connections", 5, NOW)) is None
    assert "f1" not in consumer._state.held_flights
    assert driver.db["outbox"] == {}


def test_rejected_gate_assignment_never_emits_gate_assigned(monkeypatch):
    consumer, _, _, _, events = context("flight", monkeypatch)

    async def flight(key):
        return {"id": key, "gate_id": "A01"}

    async def unoccupied(*args, **kwargs):
        return False

    async def reject(tx, *args):
        return False

    # G1: reassign_gate now rejects inside the managed transaction via
    # assign_flight_to_gate_in_tx; a rejected write must stage no outbox fact
    # and emit nothing. Provide a minimal fake driver so apply(tx) runs, with
    # inbox_seen -> not-seen so the reject path is exercised.
    class _Result:
        async def single(self):
            return None

        async def consume(self):
            return None

    class _Tx:
        async def run(self, *a, **k):
            return _Result()

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute_write(self, fn):
            return await fn(_Tx())

    class _Driver:
        def session(self):
            return _Session()

    monkeypatch.setattr(consumer, "get_flight_by_id", flight)
    monkeypatch.setattr(consumer, "is_gate_occupied", unoccupied)
    monkeypatch.setattr(consumer, "assign_flight_to_gate_in_tx", reject)
    monkeypatch.setattr(consumer, "next_outbox_revision", AsyncMock(return_value=1))
    monkeypatch.setattr(consumer, "get_driver", lambda: _Driver())
    assert asyncio.run(consumer.reassign_gate("f1", "missing", NOW)) is None
    assert events == []


def test_distinct_commands_at_one_clock_keep_distinct_facts(monkeypatch):
    consumer, _, _, _, _ = context("flight", monkeypatch)
    driver = _FakeDriver({"f1": {"id": "f1", "status": "boarding", "flight_number": "ZZ001",
                                 "estimated_time": "2024-06-15T12:30:00", "delay_minutes": 0}})
    async def get_flight(key):
        return dict(driver.db["flights"][key])
    async def unoccupied(*args, **kwargs):
        return False
    monkeypatch.setattr(consumer, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_flight_by_id", get_flight)
    monkeypatch.setattr(consumer, "is_gate_occupied", unoccupied)
    consumer._state = consumer.FlightConsumerState()
    consumer._state.sim_time = NOW
    consumer._command_results.clear()
    for command_id in ("first", "second"):
        asyncio.run(consumer._handle_command({
            "command_id": command_id, "command_type": "ReassignGate",
            "payload": {"flight_id": "f1", "gate_id": "A01"},
        }))
    assert _outbox_types(driver).count("FlightGateAssigned") == 2
    assert _outbox_types(driver).count("CommandExecuted") == 2
    assert len(driver.db["outbox"]) == 4


def test_rest_holds_read_latest_state_under_owner_lock_and_dedup_retry(monkeypatch):
    consumer, _, _, _, _ = context("flight", monkeypatch)
    driver = _FakeDriver({"f1": {"id": "f1", "status": "boarding", "flight_number": "ZZ001",
                                 "estimated_time": "2024-06-15T12:30:00", "delay_minutes": 0}})
    async def get_flight(key):
        return dict(driver.db["flights"][key])
    monkeypatch.setattr(consumer, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_flight_by_id", get_flight)
    consumer._state = consumer.FlightConsumerState()
    for reason in ("first", "second", "second"):
        asyncio.run(consumer.hold_flight("f1", reason, 5, NOW))
    assert driver.db["flights"]["f1"]["delay_minutes"] == 10
    assert len(driver.db["outbox"]) == 2

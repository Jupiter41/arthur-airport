"""Drive the actual owning-service handlers through their I/O boundaries."""

import asyncio
import importlib
import sys
from datetime import datetime
from types import ModuleType
from unittest.mock import MagicMock

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


def test_flight_handler_executes_once_and_confirms_redelivery(monkeypatch):
    consumer, _, _, documents, events = context("flight", monkeypatch)
    holds = []

    async def get_flight(key):
        return {"id": key, "status": "scheduled"}

    async def hold(*args):
        holds.append(args)
        return {"id": args[0]}

    monkeypatch.setattr(consumer, "get_flight_by_id", get_flight)
    monkeypatch.setattr(consumer, "hold_flight", hold)
    command = {
        "command_id": "hold-1",
        "command_type": "HoldFlight",
        "payload": {
            "flight_id": "f1",
            "reason": "connections",
            "duration_min": 5,
        },
    }
    asyncio.run(consumer._handle_command(command))
    consumer._command_receipts.results.clear()  # restart of receipt cache
    asyncio.run(consumer._handle_command(command))
    assert len(holds) == 1
    assert [kind for kind, _ in events] == ["CommandExecuted", "CommandExecuted"]
    assert "hold-1" in documents


def test_flight_precondition_failure_produces_rejection(monkeypatch):
    consumer, _, _, _, events = context("flight", monkeypatch)

    async def get_flight(key):
        return {"id": key, "status": "airborne"}

    monkeypatch.setattr(consumer, "get_flight_by_id", get_flight)
    asyncio.run(
        consumer._handle_command(
            {
                "command_id": "hold-airborne",
                "command_type": "HoldFlight",
                "payload": {
                    "flight_id": "f1",
                    "reason": "connections",
                    "duration_min": 5,
                },
            }
        )
    )
    assert events[0][0] == "CommandRejected"
    assert "cannot hold" in events[0][1]["reason"]


def test_passenger_lane_change_is_saved_emitted_and_rebuilt(monkeypatch):
    consumer, _, db, _, events = context("passenger", monkeypatch)
    saved = {}

    async def save_lanes(terminal, lanes, clock):
        saved[terminal] = lanes

    async def load_lanes():
        return saved

    async def passengers(status):
        return []

    monkeypatch.setattr(db, "save_security_lanes", save_lanes)
    monkeypatch.setattr(db, "load_security_lanes", load_lanes)
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
    assert [kind for kind, _ in events] == ["SecurityLanesChanged", "CommandExecuted"]
    consumer._state.security.checkpoints["B"].lanes_open = 1
    asyncio.run(consumer.rebuild_security_from_neo4j())
    assert consumer._state.security.checkpoints["B"].lanes_open == 7


def test_manual_hold_is_persisted_before_cache_and_preserves_existing_delay(
    monkeypatch,
):
    consumer, _, db, _, events = context("flight", monkeypatch)
    writes = []

    async def get_flight(key):
        return {
            "id": key,
            "status": "boarding",
            "direction": "departure",
            "estimated_time": "2024-06-15T12:10:00",
            "delay_minutes": 10,
        }

    async def save(*args):
        assert "f1" not in consumer._state.held_flights
        writes.append(args)
        return {"id": "f1", "flight_number": "AX100", "status": "delayed"}

    monkeypatch.setattr(db, "get_flight_by_id", get_flight)
    monkeypatch.setattr(db, "set_manual_hold", save)
    asyncio.run(consumer.hold_flight("f1", "connections", 5, NOW))
    assert writes[0][3] == "2024-06-15T12:15:00"
    assert writes[0][4] == 15
    assert consumer._state.held_flights["f1"]["reason"] == "connections"
    assert events[0][1]["delay_minutes"] == 15


def test_failed_hold_save_does_not_mutate_cache_or_emit_applied_fact(monkeypatch):
    consumer, _, db, _, events = context("flight", monkeypatch)

    async def get_flight(key):
        return {"id": key, "estimated_time": "2024-06-15T12:00:00"}

    async def save(*args):
        return None

    monkeypatch.setattr(db, "get_flight_by_id", get_flight)
    monkeypatch.setattr(db, "set_manual_hold", save)
    assert asyncio.run(consumer.hold_flight("f1", "connections", 5, NOW)) is None
    assert "f1" not in consumer._state.held_flights
    assert events == []


def test_rejected_gate_assignment_never_emits_gate_assigned(monkeypatch):
    consumer, _, _, _, events = context("flight", monkeypatch)

    async def flight(key):
        return {"id": key, "gate_id": "A01"}

    async def unoccupied(*args, **kwargs):
        return False

    async def reject(*args):
        return False

    monkeypatch.setattr(consumer, "get_flight_by_id", flight)
    monkeypatch.setattr(consumer, "is_gate_occupied", unoccupied)
    monkeypatch.setattr(consumer, "assign_flight_to_gate", reject)
    assert asyncio.run(consumer.reassign_gate("f1", "missing", NOW)) is None
    assert events == []

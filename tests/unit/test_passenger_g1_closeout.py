"""G1 close-out (A41) — passenger-service atomic FSM tick, discrete-event and
command-receipt paths, container-free.

Extends the fake-driver style of ``test_passenger_outbox.py`` with a richer
in-memory graph (PassengerRuntime checkpoint, CommandReceipt, connection-risk and
location properties) so the per-tick, per-owner atomicity (G1-a), the atomic
discrete-event handlers (G1-c) and the atomic command receipt (G1-b) can be
exercised without Neo4j/Kafka. ``execute_write`` commits a deepcopy only if the
callback returns without raising, so a mid-transaction failure rolls everything
back exactly as a real managed transaction would.
"""

import asyncio
import importlib
import json
import sys
from copy import deepcopy
from datetime import datetime
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import import_service_module

SIM_TIME = datetime(2026, 1, 1, 12, 30)
LATER = datetime(2026, 1, 1, 12, 31)
EARLIER = datetime(2026, 1, 1, 12, 29)


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    async def single(self):
        return self.rows[0] if self.rows else None

    async def consume(self):
        pass

    async def data(self):
        return self.rows

    def __aiter__(self):
        async def gen():
            for row in self.rows:
                yield row
        return gen()


class Driver:
    def __init__(self):
        self.db = {
            "inbox": {}, "outbox": {}, "pax": {},
            "runtime": {"last_tick": None, "revision": 0},
            "receipts": {},
        }
        self.fail_once = None

    def session(self):
        driver = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def execute_write(self, callback):
                candidate = deepcopy(driver.db)
                result = await callback(Tx(driver, candidate))
                driver.db = candidate  # commit only if callback did not raise
                return result

            async def run(self, query, **params):
                return await Tx(driver, driver.db).run(query, **params)

        return Session()


class Tx:
    def __init__(self, driver, db):
        self.driver, self.db = driver, db

    async def run(self, query, **params):
        if self.driver.fail_once and self.driver.fail_once in query:
            self.driver.fail_once = None
            raise RuntimeError("Injected storage failure")
        db = self.db

        # --- PassengerRuntime checkpoint (G1-a) ---
        if "MERGE (s:PassengerRuntime" in query and "SET s.revision" in query:
            db["runtime"]["revision"] += 1
            return Result([{
                "last_tick": db["runtime"]["last_tick"],
                "revision": db["runtime"]["revision"],
            }])
        if "MATCH (s:PassengerRuntime" in query and "SET s.last_tick_sim_time" in query:
            db["runtime"]["last_tick"] = params["ts"]
            return Result()
        if "MATCH (s:PassengerRuntime" in query and "RETURN s.last_tick_sim_time" in query:
            return Result([{"last_tick": db["runtime"]["last_tick"]}])

        # --- CommandReceipt (G1-b) ---
        if "RETURN r.event_type" in query and "RETURN" in query:
            rec = db["receipts"].get(params["id"])
            if rec is None:
                return Result([])
            return Result([{"event_type": rec[0], "payload": json.dumps(rec[1])}])
        if "MERGE (r:CommandReceipt" in query:
            db["receipts"][params["id"]] = (
                params["event_type"], json.loads(params["payload"]),
            )
            return Result()

        # --- inbox / revision ---
        if "i:PassengerInbox" in query and "RETURN i.id" in query and "RETURN" in query:
            return Result([{"id": params["id"]}] if params["id"] in db["inbox"] else [])
        if "coalesce(max(o.revision)" in query:
            revs = [row["revision"] for row in db["outbox"].values()]
            return Result([{"rev": max(revs) if revs else 0}])

        # --- rebook: read eligible passengers ---
        if "RETURN p.id AS id, p.name AS name, p.status AS status" in query:
            rows = []
            for pid in params["ids"]:
                pax = db["pax"].get(pid)
                if pax is not None:
                    rows.append({
                        "id": pid, "name": pax.get("name", ""),
                        "status": pax.get("status"),
                        "location_zone": pax.get("zone"),
                        "flight_id": pax.get("flight_id"),
                        "flight_number": pax.get("flight_number"),
                    })
            return Result(rows)

        # --- domain writes ---
        if "SET p.status = 'rebooking'" in query:
            for pid in params["ids"]:
                db["pax"].setdefault(pid, {})["status"] = "rebooking"
            return Result()
        if "MATCH (p:Passenger" in query and "SET p.status = $status" in query:
            for pid in params["ids"]:
                db["pax"][pid] = {"status": params["status"], "zone": params["zone"]}
            return Result()
        if "SET p.location_zone = r.zone" in query:
            for row in params["rows"]:
                db["pax"].setdefault(row["id"], {})["zone"] = row["zone"]
            return Result()
        if "SET p.connection_risk = r.risk" in query:
            for row in params["rows"]:
                db["pax"].setdefault(row["id"], {})["risk"] = row["risk"]
            return Result()
        if "SET p.dwell_minutes = r.dwell" in query:
            for row in params["rows"]:
                db["pax"].setdefault(row["id"], {})["dwell"] = row["dwell"]
            return Result()

        # --- inbox mark / outbox stage+drain ---
        if "MERGE (i:PassengerInbox" in query:
            db["inbox"].setdefault(params["id"], params["sim_time"])
            return Result()
        if "CREATE (e:PassengerOutbox" in query:
            for row in params["rows"]:
                db["outbox"][row["id"]] = {**row, "revision": params["revision"]}
            return Result()
        if "MATCH (e:PassengerOutbox) RETURN" in query:
            rows = sorted(db["outbox"].values(), key=lambda r: (r["revision"], r["position"]))
            return Result([{"id": r["id"], "document": r["document"]} for r in rows])
        if "MATCH (e:PassengerOutbox {id: $id}) DELETE" in query:
            db["outbox"].pop(params["id"], None)
            return Result()
        raise AssertionError(query)


@pytest.fixture
def db_mod(monkeypatch):
    mod = import_service_module("passenger", "db.neo4j")
    driver = Driver()
    monkeypatch.setattr(mod, "get_driver", lambda: driver)
    return mod, driver


def _consumer(monkeypatch):
    import_service_module("passenger", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    return importlib.import_module("kafka.consumer")


# ===========================================================================
# G1-a — per-tick, per-owner atomic FSM advancement + checkpoint
# ===========================================================================


def test_tick_applies_transitions_stages_facts_and_advances_checkpoint(db_mod):
    mod, driver = db_mod
    groups = [{"ids": ["p1", "p2"], "status": "checked_in", "zone": "check-in-A"}]
    facts = [{"id": "f1", "document": {"event_id": "f1", "payload": {"passenger_id": "p1"}}}]

    applied = asyncio.run(mod.apply_tick_atomic(
        SIM_TIME, status_groups=groups, dwell_items=[("p1", 7)],
        location_updates=[{"id": "p2", "zone": "z"}], facts=facts,
    ))
    assert applied is True
    assert driver.db["pax"]["p1"]["status"] == "checked_in"
    assert driver.db["pax"]["p1"]["dwell"] == 7
    assert driver.db["runtime"]["last_tick"] == SIM_TIME.isoformat()
    assert "f1" in driver.db["outbox"] and len(driver.db["outbox"]) == 2
    batch = next(json.loads(r["document"]) for r in driver.db["outbox"].values()
                 if json.loads(r["document"]).get("event_type") == "PassengerStatusBatchChanged")
    assert batch["payload"]["status_groups"] == groups
    assert batch["payload"]["dwell_items"] == [["p1", 7]]
    # outbox staged at the locked runtime revision
    assert driver.db["outbox"]["f1"]["revision"] == driver.db["runtime"]["revision"]


def test_tick_replay_at_or_before_checkpoint_is_noop(db_mod):
    mod, driver = db_mod
    asyncio.run(mod.apply_tick_atomic(
        SIM_TIME, status_groups=[{"ids": ["p1"], "status": "airside", "zone": "z"}],
        facts=[{"id": "a", "document": {"event_id": "a", "payload": {}}}],
    ))
    committed = deepcopy(driver.db)

    # Same sim_time (== checkpoint) → idempotent no-op.
    assert asyncio.run(mod.apply_tick_atomic(
        SIM_TIME, status_groups=[{"ids": ["p9"], "status": "airside", "zone": "z"}],
        facts=[{"id": "b", "document": {"event_id": "b", "payload": {}}}],
    )) is False
    # Earlier sim_time (crash-resume replay) → idempotent no-op.
    assert asyncio.run(mod.apply_tick_atomic(
        EARLIER, status_groups=[{"ids": ["p8"], "status": "airside", "zone": "z"}],
        facts=[{"id": "c", "document": {"event_id": "c", "payload": {}}}],
    )) is False

    assert "p9" not in driver.db["pax"] and "p8" not in driver.db["pax"]
    assert set(driver.db["outbox"]) == set(committed["outbox"])  # no new facts
    assert driver.db["runtime"]["last_tick"] == SIM_TIME.isoformat()  # unchanged


def test_tick_strictly_increasing_sim_time_applies_each(db_mod):
    mod, driver = db_mod
    asyncio.run(mod.apply_tick_atomic(
        SIM_TIME, status_groups=[{"ids": ["p1"], "status": "airside", "zone": "z"}],
        facts=[{"id": "t1", "document": {"event_id": "t1", "payload": {}}}],
    ))
    assert asyncio.run(mod.apply_tick_atomic(
        LATER, status_groups=[{"ids": ["p2"], "status": "airside", "zone": "z"}],
        facts=[{"id": "t2", "document": {"event_id": "t2", "payload": {}}}],
    )) is True
    assert driver.db["runtime"]["last_tick"] == LATER.isoformat()
    assert driver.db["outbox"]["t1"]["revision"] < driver.db["outbox"]["t2"]["revision"]


def test_tick_partial_write_rolls_back_without_advancing_checkpoint(db_mod):
    mod, driver = db_mod
    driver.fail_once = "CREATE (e:PassengerOutbox"
    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(mod.apply_tick_atomic(
            SIM_TIME, status_groups=[{"ids": ["p1"], "status": "airside", "zone": "z"}],
            facts=[{"id": "x", "document": {"event_id": "x", "payload": {}}}],
        ))
    # Nothing committed: no pax write, no outbox row, checkpoint not advanced.
    assert driver.db["pax"] == {}
    assert driver.db["outbox"] == {}
    assert driver.db["runtime"]["last_tick"] is None


def test_read_tick_checkpoint_roundtrips(db_mod):
    mod, driver = db_mod
    assert asyncio.run(mod.read_tick_checkpoint()) is None
    asyncio.run(mod.apply_tick_atomic(SIM_TIME, status_groups=[], facts=[]))
    assert asyncio.run(mod.read_tick_checkpoint()) == SIM_TIME


# ===========================================================================
# G1-b — atomic rebook command execution + owner receipt
# ===========================================================================


def test_rebook_mutates_stages_domain_facts_and_receipt_atomically(db_mod):
    mod, driver = db_mod
    driver.db["pax"]["p1"] = {"status": "at_gate", "zone": "gate-1", "name": "A"}
    driver.db["pax"]["p2"] = {"status": "departed_airport", "zone": "hall"}  # terminal → skipped

    event_type, payload, mutated = asyncio.run(mod.rebook_passengers_atomic(
        "cmd-1", "RebookPassengers", ["p1", "p2", "ghost"], SIM_TIME,
    ))
    assert (event_type, mutated) == ("CommandExecuted", True)
    assert payload["rebooked"] == 1 and payload["skipped"] == 2  # p2 terminal + ghost unknown
    assert driver.db["pax"]["p1"]["status"] == "rebooking"
    assert driver.db["pax"]["p2"]["status"] == "departed_airport"  # untouched
    assert driver.db["receipts"]["cmd-1"][0] == "CommandExecuted"
    docs = [json.loads(r["document"]) for r in driver.db["outbox"].values()]
    kinds = sorted(d["event_type"] for d in docs)
    assert kinds == ["CommandExecuted", "PassengerStatusChanged"]


def test_rebook_redelivery_reemits_receipt_without_remutating(db_mod):
    mod, driver = db_mod
    driver.db["pax"]["p1"] = {"status": "at_gate", "zone": "gate-1", "name": "A"}
    asyncio.run(mod.rebook_passengers_atomic("cmd-2", "RebookPassengers", ["p1"], SIM_TIME))
    # Deliver + clear the outbox as the delivery loop would.
    driver.db["outbox"] = {}
    pax_before = deepcopy(driver.db["pax"])

    event_type, payload, mutated = asyncio.run(mod.rebook_passengers_atomic(
        "cmd-2", "RebookPassengers", ["p1"], SIM_TIME,
    ))
    assert (event_type, mutated) == ("CommandExecuted", False)  # receipt re-emit only
    assert driver.db["pax"] == pax_before  # no re-mutation
    docs = [json.loads(r["document"]) for r in driver.db["outbox"].values()]
    assert [d["event_type"] for d in docs] == ["CommandExecuted"]  # only the receipt
    assert docs[0]["payload"]["command_id"] == "cmd-2"


def test_rebook_no_eligible_passengers_rejects(db_mod):
    mod, driver = db_mod
    driver.db["pax"]["p1"] = {"status": "departed", "zone": "z"}  # terminal
    event_type, payload, mutated = asyncio.run(mod.rebook_passengers_atomic(
        "cmd-3", "RebookPassengers", ["p1"], SIM_TIME,
    ))
    assert (event_type, mutated) == ("CommandRejected", True)
    assert "no passengers rebooked" in payload["reason"]
    assert driver.db["pax"]["p1"]["status"] == "departed"  # untouched
    docs = [json.loads(r["document"]) for r in driver.db["outbox"].values()]
    assert [d["event_type"] for d in docs] == ["CommandRejected"]  # receipt only, no domain fact


def test_rebook_partial_write_rolls_back(db_mod):
    mod, driver = db_mod
    driver.db["pax"]["p1"] = {"status": "at_gate", "zone": "gate-1", "name": "A"}
    before = deepcopy(driver.db)
    driver.fail_once = "CREATE (e:PassengerOutbox"
    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(mod.rebook_passengers_atomic("cmd-4", "RebookPassengers", ["p1"], SIM_TIME))
    assert driver.db == before
    assert driver.db["receipts"] == {}  # receipt rolled back with the domain write
    assert driver.db["pax"]["p1"]["status"] == "at_gate"


def test_handle_rebook_command_parse_error_emits_rejection(monkeypatch):
    consumer = _consumer(monkeypatch)
    consumer._state.sim_time = SIM_TIME
    emitted = []
    db = importlib.import_module("db.neo4j")
    driver = Driver()
    monkeypatch.setattr(db, "get_driver", lambda: driver)
    monkeypatch.setattr(
        consumer, "rebook_passengers_atomic",
        AsyncMock(side_effect=AssertionError("must not execute on parse error")),
    )
    from kafka import producer
    monkeypatch.setattr(producer, "_produce_event",
                        lambda kind, clock, payload, **kw: emitted.append((kind, payload)))

    # Missing inbound_flight → parse rejects before any atomic execution.
    asyncio.run(consumer._handle_command({
        "command_id": "bad-1", "command_type": "RebookPassengers",
        "payload": {"passenger_ids": ["p1"]},
    }))
    assert emitted == []
    assert driver.db["receipts"]["bad-1"][0] == "CommandRejected"
    document = json.loads(next(iter(driver.db["outbox"].values()))["document"])
    assert document["event_type"] == "CommandRejected"
    assert document["payload"]["command_id"] == "bad-1"


def test_handle_rebook_command_valid_routes_to_atomic(monkeypatch):
    consumer = _consumer(monkeypatch)
    consumer._state.sim_time = SIM_TIME
    calls = []

    async def fake_atomic(command_id, command_type, passenger_ids, sim_time):
        calls.append((command_id, passenger_ids))
        return "CommandExecuted", {"command_id": command_id}, True

    monkeypatch.setattr(consumer, "rebook_passengers_atomic", fake_atomic)
    asyncio.run(consumer._handle_command({
        "command_id": "ok-1", "command_type": "RebookPassengers",
        "payload": {"inbound_flight": "AX1", "passenger_ids": ["p1", "p2"]},
    }))
    assert calls == [("ok-1", ["p1", "p2"])]


# ===========================================================================
# G1-c — discrete-event atomic handlers
# ===========================================================================


def test_flight_cancelled_stages_status_and_alert_facts_atomically(monkeypatch):
    consumer = _consumer(monkeypatch)
    db = importlib.import_module("db.neo4j")
    driver = Driver()
    monkeypatch.setattr(db, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_passengers_by_flight", AsyncMock(return_value=[
        {"id": "p1", "name": "A", "status": "checked_in", "location_zone": "check-in-A"},
        {"id": "p2", "name": "B", "status": "boarded", "location_zone": "gate-1"},  # skipped
    ]))
    # A direct Kafka emit would be a regression on the atomic path.
    monkeypatch.setattr(consumer, "emit_passenger_alert",
                        AsyncMock(side_effect=AssertionError("must stage, not emit")))

    asyncio.run(consumer._on_flight_cancelled(
        {"flight_id": "FL1"}, SIM_TIME, "cancel-evt-1"))

    assert set(driver.db["inbox"]) == {"cancel-evt-1"}
    assert driver.db["pax"]["p1"]["status"] == "disrupted"
    assert "p2" not in driver.db["pax"]  # boarded skipped
    docs = [json.loads(r["document"]) for r in driver.db["outbox"].values()]
    kinds = sorted(d["event_type"] for d in docs)
    assert kinds == ["PassengerAlert", "PassengerStatusChanged"]  # both staged for p1


def test_flight_cancelled_redelivery_is_deduped(monkeypatch):
    consumer = _consumer(monkeypatch)
    db = importlib.import_module("db.neo4j")
    driver = Driver()
    monkeypatch.setattr(db, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_passengers_by_flight", AsyncMock(return_value=[
        {"id": "p1", "name": "A", "status": "checked_in", "location_zone": "check-in-A"},
    ]))
    asyncio.run(consumer._on_flight_cancelled({"flight_id": "FL1"}, SIM_TIME, "evt-dup"))
    committed = deepcopy(driver.db)
    asyncio.run(consumer._on_flight_cancelled({"flight_id": "FL1"}, SIM_TIME, "evt-dup"))
    assert driver.db["outbox"] == committed["outbox"]  # no second staging


def test_baggage_on_carousel_stages_location_update_atomically(monkeypatch):
    consumer = _consumer(monkeypatch)
    db = importlib.import_module("db.neo4j")
    driver = Driver()
    monkeypatch.setattr(db, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_passengers_by_flight", AsyncMock(return_value=[
        {"id": "p1", "status": "baggage_claim"},
        {"id": "p2", "status": "deplaning"},  # not at baggage_claim → not moved
    ]))
    payload = {"new_status": "on_carousel", "flight_id": "FL1",
               "scan_zone": "arrival-belt-3"}
    asyncio.run(consumer._on_baggage_status_changed(payload, SIM_TIME, "bag-evt-1"))

    assert set(driver.db["inbox"]) == {"bag-evt-1"}
    assert driver.db["pax"]["p1"]["zone"] == "carousel-3"
    assert "p2" not in driver.db["pax"]
    assert "p1" in consumer._state.passengers_at_carousel  # in-memory set updated post-commit


def test_check_connections_stages_missed_risk_and_alerts_atomically(monkeypatch):
    consumer = _consumer(monkeypatch)
    db = importlib.import_module("db.neo4j")
    driver = Driver()
    monkeypatch.setattr(db, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_connecting_passengers", AsyncMock(return_value=[]))
    monkeypatch.setattr(consumer, "evaluate_connecting_passengers", lambda *a, **k: [
        {"id": "p1", "risk_changed": True, "risk_level": "missed",
         "inbound_flight": "AX1", "connection_flight": "AX2"},
        {"id": "p2", "risk_changed": True, "risk_level": "at_risk",
         "inbound_flight": "AX3", "connection_flight": "AX4"},
        {"id": "p3", "risk_changed": False, "risk_level": "watch",
         "inbound_flight": "AX5", "connection_flight": "AX6"},
    ])
    monkeypatch.setattr(consumer, "emit_passenger_alert",
                        AsyncMock(side_effect=AssertionError("must stage, not emit")))

    asyncio.run(consumer._check_connections(SIM_TIME))

    # Durable per-check dedup id.
    assert set(driver.db["inbox"]) == {f"conn-{SIM_TIME.isoformat()}"}
    assert driver.db["pax"]["p1"]["status"] == "missed_connection"  # missed status write
    assert driver.db["pax"]["p1"]["risk"] == "missed"               # risk property write
    assert driver.db["pax"]["p2"]["risk"] == "at_risk"
    docs = [json.loads(r["document"]) for r in driver.db["outbox"].values()]
    assert sorted(d["event_type"] for d in docs) == ["PassengerAlert", "PassengerAlert"]
    assert {d["payload"]["type"] for d in docs} == {"connection_missed", "connection_at_risk"}

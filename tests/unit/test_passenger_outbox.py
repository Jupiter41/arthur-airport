"""G1 — passenger-service atomic domain-write + outbox/inbox (container-free).

Mirrors cost-service's ``test_cost_ledger.py`` fake-driver style: a Driver whose
``execute_write`` commits a deepcopy only if the callback returns without raising,
so a mid-transaction failure rolls everything back (inbox marker + outbox rows +
domain write) exactly as a real Neo4j transaction would.
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


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    async def single(self):
        return self.rows[0] if self.rows else None

    async def consume(self):
        pass

    async def data(self):
        return self.rows


class Driver:
    def __init__(self):
        self.db = {"inbox": {}, "outbox": {}, "pax": {}}
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
        if "MATCH (i:PassengerInbox" in query and "RETURN" in query:
            return Result([{"id": params["id"]}] if params["id"] in db["inbox"] else [])
        if "coalesce(max(o.revision)" in query:
            revs = [row["revision"] for row in db["outbox"].values()]
            return Result([{"rev": max(revs) if revs else 0}])
        if "MATCH (p:Passenger" in query and "SET p.status" in query:
            for pid in params["ids"]:
                db["pax"][pid] = {"status": params["status"], "zone": params["zone"]}
            return Result()
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


def _facts(*ids):
    """Build minimal {"id","document"} outbox facts with JSON-serialisable docs."""
    return [
        {"id": fid, "document": {"event_id": fid, "event_type": "PassengerStatusChanged",
                                 "payload": {"passenger_id": f"pax-{fid}"}}}
        for fid in ids
    ]


@pytest.fixture
def db_mod(monkeypatch):
    mod = import_service_module("passenger", "db.neo4j")
    driver = Driver()
    monkeypatch.setattr(mod, "get_driver", lambda: driver)
    return mod, driver


def test_partial_write_rolls_back_leaving_no_inbox_marker_and_no_outbox_row(db_mod):
    mod, driver = db_mod
    before = deepcopy(driver.db)
    groups = [{"ids": ["p1", "p2"], "status": "deplaning", "zone": "term-a-deplane"}]
    facts = _facts("f1", "f2")

    # Fail while staging the outbox — after the inbox mark and domain write in the
    # same transaction; the whole transaction must roll back.
    driver.fail_once = "CREATE (e:PassengerOutbox"
    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(mod.apply_status_change_atomic("evt-1", groups, facts, SIM_TIME))

    assert driver.db == before
    assert driver.db["inbox"] == {}
    assert driver.db["outbox"] == {}
    assert driver.db["pax"] == {}

    # The same event_id can be retried cleanly once storage recovers.
    assert asyncio.run(mod.apply_status_change_atomic("evt-1", groups, facts, SIM_TIME)) is True
    assert set(driver.db["inbox"]) == {"evt-1"}
    assert set(driver.db["outbox"]) == {"f1", "f2"}
    assert driver.db["pax"]["p1"]["status"] == "deplaning"


def test_redelivery_of_same_event_id_is_deduped_and_not_reapplied(db_mod):
    mod, driver = db_mod
    groups = [{"ids": ["p1"], "status": "departed_airport", "zone": "departed"}]

    assert asyncio.run(mod.apply_status_change_atomic("evt-9", groups, _facts("a"), SIM_TIME)) is True
    committed = deepcopy(driver.db)

    # A redelivery with the SAME event_id must be a no-op: no re-apply, no new facts.
    applied = asyncio.run(mod.apply_status_change_atomic(
        "evt-9", [{"ids": ["p1"], "status": "departed_airport", "zone": "departed"}],
        _facts("b"), SIM_TIME))
    assert applied is False
    assert driver.db == committed
    assert set(driver.db["outbox"]) == {"a"}  # "b" was never staged


def test_outbox_delivered_in_revision_position_order_and_deleted_only_on_ack(db_mod, monkeypatch):
    mod, driver = db_mod
    outbox = importlib.import_module("_common.outbox")

    # Two separate events → two revisions; facts within an event carry positions.
    asyncio.run(mod.apply_status_change_atomic(
        "evt-A", [{"ids": ["p1", "p2"], "status": "deplaning", "zone": "z"}],
        _facts("a1", "a2"), SIM_TIME))
    asyncio.run(mod.apply_status_change_atomic(
        "evt-B", [{"ids": ["p3"], "status": "deplaning", "zone": "z"}],
        _facts("b1"), SIM_TIME))

    # evt-A got revision 1, evt-B revision 2 (max over still-pending + 1).
    assert driver.db["outbox"]["a1"]["revision"] == 1
    assert driver.db["outbox"]["b1"]["revision"] == 2

    delivered = []

    def publish(document):
        delivered.append(document["event_id"])

    count = asyncio.run(outbox.publish_pending("PassengerOutbox", lambda: driver, publish))
    assert count == 3
    assert delivered == ["a1", "a2", "b1"]  # (revision, position) order
    assert driver.db["outbox"] == {}  # all deleted after ack


def test_outbox_row_retained_when_publish_confirmed_raises(db_mod):
    mod, driver = db_mod
    outbox = importlib.import_module("_common.outbox")
    asyncio.run(mod.apply_status_change_atomic(
        "evt-R", [{"ids": ["p1"], "status": "deplaning", "zone": "z"}], _facts("r1"), SIM_TIME))

    def failing_publish(document):
        raise RuntimeError("Broker unavailable")

    with pytest.raises(RuntimeError, match="Broker unavailable"):
        asyncio.run(outbox.publish_pending("PassengerOutbox", lambda: driver, failing_publish))

    # Unconfirmed fact is retained (not deleted) for a later redelivery attempt.
    assert set(driver.db["outbox"]) == {"r1"}


# --- Consumer-level: prove the canonical path stages instead of direct-emitting ---


def _consumer(monkeypatch):
    import_service_module("passenger", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    return importlib.import_module("kafka.consumer")


def test_flight_departed_stages_facts_atomically_without_direct_emit(monkeypatch):
    consumer = _consumer(monkeypatch)
    db = importlib.import_module("db.neo4j")
    producer = importlib.import_module("kafka.producer")

    driver = Driver()
    monkeypatch.setattr(db, "get_driver", lambda: driver)
    monkeypatch.setattr(consumer, "get_passengers_by_flight", AsyncMock(return_value=[
        {"id": "p1", "name": "A", "status": "boarded", "location_zone": "gate-1"},
        {"id": "p2", "name": "B", "status": "boarded", "location_zone": "gate-1"},
        {"id": "p3", "name": "C", "status": "airside", "location_zone": "hall"},  # not eligible
    ]))
    # A direct Kafka emit on the canonical path would be a regression.
    monkeypatch.setattr(consumer, "emit_passenger_status_changed",
                        AsyncMock(side_effect=AssertionError("canonical path must stage, not emit")))

    payload = {"flight_id": "FL1", "new_status": "departed", "direction": "departure"}
    asyncio.run(consumer._on_flight_status_changed(payload, SIM_TIME, "flight-evt-1"))

    assert set(driver.db["inbox"]) == {"flight-evt-1"}
    assert len(driver.db["outbox"]) == 2  # only the two boarded passengers
    docs = [json.loads(row["document"]) for row in driver.db["outbox"].values()]
    assert all(d["event_type"] == "PassengerStatusChanged" for d in docs)
    assert {d["payload"]["new_status"] for d in docs} == {"departed_airport"}
    assert {d["payload"]["passenger_id"] for d in docs} == {"p1", "p2"}
    # publish_confirmed exists and is wired for the delivery loop.
    assert callable(producer.publish_confirmed)

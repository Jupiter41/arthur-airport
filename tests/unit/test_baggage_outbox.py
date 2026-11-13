"""G1 atomic domain-write + inbox/outbox boundary for baggage-service.

Container-free: a fake Neo4j driver/transaction (mirroring tests/unit/
test_cost_ledger.py) proves the canonical "flight departed → bags in_hold"
path commits the bag status, the durable BaggageInbox marker and the staged
BaggageStatusChanged facts together or not at all, dedups redeliveries, and
delivers the outbox in (revision, position) order deleting only on broker ack.
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

NOW = datetime(2026, 1, 1, 10)


# ── Fake Neo4j (same shape as the cost-service ledger tests) ───────────────

class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    async def single(self):
        return self.rows[0] if self.rows else None

    async def consume(self):
        pass

    async def data(self):
        return self.rows


class Tx:
    def __init__(self, driver, db):
        self.driver, self.db = driver, db

    async def run(self, query, **params):
        if self.driver.fail_on and self.driver.fail_on in query:
            self.driver.fail_on = None
            raise RuntimeError("Injected storage failure")
        db = self.db
        if "BaggageOutboxSeq" in query:
            db["revision"] += 1
            return Result([{"revision": db["revision"]}])
        if "BaggageInbox" in query and "RETURN i.id" in query:
            return Result([{"id": params["id"]}] if params["id"] in db["inbox"] else [])
        if "MERGE (i:BaggageInbox" in query:
            db["inbox"].add(params["id"])
            return Result()
        if "UNWIND $changes AS change" in query:
            for change in params["changes"]:
                bag = db["baggage"].setdefault(change["id"], {"scans": 0})
                bag["status"] = change["status"]
                bag["zone"] = change["zone"]
                bag["scans"] += 1
            return Result()
        if "CREATE (e:BaggageOutbox" in query:
            for row in params["rows"]:
                db["outbox"][row["id"]] = {
                    "id": row["id"], "document": row["document"],
                    "revision": params["revision"], "position": row["position"],
                }
            return Result()
        if "MATCH (e:BaggageOutbox) RETURN" in query:
            rows = sorted(db["outbox"].values(), key=lambda r: (r["revision"], r["position"]))
            return Result([{"id": r["id"], "document": r["document"]}
                           for r in rows[:params["batch"]]])
        if "DELETE e" in query:
            db["outbox"].pop(params["id"], None)
            return Result()
        raise AssertionError(query)


class Driver:
    def __init__(self):
        self.db = {"baggage": {}, "inbox": set(), "outbox": {}, "revision": 0}
        self.fail_on = None

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


def context(monkeypatch, driver, bags):
    """Import the baggage consumer with the fake driver + flight baggage wired."""
    import_service_module("baggage", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    consumer = importlib.import_module("kafka.consumer")
    consumer._state = consumer.BaggageConsumerState()
    monkeypatch.setattr(consumer, "get_driver", lambda: driver)
    database = sys.modules["db.neo4j"]
    monkeypatch.setattr(database, "get_flight_baggage", AsyncMock(return_value=bags))
    return consumer


DEP_BAGS = [
    {"id": "b1", "tag": "fake-1", "status": "inducted", "passenger_id": "p1"},
    {"id": "b2", "tag": "fake-2", "status": "loaded", "passenger_id": None},
]


def departed(consumer, event_id):
    return consumer._on_flight_status_changed(
        {"flight_id": "f1", "new_status": "departed"}, NOW, event_id
    )


# ── (a) partial-write rollback leaves NO inbox marker and NO outbox row ────

@pytest.mark.parametrize(
    "failure", ["UNWIND $changes AS change", "MERGE (i:BaggageInbox", "CREATE (e:BaggageOutbox"]
)
def test_partial_write_rolls_back_inbox_and_outbox(monkeypatch, failure):
    driver = Driver()
    consumer = context(monkeypatch, driver, DEP_BAGS)
    before = deepcopy(driver.db)
    driver.fail_on = failure
    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(departed(consumer, "evt-dep"))
    assert driver.db == before            # nothing committed
    assert driver.db["inbox"] == set()    # no durable marker
    assert driver.db["outbox"] == {}      # no staged facts
    assert driver.db["baggage"] == {}     # no status mutation
    # The failing storage is transient: the identical input can be retried.
    assert asyncio.run(departed(consumer, "evt-dep")) is None
    assert driver.db["inbox"] == {"evt-dep"}
    assert len(driver.db["outbox"]) == 2
    assert driver.db["baggage"]["b1"]["status"] == "in_hold"


# ── (b) redelivery of the same event_id is deduped, no re-apply/re-emit ────

def test_redelivery_same_event_id_is_deduped(monkeypatch):
    driver = Driver()
    consumer = context(monkeypatch, driver, DEP_BAGS)
    asyncio.run(departed(consumer, "evt-dep"))
    assert driver.db["inbox"] == {"evt-dep"}
    assert len(driver.db["outbox"]) == 2
    assert driver.db["baggage"]["b1"]["scans"] == 1
    snapshot = deepcopy(driver.db)

    asyncio.run(departed(consumer, "evt-dep"))  # same id again
    assert driver.db == snapshot                 # no re-write, no re-stage
    assert driver.db["baggage"]["b1"]["scans"] == 1
    assert driver.db["revision"] == 1            # no revision consumed on dedup

    # A genuinely new input is still processed.
    asyncio.run(departed(consumer, "evt-dep-2"))
    assert driver.db["inbox"] == {"evt-dep", "evt-dep-2"}
    assert len(driver.db["outbox"]) == 4


def test_staged_facts_carry_stable_ids_and_full_envelope(monkeypatch):
    driver = Driver()
    consumer = context(monkeypatch, driver, DEP_BAGS)
    asyncio.run(departed(consumer, "evt-dep"))
    facts = [json.loads(r["document"]) for r in driver.db["outbox"].values()]
    by_bag = {f["payload"]["baggage_id"]: f for f in facts}
    assert set(by_bag) == {"b1", "b2"}
    assert by_bag["b1"]["event_id"] == "evt-dep:b1:in_hold"  # stable, not a uuid
    assert by_bag["b1"]["event_type"] == "BaggageStatusChanged"
    assert by_bag["b1"]["payload"]["previous_status"] == "inducted"
    assert by_bag["b1"]["payload"]["new_status"] == "in_hold"
    assert by_bag["b2"]["payload"]["previous_status"] == "loaded"


# ── (c) outbox drains in (revision, position) order; delete only on ack ────

def _outbox_module(monkeypatch):
    import_service_module("baggage", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    importlib.import_module("kafka.consumer")  # ensure baggage context on sys.path
    return importlib.import_module("_common.outbox")


def _seed_outbox(driver):
    # Insert out of order on purpose; (revision, position) is the contract.
    driver.db["outbox"] = {
        "r2p0": {"id": "r2p0", "document": json.dumps({"n": "r2p0"}), "revision": 2, "position": 0},
        "r1p1": {"id": "r1p1", "document": json.dumps({"n": "r1p1"}), "revision": 1, "position": 1},
        "r1p0": {"id": "r1p0", "document": json.dumps({"n": "r1p0"}), "revision": 1, "position": 0},
    }


def test_outbox_delivers_in_order_and_deletes_only_after_ack(monkeypatch):
    outbox = _outbox_module(monkeypatch)
    driver = Driver()
    _seed_outbox(driver)
    sent = []
    delivered = asyncio.run(
        outbox.publish_pending("BaggageOutbox", lambda: driver,
                               lambda doc: sent.append(doc["n"]))
    )
    assert delivered == 3
    assert sent == ["r1p0", "r1p1", "r2p0"]  # revision then position
    assert driver.db["outbox"] == {}          # every acked row deleted


def test_outbox_row_retained_when_broker_does_not_ack(monkeypatch):
    outbox = _outbox_module(monkeypatch)
    driver = Driver()
    _seed_outbox(driver)
    seen = []

    def fail(doc):
        seen.append(doc["n"])
        raise RuntimeError("Broker unavailable")

    with pytest.raises(RuntimeError, match="Broker unavailable"):
        asyncio.run(outbox.publish_pending("BaggageOutbox", lambda: driver, fail))
    assert seen == ["r1p0"]                 # stopped at the first unconfirmed fact
    assert len(driver.db["outbox"]) == 3    # nothing deleted

    # Broker recovers: delivery resumes, same ids, in order, then drains.
    ok = []
    assert asyncio.run(
        outbox.publish_pending("BaggageOutbox", lambda: driver, lambda doc: ok.append(doc["n"]))
    ) == 3
    assert ok == ["r1p0", "r1p1", "r2p0"]
    assert driver.db["outbox"] == {}

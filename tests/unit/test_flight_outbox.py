"""G1 — flight-service atomic domain-write + outbox/inbox (container-free).

Mirrors cost-service's ``test_cost_ledger.py`` fake-driver style: a tiny
in-memory Driver/Tx models Neo4j managed-transaction atomicity (the callback
runs against a deep copy that is only committed on success), so we can assert
the real consumer + shared ``_common.outbox`` behaviour without Neo4j or Kafka.

Covers the canonical status-change path (``_commit_transition`` inside
``_execute_transition``) and the gate-assignment path (``reassign_gate``).
"""

import asyncio
from copy import deepcopy
from datetime import datetime

import pytest
from unittest.mock import AsyncMock

from tests.conftest import import_service_module


SIM_TIME = datetime(2026, 1, 1, 12, 0, 0)

# Import the consumer ONCE: its metrics module registers global Prometheus
# collectors that cannot be re-registered, so a per-test re-import would raise
# "Duplicated timeseries". The shared outbox module is taken from the consumer's
# own binding so we exercise exactly the object it uses.
_CONSUMER = import_service_module("flight", "kafka.consumer")
_OUTBOX = _CONSUMER.outbox_common


def flight(fid="F1", status="boarding", **extra):
    base = {
        "id": fid,
        "flight_number": "ZZ100",
        "direction": "departure",
        "destination_iata": "ZZZ",
        "gate_id": "A01",
        "runway_id": None,
    }
    base.update(extra)
    return base


# ── Fake Neo4j driver ────────────────────────────────────────────

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
        self.db = {
            "flights": {},
            "runtime_rev": 0,
            "inbox": set(),
            "outbox": {},
            "gates": {},  # gate_id -> flight_id currently holding it
        }
        self.fail_on = None  # substring of a query to fail once

    def session(self):
        driver = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def execute_write(self, callback):
                # Managed-transaction atomicity: work on a copy, commit on success.
                candidate = deepcopy(driver.db)
                result = await callback(Tx(driver, candidate))
                driver.db = candidate
                return result

            async def run(self, query, **params):
                return await Tx(driver, driver.db).run(query, **params)

        return Session()


class Tx:
    def __init__(self, driver, db):
        self.driver, self.db = driver, db

    async def run(self, query, **p):
        if self.driver.fail_on and self.driver.fail_on in query:
            self.driver.fail_on = None
            raise RuntimeError("Injected storage failure")
        db = self.db
        if "MERGE (s:FlightRuntime" in query:
            db["runtime_rev"] += 1
            return Result([{"revision": db["runtime_rev"]}])
        if "MATCH (i:FlightInbox" in query:
            return Result([{"id": p["id"]}] if p["id"] in db["inbox"] else [])
        if "MERGE (i:FlightInbox" in query:
            db["inbox"].add(p["id"])
            return Result()
        if "MERGE (f)-[r:ASSIGNED_TO]->(g)" in query:  # assign_flight_to_gate_in_tx
            fid, gid = p["flight_id"], p["gate_id"]
            holder = db["gates"].get(gid)
            if holder is not None and holder != fid:
                return Result()  # occupied by another flight
            db["gates"][gid] = fid
            db["flights"].setdefault(fid, {})["gate_id"] = gid
            return Result([{"gate_id": gid}])
        if "SET f.status" in query:  # update_flight_status_in_tx
            fid = p["id"]
            f = db["flights"].get(fid)
            if f is None:
                return Result()
            f["status"] = p["status"]
            for k in ("delay_minutes", "delay_reason", "estimated_time",
                      "actual_time", "arrival_estimated_time"):
                if k in p:
                    f[k] = p[k]
            row = {"flight": dict(f, id=fid),
                   "arrival_estimated_time": f.get("arrival_estimated_time")}
            return Result([row])
        if "UNWIND $rows AS row CREATE (e:FlightOutbox" in query:  # stage_outbox
            for row in p["rows"]:
                db["outbox"][row["id"]] = {
                    "id": row["id"], "document": row["document"],
                    "revision": p["revision"], "position": row["position"],
                }
            return Result()
        if "MATCH (e:FlightOutbox) RETURN" in query:  # publish_pending (ORDER BY)
            ordered = sorted(db["outbox"].values(),
                             key=lambda r: (r["revision"], r["position"]))
            return Result([{"id": r["id"], "document": r["document"]} for r in ordered])
        if "MATCH (e:FlightOutbox {id: $id}) DELETE e" in query:
            db["outbox"].pop(p["id"], None)
            return Result()
        raise AssertionError(f"unexpected query: {query}")


@pytest.fixture
def flight_ctx(monkeypatch):
    consumer, outbox = _CONSUMER, _OUTBOX
    driver = Driver()
    monkeypatch.setattr(consumer, "get_driver", lambda: driver)
    return consumer, outbox, driver


# ── (a) partial-write rollback ───────────────────────────────────

def test_partial_write_rolls_back_inbox_and_outbox(flight_ctx):
    consumer, _, driver = flight_ctx
    driver.db["flights"]["F1"] = {"status": "boarding"}
    driver.fail_on = "SET f.status"  # fail the domain write mid-transaction
    before = deepcopy(driver.db)
    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(consumer._commit_transition(
            flight(), "boarding", "departed", SIM_TIME, {}, 0,
        ))
    # Nothing committed: no inbox marker, no outbox row, revision untouched,
    # flight still in its prior status.
    assert driver.db == before
    assert driver.db["inbox"] == set()
    assert driver.db["outbox"] == {}
    assert driver.db["runtime_rev"] == 0
    assert driver.db["flights"]["F1"]["status"] == "boarding"


# ── (b) replay / redelivery dedup ────────────────────────────────

def test_replay_same_transition_is_deduped_and_not_reemitted(flight_ctx):
    consumer, _, driver = flight_ctx
    driver.db["flights"]["F1"] = {"status": "boarding"}

    first = asyncio.run(consumer._commit_transition(
        flight(), "boarding", "departed", SIM_TIME, {}, 0,
    ))
    assert first is True
    assert driver.db["flights"]["F1"]["status"] == "departed"
    assert len(driver.db["outbox"]) == 1
    assert len(driver.db["inbox"]) == 1
    assert driver.db["runtime_rev"] == 1
    staged_id = next(iter(driver.db["outbox"]))

    # Redelivery of the exact same transition: deduped by the durable inbox.
    second = asyncio.run(consumer._commit_transition(
        flight(), "boarding", "departed", SIM_TIME, {}, 0,
    ))
    assert second is False
    assert len(driver.db["outbox"]) == 1          # no second fact
    assert next(iter(driver.db["outbox"])) == staged_id
    assert driver.db["runtime_rev"] == 1          # revision not bumped on dedup


def test_transition_stages_full_envelope_with_stable_id(flight_ctx):
    consumer, _, driver = flight_ctx
    driver.db["flights"]["F1"] = {"status": "boarding"}
    asyncio.run(consumer._commit_transition(
        flight(), "boarding", "departed", SIM_TIME, {}, 0,
    ))
    row = next(iter(driver.db["outbox"].values()))
    import json
    env = json.loads(row["document"])
    assert row["id"] == env["event_id"] == "fsc:F1:boarding:departed:2026-01-01T12:00:00"
    assert env["event_type"] == "FlightStatusChanged"
    assert env["producer"] == "flight-service"
    assert env["payload"]["flight_id"] == "F1"
    assert env["payload"]["new_status"] == "departed"


# ── (c) outbox delivery order, ack, and retention ────────────────

def test_outbox_delivers_in_revision_position_order_and_deletes_on_ack(flight_ctx):
    consumer, outbox, driver = flight_ctx
    # Stage rows out of insertion order across (revision, position).
    driver.db["outbox"] = {
        "b": {"id": "b", "document": '{"event_id":"b"}', "revision": 2, "position": 0},
        "c": {"id": "c", "document": '{"event_id":"c"}', "revision": 2, "position": 1},
        "a": {"id": "a", "document": '{"event_id":"a"}', "revision": 1, "position": 0},
    }
    delivered = []
    count = asyncio.run(outbox.publish_pending(
        "FlightOutbox", lambda: driver, lambda doc: delivered.append(doc["event_id"]),
    ))
    assert count == 3
    assert delivered == ["a", "b", "c"]          # (revision, position) order
    assert driver.db["outbox"] == {}             # deleted only after ack


def test_publish_confirmed_failure_retains_outbox_rows(flight_ctx):
    consumer, outbox, driver = flight_ctx
    driver.db["outbox"] = {
        "a": {"id": "a", "document": '{"event_id":"a"}', "revision": 1, "position": 0},
        "b": {"id": "b", "document": '{"event_id":"b"}', "revision": 2, "position": 0},
    }

    def fail(doc):
        raise RuntimeError("Broker unavailable")

    with pytest.raises(RuntimeError, match="Broker unavailable"):
        asyncio.run(outbox.publish_pending("FlightOutbox", lambda: driver, fail))
    # The unacked row (and everything after it) is retained for retry.
    assert set(driver.db["outbox"]) == {"a", "b"}


def test_committed_fact_then_delivers_end_to_end(flight_ctx):
    consumer, outbox, driver = flight_ctx
    driver.db["flights"]["F1"] = {"status": "boarding"}
    asyncio.run(consumer._commit_transition(
        flight(), "boarding", "departed", SIM_TIME, {}, 0,
    ))
    delivered = []
    asyncio.run(outbox.publish_pending(
        "FlightOutbox", lambda: driver, lambda doc: delivered.append(doc["event_id"]),
    ))
    assert delivered == ["fsc:F1:boarding:departed:2026-01-01T12:00:00"]
    assert driver.db["outbox"] == {}


# ── gate-assignment path (reassign_gate) ─────────────────────────

def test_reassign_gate_is_atomic_and_dedupes(flight_ctx, monkeypatch):
    consumer, _, driver = flight_ctx
    monkeypatch.setattr(consumer, "get_flight_by_id",
                        AsyncMock(return_value=flight(gate_id="A01")))
    monkeypatch.setattr(consumer, "is_gate_occupied", AsyncMock(return_value=False))
    monkeypatch.setattr(consumer, "_state", consumer.FlightConsumerState())

    result = asyncio.run(consumer.reassign_gate("F1", "B05", SIM_TIME))
    assert result is not None and result["gate_id"] == "B05"
    assert driver.db["gates"]["B05"] == "F1"      # ASSIGNED_TO write committed
    assert len(driver.db["outbox"]) == 1          # FlightGateAssigned staged
    import json
    env = json.loads(next(iter(driver.db["outbox"].values()))["document"])
    assert env["event_type"] == "FlightGateAssigned"
    assert env["payload"]["reason"] == "reassignment"

    # Replaying the same reassignment does not stage a second fact.
    asyncio.run(consumer.reassign_gate("F1", "B05", SIM_TIME))
    assert len(driver.db["outbox"]) == 1

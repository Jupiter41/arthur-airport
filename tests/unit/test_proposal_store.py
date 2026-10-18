"""Proposal decisions and command scheduling are atomic and replica independent."""

import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import importlib
import json

import pytest

from tests.conftest import import_service_module

NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


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
        async def rows():
            for row in self.rows:
                yield row
        return rows()


class Driver:
    def __init__(self):
        self.db = {"proposals": {}, "outbox": {}, "revision": 0, "clock": None, "offset": None}
        self.fail_after_outbox = False
        self.lose_commit_ack = False
        self.lock = asyncio.Lock()

    def session(self):
        driver = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def execute_write(self, callback):
                async with driver.lock:
                    candidate = deepcopy(driver.db)
                    result = await callback(Tx(driver, candidate))
                    driver.db = candidate
                if driver.lose_commit_ack:
                    driver.lose_commit_ack = False
                    return await self.execute_write(callback)
                return result

            async def run(self, query, **params):
                return await Tx(driver, driver.db).run(query, **params)

        return Session()


class Tx:
    def __init__(self, driver, db):
        self.driver, self.db = driver, db

    async def run(self, query, **params):
        db = self.db
        if query.startswith("CREATE CONSTRAINT") or query.startswith("CREATE INDEX"):
            return Result()
        if "MERGE (s:AnalysisRuntime" in query:
            db["revision"] += 1
            return Result([{"revision": db["revision"]}])
        if "MERGE (p:ActionProposal" in query:
            db["proposals"][params["id"]] = {"document": params["document"], "status": params["status"],
                "target_key": params["key"], "recommendation_id": params["recommendation_id"]}
        elif "MATCH (p:ActionProposal {id:" in query:
            row = db["proposals"].get(params["id"])
            return Result([row] if row else [])
        elif "p.target_key = $key" in query:
            return Result([row for row in db["proposals"].values()
                if (row["target_key"] == params["key"] and row["status"] in params["active"])
                or (params["recommendation_id"] is not None
                    and row["recommendation_id"] == params["recommendation_id"]
                    and row["status"] not in {"failed", "rejected"})][:1])
        elif "MATCH (p:ActionProposal) RETURN" in query:
            return Result(db["proposals"].values())
        elif "CREATE (e:AnalysisOutbox)" in query:
            db["outbox"].update({row["id"]: row for row in params["rows"]})
            if self.driver.fail_after_outbox:
                self.driver.fail_after_outbox = False
                raise RuntimeError("Injected failure after durable effects")
        elif "MATCH (e:AnalysisOutbox) RETURN" in query:
            return Result(sorted(db["outbox"].values(), key=lambda row: (row["revision"], row["position"])))
        elif "DELETE e" in query:
            db["outbox"].pop(params["id"], None)
        elif "RETURN s.clock_offset" in query:
            return Result([{"offset": db["offset"]}])
        elif "SET s.clock =" in query:
            db.update(clock=params["clock"], offset=params["offset"])
        elif "RETURN s.clock AS clock" in query:
            return Result([{"clock": db["clock"]}])
        else:
            raise AssertionError(query)
        return Result()


@pytest.fixture
def context(monkeypatch):
    execution = import_service_module("analysis", "services.action_execution")
    store = importlib.import_module("services.proposal_store")
    worker = importlib.import_module("services.action_outbox")
    driver = Driver()
    monkeypatch.setattr(store, "get_driver", lambda: driver)
    monkeypatch.setattr(worker, "get_driver", lambda: driver)
    execution.approval_queue.clear()
    return store, execution, worker, driver


async def create(context, *, human=True, proposal_id=None, recommendation_id="synthetic-rec"):
    store, execution, _, _ = context
    proposal = execution.approval_queue.propose(
        action_type="open_security_lane", description="Synthetic security relief",
        parameters={"terminal": "B", "new_lane_count": 5}, confidence_score=0.9,
        proposed_by="operator", proposed_at=NOW, requires_human=human,
        recommendation_id=recommendation_id, bottleneck_id="synthetic-bottleneck",
    )
    if proposal_id:
        proposal.id = proposal_id
    return await execution.persist(proposal, NOW)


def commands(driver):
    return [json.loads(row["document"]) for row in driver.db["outbox"].values()
            if row["topic"].endswith(".commands")]


def document(driver, key):
    return json.loads(driver.db["proposals"][key]["document"])


def test_creation_deduplicates_active_targets_after_cache_loss(context):
    _, execution, _, driver = context
    first = asyncio.run(create(context))
    execution.approval_queue.clear()
    second = asyncio.run(create(context, recommendation_id="different-recommendation"))
    assert first.id == second.id
    assert len(driver.db["proposals"]) == len(driver.db["outbox"]) == 1


@pytest.mark.parametrize("mutation", ["create", "approve", "reject", "receipt"])
def test_state_and_outbox_roll_back_together(context, mutation):
    store, _, _, driver = context
    proposal = asyncio.run(create(context)) if mutation != "create" else None
    if mutation == "receipt":
        asyncio.run(store.dispatch(proposal.id, NOW, approve_by="operator"))
    before = deepcopy(driver.db)
    driver.fail_after_outbox = True
    with pytest.raises(RuntimeError, match="Injected"):
        if mutation == "create":
            asyncio.run(create(context))
        elif mutation == "approve":
            asyncio.run(store.dispatch(proposal.id, NOW, approve_by="operator"))
        elif mutation == "reject":
            asyncio.run(store.reject(proposal.id, NOW, "operator", "unsafe"))
        else:
            asyncio.run(store.receipt("CommandExecuted", {"command_id": proposal.id,
                "command_type": "OpenSecurityLane"}, NOW, "passengers.events"))
    assert driver.db == before


def test_competing_approvals_and_timeout_retries_schedule_one_attempt(context):
    store, execution, _, driver = context

    async def exercise():
        proposal = await create(context)
        await asyncio.gather(*(store.dispatch(proposal.id, NOW, approve_by="operator") for _ in range(4)))
        assert len(commands(driver)) == 1
        execution.approval_queue.clear()
        await asyncio.gather(*(store.dispatch(proposal.id, NOW + timedelta(minutes=5)) for _ in range(4)))
        assert document(driver, proposal.id)["dispatch_attempts"] == 2
        assert len(commands(driver)) == 2
        assert {command["command_id"] for command in commands(driver)} == {proposal.id}
    asyncio.run(exercise())


def test_approve_reject_race_has_one_legal_winner(context):
    store, _, _, driver = context

    async def exercise():
        proposal = await create(context)
        results = await asyncio.gather(store.reject(proposal.id, NOW, "operator", "unsafe"),
            store.dispatch(proposal.id, NOW, approve_by="another-operator"))
        assert sum(result is not None for result in results) == 1
        assert document(driver, proposal.id)["status"] == "rejected"
        assert commands(driver) == []
    asyncio.run(exercise())


def test_old_dispatch_cache_cannot_overwrite_confirmed_receipt(context):
    store, execution, _, driver = context
    proposal = asyncio.run(create(context))
    stale = asyncio.run(store.dispatch(proposal.id, NOW, approve_by="operator"))
    assert asyncio.run(execution.receive_result("CommandExecuted", {
        "command_id": proposal.id, "command_type": "OpenSecurityLane"}, NOW, "passengers.events"))
    execution.approval_queue.cache(stale)
    assert proposal.status == "executed"
    assert document(driver, proposal.id)["status"] == "executed"
    assert not asyncio.run(execution.receive_result("CommandRejected", {
        "command_id": proposal.id, "command_type": "OpenSecurityLane"}, NOW, "passengers.events"))


def test_broker_failure_retains_same_outbox_envelopes_until_ack(context, monkeypatch):
    store, _, worker, driver = context
    proposal = asyncio.run(create(context))
    asyncio.run(store.dispatch(proposal.id, NOW, approve_by="operator"))
    before = deepcopy(driver.db["outbox"])
    monkeypatch.setattr(worker, "publish_confirmed", lambda *args: (_ for _ in ()).throw(RuntimeError("broker")))
    with pytest.raises(RuntimeError, match="broker"):
        asyncio.run(worker.publish_pending())
    assert driver.db["outbox"] == before
    sent = []
    monkeypatch.setattr(worker, "publish_confirmed", lambda *args: sent.append(args))
    asyncio.run(worker.publish_pending())
    assert driver.db["outbox"] == {}
    assert [row[2] for row in sent] == [json.loads(row["document"]) for row in before.values()]


def test_broker_position_fences_stale_clock_owner_and_invalid_tick(context):
    store, _, _, _ = context
    assert asyncio.run(store.save_clock({"sim_time": NOW.isoformat()}, (0, 20)))
    assert not asyncio.run(store.save_clock({"sim_time": (NOW - timedelta(days=1)).isoformat()}, (0, 19)))
    assert asyncio.run(store.load_clock())["sim_time"] == "2026-01-01T12:00:00Z"
    with pytest.raises(ValueError):
        asyncio.run(store.save_clock({"sim_time": "invalid"}, (0, 21)))
    assert asyncio.run(store.load_clock())["sim_time"] == "2026-01-01T12:00:00Z"


def test_ambiguous_commits_keep_original_proposal_and_single_dispatch(context):
    store, _, _, driver = context
    driver.lose_commit_ack = True
    proposal = asyncio.run(create(context))
    assert len(driver.db["outbox"]) == 1
    driver.lose_commit_ack = True
    asyncio.run(store.dispatch(proposal.id, NOW, approve_by="operator"))
    assert len(commands(driver)) == 1
    assert document(driver, proposal.id)["dispatch_attempts"] == 1

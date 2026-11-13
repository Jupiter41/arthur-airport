"""Discovery identities, timers and facts survive replay and failed commits."""
import asyncio
from copy import deepcopy
import importlib
import json
from unittest.mock import AsyncMock

import pytest

from tests.conftest import import_service_module
from tests.unit.test_proposal_store import Result


@pytest.fixture
def discovery(monkeypatch):
    module = import_service_module("analysis", "services.projection_store")
    proposals = importlib.import_module("services.proposal_store")
    graph = {key: [] for key in ("flights", "gates", "incidents", "weather", "baggage", "vehicles", "cost")}
    graph["security"] = [{"terminal": "B", "checkpoint": {
        "queue_depth": 300, "lanes_open": 2, "wait_minutes": 50, "at": "2026-01-01T12:00:00Z"}}]
    database = {"document": None, "outbox": [], "revision": 0, "offset": 1,
                "clock": {"sim_time": "2026-01-01T12:00:00Z", "tick_number": 1}}
    fail = [False]
    lock = asyncio.Lock()

    class Tx:
        def __init__(self, candidate):
            self.db = candidate

        async def run(self, query, **params):
            if "s.clock AS clock" in query:
                return Result([{"clock": json.dumps(self.db["clock"]), "offset": self.db["offset"]}])
            if "RETURN s.document AS document" in query:
                return Result([{"document": self.db["document"]}])
            if "SET s.document = $document" in query:
                self.db["document"] = params["document"]
            elif "MATCH (p:ActionProposal)" in query:
                return Result()
            elif "CREATE (e:AnalysisOutbox)" in query:
                self.db["outbox"].extend(params["rows"])
                if fail[0]:
                    raise RuntimeError("Failed after discovery + outbox writes")
            else:
                raise AssertionError(query)
            return Result()

    async def transaction(callback):
        async with lock:
            candidate = deepcopy(database)
            candidate["revision"] += 1
            result = await callback(Tx(candidate), candidate["revision"])
            database.update(candidate)
            return result

    monkeypatch.setattr(proposals, "_transaction", transaction)
    monkeypatch.setattr(module, "load_operational_projection", AsyncMock(side_effect=lambda **kw: deepcopy(graph)))
    monkeypatch.setattr(module, "query_connection_clusters", AsyncMock(return_value=[]))
    return module, graph, database, fail


def test_replay_and_independent_restore_retain_ids_and_do_not_emit_twice(discovery):
    module, _, database, _ = discovery
    first, new, _ = asyncio.run(module.evaluate())
    assert new and first["recommendations"]
    facts = deepcopy(database["outbox"])
    second, new, resolved = asyncio.run(module.evaluate())
    assert second == first and not new and not resolved
    assert database["outbox"] == facts
    state, active, recs = module.restore(json.loads(database["document"]))
    assert state.security["Terminal B"].queue_depth == 300
    assert set(active) == {bn["id"] for bn in first["bottlenecks"]}
    assert [rec.id for rec in recs] == [rec["id"] for rec in first["recommendations"]]


def test_discovery_and_facts_roll_back_together(discovery):
    module, _, database, fail = discovery
    before = deepcopy(database)
    fail[0] = True
    with pytest.raises(RuntimeError, match="after discovery"):
        asyncio.run(module.evaluate())
    assert database == before
    fail[0] = False
    assert asyncio.run(module.evaluate())[0]["bottlenecks"]


def test_competing_evaluators_publish_one_discovery(discovery):
    module, _, database, _ = discovery
    async def compete():
        return await asyncio.gather(module.evaluate(), module.evaluate())
    first, second = asyncio.run(compete())
    assert first[0] == second[0]
    assert bool(first[1]) != bool(second[1])
    facts = [json.loads(row["document"]) for row in database["outbox"]]
    assert sum(row["event_type"] == "BottleneckDetected" for row in facts) == 1


def test_late_owner_snapshot_at_same_clock_resolves_existing_bottleneck(discovery):
    module, graph, database, _ = discovery
    first, _, _ = asyncio.run(module.evaluate())
    graph["security"][0]["checkpoint"].update(queue_depth=0, wait_minutes=0)
    second, new, resolved = asyncio.run(module.evaluate())
    assert second["clock_offset"] == first["clock_offset"]
    assert not second["bottlenecks"] and not second["recommendations"]
    assert len(resolved) == 1 and not new
    assert any(json.loads(row["document"])["event_type"] == "BottleneckResolved" for row in database["outbox"])


def test_threshold_duration_survives_restart_and_newer_offset_rewind(discovery):
    module, graph, database, _ = discovery
    graph["security"] = []
    graph["baggage"] = [{"document": json.dumps({"at": "2026-01-01T12:00:00Z", "zones": [{
        "zone_id": "make-up-B-1", "items": 20, "throughput_per_hour": 150, "utilisation_pct": 100,
    }]})}]
    first, _, _ = asyncio.run(module.evaluate())
    assert first["threshold_timers"]["make-up-B-1"]
    database.update(offset=2, clock={"sim_time": "2026-01-01T12:06:00Z", "tick_number": 2})
    second, new, _ = asyncio.run(module.evaluate())
    assert len(new) == 1 and second["bottlenecks"]
    database.update(offset=3, clock={"sim_time": "2026-01-01T11:00:00Z", "tick_number": 0})
    third, _, resolved = asyncio.run(module.evaluate())
    assert resolved and not third["bottlenecks"]

"""RC1: lifecycle retention — archive finished entities, purge archives, prune inbox."""
import asyncio
import importlib
import json
import sys
from datetime import datetime
from types import ModuleType
from unittest.mock import MagicMock

from tests.conftest import import_service_module

NOW = datetime(2024, 7, 8, 12, 0, 0)


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    async def data(self):
        return self._rows

    async def single(self):
        return self._rows[0] if self._rows else None

    async def consume(self):
        return None


class _Tx:
    """Records every query; ``respond(query, params)`` supplies result rows."""

    def __init__(self, respond):
        self.respond = respond
        self.queries: list[tuple[str, dict]] = []

    async def run(self, query, **params):
        self.queries.append((query, params))
        return _Result(self.respond(query, params))


class _Driver:
    def __init__(self, respond):
        self.respond = respond
        self.txs: list[_Tx] = []

    def session(self):
        driver = self

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def run(self, query, **params):
                tx = _Tx(driver.respond)
                driver.txs.append(tx)
                return await tx.run(query, **params)

            async def execute_write(self, fn):
                tx = _Tx(driver.respond)
                driver.txs.append(tx)
                return await fn(tx)

        return _Session()


def _retention():
    import_service_module("flight", "application.commands")
    return importlib.import_module("_common.retention")


def _metrics_stub(monkeypatch):
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)


def _staged(tx):
    for query, params in tx.queries:
        if "CREATE (e:" in query and "Outbox" in query:
            return [json.loads(row["document"]) for row in params["rows"]]
    return []


# ── shared helpers ────────────────────────────────────────────────

def test_cutoffs_derive_from_sim_time():
    retention = _retention()
    archive_before, purge_before = retention.cutoffs(NOW)
    assert archive_before == "2024-07-07T12:00:00"   # 24 sim-h
    assert purge_before == "2024-07-01T12:00:00"     # 168 sim-h
    assert retention.cutoffs(None) == (None, None)


def test_run_pass_drains_until_a_short_batch_and_respects_the_budget():
    retention = _retention()
    calls = {"full": 0, "short": 0}

    async def always_full():
        calls["full"] += 1
        return 10

    async def short_after_two():
        calls["short"] += 1
        return 10 if calls["short"] < 3 else 4

    totals = asyncio.run(retention.run_pass(
        [always_full, short_after_two], batch=10, max_batches=5, pause_s=0))
    assert calls == {"full": 5, "short": 3}
    assert totals == {"always_full": 50, "short_after_two": 24}


def test_run_pass_isolates_a_failing_task():
    retention = _retention()

    async def boom():
        raise RuntimeError("deadlock")

    async def fine():
        return 1

    totals = asyncio.run(retention.run_pass([boom, fine], batch=10, pause_s=0))
    assert totals == {"boom": 0, "fine": 1}


def test_prune_inbox_uses_wall_clock_marker_age():
    retention = _retention()
    driver = _Driver(lambda q, p: [{"n": 7}])
    assert asyncio.run(retention.prune_inbox(lambda: driver, "CostInbox", retention_h=168)) == 7
    query, params = driver.txs[0].queries[0]
    assert "i.seen_at < timestamp() - $age_ms" in query and "DETACH DELETE i" in query
    assert params["age_ms"] == 168 * 3_600_000


def test_mark_inbox_stamps_seen_at():
    import_service_module("flight", "application.commands")
    outbox = importlib.import_module("_common.outbox")
    tx = _Tx(lambda q, p: [])
    asyncio.run(outbox.mark_inbox(tx, "FlightInbox", "evt-1", "2024-07-08T12:00:00"))
    assert "i.seen_at = coalesce(i.seen_at, timestamp())" in tx.queries[0][0]


# ── baggage owner ─────────────────────────────────────────────────

def _baggage_retention(monkeypatch, driver):
    import_service_module("baggage", "application.commands")
    _metrics_stub(monkeypatch)
    module = importlib.import_module("services.retention")
    monkeypatch.setattr(module, "get_driver", lambda: driver)
    return module


def _revision_or(rows):
    def respond(query, params):
        if "BaggageOutboxSeq" in query or "PassengerRuntime" in query:
            return [{"revision": 42}]
        return rows(query, params)
    return respond


def test_collected_bags_are_archived_with_their_scan_trail_and_an_event(monkeypatch):
    driver = _Driver(_revision_or(lambda q, p: [{"id": "b1"}, {"id": "b2"}]
                                  if "status = 'collected'" in q else []))
    module = _baggage_retention(monkeypatch, driver)
    assert asyncio.run(module.archive_collected("2024-07-07T12:00:00", NOW, 1000)) == 2
    tx = driver.txs[0]
    archive = next(q for q, _ in tx.queries if "SET b:BaggageArchive" in q)
    assert "REMOVE b:Baggage:UnscannedBaggage:ReviewBaggage" in archive
    assert "REMOVE s:ScanEvent SET s:ScanEventArchive" in archive
    [fact] = _staged(tx)
    assert fact["event_type"] == "EntitiesArchived"
    assert fact["payload"] == {"entity": "Baggage", "ids": ["b1", "b2"], "count": 2,
                               "archive_before": "2024-07-07T12:00:00"}


def test_hold_sweep_archives_only_departure_bags_and_walks_a_keyset_cursor(monkeypatch):
    pages = [
        [{"id": "a1", "at": "2024-06-29T10:00:00", "departed": False},   # stuck arrival (RC8)
         {"id": "d1", "at": "2024-06-29T10:00:00", "departed": True}],
        [{"id": "d2", "at": "2024-06-30T09:00:00", "departed": True}],
    ]
    seen_cursors = []

    def rows(query, params):
        if "b.status = 'in_hold'" in query:
            seen_cursors.append((params["ts"], params["id"]))
            return pages.pop(0)
        return []

    driver = _Driver(_revision_or(rows))
    module = _baggage_retention(monkeypatch, driver)
    sweep = module.HoldSweep()
    assert asyncio.run(sweep.step("2024-07-07T12:00:00", NOW, 2)) == 2   # full page
    assert (sweep.ts, sweep.id) == ("2024-06-29T10:00:00", "d1")
    assert asyncio.run(sweep.step("2024-07-07T12:00:00", NOW, 2)) == 1   # short ⇒ pass done
    assert (sweep.ts, sweep.id) == ("", "")
    assert seen_cursors == [("", ""), ("2024-06-29T10:00:00", "d1")]
    archived = [p["ids"] for tx in driver.txs for q, p in tx.queries if "SET b:BaggageArchive" in q]
    assert archived == [["d1"], ["d2"]]                 # a1 stays live


def test_purge_deletes_archived_bags_and_reports_the_count(monkeypatch):
    driver = _Driver(_revision_or(lambda q, p: [{"n": 3}] if "BaggageArchive" in q else []))
    module = _baggage_retention(monkeypatch, driver)
    assert asyncio.run(module.purge_archived("2024-07-01T12:00:00", NOW, 1000)) == 3
    [fact] = _staged(driver.txs[0])
    assert fact["event_type"] == "EntitiesPurged"
    assert fact["payload"]["count"] == 3


def test_baggage_tasks_are_inert_before_the_first_clock_tick(monkeypatch):
    driver = _Driver(lambda q, p: [{"n": 0}])
    module = _baggage_retention(monkeypatch, driver)
    archive, hold, purge, _ = module.tasks(lambda: None, batch=10)
    for task in (archive, hold, purge):
        assert asyncio.run(task()) == 0
    assert driver.txs == []


# ── passenger owner ───────────────────────────────────────────────

def test_departed_passengers_are_archived_with_an_event(monkeypatch):
    import_service_module("passenger", "application.commands")
    _metrics_stub(monkeypatch)
    module = importlib.import_module("services.retention")
    driver = _Driver(_revision_or(lambda q, p: [{"id": "p1"}] if "SET p:PassengerArchive" in q else []))
    monkeypatch.setattr(module, "get_driver", lambda: driver)
    assert asyncio.run(module.archive_departed("2024-07-07T12:00:00", NOW, 1000)) == 1
    query, params = driver.txs[0].queries[0]
    assert "p.departed_airport_at < $before" in query and "REMOVE p:Passenger" in query
    assert params["at"] == NOW.isoformat()
    [fact] = _staged(driver.txs[0])
    assert fact["payload"]["entity"] == "Passenger" and fact["payload"]["ids"] == ["p1"]


# ── consumers ─────────────────────────────────────────────────────

def test_analysis_drops_archived_and_collected_bags_from_targets():
    state_mod = import_service_module("analysis", "services.state")
    state = state_mod.OperationalState()
    state.baggage_targets = {"b1": {"status": "in_hold"}, "b2": {"status": "loaded"},
                             "b3": {"status": "on_carousel"}}
    state.on_entities_archived({"entity": "Passenger", "ids": ["b2"]})
    assert "b2" in state.baggage_targets
    state.on_entities_archived({"entity": "Baggage", "ids": ["b1", "missing"]})
    state.on_baggage_status_batch_changed({"status_changes": [
        {"id": "b3", "status": "collected", "zone": "carousel-1"}]})
    assert state.baggage_targets == {"b2": {"status": "loaded"}}

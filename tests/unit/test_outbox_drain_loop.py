"""RC3: the shared outbox drain loop (batching, combined delete+read, wake-up)."""
import asyncio
import json

from tests.conftest import import_service_module

import_service_module("flight", "application.commands")
from _common import outbox  # noqa: E402


class _Result:
    def __init__(self, rows):
        self._rows = rows

    async def data(self):
        return self._rows

    async def consume(self):
        return None


class _Driver:
    """In-memory outbox that understands the drain loop's single query."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.queries: list[dict] = []

    def add(self, event_id, revision, position):
        self.rows[event_id] = {
            "id": event_id, "document": json.dumps({"event_id": event_id}),
            "revision": revision, "position": position,
        }

    def session(self):
        driver = self

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def run(self, query, **params):
                assert "DELETE d" in query and "ORDER BY e.revision, e.position" in query
                driver.queries.append(params)
                for event_id in params["acked"]:
                    driver.rows.pop(event_id, None)
                ordered = sorted(driver.rows.values(), key=lambda r: (r["revision"], r["position"]))
                return _Result([{"id": r["id"], "document": r["document"]}
                                for r in ordered[:params["batch"]]])

        return _Session()


async def _run_until(driver, stop, published, *, poll_interval_s=30.0, batch=1000, fail=None):
    def publish_batch(documents):
        if fail and fail():
            raise RuntimeError("broker down")
        published.append([d["event_id"] for d in documents])

    return asyncio.create_task(outbox.run(
        "TestOutbox", lambda: driver, lambda doc: None, stop,
        poll_interval_s=poll_interval_s, publish_batch_confirmed=publish_batch, batch=batch,
    ))


def test_drains_in_order_and_deletes_acked_rows_in_the_next_read():
    async def scenario():
        driver, stop, published = _Driver(), asyncio.Event(), []
        for i in range(5):
            driver.add(f"e{i}", revision=1 if i < 3 else 2, position=i)
        task = await _run_until(driver, stop, published, batch=2)
        for _ in range(50):
            await asyncio.sleep(0.01)
            if not driver.rows:
                break
        stop.set()
        await task
        return driver, published

    driver, published = asyncio.run(scenario())
    assert published == [["e0", "e1"], ["e2", "e3"], ["e4"]]
    assert driver.rows == {}
    # Acked ids ride along with the next read: no separate delete round trip.
    assert driver.queries[1]["acked"] == ["e0", "e1"]
    assert driver.queries[2]["acked"] == ["e2", "e3"]


def test_unacked_batch_is_retained_and_redelivered_with_same_ids():
    async def scenario():
        driver, stop, published = _Driver(), asyncio.Event(), []
        driver.add("a", 1, 0)
        driver.add("b", 1, 1)
        attempts = {"n": 0}

        def fail():
            attempts["n"] += 1
            return attempts["n"] == 1

        task = await _run_until(driver, stop, published, poll_interval_s=0.01, fail=fail)
        for _ in range(100):
            await asyncio.sleep(0.01)
            if not driver.rows:
                break
        stop.set()
        await task
        return driver, published

    driver, published = asyncio.run(scenario())
    assert published == [["a", "b"]]
    assert driver.rows == {}


def test_notify_wakes_an_idle_loop_without_waiting_for_the_poll_interval():
    async def scenario():
        driver, stop, published = _Driver(), asyncio.Event(), []
        task = await _run_until(driver, stop, published, poll_interval_s=30.0)
        await asyncio.sleep(0.05)  # idle: first read found nothing
        driver.add("late", 1, 0)
        outbox.notify("TestOutbox")
        for _ in range(50):
            await asyncio.sleep(0.01)
            if published:
                break
        stop.set()
        await task
        return published

    assert asyncio.run(scenario()) == [["late"]]


def test_notify_before_commit_is_caught_by_the_settle_window():
    async def scenario():
        driver, stop, published = _Driver(), asyncio.Event(), []
        task = await _run_until(driver, stop, published, poll_interval_s=30.0)
        await asyncio.sleep(0.05)
        outbox.notify("TestOutbox")       # writer notifies, then commits a bit later
        await asyncio.sleep(0.08)
        driver.add("committed", 1, 0)
        for _ in range(50):
            await asyncio.sleep(0.01)
            if published:
                break
        stop.set()
        await task
        return published

    assert asyncio.run(scenario()) == [["committed"]]


def test_stop_flushes_the_last_acked_delete():
    async def scenario():
        driver, stop, published = _Driver(), asyncio.Event(), []
        driver.add("only", 1, 0)

        def publish_then_stop(documents):
            published.append([d["event_id"] for d in documents])
            stop.set()

        await outbox.run("TestOutbox", lambda: driver, lambda doc: None, stop,
                         publish_batch_confirmed=publish_then_stop)
        return driver, published

    driver, published = asyncio.run(scenario())
    assert published == [["only"]]
    assert driver.rows == {}


def test_default_batch_is_large_enough_for_one_baggage_tick():
    assert outbox.DEFAULT_BATCH >= 700


def test_notify_outside_an_event_loop_is_a_no_op():
    outbox.notify("TestOutbox")


def test_analysis_follows_pipeline_hops_from_the_baggage_batch():
    state_mod = import_service_module("analysis", "services.state")
    state = state_mod.OperationalState()
    state.baggage_targets["b1"] = {"flight_id": "F1", "zone": "induction-A", "status": "inducted"}
    state.on_baggage_status_batch_changed({"status_changes": [
        {"id": "b1", "status": "screening", "zone": "screening-A1", "previous_status": "inducted"},
        {"id": "b2", "status": "inducted", "zone": "induction-B", "flight_id": "F2"},
    ]})
    assert state.baggage_targets["b1"] == {"flight_id": "F1", "zone": "screening-A1", "status": "screening"}
    assert state.baggage_targets["b2"] == {"flight_id": "F2", "zone": "induction-B", "status": "inducted"}


def test_cost_service_no_longer_subscribes_to_baggage_or_passenger_streams():
    consumer = import_service_module("cost", "kafka.consumer")
    assert "baggage.events" not in consumer.TOPICS
    assert "passengers.events" not in consumer.TOPICS

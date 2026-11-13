"""Container-free regressions for private tick state, retry and durable replay."""
import asyncio
from collections import deque
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from tests.conftest import import_service_module

# Ensure the shared library is importable without binding to a domain consumer.
import_service_module("flight", "application.commands")
from _common.checkpoint import SnapshotCodec  # noqa: E402
from _common.transaction_scope import current, run_tick  # noqa: E402

NOW = datetime(2100, 1, 1, 12)
CODEC = SnapshotCodec((), ("queue", "counter", "last_tick_sim_time"))


class Result:
    def __init__(self, row=None):
        self.row = row

    async def single(self):
        return self.row

    async def consume(self):
        pass


class Driver:
    def __init__(self):
        self.data = {"last_tick": None, "document": None, "revision": 0, "facts": []}
        self.fail = False

    def session(self):
        driver = self
        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def run(self, query, **params):
                assert "MERGE (s:TestRuntime" in query
                return Result()

            async def execute_write(self, callback):
                candidate = deepcopy(driver.data)
                result = await callback(Tx(driver, candidate))
                driver.data = candidate
                return result
        return Session()


class Tx:
    def __init__(self, driver, data):
        self.driver, self.data = driver, data

    async def run(self, query, **params):
        if "RETURN s.last_tick_sim_time" in query:
            return Result(dict(self.data))
        if "s.document = $document" in query:
            self.data.update(last_tick=params["ts"], document=params["document"])
            self.data["revision"] += 1
            return Result({"revision": self.data["revision"]})
        if "CREATE (e:TestOutbox" in query:
            self.data["facts"].extend(params["rows"])
            if self.driver.fail:
                raise RuntimeError("after writes, before commit")
            return Result()
        raise AssertionError(query)


def state():
    return SimpleNamespace(queue=deque(["p1"]), counter=0, last_tick_sim_time=None,
                           sim_time=None, ws_broadcast=None)


def test_failed_tick_discards_private_state_facts_and_post_commit_effects():
    driver, original, effects = Driver(), state(), []
    driver.fail = True
    async def advance(payload, clock):
        scope = current.get()
        scope.state.queue.popleft()
        scope.state.counter += 1
        scope.state.last_tick_sim_time = clock
        scope.state.sim_time = clock
        scope.facts.append({"id": "fact", "document": {"event_id": "fact"}})
        scope.effects.append(lambda: effects.append("committed"))
        assert list(original.queue) == ["p1"]  # API readers still see committed state
    before = deepcopy(driver.data)
    with pytest.raises(RuntimeError, match="before commit"):
        asyncio.run(run_tick("TestRuntime", "TestOutbox", original, CODEC,
                             lambda: driver, advance, {}, NOW))
    assert driver.data == before
    assert original.counter == 0 and list(original.queue) == ["p1"]
    assert effects == [] and current.get() is None
    driver.fail = False
    asyncio.run(run_tick("TestRuntime", "TestOutbox", original, CODEC,
                         lambda: driver, advance, {}, NOW))
    assert original.counter == 1 and not original.queue
    assert effects == ["committed"]
    committed = deepcopy(driver.data)
    # A fresh owner restores the winning checkpoint and does not re-run advance.
    restarted = state()
    asyncio.run(run_tick("TestRuntime", "TestOutbox", restarted, CODEC,
                         lambda: driver, advance, {}, NOW))
    assert restarted.counter == 1 and not restarted.queue
    assert driver.data == committed and effects == ["committed"]


def test_checkpoint_roundtrip_preserves_tuples_sets_queues_and_simulation_time():
    original = state()
    original.queue = deque([({("flight", "task"): {"one", "two"}}, NOW)])
    restored = state()
    CODEC.restore(restored, CODEC.dump(original))
    assert restored.queue == original.queue
    assert isinstance(restored.queue, deque)
    with pytest.raises(ValueError, match="version"):
        CODEC.restore(restored, '{"version": 2}')
    original.queue.append(object())
    with pytest.raises(TypeError, match="Unsupported"):
        CODEC.dump(original)


@pytest.mark.parametrize("broker_error", [None, "injected broker error"])
def test_broker_batch_requires_every_acknowledgement_and_preserves_enqueue_order(broker_error):
    from _common.kafka_runtime import publish_confirmed_batch
    documents = [{"event_id": "first"}, {"event_id": "second"}]
    class Producer:
        def __init__(self):
            self.sent = []
        def produce(self, **kwargs):
            self.sent.append(kwargs)
        def poll(self, timeout):
            for index, item in enumerate(self.sent):
                item["callback"](broker_error if index == 1 else None, None)
    producer = Producer()
    if broker_error:
        with pytest.raises(RuntimeError, match="acknowledgement"):
            publish_confirmed_batch(producer, documents, lambda doc: "test.events", lambda doc: doc["event_id"])
    else:
        publish_confirmed_batch(producer, documents, lambda doc: "test.events", lambda doc: doc["event_id"])
    assert [item["key"] for item in producer.sent] == [b"first", b"second"]

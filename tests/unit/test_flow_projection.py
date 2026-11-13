"""Historical-count reads stay responsive during refresh and source failure."""
import asyncio
from datetime import datetime
import sys
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

from tests.conftest import import_service_module


@pytest.fixture
def projection(monkeypatch):
    module = import_service_module("passenger", "services.flow_projection")
    consumer = ModuleType("kafka.consumer")
    consumer.get_sim_time = lambda: datetime(2100, 1, 1, 12)
    monkeypatch.setitem(sys.modules, "kafka.consumer", consumer)
    monkeypatch.setattr(module, "_counts", None)
    monkeypatch.setattr(module, "_failed", False)
    monkeypatch.setattr(module, "_lock", asyncio.Lock())
    return module


def test_cold_read_recovers_from_graph_then_warm_reads_avoid_recounts(projection, monkeypatch):
    query = AsyncMock(return_value={"airside": 12, "departed_airport": 10000000})
    monkeypatch.setattr(projection, "get_status_counts", query)
    async def exercise():
        for _ in range(10):
            counts, metadata = await projection.read()
            assert counts["airside"] == 12
            assert metadata["counts_observed_sim_time"] == "2100-01-01T12:00:00"
            assert not metadata["counts_stale"]
            counts.clear()  # callers cannot modify the published observation
    asyncio.run(exercise())
    query.assert_awaited_once()


def test_slow_refresh_never_blocks_readers_or_publishes_partial_counts(projection, monkeypatch):
    monkeypatch.setattr(projection, "get_status_counts", AsyncMock(return_value={"airside": 12}))
    async def exercise():
        await projection.refresh()
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow():
            entered.set()
            await release.wait()
            return {"airside": 13}
        monkeypatch.setattr(projection, "get_status_counts", slow)
        task = asyncio.create_task(projection.refresh())
        await entered.wait()
        counts, _ = await asyncio.wait_for(projection.read(), timeout=0.5)
        assert counts == {"airside": 12}
        release.set()
        await task
        assert (await projection.read())[0] == {"airside": 13}
    asyncio.run(exercise())


def test_failure_retains_observation_and_marks_stale_then_empty_success_replaces(projection, monkeypatch):
    query = AsyncMock(side_effect=[{"airside": 12}, RuntimeError("storage"), {}])
    monkeypatch.setattr(projection, "get_status_counts", query)
    async def exercise():
        await projection.refresh()
        with pytest.raises(RuntimeError, match="storage"):
            await projection.refresh()
        counts, metadata = await projection.read()
        assert counts == {"airside": 12} and metadata["counts_stale"]
        await projection.refresh()
        counts, metadata = await projection.read()
        assert counts == {} and not metadata["counts_stale"]
    asyncio.run(exercise())

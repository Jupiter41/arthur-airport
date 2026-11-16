"""Contained incidents still resolve; only measured queue recovery clears alerts."""
import asyncio
import importlib
import sys
from datetime import datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import import_service_module


def consumer(monkeypatch):
    import_service_module("incident", "services.lifecycle")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    return importlib.import_module("kafka.consumer")


def test_contained_incidents_remain_in_timed_query(monkeypatch):
    db = import_service_module("incident", "db.neo4j")
    result = AsyncMock()
    result.data.return_value = [{"i": {"id": "contained", "status": "contained", "ttr_remaining": 2}}]
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.run.return_value = result
    monkeypatch.setattr(db, "get_driver", lambda: SimpleNamespace(session=lambda: session))
    rows = asyncio.run(db.get_active_incidents_with_ttr())
    assert rows[0]["status"] == "contained"
    assert "['active', 'contained']" in session.run.call_args.args[0]


def test_contained_timer_reaches_existing_lifecycle_resolution(monkeypatch):
    lifecycle = import_service_module("incident", "services.lifecycle")
    monkeypatch.setattr(lifecycle, "get_active_incidents_with_ttr", AsyncMock(return_value=[{
        "id": "contained", "status": "contained", "ttr_remaining": 2,
    }]))
    monkeypatch.setattr(lifecycle, "update_ttr_remaining", AsyncMock())
    resolve = AsyncMock()
    monkeypatch.setattr(lifecycle, "resolve_incident", resolve)
    now = datetime(2024, 7, 6, 9)
    asyncio.run(lifecycle.tick_ttr(now, 3))
    resolve.assert_awaited_once_with("contained", now, note="Auto-resolved: TTR elapsed",
                                   resolution_reason="ttr_elapsed")


@pytest.mark.parametrize("patch,at,clears", [
    ({}, datetime(2024, 7, 6, 9), True),
    ({"frozen": True}, datetime(2024, 7, 6, 9), False),
    ({"wait_minutes": 20}, datetime(2024, 7, 6, 9), False),
    ({"wait_minutes": None}, datetime(2024, 7, 6, 9), False),
    ({"wait_minutes": float("nan")}, datetime(2024, 7, 6, 9), False),
    ({}, datetime(2024, 6, 19, 9), False),
])
def test_queue_clear_requires_newer_valid_non_frozen_owner_evidence(monkeypatch, patch, at, clears):
    module = consumer(monkeypatch)
    monkeypatch.setattr(module, "find_active_incident_by_type_and_location", AsyncMock(return_value={
        "id": "congestion", "started_at": "2024-07-06T08:00:00",
    }))
    resolve = AsyncMock()
    monkeypatch.setattr(module, "resolve_incident", resolve)
    asyncio.run(module._on_security_queue_updated({
        "terminal": "B", "wait_minutes": 0, "frozen": False, **patch,
    }, at))
    assert bool(resolve.await_count) == clears


def test_queue_recovery_compares_instants_across_offsets(monkeypatch):
    module = consumer(monkeypatch)
    monkeypatch.setattr(module, "find_active_incident_by_type_and_location", AsyncMock(return_value={
        "id": "congestion", "started_at": "2024-07-06T10:00:00+02:00",
    }))
    resolve = AsyncMock()
    monkeypatch.setattr(module, "resolve_incident", resolve)
    asyncio.run(module._on_security_queue_updated({"terminal": "A", "wait_minutes": 0, "frozen": False},
                                                  datetime(2024, 7, 6, 9)))
    resolve.assert_awaited_once()

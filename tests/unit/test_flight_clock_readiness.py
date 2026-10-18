"""A restart must never expand the current-day list to all seeded days."""

import asyncio
import importlib
import sys
from datetime import datetime
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from tests.conftest import import_service_module


def test_flight_list_requires_clock_and_filters_simulated_day(monkeypatch):
    import_service_module("flight", "application.commands")
    for name in list(sys.modules):
        if name == "models" or name.startswith("models."):
            monkeypatch.delitem(sys.modules, name)
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    router = importlib.import_module("routers.flights")
    query = AsyncMock(return_value=([{"id": "synthetic-flight"}], 420))
    monkeypatch.setattr(router, "get_all_flights", query)
    monkeypatch.setattr(router, "get_sim_time", lambda: None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(router.list_flights())
    assert error.value.status_code == 503
    query.assert_not_awaited()

    monkeypatch.setattr(router, "get_sim_time", lambda: datetime(2026, 1, 7, 12))
    result = asyncio.run(router.list_flights(limit=1))
    assert result["total"] == 420
    assert query.await_args.kwargs["sim_date_prefix"] == "2026-01-07"

"""Today's activity is scoped to the simulated day, despite retained history."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.conftest import import_service_module


def test_status_counts_only_passengers_of_current_day_flights(monkeypatch):
    module = import_service_module("sim", "routers.sim")
    session = AsyncMock()
    session.__aenter__.return_value = session
    flights, passengers = AsyncMock(), AsyncMock()
    flights.single.return_value = {"cnt": 420}
    passengers.single.return_value = {"cnt": 68000}
    session.run.side_effect = [flights, passengers]
    monkeypatch.setattr(module, "get_driver", lambda: SimpleNamespace(session=lambda: session))
    monkeypatch.setattr(module.clock, "get_sim_time", lambda: datetime(2024, 7, 6, 9))
    monkeypatch.setattr(module.clock, "get_state", lambda: {
        "running": True, "paused": False, "sim_time": "2024-07-06T09:00:00",
        "real_time": "unused", "speed_multiplier": 60, "day_number": 22, "tick_number": 30420,
    })
    result = asyncio.run(module.sim_status())
    assert result["flights_today"] == 420 and result["passengers_today"] == 68000
    query = session.run.call_args.args[0]
    assert "[:ON_FLIGHT]" in query and "count(DISTINCT p)" in query
    assert session.run.call_args.kwargs == {"prefix": "2024-07-06"}

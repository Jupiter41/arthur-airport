"""RC10 — owners report source health; the gateway only derives status from it."""

import asyncio
import importlib
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

from tests.conftest import import_service_module

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services"))

from _common.data_sources import SourceHealth  # noqa: E402


def test_health_block_labels_each_clock():
    health = SourceHealth()
    health.record_ingest(observation_at=datetime(2024, 7, 8, 9, 0), items=4)
    block = health.as_dict()
    assert block["last_observation_at"] == "2024-07-08T09:00:00"
    assert block["last_ingest_at"].endswith("Z") and block["items"] == 4
    assert (block["last_ingest_clock"], block["last_observation_clock"], block["last_error_clock"]) == \
        ("wall", "sim", "wall")
    health.record_error("x" * 1000)
    assert len(health.as_dict()["last_error"]) == 300 and health.as_dict()["last_error_at"]


def _metrics_stub(monkeypatch):
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)


def test_adsb_reports_disabled_when_adsb_enabled_is_false(monkeypatch):
    monkeypatch.setenv("ADSB_ENABLED", "false")
    adsb = import_service_module("flight", "services.adsb")
    cache = adsb.ADSBCache()
    monkeypatch.setattr(adsb, "get_adsb_cache", lambda: cache)
    info = adsb.adsb_source_info()
    assert info["source"] == "disabled"
    assert info["health"]["enabled"] is False and info["aircraft_count"] == 0


def test_adsb_records_ingest_and_poll_failures(monkeypatch):
    monkeypatch.setenv("ADSB_ENABLED", "true")
    adsb = import_service_module("flight", "services.adsb")
    cache = adsb.ADSBCache()
    cache._parse_adsb_lol({"ac": []})
    assert cache.health.last_ingest_at and cache.health.items == 0

    class Failing:
        async def get(self, *a, **k):
            raise RuntimeError("network down")
    cache._client = Failing()
    asyncio.run(cache.poll_once())
    assert "network down" in cache.health.last_error
    assert cache.health.last_error_at >= cache.health.last_ingest_at


def _weather_state(monkeypatch, source):
    import_service_module("weather", "services.parameters")
    _metrics_stub(monkeypatch)
    consumer = importlib.import_module("kafka.consumer")
    state = consumer.WeatherConsumerState()
    state.current_params = object()          # already initialised
    state.current_category = "VMC"
    state.weather_source = source
    state._historical = None
    state.last_fsm_hour = 8
    state.last_metar_total_min = 9 * 60      # skip the METAR branch
    monkeypatch.setattr(state, "_apply_transition", AsyncMock())
    return state


def test_weather_hourly_evaluation_is_the_observation(monkeypatch):
    state = _weather_state(monkeypatch, "simulated")
    asyncio.run(state.on_clock_tick({"step_minutes": 1}, datetime(2024, 7, 8, 9, 0)))
    assert state.health.last_observation_at == "2024-07-08T09:00:00"
    assert state.health.last_error is None


def test_weather_external_source_without_data_records_an_error(monkeypatch):
    state = _weather_state(monkeypatch, "historical")
    asyncio.run(state.on_clock_tick({"step_minutes": 1}, datetime(2024, 7, 8, 9, 0)))
    assert state.health.last_observation_at is None
    assert "historical: no observation" in state.health.last_error


def test_passenger_source_reports_the_owner_clock(monkeypatch):
    import_service_module("passenger", "application.commands")
    _metrics_stub(monkeypatch)
    consumer = importlib.import_module("kafka.consumer")
    state = consumer.PassengerConsumerState()
    state.last_tick_sim_time = datetime(2024, 7, 8, 9, 53)
    monkeypatch.setattr(consumer, "_state", state)
    info = consumer.get_passenger_source_info()
    assert info["health"]["last_observation_at"] == "2024-07-08T09:53:00"
    assert info["health"]["last_observation_clock"] == "sim"

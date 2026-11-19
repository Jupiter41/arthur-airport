"""RC13: saved preferences never stand in for owner configuration."""
import asyncio
from dataclasses import replace
import importlib
import sys
from types import SimpleNamespace

from tests.conftest import import_service_module


def test_initial_preferences_follow_authoritative_config_and_restore_stays_requested(monkeypatch):
    config = import_service_module("sim", "services.airport_config")
    runtime = config.load_airport_runtime_config()
    operations = runtime.operations.model_copy(deep=True)
    operations.security_lanes_open = {"A": 7, "B": 11, "C": 9}
    operations.baggage.sorting_matrix_hr = 6100
    operations.baggage.screening_units_per_terminal = 3
    monkeypatch.setattr(config, "load_airport_runtime_config", lambda: replace(runtime, operations=operations))
    settings = importlib.import_module("services.settings")
    response = settings.settings_response()
    assert [response[f"lanes_{t}"] for t in "abc"] == [7, 11, 9]
    assert response["sorting_capacity"] == 6100
    assert response["screening_units"] == 9
    # Legacy durable preferences are retained honestly, without claiming execution.
    settings.update_settings({"lanes_a": 4, "sorting_capacity": 1800, "wind_kt": 90})
    response = settings.settings_response()
    assert response["requested"]["lanes_a"] == 4
    assert response["application"]["lanes_a"] == "owner_command"
    assert response["application"]["sorting_capacity"] == "configuration_restart"
    assert response["application"]["wind_kt"] == "stored_only"
    assert response["application"]["daily_flights"] == "next_manifest"
    assert "effective" not in response
    snapshot = settings.get_settings()
    snapshot.hourly_weights[5] = 999
    assert settings.get_settings().hourly_weights.get(5) != 999


def test_baggage_configuration_observes_initialized_zones_not_settings(monkeypatch):
    conveyor_module = import_service_module("baggage", "services.conveyor")
    conveyor = conveyor_module.ConveyorSystem()
    conveyor.get_all_zones()["sorting-matrix"].throughput_per_hr = 6200
    monkeypatch.setitem(sys.modules, "kafka.consumer", SimpleNamespace(
        get_sim_time=lambda: None, get_conveyor=lambda: conveyor))
    route = importlib.import_module("routers.baggage")
    screening = importlib.import_module("services.screening")
    monkeypatch.setattr(screening, "FALSE_POSITIVE_RATE", 0.012)
    response = asyncio.run(route.baggage_configuration())
    assert response == {"sim_time": None, "values": {
        "sorting_capacity": 6200, "screening_units": 6, "dg_false_positive_rate": 0.012,
    }}

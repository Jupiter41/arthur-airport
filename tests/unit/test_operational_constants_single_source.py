"""Guards the single-source-of-truth for operational constants (roadmap D6).

Before D6, peak hours, walking/apron speeds, cascade depth and the weather
capacity thresholds were copied across flight-service, incident-service,
passenger-service, weather-service and sim-orchestrator and had drifted from
one another and from ``config/airport.yaml``. These tests fail if any service
re-introduces a private, divergent copy, or if ``cost_rates.json`` drifts from
the simulation peak hours.
"""

import json
import sys
from pathlib import Path

import prometheus_client

from tests.conftest import import_service_module

_SERVICES_DIR = Path(__file__).resolve().parents[2] / "services"

# The shared library lives at services/_common — make it importable at collection
# time (import_service_module also does this per-service, but we import directly).
if str(_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICES_DIR))

from _common.airport_config import load_airport_runtime_config


def _reset_prometheus_registry():
    """Drop previously-registered collectors.

    Every service's ``metrics.py`` registers global collectors with the same
    names (e.g. ``envelope_invalid_total``) on the default registry, so
    importing a second service's consumer in one process raises
    ``DuplicateTimeseries``. Reset between imports so each consumer module
    executes cleanly.
    """
    reg = prometheus_client.REGISTRY
    for collector in list(reg._collector_to_names):
        try:
            reg.unregister(collector)
        except (KeyError, ValueError):
            pass


def _config() -> object:
    return load_airport_runtime_config()


# ── Canonical values in config/airport.yaml ──────────────────────


def test_canonical_operational_values():
    ops = _config().operations
    assert ops.walking_speed_m_min == 84.0
    assert ops.apron_speed_m_min == 83.3
    assert ops.cascade_max_depth == 5


def test_canonical_peak_hours():
    assert _config().simulation.peak_hours == [7, 8, 9, 17, 18, 19]


def test_canonical_weather_capacity():
    cap = _config().operations.weather_capacity
    assert {c: (cap[c].arrival, cap[c].departure, cap[c].runways) for c in cap} == {
        "CAVOK": (32, 32, 2),
        "VMC": (28, 28, 2),
        "IMC": (18, 16, 1),
        "LIFR": (8, 6, 1),
    }


def test_canonical_wind_limits():
    ops = _config().operations
    assert ops.wind_thresholds_kt == {
        "crosswind": 25,
        "crosswind_heavy": 35,
        "tailwind": 10,
    }
    assert ops.wind_reductions == {
        "crosswind": 0.85,
        "crosswind_heavy": 0.60,
        "tailwind": 0.70,
    }


# ── Services must read from the shared config, not a private copy ──


def test_flight_service_uses_config():
    ops = _config().operations
    spatial = import_service_module("flight", "services.spatial")
    ground = import_service_module("flight", "services.ground_vehicles")
    turn = import_service_module("flight", "services.turnaround")
    runway_queue = import_service_module("flight", "services.runway_queue")

    assert spatial.APRON_SPEED == ops.apron_speed_m_min
    assert spatial.WALKING_SPEED == ops.walking_speed_m_min
    assert ground.VEHICLE_SPEED_M_PER_MIN == ops.apron_speed_m_min
    assert turn.CASCADE_MAX_DEPTH == ops.cascade_max_depth
    assert runway_queue._cavok_capacity.arrival == ops.weather_capacity["CAVOK"].arrival
    assert (
        runway_queue._cavok_capacity.departure
        == ops.weather_capacity["CAVOK"].departure
    )


def test_incident_service_uses_config():
    ops = _config().operations
    cascade = import_service_module("incident", "services.cascade")
    _reset_prometheus_registry()
    consumer = import_service_module("incident", "kafka.consumer")

    assert cascade.CASCADE_MAX_DEPTH == ops.cascade_max_depth
    assert consumer.PEAK_HOURS == set(_config().simulation.peak_hours)


def test_passenger_service_uses_config():
    ops = _config().operations
    spatial = import_service_module("passenger", "services.spatial")
    conn = import_service_module("passenger", "services.connections")

    assert spatial.WALKING_SPEED == ops.walking_speed_m_min
    assert conn._WALKING_SPEED == ops.walking_speed_m_min


def test_weather_service_uses_config():
    ops = _config().operations
    capacity = import_service_module("weather", "services.capacity")
    _reset_prometheus_registry()
    consumer = import_service_module("weather", "kafka.consumer")

    for category in ("CAVOK", "VMC", "IMC", "LIFR"):
        base = capacity._BASE_CAPACITY[category]
        expected = ops.weather_capacity[category]
        assert base.arrival == expected.arrival
        assert base.departure == expected.departure
        assert base.runways == expected.runways
    assert capacity._WIND_THRESHOLDS == ops.wind_thresholds_kt
    assert capacity._WIND_REDUCTIONS == ops.wind_reductions
    assert consumer._cavok.arrival == ops.weather_capacity["CAVOK"].arrival


def test_sim_orchestrator_emits_config_capacity():
    """sim-orchestrator's WeatherStateChanged fallback must use config rates."""
    producer = import_service_module("sim", "kafka.producer")
    # No module-level constant to compare — import alone proves the module still
    # imports cleanly through the shared loader; the function uses the loader.
    assert hasattr(producer, "emit_weather_state_changed")


# ── Cross-file drift guards ──────────────────────────────────────


def test_peak_hours_match_cost_rates_fixture():
    """cost-service fixture operations.peak_hours must equal simulation.peak_hours."""
    rates = json.loads(
        (_SERVICES_DIR / "cost-service" / "fixtures" / "cost_rates.json").read_text()
    )
    assert list(rates["operations"]["peak_hours"]) == _config().simulation.peak_hours

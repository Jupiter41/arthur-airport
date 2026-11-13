"""Threshold and analysis behavior for the independent host monitor."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import time

spec = importlib.util.spec_from_file_location("pi_monitor", Path(__file__).resolve().parents[2] / "scripts/raspberry_monitor.py")
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


def test_unknown_values_and_exact_thresholds():
    assert monitor.zone("temperature_c", None) == "unknown"
    assert monitor.zone("temperature_c", 70) == "warning"
    assert monitor.zone("temperature_c", 80) == "danger"
    assert monitor.zone("mem_available_mib", 450) == "danger"
    assert monitor.zone("mem_available_mib", 751) == "normal"


def test_current_and_historical_firmware_flags_are_distinct():
    base = {"ts": 1, "throttled_flags": 0x10000, "containers": [], "docker_available": True}
    past = monitor.analyse(base)
    assert past["zones"]["firmware"] == "normal"
    assert any("past" in advice for advice in past["recommendations"])
    current = monitor.analyse({**base, "throttled_flags": 0x10001})
    assert current["overall"] == "danger"


def test_unhealthy_containers_and_temperature_rise_trigger_analysis():
    sample = {"ts": 120, "temperature_c": 76, "throttled_flags": 0,
              "containers": [{"name": "fake-airport", "state": "running", "status": "Up (unhealthy)"}], "docker_available": True}
    result = monitor.analyse(sample, {"ts": 60, "temperature_c": 70})
    assert result["overall"] == "danger"
    assert any("6.0" in text for text in result["recommendations"])


def test_export_filters_history_and_does_not_expose_raw_counters(tmp_path):
    path = str(tmp_path / "metrics.sqlite3")
    now = int(time.time())
    with monitor.connect(path) as db:
        for age in (7200, 120, 60):
            sample = {"ts": now - age, "temperature_c": 42, "_cpu_total": 999, "containers": [], "analysis": {}}
            db.execute("INSERT INTO samples VALUES (?,?)", (now - age, json.dumps(sample)))
    result = monitor.export(path, 1)
    assert len(result["history"]) == 2
    assert "_cpu_total" not in result["latest"]
    assert result["summary"]["temperature_c"]["danger_samples"] == 0


def test_stopped_airport_is_danger_but_completed_initializer_is_expected():
    base = {"ts": 1, "throttled_flags": 0, "docker_available": True}
    init = {"name": "arthur-airport-pi-kafka-init-1", "state": "exited"}
    assert monitor.analyse({**base, "containers": [init]})["zones"]["containers"] == "normal"
    service = {"name": "arthur-airport-pi-flight-service-1", "state": "exited"}
    assert monitor.analyse({**base, "containers": [init, service]})["overall"] == "danger"
    service["state"] = "paused"
    assert monitor.analyse({**base, "containers": [service]})["overall"] == "warning"
    missing = monitor.analyse({**base, "docker_available": False, "containers": []})
    assert missing["zones"]["containers"] == "unknown"
    assert any("unavailable" in advice for advice in missing["recommendations"])

"""Unit tests for sim-orchestrator scenario definition CRUD semantics."""

import importlib
import os
import sys
import types
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SVC_DIR = ROOT / "services" / "sim-orchestrator"


def _load_engine_module(base_dir: Path, user_dir: Path):
    """Import scenario_engine in a clean sim-orchestrator module context."""
    for key in list(sys.modules):
        if key == "services" or key.startswith("services."):
            del sys.modules[key]
        if key == "kafka" or key.startswith("kafka."):
            del sys.modules[key]

    if str(SVC_DIR) not in sys.path:
        sys.path.insert(0, str(SVC_DIR))

    kafka_mod = types.ModuleType("kafka")
    producer_mod = types.ModuleType("kafka.producer")

    def _noop_emit_inject_incident(**_kwargs):
        return None

    producer_mod.emit_inject_incident = _noop_emit_inject_incident
    kafka_mod.producer = producer_mod
    sys.modules["kafka"] = kafka_mod
    sys.modules["kafka.producer"] = producer_mod

    os.environ["SCENARIOS_DIR"] = str(base_dir)
    os.environ["SCENARIOS_USER_DIR"] = str(user_dir)

    module = importlib.import_module("services.scenario_engine")
    return importlib.reload(module)


def _write_yaml(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=False)


@pytest.fixture
def engine_with_dirs(tmp_path):
    base_dir = tmp_path / "base"
    user_dir = tmp_path / "user"

    _write_yaml(
        base_dir / "base-scenario.yaml",
        {
            "name": "Base Scenario",
            "description": "Built-in baseline",
            "sim_speed": 600,
            "start_time": "2024-06-15T07:30:00",
            "duration_sim_minutes": 60,
            "events": [],
            "expected_outcomes": [],
        },
    )

    module = _load_engine_module(base_dir, user_dir)
    engine = module.ScenarioEngine()
    engine.load_definitions()
    return module, engine, base_dir, user_dir


def test_loads_base_with_metadata(engine_with_dirs):
    _module, engine, _base_dir, _user_dir = engine_with_dirs

    listed = engine.list_scenarios()
    assert len(listed) == 1
    assert listed[0]["name"] == "Base Scenario"
    assert listed[0]["is_base"] is True

    payload = engine.get_definition_payload("Base Scenario")
    assert payload is not None
    assert payload["is_base"] is True


def test_create_update_delete_custom(engine_with_dirs):
    module, engine, _base_dir, user_dir = engine_with_dirs

    created = engine.create_definition(
        module.ScenarioDefinition.model_validate(
            {
                "name": "Custom One",
                "description": "My custom scenario",
                "sim_speed": 60,
                "start_time": "2024-06-15T06:00:00",
                "duration_sim_minutes": 90,
                "events": [],
                "expected_outcomes": [],
            }
        )
    )
    assert created.name == "Custom One"
    assert engine.is_base("Custom One") is False

    listed = engine.list_scenarios()
    custom = next(item for item in listed if item["name"] == "Custom One")
    assert custom["is_base"] is False

    updated = engine.update_definition(
        "Custom One",
        module.ScenarioDefinition.model_validate(
            {
                "name": "Custom Renamed",
                "description": "Edited",
                "sim_speed": 600,
                "start_time": "2024-06-15T07:00:00",
                "duration_sim_minutes": 120,
                "events": [],
                "expected_outcomes": [],
            }
        ),
    )
    assert updated.name == "Custom Renamed"
    assert engine.get_definition("Custom One") is None
    assert engine.get_definition("Custom Renamed") is not None

    engine.delete_definition("Custom Renamed")
    assert engine.get_definition("Custom Renamed") is None
    assert list(user_dir.glob("*.yaml")) == []


def test_base_scenarios_are_immutable(engine_with_dirs):
    module, engine, _base_dir, _user_dir = engine_with_dirs

    with pytest.raises(PermissionError):
        engine.update_definition(
            "Base Scenario",
            module.ScenarioDefinition.model_validate(
                {
                    "name": "Base Scenario",
                    "description": "Mutated",
                    "sim_speed": 60,
                    "start_time": "2024-06-15T06:00:00",
                    "duration_sim_minutes": 30,
                    "events": [],
                    "expected_outcomes": [],
                }
            ),
        )

    with pytest.raises(PermissionError):
        engine.delete_definition("Base Scenario")


def test_fork_creates_custom_copy(engine_with_dirs):
    _module, engine, _base_dir, _user_dir = engine_with_dirs

    forked = engine.fork_definition("Base Scenario", "Forked Scenario")
    assert forked.name == "Forked Scenario"
    assert engine.is_base("Forked Scenario") is False

    original = engine.get_definition("Base Scenario")
    copied = engine.get_definition("Forked Scenario")
    assert original is not None and copied is not None
    assert copied.description == original.description

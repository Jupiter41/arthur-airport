"""Clock restart and operator-state durability without external infrastructure."""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


def load_runtime(state=None, failure=False):
    record = {"state": state} if state else None
    session = AsyncMock()
    session.__aenter__.return_value = session
    result = AsyncMock()
    result.single.return_value = record
    result.data.return_value = []
    session.run.return_value = result
    if failure:
        session.run.side_effect = RuntimeError("database unavailable")
    now = datetime(2024, 6, 16, 12, tzinfo=timezone.utc)
    clock = SimpleNamespace(get_state=lambda: {
        "sim_time": now.isoformat(), "day_number": 2, "tick_number": 42,
        "speed_multiplier": 10, "paused": True,
    }, get_sim_time=lambda: now, pause=Mock(), resume=Mock(), restore_state=Mock(),
        SIM_START_TIME=datetime(2024, 6, 15, 6), get_speed=lambda: 60)
    settings = SimpleNamespace(model_dump=lambda: {"daily_flights": 50})
    producer = ModuleType("kafka.producer"); producer.produce_event = Mock()
    db = ModuleType("db.neo4j"); db.get_driver = lambda: SimpleNamespace(session=lambda: session)
    services = ModuleType("services"); services.clock = clock
    settings_module = ModuleType("services.settings")
    settings_module.get_settings = lambda: settings
    settings_module.update_settings = Mock()
    spec = importlib.util.spec_from_file_location("runtime_checkpoint_under_test",
        Path(__file__).resolve().parents[2] / "services/sim-orchestrator/services/runtime_state.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", {"services": services, "services.settings": settings_module,
                                    "db.neo4j": db, "kafka.producer": producer}):
        spec.loader.exec_module(module)
    return module, clock, producer, session, settings_module


def test_checkpoint_writes_graph_before_publishing_control_event():
    module, clock, producer, session, _ = load_runtime()
    asyncio.run(module.checkpoint(command="pause"))
    args = session.run.call_args.kwargs
    assert args["sim_time"] == clock.get_sim_time().isoformat()
    assert args["tick"] == 42 and args["paused"] is True
    assert producer.produce_event.call_args.kwargs["event_type"] == "SimControlChanged"


def test_restore_recovers_clock_pause_and_operator_settings():
    module, clock, _, _, settings = load_runtime({
        "sim_time": "2024-06-16T12:00:00+00:00", "day_number": 2,
        "tick_number": 42, "speed_multiplier": 10, "paused": True,
        "settings_json": '{"daily_flights":75}',
    })
    assert asyncio.run(module.restore()) is True
    clock.restore_state.assert_called_once_with(datetime(2024, 6, 16, 12, tzinfo=timezone.utc), 2, 42, 10)
    clock.pause.assert_called_once()
    settings.update_settings.assert_called_once_with({"daily_flights": 75})


def test_database_failure_pauses_and_does_not_acknowledge_command_event():
    module, clock, producer, _, _ = load_runtime(failure=True)
    try:
        asyncio.run(module.checkpoint(command="settings"))
        assert False, "database failure must reach the caller"
    except RuntimeError:
        pass
    clock.pause.assert_called_once()
    producer.produce_event.assert_not_called()


def test_fresh_airport_without_recorded_progress_still_initializes_normally():
    module, clock, producer, _, _ = load_runtime()
    assert asyncio.run(module.restore()) is False
    clock.restore_state.assert_not_called()
    producer.produce_event.assert_not_called()


def test_legacy_clock_uses_recorded_progress_and_normalizes_utc():
    module, _, _, _, _ = load_runtime()
    values = [{"at": "2024-07-06T11:00:00+02:00"}, {"at": "2024-06-19T08:20:00"},
              {"at": None}, {"at": "invalid"}]
    assert module.legacy_clock_bound(values, datetime(2024, 6, 15, 6)) == datetime(2024, 7, 6, 9)
    assert module.legacy_clock_bound([{"at": "2024-06-01T00:00:00"}], datetime(2024, 6, 15, 6)) is None


def test_legacy_recovery_persists_clock_and_emits_recovery_without_resetting_weather():
    module, clock, producer, session, _ = load_runtime()
    session.run.return_value.data.return_value = [{"at": "2024-07-06T09:00:00"}]
    assert asyncio.run(module.restore()) is True
    clock.restore_state.assert_called_once_with(datetime(2024, 7, 6, 9), 22, 30420, 60)
    clock.pause.assert_called_once()
    assert "scheduled_time" not in session.run.call_args_list[1].args[0]
    assert producer.produce_event.call_args.kwargs["payload"]["command"] == "legacy_clock_recovered"
    assert "MERGE (s:SimState" in session.run.call_args.args[0]


def test_legacy_recovery_derives_elapsed_time_from_utc_start():
    module, clock, _, session, _ = load_runtime()
    clock.SIM_START_TIME = datetime(2024, 6, 15, 8, tzinfo=timezone(timedelta(hours=2)))
    session.run.return_value.data.return_value = [{"at": "2024-06-16T06:00:00Z"}]
    assert asyncio.run(module.restore()) is True
    assert clock.restore_state.call_args.args[:3] == (datetime(2024, 6, 16, 6), 2, 1440)

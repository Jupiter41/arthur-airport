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


def test_transient_checkpoint_failure_is_retried_without_pausing():
    from neo4j.exceptions import TransientError
    module, clock, producer, session, _ = load_runtime()
    module.CHECKPOINT_RETRY_DELAYS_S = (0, 0, 0, 0)
    ok = session.run.return_value
    session.run.side_effect = [TransientError("memory pool"), TransientError("lock"), ok]
    asyncio.run(module.checkpoint(command="tick"))
    assert session.run.call_count == 3
    clock.pause.assert_not_called()
    producer.produce_event.assert_called_once()


def test_persistent_transient_failure_still_pauses_after_retries():
    from neo4j.exceptions import TransientError
    module, clock, producer, session, _ = load_runtime()
    module.CHECKPOINT_RETRY_DELAYS_S = (0, 0)
    session.run.side_effect = TransientError("memory pool")
    try:
        asyncio.run(module.checkpoint())
        assert False, "exhausted retries must reach the caller"
    except TransientError:
        pass
    assert session.run.call_count == 3
    clock.pause.assert_called_once()


def load_clock(emitted):
    producer = ModuleType("kafka.producer")
    producer.emit_clock_tick = lambda **kw: emitted.append(("tick", kw["sim_time"]))
    metrics = ModuleType("metrics")
    for name in ("sim_tick_total", "sim_tick_latency_ms", "sim_speed_multiplier",
                 "sim_day_number", "sim_paused"):
        setattr(metrics, name, Mock())
    spec = importlib.util.spec_from_file_location("clock_under_test",
        Path(__file__).resolve().parents[2] / "services/sim-orchestrator/services/clock.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", {"kafka.producer": producer, "metrics": metrics}):
        spec.loader.exec_module(module)
    return module


def test_day_seeding_runs_in_background_with_a_midnight_barrier():
    """Seeding must not stall 23:30-23:59 ticks, yet must finish before day 2 starts."""
    emitted: list = []
    clock = load_clock(emitted)
    clock.restore_state(datetime(2024, 6, 15, 23, 28), 1, 0, 600_000)  # ~0 s per tick
    seeding = asyncio.Event()

    async def scenario():
        async def slow_seed():
            await seeding.wait()
            emitted.append(("seeded", None))

        task_holder = {}
        async def on_day(next_day, sim_time):
            task_holder["task"] = asyncio.create_task(slow_seed())

        async def on_day_start(new_day, sim_time):
            emitted.append(("day_start", sim_time))
            await task_holder["task"]

        async def on_tick(sim_time):
            if sim_time == datetime(2024, 6, 15, 23, 50):
                # Ticks kept flowing after 23:30 while seeding was still running.
                assert ("seeded", None) not in emitted
                seeding.set()
            if sim_time >= datetime(2024, 6, 16, 0, 1):
                clock.stop()

        clock.configure_callbacks(on_day=on_day, on_tick=on_tick, on_day_start=on_day_start)
        clock.MAX_TICKS_PER_SEC = 10_000
        await asyncio.wait_for(clock.run_clock_loop(), timeout=10)

    asyncio.run(scenario())
    ticks = [t for kind, t in emitted if kind == "tick"]
    assert datetime(2024, 6, 15, 23, 40) in ticks           # not blocked by seeding
    seeded = emitted.index(("seeded", None))
    midnight = emitted.index(("tick", datetime(2024, 6, 16, 0, 0)))
    assert seeded < midnight                                 # barrier before day 2
    assert clock.get_sim_day() == 2

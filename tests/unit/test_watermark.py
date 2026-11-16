"""RC4: tick watermark and clock back-pressure."""
import importlib.util
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "watermark_under_test", ROOT / "services/sim-orchestrator/services/watermark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Wall:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


T = datetime(2024, 7, 8, 12, 0)


def test_slowest_live_owner_holds_the_clock():
    wm = _module()
    wall = _Wall()
    tracker = wm.WatermarkTracker(max_lag_min=5, stale_s=30, clock=wall)
    tracker.observe("flight-service", datetime(2024, 7, 8, 11, 59))
    tracker.observe("passenger-service", datetime(2024, 7, 8, 11, 54))
    assert tracker.blocking(datetime(2024, 7, 8, 12, 0)) == ["passenger-service"]  # 6 min behind
    tracker.observe("passenger-service", datetime(2024, 7, 8, 11, 56))
    assert tracker.blocking(datetime(2024, 7, 8, 12, 0)) == []


def test_a_silent_owner_stops_holding_and_is_reported_stale():
    wm = _module()
    wall = _Wall()
    tracker = wm.WatermarkTracker(max_lag_min=5, stale_s=30, clock=wall)
    tracker.observe("baggage-service", datetime(2024, 7, 8, 11, 0))
    assert tracker.blocking(T) == ["baggage-service"]
    wall.t += 31
    assert tracker.blocking(T) == []
    assert tracker.status(T)["baggage-service"] == {
        "sim_time": "2024-07-08T11:00:00", "lag_minutes": 60.0, "stale": True}


def test_allowed_lag_scales_with_the_clock_step():
    wm = _module()
    tracker = wm.WatermarkTracker(max_lag_min=5, stale_s=30, clock=_Wall())
    tracker.observe("flight-service", datetime(2024, 7, 8, 11, 49))
    assert tracker.blocking(T, step_minutes=1) == ["flight-service"]
    assert tracker.blocking(T, step_minutes=6) == []   # 11 min allowed at a 6-min step


def test_handle_accepts_only_tick_processed_and_reset_clears():
    wm = _module()
    tracker = wm.WatermarkTracker(clock=_Wall())
    assert wm.handle({"event_type": "TickProcessed",
                      "payload": {"owner": "flight-service", "sim_time": "2024-07-08T12:00:00"}}, tracker)
    assert not wm.handle({"event_type": "SimClockTick", "payload": {}}, tracker)
    assert not wm.handle({"event_type": "TickProcessed", "payload": {"owner": "x"}}, tracker)
    assert set(tracker.marks) == {"flight-service"}
    tracker.reset()
    assert tracker.marks == {}


def test_owners_publish_a_watermark_after_their_tick():
    for svc in ("flight", "passenger", "baggage"):
        consumer = (ROOT / f"services/{svc}-service/kafka/consumer.py").read_text()
        assert "emit_tick_processed(" in consumer, svc
    runtime = (ROOT / "services/_common/kafka_runtime.py").read_text()
    assert 'WATERMARK_TOPIC = "sim.watermark"' in runtime
    compose = (ROOT / "docker-compose.yml").read_text()
    assert '"sim.watermark:1:1"' in compose

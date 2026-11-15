"""Unit tests for flight-service runway queue — pure logic, no I/O."""

from datetime import datetime, timedelta


from tests.conftest import import_service_module

_rq = import_service_module("flight", "services.runway_queue")
RunwayQueue = _rq.RunwayQueue
separation_seconds = _rq.separation_seconds


BASE_TIME = datetime(2025, 6, 15, 10, 0, 0)


class TestRunwayQueueBasic:
    def test_initial_state(self):
        rq = RunwayQueue()
        assert rq.arrivals_queued == 0
        assert rq.departures_queued == 0
        assert rq.weather_category == "CAVOK"
        assert rq.ils_required is False

    def test_enqueue_arrival(self):
        rq = RunwayQueue()
        rq.enqueue_arrival("flt-1", BASE_TIME.isoformat())
        assert rq.arrivals_queued == 1

    def test_enqueue_departure(self):
        rq = RunwayQueue()
        rq.enqueue_departure("flt-1", BASE_TIME.isoformat())
        assert rq.departures_queued == 1

    def test_no_duplicate_enqueue(self):
        rq = RunwayQueue()
        rq.enqueue_arrival("flt-1", BASE_TIME.isoformat())
        rq.enqueue_arrival("flt-1", BASE_TIME.isoformat())
        assert rq.arrivals_queued == 1

    def test_remove(self):
        rq = RunwayQueue()
        rq.enqueue_arrival("flt-1", BASE_TIME.isoformat())
        rq.remove("flt-1")
        # Lazy removal: item still in heap but marked removed
        # assign_slots will skip it


class TestRunwayCapacity:
    def test_update_capacity(self):
        rq = RunwayQueue()
        rq.update_capacity(18, 16, "IMC")
        assert rq.arrival_rate == 18
        assert rq.departure_rate == 16
        assert rq.weather_category == "IMC"
        assert rq.ils_required is True

    def test_cavok_full_capacity(self):
        rq = RunwayQueue()
        assert rq.capacity_per_hour == 64  # 32 + 32


class TestAssignSlots:
    def test_assigns_arrivals(self):
        rq = RunwayQueue()
        for i in range(5):
            rq.enqueue_arrival(f"arr-{i}", (BASE_TIME + timedelta(minutes=i)).isoformat())
        assigned = rq.assign_slots(BASE_TIME)
        assert len(assigned) > 0
        assert all(a["operation"] == "landing" for a in assigned)

    def test_assigns_departures(self):
        rq = RunwayQueue()
        for i in range(5):
            rq.enqueue_departure(f"dep-{i}", (BASE_TIME + timedelta(minutes=i)).isoformat())
        assigned = rq.assign_slots(BASE_TIME)
        assert len(assigned) > 0
        assert all(a["operation"] == "takeoff" for a in assigned)

    def test_mixed_arrivals_and_departures(self):
        rq = RunwayQueue()
        rq.enqueue_arrival("arr-1", BASE_TIME.isoformat())
        rq.enqueue_departure("dep-1", BASE_TIME.isoformat())
        assigned = rq.assign_slots(BASE_TIME)
        ops = {a["operation"] for a in assigned}
        assert "landing" in ops
        assert "takeoff" in ops

    def test_emergency_priority(self):
        rq = RunwayQueue()
        # Normal first, emergency second
        rq.enqueue_arrival("normal", (BASE_TIME + timedelta(minutes=1)).isoformat())
        rq.enqueue_arrival("emergency", (BASE_TIME + timedelta(minutes=5)).isoformat(), is_emergency=True)
        assigned = rq.assign_slots(BASE_TIME)
        # Emergency should be assigned first
        if len(assigned) >= 2:
            assert assigned[0]["flight_id"] == "emergency"

    def test_removed_flight_skipped(self):
        rq = RunwayQueue()
        rq.enqueue_arrival("flt-1", BASE_TIME.isoformat())
        rq.enqueue_arrival("flt-2", (BASE_TIME + timedelta(minutes=1)).isoformat())
        rq.remove("flt-1")
        assigned = rq.assign_slots(BASE_TIME)
        flight_ids = [a["flight_id"] for a in assigned]
        assert "flt-1" not in flight_ids

    def test_current_rate_tracks_assignments(self):
        rq = RunwayQueue()
        for i in range(3):
            rq.enqueue_arrival(f"flt-{i}", BASE_TIME.isoformat())
        rq.assign_slots(BASE_TIME)
        assert rq.current_rate > 0

    def test_imc_arrivals_priority(self):
        """In IMC, arrival slots get bonus."""
        rq = RunwayQueue()
        rq.update_capacity(18, 16, "IMC")
        for i in range(10):
            rq.enqueue_arrival(f"arr-{i}", (BASE_TIME + timedelta(minutes=i)).isoformat())
        for i in range(10):
            rq.enqueue_departure(f"dep-{i}", (BASE_TIME + timedelta(minutes=i)).isoformat())
        assigned = rq.assign_slots(BASE_TIME)
        landings = sum(1 for a in assigned if a["operation"] == "landing")
        takeoffs = sum(1 for a in assigned if a["operation"] == "takeoff")
        # IMC should prioritize arrivals
        assert landings >= takeoffs


def test_snapshot_reports_owner_order_and_wake_separation_without_mutating():
    from datetime import datetime
    q = RunwayQueue()
    q.enqueue_arrival("late", "2026-01-01T12:10:00", aircraft_type="A320")
    q.enqueue_arrival("heavy", "2026-01-01T12:05:00", aircraft_type="B77W")
    q.enqueue_arrival("mayday", "2026-01-01T12:20:00", is_emergency=True, aircraft_type="A320")
    q.enqueue_departure("dep", "2026-01-01T12:00:00", aircraft_type="A320")
    q.remove("late")
    snap = q.snapshot(datetime(2026, 1, 1, 12, 0))
    assert [a["flight_id"] for a in snap["arrivals"]] == ["mayday", "heavy"]
    assert snap["arrivals"][0]["emergency"] is True
    assert snap["arrivals"][0]["wake_separation_seconds"] is None  # nothing landed yet
    assert snap["arrivals"][1]["weight_category"] == "HEAVY"
    assert snap["arrivals"][1]["wake_separation_seconds"] == separation_seconds("A320", "B77W")
    assert [d["flight_id"] for d in snap["departures"]] == ["dep"]
    assert snap["runway_occupied"] is False
    assert q.snapshot(datetime(2026, 1, 1, 12, 0)) == snap  # read-only

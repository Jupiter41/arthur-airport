"""Unit tests for turnaround task graph — GAP-2-8.

Covers:
  1. On-time narrow-body turnaround
  2. On-time wide-body turnaround
  3. Baggage delay propagation (extends baggage_offload)
  4. Fueling delay absorbed by slack
  5. Delay that exceeds slack and pushes departure
  6. Critical path computation
  7. Topological ordering
"""

from datetime import datetime, timedelta

from tests.conftest import import_service_module

_tp = import_service_module("flight", "services.turnaround_plan")

TurnaroundTask = _tp.TurnaroundTask
TurnaroundPlan = _tp.TurnaroundPlan
TaskStatus = _tp.TaskStatus
create_turnaround_plan = _tp.create_turnaround_plan
compute_critical_path = _tp.compute_critical_path
topological_order = _tp.topological_order
nominal_turnaround_minutes = _tp.nominal_turnaround_minutes
NARROW_BODY_TASKS = _tp.NARROW_BODY_TASKS
WIDE_BODY_TASKS = _tp.WIDE_BODY_TASKS

BASE_TIME = datetime(2025, 6, 15, 10, 0, 0)


class TestCriticalPath:
    """Test critical path computation on task DAGs."""

    def test_narrow_body_critical_path(self):
        """Narrow-body turnaround critical path should be 35 min."""
        cp = nominal_turnaround_minutes("A320")
        assert cp == 35

    def test_wide_body_critical_path(self):
        """Wide-body turnaround critical path should be 50 min."""
        cp = nominal_turnaround_minutes("B77W")
        assert cp == 50

    def test_single_task(self):
        tasks = [TurnaroundTask(name="only", starts_after=[], duration_min=10)]
        assert compute_critical_path(tasks) == 10

    def test_serial_chain(self):
        tasks = [
            TurnaroundTask(name="a", starts_after=[], duration_min=5),
            TurnaroundTask(name="b", starts_after=["a"], duration_min=10),
            TurnaroundTask(name="c", starts_after=["b"], duration_min=3),
        ]
        assert compute_critical_path(tasks) == 18

    def test_parallel_paths(self):
        tasks = [
            TurnaroundTask(name="a", starts_after=[], duration_min=5),
            TurnaroundTask(name="b", starts_after=[], duration_min=8),
            TurnaroundTask(name="c", starts_after=["a", "b"], duration_min=2),
        ]
        # Critical path is b(8) + c(2) = 10
        assert compute_critical_path(tasks) == 10


class TestTopologicalOrder:
    def test_basic_order(self):
        tasks = [
            TurnaroundTask(name="a", starts_after=[], duration_min=1),
            TurnaroundTask(name="b", starts_after=["a"], duration_min=1),
            TurnaroundTask(name="c", starts_after=["b"], duration_min=1),
        ]
        order = topological_order(tasks)
        assert order.index("a") < order.index("b") < order.index("c")


class TestTurnaroundPlanLifecycle:
    """Test TurnaroundPlan creation, start, advance, completion."""

    def test_narrow_body_on_time(self):
        """Run a narrow-body turnaround to completion in 35 min."""
        plan = create_turnaround_plan("N12345", "FL-001", "A320")
        assert not plan.is_complete
        assert not plan.deplaning_done
        assert not plan.ready_for_boarding

        started = plan.start(BASE_TIME)
        assert len(started) > 0  # jetbridge_connect and fueling start immediately

        # Advance minute by minute until completion
        t = BASE_TIME
        for _ in range(60):  # safety limit
            t += timedelta(minutes=1)
            plan.advance(t)
            if plan.is_complete:
                break

        assert plan.is_complete
        assert plan.deplaning_done
        assert plan.ready_for_boarding
        assert plan.pushback_done

        # Should complete at BASE_TIME + 35 min
        completion_time = t
        elapsed = (completion_time - BASE_TIME).total_seconds() / 60
        assert elapsed == 35

    def test_wide_body_on_time(self):
        """Run a wide-body turnaround to completion in 50 min."""
        plan = create_turnaround_plan("N99999", "FL-002", "B77W")
        plan.start(BASE_TIME)

        t = BASE_TIME
        for _ in range(80):
            t += timedelta(minutes=1)
            plan.advance(t)
            if plan.is_complete:
                break

        assert plan.is_complete
        elapsed = (t - BASE_TIME).total_seconds() / 60
        assert elapsed == 50

    def test_deplaning_done_before_complete(self):
        """Deplaning should complete before the full turnaround."""
        plan = create_turnaround_plan("N12345", "FL-001", "A320")
        plan.start(BASE_TIME)

        # Narrow-body deplaning: jetbridge(2) + deplaning(12) = 14 min
        t = BASE_TIME
        for _ in range(14):
            t += timedelta(minutes=1)
            plan.advance(t)

        assert plan.deplaning_done
        assert not plan.is_complete

    def test_ready_for_boarding_timing(self):
        """Ready for boarding after deplaning(14) + cleaning(6) = 20 min."""
        plan = create_turnaround_plan("N12345", "FL-001", "A320")
        plan.start(BASE_TIME)

        t = BASE_TIME
        for _ in range(19):
            t += timedelta(minutes=1)
            plan.advance(t)
        assert not plan.ready_for_boarding

        t += timedelta(minutes=1)
        plan.advance(t)
        assert plan.ready_for_boarding


class TestBaggageDelayPropagation:
    """Test that extending baggage_offload delays the turnaround."""

    def test_baggage_delay_extends_turnaround(self):
        """A 10-min baggage delay on the offload should be absorbed by slack."""
        plan = create_turnaround_plan("N12345", "FL-001", "A320")
        plan.start(BASE_TIME)

        # Extend baggage_offload by 10 min at the very start
        assert plan.extend_task("baggage_offload", 10)

        # Original baggage chain: jetbridge(2) + offload(10+10) + loading(10) = 32
        # Deplaning chain: jetbridge(2) + deplaning(12) + cleaning(6) + boarding(12) = 32
        # Both chains tie at 32, door_close at 32 + 2 + 1 = 35

        t = BASE_TIME
        for _ in range(60):
            t += timedelta(minutes=1)
            plan.advance(t)
            if plan.is_complete:
                break

        elapsed = (t - BASE_TIME).total_seconds() / 60
        assert elapsed == 35  # baggage delay absorbed — ties with deplaning chain

    def test_large_baggage_delay_pushes_departure(self):
        """A 15-min baggage delay should exceed slack and push departure."""
        plan = create_turnaround_plan("N12345", "FL-001", "A320")
        plan.start(BASE_TIME)

        # Extend baggage_offload by 15 min immediately
        assert plan.extend_task("baggage_offload", 15)

        t = BASE_TIME
        for _ in range(60):
            t += timedelta(minutes=1)
            plan.advance(t)
            if plan.is_complete:
                break

        elapsed = (t - BASE_TIME).total_seconds() / 60
        # baggage chain: 2 + 25 + 10 = 37 > 32 (deplaning chain)
        # door_close at max(32, 37, 18, 24) = 37, + 2 + 1 = 40
        assert elapsed == 40


class TestFuelingSlack:
    """Test that fueling delay is absorbed when it doesn't exceed slack."""

    def test_fueling_absorbed(self):
        """A moderate fueling extension should be absorbed by slack."""
        plan = create_turnaround_plan("N12345", "FL-001", "A320")
        plan.start(BASE_TIME)

        # Original fueling = 18 min, starts at T+0, finishes at T+18
        # door_close waits for max(32, 22, 18, 24) = 32
        # Extending fueling by 10 → finishes at T+28, still < 32
        assert plan.extend_task("fueling", 10)

        t = BASE_TIME
        for _ in range(50):
            t += timedelta(minutes=1)
            plan.advance(t)
            if plan.is_complete:
                break

        elapsed = (t - BASE_TIME).total_seconds() / 60
        assert elapsed == 35  # absorbed

    def test_fueling_exceeds_slack(self):
        """A large fueling extension pushes departure."""
        plan = create_turnaround_plan("N12345", "FL-001", "A320")
        plan.start(BASE_TIME)

        # Extend fueling by 20 → finishes at T+38 > 32
        assert plan.extend_task("fueling", 20)

        t = BASE_TIME
        for _ in range(60):
            t += timedelta(minutes=1)
            plan.advance(t)
            if plan.is_complete:
                break

        elapsed = (t - BASE_TIME).total_seconds() / 60
        # door_close at max(32, 22, 38, 24) = 38, + 2 + 1 = 41
        assert elapsed == 41


class TestExtendTask:
    def test_extend_nonexistent_task(self):
        plan = create_turnaround_plan("N12345", "FL-001", "A320")
        assert not plan.extend_task("nonexistent", 5)

    def test_extend_task_twice(self):
        plan = create_turnaround_plan("N12345", "FL-001", "A320")
        plan.extend_task("baggage_offload", 5)
        plan.extend_task("baggage_offload", 3)
        assert plan.tasks["baggage_offload"].duration_min == 18  # 10 + 5 + 3


class TestToDict:
    def test_plan_serializable(self):
        plan = create_turnaround_plan("N12345", "FL-001", "A320", "FL-002")
        plan.start(BASE_TIME)
        d = plan.to_dict()
        assert d["aircraft_registration"] == "N12345"
        assert d["arrival_flight_id"] == "FL-001"
        assert d["paired_departure_id"] == "FL-002"
        assert isinstance(d["tasks"], list)
        assert len(d["tasks"]) == 10
        assert d["critical_path_minutes"] == 35

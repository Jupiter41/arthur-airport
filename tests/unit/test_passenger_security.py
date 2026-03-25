"""Unit tests for passenger-service security model — pure logic, no I/O."""


from tests.conftest import import_service_module

_sec = import_service_module("passenger", "services.security")
BASE_THROUGHPUT_PER_LANE = _sec.BASE_THROUGHPUT_PER_LANE
SA_LANE_THROUGHPUT = _sec.SA_LANE_THROUGHPUT
SA_LANE_BREACH_THROUGHPUT = _sec.SA_LANE_BREACH_THROUGHPUT
SecurityCheckpoint = _sec.SecurityCheckpoint
SecuritySystem = _sec.SecuritySystem


class TestSecurityCheckpoint:
    """Verify per-terminal security checkpoint behavior."""

    def test_initial_state(self):
        cp = SecurityCheckpoint("A", lanes_open=4)
        assert cp.queue_depth == 0
        assert cp.sa_queue_depth == 0
        assert cp.frozen is False

    def test_enqueue_main(self):
        cp = SecurityCheckpoint("A")
        cp.enqueue("p1")
        cp.enqueue("p2")
        assert cp.queue_depth == 2

    def test_enqueue_sa(self):
        cp = SecurityCheckpoint("A")
        cp.enqueue("p1", special_assistance=True)
        assert cp.sa_queue_depth == 1
        assert cp.queue_depth == 0

    def test_no_duplicate_enqueue(self):
        cp = SecurityCheckpoint("A")
        cp.enqueue("p1")
        cp.enqueue("p1")
        assert cp.queue_depth == 1

    def test_effective_throughput_normal(self):
        cp = SecurityCheckpoint("A", lanes_open=4)
        tp = cp.effective_throughput(forecast_queue=0)
        assert tp == 4 * BASE_THROUGHPUT_PER_LANE

    def test_effective_throughput_frozen(self):
        cp = SecurityCheckpoint("A")
        cp.freeze()
        assert cp.effective_throughput(forecast_queue=0) == 0.0

    def test_freeze_and_unfreeze(self):
        cp = SecurityCheckpoint("A")
        cp.freeze()
        assert cp.frozen is True
        cp.unfreeze()
        assert cp.frozen is False

    def test_drain_basic(self):
        cp = SecurityCheckpoint("A", lanes_open=4)
        for i in range(20):
            cp.enqueue(f"p{i}")
        main_drained, sa_drained = cp.drain(forecast_queue=0)
        assert len(main_drained) > 0
        assert cp.queue_depth < 20

    def test_drain_frozen_main(self):
        cp = SecurityCheckpoint("A")
        for i in range(10):
            cp.enqueue(f"p{i}")
        cp.freeze()
        main_drained, sa_drained = cp.drain(forecast_queue=0)
        assert len(main_drained) == 0  # Frozen main queue
        # SA queue still drains (reduced)
        cp.enqueue("sa1", special_assistance=True)
        _, sa_out = cp.drain(forecast_queue=0)
        # Even frozen, SA processes at reduced rate

    def test_wait_minutes_calculation(self):
        cp = SecurityCheckpoint("A", lanes_open=4)
        for i in range(720):  # 720 pax / 720 throughput per hour = 60 min
            cp.enqueue(f"p{i}")
        wait = cp.wait_minutes(forecast_queue=0)
        assert wait == 60.0

    def test_wait_minutes_frozen(self):
        cp = SecurityCheckpoint("A")
        cp.enqueue("p1")
        cp.freeze()
        assert cp.wait_minutes(forecast_queue=0) == 999.0

    def test_drain_at_least_1_if_not_frozen(self):
        cp = SecurityCheckpoint("A", lanes_open=1)
        cp.enqueue("p1")
        drain = cp.drain_per_tick(forecast_queue=0)
        assert drain >= 1

    def test_sa_throughput_normal(self):
        cp = SecurityCheckpoint("A")
        assert cp.sa_throughput() == float(SA_LANE_THROUGHPUT)

    def test_sa_throughput_breach(self):
        cp = SecurityCheckpoint("A")
        cp.freeze()
        assert cp.sa_throughput() == float(SA_LANE_BREACH_THROUGHPUT)


class TestSecuritySystem:
    """Verify the 3-terminal system."""

    def test_has_three_terminals(self):
        system = SecuritySystem()
        assert set(system.checkpoints.keys()) == {"A", "B", "C"}

    def test_enqueue_routes_to_terminal(self):
        system = SecuritySystem()
        system.enqueue("B", "p1")
        assert system.get("B").queue_depth == 1
        assert system.get("A").queue_depth == 0

    def test_freeze_terminal(self):
        system = SecuritySystem()
        system.freeze_terminal("C")
        assert system.get("C").frozen is True
        assert system.get("A").frozen is False

    def test_unfreeze_terminal(self):
        system = SecuritySystem()
        system.freeze_terminal("A")
        system.unfreeze_terminal("A")
        assert system.get("A").frozen is False

    def test_drain_all(self):
        system = SecuritySystem()
        for i in range(10):
            system.enqueue("A", f"pa{i}")
            system.enqueue("B", f"pb{i}")
        result = system.drain_all({"A": 0, "B": 0, "C": 0})
        assert "A" in result
        assert "B" in result
        assert "C" in result

    def test_get_summary(self):
        system = SecuritySystem()
        for i in range(50):
            system.enqueue("A", f"p{i}")
        summary = system.get_summary({"A": 0, "B": 0, "C": 0})
        assert "terminal_a" in summary
        assert summary["terminal_a"]["queue_depth"] == 50
        assert summary["terminal_a"]["lanes_open"] > 0

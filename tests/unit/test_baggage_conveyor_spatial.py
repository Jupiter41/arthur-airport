"""Unit tests for conveyor cross-terminal transit delay model."""

from tests.conftest import import_service_module

_cv = import_service_module("baggage", "services.conveyor")
ConveyorSystem = _cv.ConveyorSystem
BagInZone = _cv.BagInZone


def _make_bag(bag_id: str, terminal: str, gate_terminal: str = "") -> BagInZone:
    return BagInZone(
        baggage_id=bag_id,
        tag=f"007{bag_id}",
        flight_id="F1",
        is_dg=False,
        dg_class=None,
        passenger_id=None,
        terminal=terminal,
        entered_at="2025-06-15T10:00:00",
        gate_terminal=gate_terminal or terminal,
    )


class TestSameTerminalImmediate:
    """Same-terminal bags should reach make-up immediately after sorting."""

    def test_same_terminal_no_transit_delay(self):
        cs = ConveyorSystem()
        bag = _make_bag("b1", "A", "A")
        cs._zones["sorting-matrix"].queue.append(bag)

        outputs = cs.advance_tick("2025-06-15T10:05:00")

        # Bag should have exited sorting
        assert "sorting-matrix" in outputs
        # Bag should be in a make-up-A zone now
        total_makeup_a = sum(
            cs._zones[f"make-up-A-{n}"].items for n in range(1, 6)
        )
        assert total_makeup_a == 1
        assert cs.transit_queue_depth == 0


class TestCrossTerminalDelay:
    """Cross-terminal bags should be held in transit queue."""

    def test_adjacent_terminal_delayed(self):
        cs = ConveyorSystem()
        bag = _make_bag("b1", "A", "B")
        cs._zones["sorting-matrix"].queue.append(bag)

        outputs = cs.advance_tick("2025-06-15T10:05:00")

        # Bag exited sorting
        assert "sorting-matrix" in outputs
        # Bag should NOT be in make-up yet — it's in transit
        total_makeup_b = sum(
            cs._zones[f"make-up-B-{n}"].items for n in range(1, 6)
        )
        assert total_makeup_b == 0
        assert cs.transit_queue_depth == 1

    def test_far_terminal_delayed(self):
        cs = ConveyorSystem()
        bag = _make_bag("b1", "A", "C")
        cs._zones["sorting-matrix"].queue.append(bag)

        cs.advance_tick("2025-06-15T10:05:00")

        assert cs.transit_queue_depth == 1
        total_makeup_c = sum(
            cs._zones[f"make-up-C-{n}"].items for n in range(1, 6)
        )
        assert total_makeup_c == 0

    def test_transit_bag_delivered_after_delay(self):
        cs = ConveyorSystem()
        bag = _make_bag("b1", "A", "B")
        cs._zones["sorting-matrix"].queue.append(bag)

        # Tick 1: bag enters transit (A→B adjacent = 8-4=4 min extra delay)
        cs.advance_tick("2025-06-15T10:05:00", delta_minutes=1)
        assert cs.transit_queue_depth == 1

        # Ticks 2-4: still in transit (3 of 4 remaining minutes)
        for i in range(3):
            cs.advance_tick(f"2025-06-15T10:{6+i:02d}:00", delta_minutes=1)
            assert cs.transit_queue_depth == 1

        # Tick 5: 4th minute elapsed — bag delivered
        cs.advance_tick("2025-06-15T10:09:00", delta_minutes=1)
        assert cs.transit_queue_depth == 0

        total_makeup_b = sum(
            cs._zones[f"make-up-B-{n}"].items for n in range(1, 6)
        )
        assert total_makeup_b == 1

    def test_far_terminal_takes_longer(self):
        cs = ConveyorSystem()
        bag = _make_bag("b1", "A", "C")
        cs._zones["sorting-matrix"].queue.append(bag)

        # A→C far = 12-4=8 min extra delay
        cs.advance_tick("2025-06-15T10:05:00", delta_minutes=1)
        assert cs.transit_queue_depth == 1

        # Advance 7 more minutes — should still be in transit (7 of 8)
        for i in range(7):
            cs.advance_tick(f"2025-06-15T10:{6+i:02d}:00", delta_minutes=1)
        assert cs.transit_queue_depth == 1

        # 8th minute: bag delivered
        cs.advance_tick("2025-06-15T10:13:00", delta_minutes=1)
        assert cs.transit_queue_depth == 0

        total_makeup_c = sum(
            cs._zones[f"make-up-C-{n}"].items for n in range(1, 6)
        )
        assert total_makeup_c == 1

    def test_multi_minute_tick_delivers_transit(self):
        """A 5-minute tick should deliver a bag with 4-min transit delay."""
        cs = ConveyorSystem()
        bag = _make_bag("b1", "A", "B")
        cs._zones["sorting-matrix"].queue.append(bag)

        cs.advance_tick("2025-06-15T10:05:00", delta_minutes=1)
        assert cs.transit_queue_depth == 1

        # 5-minute tick covers the 4-min delay
        cs.advance_tick("2025-06-15T10:10:00", delta_minutes=5)
        assert cs.transit_queue_depth == 0

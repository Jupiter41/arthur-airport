"""Unit tests for baggage-service conveyor system — pure logic, no I/O."""

import pytest

from tests.conftest import import_service_module

_conv = import_service_module("baggage", "services.conveyor")
BagInZone = _conv.BagInZone
ZoneState = _conv.ZoneState
ConveyorSystem = _conv.ConveyorSystem
ZONE_THROUGHPUT = _conv.ZONE_THROUGHPUT
TERMINAL_SCREENING = _conv.TERMINAL_SCREENING
TERMINAL_MAKEUP = _conv.TERMINAL_MAKEUP
ZONE_TO_STATUS = _conv.ZONE_TO_STATUS


SIM_TIME = "2025-06-15T10:00:00"


def _bag(
    baggage_id: str = "bag-1",
    tag: str = "TAG001",
    flight_id: str = "flt-1",
    terminal: str = "A",
    is_dg: bool = False,
) -> BagInZone:
    return BagInZone(
        baggage_id=baggage_id,
        tag=tag,
        flight_id=flight_id,
        is_dg=is_dg,
        dg_class=None,
        passenger_id="pax-1",
        terminal=terminal,
        entered_at=SIM_TIME,
    )


# ── Zone Throughput map ──────────────────────────────────────────

class TestZoneThroughput:
    def test_all_induction_zones(self):
        for t in "ABC":
            assert f"induction-{t}" in ZONE_THROUGHPUT

    def test_six_screening_units(self):
        for n in range(1, 7):
            assert f"screening-unit-{n}" in ZONE_THROUGHPUT

    def test_sorting_matrix(self):
        assert "sorting-matrix" in ZONE_THROUGHPUT
        assert ZONE_THROUGHPUT["sorting-matrix"] == 1800

    def test_makeup_zones(self):
        for t in "ABC":
            for n in range(1, 6):
                assert f"make-up-{t}-{n}" in ZONE_THROUGHPUT

    def test_arrival_belts(self):
        for n in range(1, 7):
            assert f"arrival-belt-{n}" in ZONE_THROUGHPUT


class TestTerminalMapping:
    def test_terminal_screening_mapping(self):
        assert len(TERMINAL_SCREENING["A"]) == 2
        assert len(TERMINAL_SCREENING["B"]) == 2
        assert len(TERMINAL_SCREENING["C"]) == 2

    def test_terminal_makeup_mapping(self):
        assert len(TERMINAL_MAKEUP["A"]) == 5
        assert len(TERMINAL_MAKEUP["B"]) == 5
        assert len(TERMINAL_MAKEUP["C"]) == 5


class TestZoneToStatus:
    def test_induction_maps_to_inducted(self):
        assert ZONE_TO_STATUS["induction-A"] == "inducted"

    def test_screening_maps(self):
        assert ZONE_TO_STATUS["screening-unit-1"] == "screening"

    def test_sorting_maps(self):
        assert ZONE_TO_STATUS["sorting-matrix"] == "sorting"

    def test_makeup_maps_to_loaded(self):
        assert ZONE_TO_STATUS["make-up-A-1"] == "loaded"

    def test_arrival_belt_maps(self):
        assert ZONE_TO_STATUS["arrival-belt-1"] == "on_carousel"


# ── ConveyorSystem ───────────────────────────────────────────────

class TestConveyorSystem:
    def test_initialization(self):
        system = ConveyorSystem()
        zones = system.get_all_zones()
        assert len(zones) == len(ZONE_THROUGHPUT)

    def test_induct_bag_routes_to_terminal(self):
        system = ConveyorSystem()
        bag = _bag(terminal="B")
        zone_id = system.induct_bag(bag, SIM_TIME)
        assert zone_id == "induction-B"
        assert system.get_zone("induction-B").items == 1

    def test_induct_bag_fallback(self):
        """Invalid terminal falls back to induction-A."""
        system = ConveyorSystem()
        bag = _bag(terminal="X")
        zone_id = system.induct_bag(bag, SIM_TIME)
        assert zone_id == "induction-A"

    def test_remove_bag(self):
        system = ConveyorSystem()
        bag = _bag(baggage_id="bag-rem")
        system.induct_bag(bag, SIM_TIME)
        removed = system.remove_bag_from_all_zones("bag-rem")
        assert removed is not None
        assert removed.baggage_id == "bag-rem"

    def test_remove_nonexistent_bag(self):
        system = ConveyorSystem()
        removed = system.remove_bag_from_all_zones("nonexistent")
        assert removed is None

    def test_set_zone_status(self):
        system = ConveyorSystem()
        system.set_zone_status("sorting-matrix", "offline")
        assert system.get_zone("sorting-matrix").status == "offline"

    def test_drain_offline_zone_empty(self):
        system = ConveyorSystem()
        zone = system.get_zone("induction-A")
        bag = _bag()
        system.induct_bag(bag, SIM_TIME)
        system.set_zone_status("induction-A", "offline")
        drained = system.drain_zone(zone)
        assert len(drained) == 0

    def test_drain_degraded_zone_reduced(self):
        system = ConveyorSystem()
        for i in range(100):
            system.induct_bag(_bag(baggage_id=f"bag-{i}"), SIM_TIME)
        system.set_zone_status("induction-A", "degraded")
        zone = system.get_zone("induction-A")
        drained = system.drain_zone(zone)
        # Degraded = 50% throughput; 600/hr/2 = 300/hr → 5/min
        assert len(drained) <= 10  # Max normal is 10/min

    def test_advance_tick_pipeline(self):
        """Bags flow from induction through the pipeline."""
        system = ConveyorSystem()
        for i in range(5):
            system.induct_bag(_bag(baggage_id=f"bag-{i}"), SIM_TIME)
        
        outputs = system.advance_tick(SIM_TIME)
        # After one tick, bags should have left induction
        assert "induction-A" in outputs
        # And entered screening
        screening_zones = [f"screening-unit-{n}" for n in range(1, 7)]
        total_in_screening = sum(
            system.get_zone(z).items for z in screening_zones
        )
        assert total_in_screening > 0

    def test_get_zone_summary(self):
        system = ConveyorSystem()
        summary = system.get_zone_summary()
        assert len(summary) == len(ZONE_THROUGHPUT)
        for item in summary:
            assert "zone_id" in item
            assert "items" in item
            assert "status" in item
            assert "throughput_per_hour" in item

    def test_get_system_failures_count(self):
        system = ConveyorSystem()
        assert system.get_system_failures_count() == 0
        system.set_zone_status("sorting-matrix", "offline")
        assert system.get_system_failures_count() == 1
        system.set_zone_status("induction-A", "offline")
        assert system.get_system_failures_count() == 2

    def test_multiple_ticks_flow(self):
        """Multiple ticks move bags further in the pipeline."""
        system = ConveyorSystem()
        for i in range(10):
            system.induct_bag(_bag(baggage_id=f"bag-{i}"), SIM_TIME)
        
        # Run several ticks
        for tick in range(5):
            system.advance_tick(f"2025-06-15T10:{tick:02d}:00")
        
        # Bags should have advanced past induction
        assert system.get_zone("induction-A").items < 10

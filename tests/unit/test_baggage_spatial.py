"""Unit tests for baggage conveyor spatial model — transit times."""

from tests.conftest import import_service_module

_sp = import_service_module("baggage", "services.spatial")
terminal_distance = _sp.terminal_distance
sorting_to_makeup_minutes = _sp.sorting_to_makeup_minutes
bag_conveyor_time = _sp.bag_conveyor_time
arrival_carousel_for_terminal = _sp.arrival_carousel_for_terminal
SORTING_TO_MAKEUP_SAME = _sp.SORTING_TO_MAKEUP_SAME
SORTING_TO_MAKEUP_ADJACENT = _sp.SORTING_TO_MAKEUP_ADJACENT
SORTING_TO_MAKEUP_FAR = _sp.SORTING_TO_MAKEUP_FAR


class TestTerminalDistance:
    def test_same_terminal(self):
        assert terminal_distance("A", "A") == 0
        assert terminal_distance("B", "B") == 0
        assert terminal_distance("C", "C") == 0

    def test_adjacent(self):
        assert terminal_distance("A", "B") == 1
        assert terminal_distance("B", "A") == 1
        assert terminal_distance("B", "C") == 1
        assert terminal_distance("C", "B") == 1

    def test_far(self):
        assert terminal_distance("A", "C") == 2
        assert terminal_distance("C", "A") == 2


class TestSortingToMakeupMinutes:
    def test_same_terminal(self):
        assert sorting_to_makeup_minutes("A", "A") == SORTING_TO_MAKEUP_SAME

    def test_adjacent_terminal(self):
        t = sorting_to_makeup_minutes("A", "B")
        assert t == SORTING_TO_MAKEUP_ADJACENT

    def test_far_terminal(self):
        t = sorting_to_makeup_minutes("A", "C")
        assert t == SORTING_TO_MAKEUP_FAR

    def test_adjacent_reverse(self):
        assert sorting_to_makeup_minutes("B", "A") == SORTING_TO_MAKEUP_ADJACENT

    def test_ordering(self):
        assert SORTING_TO_MAKEUP_SAME < SORTING_TO_MAKEUP_ADJACENT < SORTING_TO_MAKEUP_FAR


class TestBagConveyorTime:
    def test_same_terminal(self):
        t = bag_conveyor_time("A", "A")
        # 2 + 3 + 2 + 2 + 4 = 13
        assert t == 13

    def test_adjacent_terminal(self):
        t = bag_conveyor_time("A", "B")
        # 2 + 3 + 2 + 2 + 8 = 17
        assert t == 17

    def test_far_terminal(self):
        t = bag_conveyor_time("A", "C")
        # 2 + 3 + 2 + 2 + 12 = 21
        assert t == 21

    def test_cross_terminal_always_slower(self):
        same = bag_conveyor_time("B", "B")
        adjacent = bag_conveyor_time("B", "C")
        assert same < adjacent
        assert bag_conveyor_time("A", "C") > adjacent


class TestArrivalCarousel:
    def test_terminal_a(self):
        assert arrival_carousel_for_terminal("A") == [1, 2]

    def test_terminal_b(self):
        assert arrival_carousel_for_terminal("B") == [3, 4]

    def test_terminal_c(self):
        assert arrival_carousel_for_terminal("C") == [5, 6]

    def test_unknown_fallback(self):
        assert arrival_carousel_for_terminal("X") == [1, 2]

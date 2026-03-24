"""Unit tests for baggage-service screening — pure logic, no I/O."""

import random

import pytest

from tests.conftest import import_service_module

_scr = import_service_module("baggage", "services.screening")
DETECTION_RATES = _scr.DETECTION_RATES
FALSE_POSITIVE_RATE = _scr.FALSE_POSITIVE_RATE
screen_item = _scr.screen_item


class TestScreenItem:
    """Verify DG detection logic."""

    def test_clean_item_usually_clears(self):
        """Clean items should clear most of the time."""
        clear_count = sum(
            1 for _ in range(1000)
            if screen_item(f"bag-{_}", is_dg=False, dg_class=None) == "clear"
        )
        # With 0.3% false positive rate, expect ~997/1000 clears
        assert clear_count > 950

    def test_dg_class_3_detected_at_high_rate(self):
        """DG class 3 (flammable liquids) has 91% detection rate."""
        flagged = sum(
            1 for i in range(1000)
            if screen_item(f"bag-{i}", is_dg=True, dg_class="3") == "flagged"
        )
        # Expect ~910/1000 detections
        assert flagged > 800

    def test_dg_class_9_lower_rate(self):
        """DG class 9 (misc) has only 72% detection rate."""
        flagged = sum(
            1 for i in range(1000)
            if screen_item(f"bag-{i}", is_dg=True, dg_class="9") == "flagged"
        )
        # Expect ~720/1000 — wider tolerance
        assert flagged > 600
        assert flagged < 900

    def test_false_positive_exists(self):
        """Over enough clean items, some false positives appear."""
        results = [
            screen_item(f"bag-{i}", is_dg=False, dg_class=None)
            for i in range(10000)
        ]
        fp_count = results.count("false_positive")
        assert fp_count > 0, "No false positives in 10000 screenings"

    def test_returns_valid_values(self):
        for _ in range(100):
            result = screen_item("bag-1", is_dg=False, dg_class=None)
            assert result in ("clear", "false_positive")

    def test_dg_without_class_uses_default(self):
        """DG flagged but no class uses 80% default rate."""
        flagged = sum(
            1 for i in range(1000)
            if screen_item(f"bag-{i}", is_dg=True, dg_class="unknown") == "flagged"
        )
        assert flagged > 650

    def test_detection_rates_keys(self):
        assert set(DETECTION_RATES.keys()) == {"2", "3", "8", "9"}

    def test_false_positive_rate_is_low(self):
        assert FALSE_POSITIVE_RATE < 0.01

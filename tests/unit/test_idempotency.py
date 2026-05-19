"""Unit tests for idempotency and duplicate event handling across all consumers.

Tests the shared IdempotencyTracker from _common.idempotency and envelope
validation logic.
"""

import sys
import os
from datetime import datetime

# Make _common importable by adding the services directory to the path
_SERVICES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "services")
sys.path.insert(0, _SERVICES_DIR)

from _common.idempotency import IdempotencyTracker  # noqa: E402


def validate_envelope(envelope: dict) -> tuple[str, datetime, dict] | None:
    """Minimal reproduction of _validate_envelope used across all consumers."""
    event_type = envelope.get("event_type")
    if not isinstance(event_type, str):
        return None

    sim_time_str = envelope.get("sim_time")
    if not sim_time_str:
        return None
    try:
        sim_time = datetime.fromisoformat(str(sim_time_str)).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None

    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return None

    return event_type, sim_time, payload


# ── Tests ────────────────────────────────────────────────────


class TestIdempotencyChecker:
    """Test the shared IdempotencyTracker used by all consumer state holders."""

    def test_first_event_not_duplicate(self):
        tracker = IdempotencyTracker(max_size=100)
        assert tracker.is_duplicate("evt-001") is False

    def test_second_same_event_is_duplicate(self):
        tracker = IdempotencyTracker(max_size=100)
        tracker.is_duplicate("evt-001")
        assert tracker.is_duplicate("evt-001") is True

    def test_different_events_not_duplicate(self):
        tracker = IdempotencyTracker(max_size=100)
        tracker.is_duplicate("evt-001")
        assert tracker.is_duplicate("evt-002") is False

    def test_empty_event_id_never_duplicate(self):
        tracker = IdempotencyTracker(max_size=100)
        assert tracker.is_duplicate("") is False
        assert tracker.is_duplicate("") is False

    def test_eviction_at_max(self):
        tracker = IdempotencyTracker(max_size=100)
        for i in range(150):
            tracker.is_duplicate(f"evt-{i}")
        assert len(tracker) <= 100

    def test_fifo_eviction_oldest_removed(self):
        tracker = IdempotencyTracker(max_size=5)
        for i in range(5):
            tracker.is_duplicate(f"evt-{i}")
        # Fill up — evt-0 through evt-4 are stored
        assert "evt-0" in tracker
        # Insert one more — evt-0 should be evicted
        tracker.is_duplicate("evt-5")
        assert "evt-0" not in tracker
        assert "evt-5" in tracker
        # evt-1 should also still be there
        assert "evt-1" in tracker

    def test_many_duplicates_all_rejected(self):
        tracker = IdempotencyTracker(max_size=100)
        tracker.is_duplicate("evt-X")
        for _ in range(100):
            assert tracker.is_duplicate("evt-X") is True

    def test_independent_instances(self):
        a = IdempotencyTracker(max_size=100)
        b = IdempotencyTracker(max_size=100)
        a.is_duplicate("shared-id")
        assert b.is_duplicate("shared-id") is False  # different instance

    def test_clear(self):
        tracker = IdempotencyTracker(max_size=100)
        tracker.is_duplicate("evt-001")
        tracker.clear()
        assert tracker.is_duplicate("evt-001") is False
        assert len(tracker) == 1


class TestEnvelopeValidation:
    """Test the envelope validation pattern used by all consumers."""

    def test_valid_envelope(self):
        result = validate_envelope({
            "event_type": "SimClockTick",
            "sim_time": "2025-01-01T12:00:00",
            "payload": {"day_of_sim": 1},
        })
        assert result is not None
        event_type, sim_time, payload = result
        assert event_type == "SimClockTick"
        assert sim_time.hour == 12
        assert payload["day_of_sim"] == 1

    def test_missing_event_type(self):
        assert validate_envelope({"sim_time": "2025-01-01T00:00:00", "payload": {}}) is None

    def test_non_string_event_type(self):
        assert validate_envelope({"event_type": 42, "sim_time": "2025-01-01T00:00:00", "payload": {}}) is None

    def test_missing_sim_time(self):
        assert validate_envelope({"event_type": "SimClockTick", "payload": {}}) is None

    def test_empty_sim_time(self):
        assert validate_envelope({"event_type": "SimClockTick", "sim_time": "", "payload": {}}) is None

    def test_unparseable_sim_time(self):
        assert validate_envelope({"event_type": "SimClockTick", "sim_time": "not-a-date", "payload": {}}) is None

    def test_missing_payload(self):
        assert validate_envelope({"event_type": "SimClockTick", "sim_time": "2025-01-01T00:00:00"}) is None

    def test_non_dict_payload(self):
        assert validate_envelope({"event_type": "SimClockTick", "sim_time": "2025-01-01T00:00:00", "payload": "string"}) is None

    def test_list_payload(self):
        assert validate_envelope({"event_type": "SimClockTick", "sim_time": "2025-01-01T00:00:00", "payload": [1, 2]}) is None

    def test_strips_timezone(self):
        result = validate_envelope({"event_type": "SimClockTick", "sim_time": "2025-01-01T12:00:00+02:00", "payload": {}})
        assert result is not None
        _, sim_time, _ = result
        assert sim_time.tzinfo is None

    def test_empty_envelope(self):
        assert validate_envelope({}) is None

    def test_all_event_types_accepted(self):
        """All known event types pass validation (type is just str check)."""
        for event_type in [
            "SimClockTick", "FlightStatusChanged", "FlightCancelled",
            "FlightGateAssigned", "WeatherStateChanged", "IncidentCreated",
            "IncidentStatusChanged", "BaggageStatusChanged", "BaggageFlagged",
            "PassengerStatusChanged",
        ]:
            result = validate_envelope({
                "event_type": event_type,
                "sim_time": "2025-06-15T10:30:00",
                "payload": {},
            })
            assert result is not None, f"Valid envelope rejected for {event_type}"

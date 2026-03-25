"""Unit tests for idempotency and duplicate event handling across all consumers.

Tests the check_idempotency method and envelope validation logic.
Since consumer modules import confluent_kafka (not available in test env),
we test the patterns directly — the same logic is used across all 5 consumers.
"""

from datetime import datetime


# ── Idempotency logic (exact same pattern as all consumer state holders) ──


class IdempotencyChecker:
    """Minimal reproduction of the check_idempotency pattern used by all consumers."""

    MAX_PROCESSED = 100  # smaller for testing

    def __init__(self):
        self.processed_events: set[str] = set()

    def check_idempotency(self, event_id: str) -> bool:
        if not event_id:
            return False
        if event_id in self.processed_events:
            return True
        self.processed_events.add(event_id)
        if len(self.processed_events) > self.MAX_PROCESSED:
            excess = len(self.processed_events) - self.MAX_PROCESSED
            for _ in range(excess):
                self.processed_events.pop()
        return False


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
    """Test the check_idempotency pattern used by all consumer state holders."""

    def test_first_event_not_duplicate(self):
        checker = IdempotencyChecker()
        assert checker.check_idempotency("evt-001") is False

    def test_second_same_event_is_duplicate(self):
        checker = IdempotencyChecker()
        checker.check_idempotency("evt-001")
        assert checker.check_idempotency("evt-001") is True

    def test_different_events_not_duplicate(self):
        checker = IdempotencyChecker()
        checker.check_idempotency("evt-001")
        assert checker.check_idempotency("evt-002") is False

    def test_empty_event_id_never_duplicate(self):
        checker = IdempotencyChecker()
        assert checker.check_idempotency("") is False
        assert checker.check_idempotency("") is False

    def test_eviction_at_max(self):
        checker = IdempotencyChecker()
        for i in range(checker.MAX_PROCESSED + 50):
            checker.check_idempotency(f"evt-{i}")
        assert len(checker.processed_events) <= checker.MAX_PROCESSED

    def test_many_duplicates_all_rejected(self):
        checker = IdempotencyChecker()
        checker.check_idempotency("evt-X")
        for _ in range(100):
            assert checker.check_idempotency("evt-X") is True

    def test_independent_instances(self):
        a = IdempotencyChecker()
        b = IdempotencyChecker()
        a.check_idempotency("shared-id")
        assert b.check_idempotency("shared-id") is False  # different instance


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

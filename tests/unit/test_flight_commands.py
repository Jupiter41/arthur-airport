"""Unit tests for the flight-service pure command layer (`flights.commands`).

Covers parse_command / validate_hold_precondition — pure, no Kafka/Neo4j.
"""

from tests.conftest import import_service_module

_cmd = import_service_module("flight", "application.commands")

parse_command = _cmd.parse_command
validate_hold_precondition = _cmd.validate_hold_precondition
HoldFlight = _cmd.HoldFlight
ReassignGate = _cmd.ReassignGate
HOLDABLE_STATUSES = _cmd.HOLDABLE_STATUSES


# ── parse_command: HoldFlight ────────────────────────────────────

class TestParseHold:
    def test_valid(self):
        cmd, err = parse_command("HoldFlight", {"flight_id": "F1", "reason": "gate_conflict", "duration_min": 20})
        assert err is None
        assert cmd == HoldFlight(flight_id="F1", reason="gate_conflict", duration_min=20)

    def test_legacy_duration_field(self):
        cmd, err = parse_command("HoldFlight", {"flight_id": "F1", "reason": "x", "expected_duration_minutes": 15})
        assert err is None
        assert cmd.duration_min == 15

    def test_duration_as_numeric_string(self):
        cmd, err = parse_command("HoldFlight", {"flight_id": "F1", "reason": "x", "duration_min": "30"})
        assert err is None and cmd.duration_min == 30

    def test_missing_flight_id(self):
        cmd, err = parse_command("HoldFlight", {"reason": "x", "duration_min": 10})
        assert cmd is None and "flight_id" in err

    def test_empty_flight_id(self):
        cmd, err = parse_command("HoldFlight", {"flight_id": "", "reason": "x", "duration_min": 10})
        assert cmd is None and "flight_id" in err

    def test_missing_reason(self):
        cmd, err = parse_command("HoldFlight", {"flight_id": "F1", "duration_min": 10})
        assert cmd is None and "reason" in err

    def test_missing_duration(self):
        cmd, err = parse_command("HoldFlight", {"flight_id": "F1", "reason": "x"})
        assert cmd is None and "duration_min" in err

    def test_zero_duration_rejected(self):
        cmd, err = parse_command("HoldFlight", {"flight_id": "F1", "reason": "x", "duration_min": 0})
        assert cmd is None and "duration_min" in err

    def test_negative_duration_rejected(self):
        cmd, err = parse_command("HoldFlight", {"flight_id": "F1", "reason": "x", "duration_min": -5})
        assert cmd is None

    def test_bool_duration_rejected(self):
        # True is an int in Python but must not count as a duration
        cmd, err = parse_command("HoldFlight", {"flight_id": "F1", "reason": "x", "duration_min": True})
        assert cmd is None

    def test_non_numeric_duration_rejected(self):
        cmd, err = parse_command("HoldFlight", {"flight_id": "F1", "reason": "x", "duration_min": "soon"})
        assert cmd is None


# ── parse_command: ReassignGate ──────────────────────────────────

class TestParseReassign:
    def test_valid(self):
        cmd, err = parse_command("ReassignGate", {"flight_id": "F1", "gate_id": "B07"})
        assert err is None
        assert cmd == ReassignGate(flight_id="F1", gate_id="B07")

    def test_missing_gate(self):
        cmd, err = parse_command("ReassignGate", {"flight_id": "F1"})
        assert cmd is None and "gate_id" in err

    def test_missing_flight(self):
        cmd, err = parse_command("ReassignGate", {"gate_id": "B07"})
        assert cmd is None and "flight_id" in err


# ── parse_command: envelope-level ────────────────────────────────

class TestParseEnvelope:
    def test_unknown_command_type(self):
        cmd, err = parse_command("DoTheThing", {"flight_id": "F1"})
        assert cmd is None and "unknown command_type" in err

    def test_none_command_type(self):
        cmd, err = parse_command(None, {})
        assert cmd is None

    def test_non_dict_payload(self):
        cmd, err = parse_command("HoldFlight", None)
        assert cmd is None and "payload" in err

    def test_list_payload(self):
        cmd, err = parse_command("HoldFlight", ["nope"])
        assert cmd is None and "payload" in err


# ── validate_hold_precondition ───────────────────────────────────

class TestHoldPrecondition:
    def test_holdable_statuses_accepted(self):
        for status in ("boarding", "scheduled", "approach"):
            assert validate_hold_precondition(status) is None

    def test_holdable_set_is_exactly_those_three(self):
        assert HOLDABLE_STATUSES == {"boarding", "scheduled", "approach"}

    def test_non_holdable_rejected(self):
        for status in ("departed", "airborne", "landed", "at_gate", "arrived", "cancelled", "diverted"):
            assert validate_hold_precondition(status) is not None

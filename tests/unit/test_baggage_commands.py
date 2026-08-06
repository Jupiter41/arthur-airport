"""Unit tests for baggage-service pure command layer (`baggage.commands`).

Covers parse_command — pure, no Kafka/Neo4j.
"""

from tests.conftest import import_service_module

_cmd = import_service_module("baggage", "application.commands")

parse_command = _cmd.parse_command
RedirectBaggage = _cmd.RedirectBaggage


# ── parse_command: RedirectBaggage ──────────────────────────────

class TestParseRedirectBaggage:
    def test_valid(self):
        cmd, err = parse_command(
            "RedirectBaggage", {"bag_id": "BAG-001", "target_flight_id": "AX123"}
        )
        assert err is None
        assert cmd == RedirectBaggage(bag_id="BAG-001", target_flight_id="AX123")

    def test_missing_bag_id(self):
        cmd, err = parse_command("RedirectBaggage", {"target_flight_id": "AX123"})
        assert cmd is None and "bag_id" in err

    def test_empty_bag_id(self):
        cmd, err = parse_command("RedirectBaggage", {"bag_id": "", "target_flight_id": "AX123"})
        assert cmd is None and "bag_id" in err

    def test_missing_target_flight(self):
        cmd, err = parse_command("RedirectBaggage", {"bag_id": "BAG-001"})
        assert cmd is None and "target_flight_id" in err

    def test_empty_target_flight(self):
        cmd, err = parse_command("RedirectBaggage", {"bag_id": "BAG-001", "target_flight_id": ""})
        assert cmd is None and "target_flight_id" in err

    def test_same_bag_and_flight_rejected(self):
        cmd, err = parse_command("RedirectBaggage", {"bag_id": "X", "target_flight_id": "X"})
        assert cmd is None and "differ" in err

    def test_non_string_bag_id(self):
        cmd, err = parse_command("RedirectBaggage", {"bag_id": 42, "target_flight_id": "AX123"})
        assert cmd is None

    def test_non_string_target(self):
        cmd, err = parse_command("RedirectBaggage", {"bag_id": "BAG-001", "target_flight_id": None})
        assert cmd is None


# ── parse_command: envelope-level ────────────────────────────────

class TestParseEnvelope:
    def test_unknown_command_type(self):
        cmd, err = parse_command("OffloadBag", {"bag_id": "X"})
        assert cmd is None and "unknown command_type" in err

    def test_none_command_type(self):
        cmd, err = parse_command(None, {})
        assert cmd is None

    def test_non_dict_payload(self):
        cmd, err = parse_command("RedirectBaggage", "not-a-dict")
        assert cmd is None and "payload" in err

    def test_list_payload(self):
        cmd, err = parse_command("RedirectBaggage", ["BAG-001", "AX123"])
        assert cmd is None and "payload" in err

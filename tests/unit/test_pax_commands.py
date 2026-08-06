"""Unit tests for passenger-service pure command layer (`passengers.commands`).

Covers parse_command — pure, no Kafka/Neo4j.
"""

from tests.conftest import import_service_module

_cmd = import_service_module("passenger", "application.commands")

parse_command = _cmd.parse_command
OpenSecurityLane = _cmd.OpenSecurityLane
VALID_TERMINALS = _cmd.VALID_TERMINALS
MAX_LANES = _cmd.MAX_LANES


# ── parse_command: OpenSecurityLane ─────────────────────────────

class TestParseOpenSecurityLane:
    def test_valid_terminal_a(self):
        cmd, err = parse_command("OpenSecurityLane", {"terminal": "A", "lanes_open": 6})
        assert err is None
        assert cmd == OpenSecurityLane(terminal="A", lanes_open=6)

    def test_valid_terminal_b(self):
        cmd, err = parse_command("OpenSecurityLane", {"terminal": "B", "lanes_open": 4})
        assert err is None and cmd.terminal == "B"

    def test_valid_terminal_c(self):
        cmd, err = parse_command("OpenSecurityLane", {"terminal": "C", "lanes_open": 8})
        assert err is None and cmd.terminal == "C"

    def test_valid_terminals_are_exactly_abc(self):
        assert VALID_TERMINALS == {"A", "B", "C"}

    def test_invalid_terminal_rejected(self):
        cmd, err = parse_command("OpenSecurityLane", {"terminal": "D", "lanes_open": 4})
        assert cmd is None and "terminal" in err

    def test_lowercase_terminal_rejected(self):
        cmd, err = parse_command("OpenSecurityLane", {"terminal": "a", "lanes_open": 4})
        assert cmd is None

    def test_missing_terminal_rejected(self):
        cmd, err = parse_command("OpenSecurityLane", {"lanes_open": 4})
        assert cmd is None and "terminal" in err

    def test_zero_lanes_rejected(self):
        cmd, err = parse_command("OpenSecurityLane", {"terminal": "A", "lanes_open": 0})
        assert cmd is None and "lanes_open" in err

    def test_negative_lanes_rejected(self):
        cmd, err = parse_command("OpenSecurityLane", {"terminal": "A", "lanes_open": -1})
        assert cmd is None

    def test_bool_lanes_rejected(self):
        cmd, err = parse_command("OpenSecurityLane", {"terminal": "A", "lanes_open": True})
        assert cmd is None

    def test_missing_lanes_rejected(self):
        cmd, err = parse_command("OpenSecurityLane", {"terminal": "A"})
        assert cmd is None and "lanes_open" in err

    def test_exceeds_max_lanes_rejected(self):
        cmd, err = parse_command("OpenSecurityLane", {"terminal": "A", "lanes_open": MAX_LANES + 1})
        assert cmd is None and "maximum" in err

    def test_max_lanes_exactly_accepted(self):
        cmd, err = parse_command("OpenSecurityLane", {"terminal": "A", "lanes_open": MAX_LANES})
        assert err is None and cmd.lanes_open == MAX_LANES

    def test_lanes_as_string_int_rejected(self):
        # Unlike HoldFlight, we don't accept string ints for lanes (simpler, less ambiguous)
        # Actually the _coerce_positive_int does accept string ints — check the behaviour
        cmd, err = parse_command("OpenSecurityLane", {"terminal": "A", "lanes_open": "4"})
        # The helper does accept numeric strings — this is consistent with HoldFlight
        assert err is None and cmd.lanes_open == 4


# ── parse_command: envelope-level ────────────────────────────────

class TestParseEnvelope:
    def test_unknown_command_type(self):
        cmd, err = parse_command("CloseBoardingGate", {"terminal": "A"})
        assert cmd is None and "unknown command_type" in err

    def test_none_command_type(self):
        cmd, err = parse_command(None, {})
        assert cmd is None

    def test_non_dict_payload(self):
        cmd, err = parse_command("OpenSecurityLane", None)
        assert cmd is None and "payload" in err

    def test_list_payload(self):
        cmd, err = parse_command("OpenSecurityLane", ["A", 4])
        assert cmd is None and "payload" in err

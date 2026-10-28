"""Unit tests for incident-service command parsing/preconditions (roadmap G6).

Covers the pure `incidents.commands` layer — the part with real branching.
The adapter path (Kafka consume → Neo4j contain/resolve → fact + receipt) is
exercised by the live integration test, not here.
"""

from tests.conftest import import_service_module

_cmd = import_service_module("incident", "application.commands")
parse_command = _cmd.parse_command
ContainIncident = _cmd.ContainIncident
ResolveIncident = _cmd.ResolveIncident
validate_contain_precondition = _cmd.validate_contain_precondition
validate_resolve_precondition = _cmd.validate_resolve_precondition


class TestParseContain:
    def test_valid(self):
        cmd, err = parse_command("ContainIncident", {"incident_id": "inc-1", "note": "n"})
        assert err is None
        assert cmd == ContainIncident(incident_id="inc-1", note="n")

    def test_note_defaults_empty(self):
        cmd, err = parse_command("ContainIncident", {"incident_id": "inc-1"})
        assert err is None
        assert cmd.note == ""

    def test_missing_incident_id(self):
        cmd, err = parse_command("ContainIncident", {"note": "n"})
        assert cmd is None and "incident_id" in err

    def test_empty_incident_id(self):
        cmd, err = parse_command("ContainIncident", {"incident_id": ""})
        assert cmd is None and "incident_id" in err

    def test_non_string_note_rejected(self):
        cmd, err = parse_command("ContainIncident", {"incident_id": "inc-1", "note": 5})
        assert cmd is None and "note" in err


class TestParseResolve:
    def test_valid(self):
        cmd, err = parse_command("ResolveIncident", {"incident_id": "inc-9", "note": "done"})
        assert err is None
        assert cmd == ResolveIncident(incident_id="inc-9", note="done")


class TestEnvelopeRejections:
    def test_unknown_type(self):
        cmd, err = parse_command("Nope", {"incident_id": "inc-1"})
        assert cmd is None and "unknown command_type" in err

    def test_none_type(self):
        cmd, err = parse_command(None, {"incident_id": "inc-1"})
        assert cmd is None and err is not None

    def test_non_dict_payload(self):
        cmd, err = parse_command("ContainIncident", ["not", "a", "dict"])
        assert cmd is None and "payload" in err


class TestPreconditions:
    def test_contain_only_from_active(self):
        assert validate_contain_precondition("active") is None
        assert validate_contain_precondition("contained") is not None
        assert validate_contain_precondition("resolved") is not None

    def test_resolve_from_active_or_contained(self):
        assert validate_resolve_precondition("active") is None
        assert validate_resolve_precondition("contained") is None

    def test_resolve_already_resolved_is_ok(self):
        # Idempotent no-op, not an error.
        assert validate_resolve_precondition("resolved") is None

    def test_resolve_unknown_status_rejected(self):
        assert validate_resolve_precondition("bogus") is not None

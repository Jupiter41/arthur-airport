"""Unit tests for gate compatibility constraints (GAP-3-8).

Verifies that:
- International flights require international-capable gates
- Wide-body aircraft require wide-body-capable gates
- Domestic/narrow-body flights have no extra constraints
"""

import asyncio
import importlib
import sys
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FLIGHT_SVC = os.path.join(ROOT, "services", "flight-service")

# Clear stale caches
for k in list(sys.modules):
    if k.startswith(("services.", "db.")):
        del sys.modules[k]
for p in [FLIGHT_SVC]:
    while p in sys.path:
        sys.path.remove(p)
sys.path.insert(0, FLIGHT_SVC)

# Stub out db.neo4j so gate_resolver can be imported without the neo4j driver
_mock_db = MagicMock()
sys.modules["db"] = _mock_db
sys.modules["db.neo4j"] = _mock_db

_gr = importlib.import_module("services.gate_resolver")
ensure_gate_assigned = _gr.ensure_gate_assigned
INTERNATIONAL_FLIGHT_TYPES = _gr.INTERNATIONAL_FLIGHT_TYPES
WIDE_BODY_TYPES = _gr.WIDE_BODY_TYPES

BASE_TIME = datetime(2025, 6, 15, 10, 0, 0)


class TestGateCapabilityFlags:
    """Verify the gate resolver knows which flight types are international / wide-body."""

    def test_international_short_is_international(self):
        assert "international_short" in INTERNATIONAL_FLIGHT_TYPES

    def test_international_long_is_international(self):
        assert "international_long" in INTERNATIONAL_FLIGHT_TYPES

    def test_domestic_not_international(self):
        assert "domestic" not in INTERNATIONAL_FLIGHT_TYPES

    def test_b77w_is_wide_body(self):
        assert "B77W" in WIDE_BODY_TYPES

    def test_a320_not_wide_body(self):
        assert "A320" not in WIDE_BODY_TYPES


def _run(coro):
    """Helper to run async function in tests without pytest-asyncio."""
    return asyncio.new_event_loop().run_until_complete(coro)


class TestGateAssignmentConstraints:
    """Verify ensure_gate_assigned passes capability requirements to get_available_gate."""

    def test_international_flight_requires_international_gate(self):
        """An international_long flight must request an international-capable gate."""
        captured_calls = []

        async def mock_get_available_gate(terminal_id, exclude_flight_id=None,
                                          require_international=False,
                                          require_wide_body=False):
            captured_calls.append({
                "terminal": terminal_id,
                "require_international": require_international,
                "require_wide_body": require_wide_body,
            })
            return "A03"

        async def mock_assign(flight_id, gate_id, sim_time):
            pass

        with patch.object(_gr, "get_available_gate", side_effect=mock_get_available_gate), \
             patch.object(_gr, "assign_flight_to_gate", side_effect=mock_assign):
            gate = _run(ensure_gate_assigned(
                "fl-001", None, "T-A", BASE_TIME,
                aircraft_type="A320",
                flight_type="international_long",
            ))

        assert gate == "A03"
        assert len(captured_calls) >= 1
        assert captured_calls[0]["require_international"] is True
        assert captured_calls[0]["require_wide_body"] is False

    def test_wide_body_flight_requires_wide_body_gate(self):
        """A B77W aircraft must request a wide-body-capable gate."""
        captured_calls = []

        async def mock_get_available_gate(terminal_id, exclude_flight_id=None,
                                          require_international=False,
                                          require_wide_body=False):
            captured_calls.append({
                "terminal": terminal_id,
                "require_international": require_international,
                "require_wide_body": require_wide_body,
            })
            return "A01"

        async def mock_assign(flight_id, gate_id, sim_time):
            pass

        with patch.object(_gr, "get_available_gate", side_effect=mock_get_available_gate), \
             patch.object(_gr, "assign_flight_to_gate", side_effect=mock_assign):
            gate = _run(ensure_gate_assigned(
                "fl-002", None, "T-A", BASE_TIME,
                aircraft_type="B77W",
                flight_type="domestic",
            ))

        assert gate == "A01"
        assert len(captured_calls) >= 1
        assert captured_calls[0]["require_international"] is False
        assert captured_calls[0]["require_wide_body"] is True

    def test_international_wide_body_requires_both(self):
        """An international wide-body must request both capabilities."""
        captured_calls = []

        async def mock_get_available_gate(terminal_id, exclude_flight_id=None,
                                          require_international=False,
                                          require_wide_body=False):
            captured_calls.append({
                "require_international": require_international,
                "require_wide_body": require_wide_body,
            })
            return "A02"

        async def mock_assign(flight_id, gate_id, sim_time):
            pass

        with patch.object(_gr, "get_available_gate", side_effect=mock_get_available_gate), \
             patch.object(_gr, "assign_flight_to_gate", side_effect=mock_assign):
            gate = _run(ensure_gate_assigned(
                "fl-003", None, "T-B", BASE_TIME,
                aircraft_type="B77W",
                flight_type="international_long",
            ))

        assert gate == "A02"
        assert captured_calls[0]["require_international"] is True
        assert captured_calls[0]["require_wide_body"] is True

    def test_domestic_narrow_body_no_constraints(self):
        """A domestic A320 flight has no special gate requirements."""
        captured_calls = []

        async def mock_get_available_gate(terminal_id, exclude_flight_id=None,
                                          require_international=False,
                                          require_wide_body=False):
            captured_calls.append({
                "require_international": require_international,
                "require_wide_body": require_wide_body,
            })
            return "C10"

        async def mock_assign(flight_id, gate_id, sim_time):
            pass

        with patch.object(_gr, "get_available_gate", side_effect=mock_get_available_gate), \
             patch.object(_gr, "assign_flight_to_gate", side_effect=mock_assign):
            gate = _run(ensure_gate_assigned(
                "fl-004", None, "T-C", BASE_TIME,
                aircraft_type="A320",
                flight_type="domestic",
            ))

        assert gate == "C10"
        assert captured_calls[0]["require_international"] is False
        assert captured_calls[0]["require_wide_body"] is False

    def test_no_gate_found_returns_none(self):
        """When no compatible gate is available, return None."""
        async def mock_get_available_gate(terminal_id, exclude_flight_id=None,
                                          require_international=False,
                                          require_wide_body=False):
            return None

        with patch.object(_gr, "get_available_gate", side_effect=mock_get_available_gate):
            gate = _run(ensure_gate_assigned(
                "fl-005", None, "T-C", BASE_TIME,
                aircraft_type="B77W",
                flight_type="international_long",
            ))

        assert gate is None

    def test_fallback_terminal_preserves_constraints(self):
        """When first terminal has no compatible gate, fallback terminals still enforce constraints."""
        call_count = 0

        async def mock_get_available_gate(terminal_id, exclude_flight_id=None,
                                          require_international=False,
                                          require_wide_body=False):
            nonlocal call_count
            call_count += 1
            assert require_international is True, \
                f"Fallback call #{call_count} lost require_international"
            if terminal_id == "T-C":
                return None
            return "B05"

        async def mock_assign(flight_id, gate_id, sim_time):
            pass

        with patch.object(_gr, "get_available_gate", side_effect=mock_get_available_gate), \
             patch.object(_gr, "assign_flight_to_gate", side_effect=mock_assign):
            gate = _run(ensure_gate_assigned(
                "fl-006", None, "T-C", BASE_TIME,
                aircraft_type="A320",
                flight_type="international_short",
            ))

        assert gate == "B05"
        assert call_count >= 2

"""Guards the single-source-of-truth for aircraft body-class + finance constants.

Before A3 the ``WIDE_BODY_TYPES`` set was copied into cost-service,
planning-service and flight-service and had drifted: cost listed ``A359`` but
not ``B748``/``A380``; planning/flight listed ``B748``/``A380`` but not
``A359``. A ``B748`` was wide-body for gate assignment but narrow-body for
ground-handling cost. These tests fail if any service re-introduces a private,
divergent copy.
"""

import json
import sys
from pathlib import Path

from tests.conftest import import_service_module

_SERVICES_DIR = Path(__file__).resolve().parents[2] / "services"

# The shared library lives at services/_common — make it importable at collection
# time (import_service_module also does this per-service, but we import directly).
if str(_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICES_DIR))

from _common.aircraft import WIDE_BODY_TYPES, aircraft_family


def test_canonical_set_is_the_full_union():
    # The union that carbon-tracking always used — now canonical for everyone.
    assert WIDE_BODY_TYPES == frozenset(
        {"A332", "A333", "A359", "A380", "B748", "B77W"}
    )


def test_a359_is_wide_body_and_a320_is_not():
    assert aircraft_family("A359") == "wide"
    assert aircraft_family("A380") == "wide"
    assert aircraft_family("B748") == "wide"
    assert aircraft_family("A320") == "narrow"


def test_flight_service_uses_the_canonical_set():
    """flight-service modules must import the shared set, not a private copy.

    Identity check: the same frozenset object proves they import from
    ``_common.aircraft`` rather than redefining it (a redefined literal would
    be an equal-but-distinct object — and historically a *divergent* one).
    """
    gate = import_service_module("flight", "services.gate_resolver")
    turn = import_service_module("flight", "services.turnaround")
    plan = import_service_module("flight", "services.turnaround_plan")
    assert gate.WIDE_BODY_TYPES is WIDE_BODY_TYPES
    assert turn.WIDE_BODY_TYPES is WIDE_BODY_TYPES
    assert plan.WIDE_BODY_TYPES is WIDE_BODY_TYPES
    # The concrete drift that used to exist: A359 must now be wide everywhere.
    assert "A359" in gate.WIDE_BODY_TYPES


def test_cost_service_uses_the_canonical_set():
    cost = import_service_module("cost", "services.cost_engine")
    assert cost.WIDE_BODY_TYPES is WIDE_BODY_TYPES


def test_finance_constants_match_cost_rates_fixture():
    """cost-service fixture fees must not drift from the shared constants."""
    from _common import finance_constants as fc

    rates_path = _SERVICES_DIR / "cost-service" / "fixtures" / "cost_rates.json"
    fees = json.loads(rates_path.read_text())["airport_fees"]

    assert fees["landing_rate_per_tonne_eur"] == fc.LANDING_FEE_PER_TONNE_EUR
    assert fees["gate_rate_per_hour_eur"] == fc.GATE_FEE_PER_HOUR_EUR
    assert fees["passenger_departure_fee_eur"] == fc.PAX_DEPARTURE_FEE_EUR

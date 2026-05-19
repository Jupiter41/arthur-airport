"""Unit tests for cost-service cost engine.

Tests all cost/revenue calculators with real rate fixtures, running totals
state management, and EU261 regulation compliance. Validates business
behaviour — not technical plumbing.
"""

import json
from pathlib import Path

import pytest

from tests.conftest import import_service_module

_engine = import_service_module("cost", "services.cost_engine")

compute_landing_fee = _engine.compute_landing_fee
compute_passenger_fee = _engine.compute_passenger_fee
compute_gate_fee = _engine.compute_gate_fee
compute_eu261 = _engine.compute_eu261
compute_holding_cost_per_tick = _engine.compute_holding_cost_per_tick
compute_ground_handling = _engine.compute_ground_handling
compute_incident_direct_cost = _engine.compute_incident_direct_cost
compute_incident_response_cost = _engine.compute_incident_response_cost
compute_staffing_cost_per_hour = _engine.compute_staffing_cost_per_hour
compute_retail_revenue_per_tick = _engine.compute_retail_revenue_per_tick
_aircraft_family = _engine._aircraft_family
_record_cost = _engine._record_cost
get_running_totals = _engine.get_running_totals
init_running_totals = _engine.init_running_totals
_running_totals = _engine._running_totals

# Load the actual cost_rates.json fixture used in production
FIXTURES_PATH = Path(__file__).parent.parent.parent / "services" / "cost-service" / "fixtures" / "cost_rates.json"

with open(FIXTURES_PATH) as f:
    RATES = json.load(f)


@pytest.fixture(autouse=True)
def reset_running_totals():
    """Reset running totals before each test to avoid state leakage."""
    _running_totals["total_cost_eur"] = 0.0
    _running_totals["total_revenue_eur"] = 0.0
    _running_totals["net_eur"] = 0.0
    _running_totals["by_category"].clear()
    _running_totals["eu261_exposure"] = 0.0
    _running_totals["last_updated"] = None
    yield


# ─── Aircraft family classification ──────────────────────────────


class TestAircraftFamily:
    def test_wide_body_types(self):
        for ac in ("B77W", "A333", "A332", "A359"):
            assert _aircraft_family(ac) == "wide", f"{ac} should be wide-body"

    def test_regional_types(self):
        for ac in ("DH8D", "E195", "AT75"):
            assert _aircraft_family(ac) == "regional", f"{ac} should be regional"

    def test_narrow_body_default(self):
        for ac in ("A320", "A321", "B738", "UNKNOWN"):
            assert _aircraft_family(ac) == "narrow", f"{ac} should default to narrow"


# ─── Landing fees ────────────────────────────────────────────────


class TestLandingFee:
    def test_a320_landing_fee(self):
        """A320 at 78t × €12/tonne = €936."""
        fee = compute_landing_fee("A320", RATES)
        assert fee == 936.0

    def test_wide_body_much_higher(self):
        """B77W (352t) should cost much more than A320 (78t)."""
        wide = compute_landing_fee("B77W", RATES)
        narrow = compute_landing_fee("A320", RATES)
        assert wide > narrow * 3

    def test_regional_lower(self):
        """Regional DH8D (29t) should cost less than narrow-body."""
        regional = compute_landing_fee("DH8D", RATES)
        narrow = compute_landing_fee("A320", RATES)
        assert regional < narrow

    def test_unknown_aircraft_uses_default_mtow(self):
        """Unknown type falls back to 78,000 kg default."""
        fee = compute_landing_fee("ZZZZ", RATES)
        assert fee == 78_000 / 1_000 * RATES["airport_fees"]["landing_rate_per_tonne_eur"]

    def test_all_known_types_nonzero(self):
        """Every known aircraft type produces a positive landing fee."""
        for ac_type in RATES["mtow_kg"]:
            assert compute_landing_fee(ac_type, RATES) > 0


# ─── Passenger fees ──────────────────────────────────────────────


class TestPassengerFee:
    def test_typical_pax_count(self):
        fee = compute_passenger_fee(180, RATES)
        assert fee == 180 * 12.0

    def test_zero_passengers(self):
        assert compute_passenger_fee(0, RATES) == 0.0


# ─── Gate fees ───────────────────────────────────────────────────


class TestGateFee:
    def test_one_hour(self):
        fee = compute_gate_fee(60, RATES)
        assert fee == 150.0

    def test_fractional_hours(self):
        """90 minutes = 1.5 hours × €150 = €225."""
        fee = compute_gate_fee(90, RATES)
        assert fee == 225.0

    def test_zero_minutes(self):
        assert compute_gate_fee(0, RATES) == 0.0


# ─── EU261 compensation ─────────────────────────────────────────


class TestEU261:
    """Validates EU Regulation 261/2004 compliance tiers."""

    def test_below_threshold_returns_zero(self):
        """Delays under 180 min never trigger EU261."""
        amount, desc = compute_eu261(179, 2000, 150, RATES)
        assert amount == 0.0
        assert "below" in desc.lower() or "threshold" in desc.lower()

    def test_exactly_180_min_short_haul(self):
        """180 min delay, <1500 km = €250 per pax."""
        amount, _ = compute_eu261(180, 1000, 100, RATES)
        assert amount == 25_000.0  # 100 pax × €250

    def test_180_min_medium_haul(self):
        """180 min delay, 1500–3500 km = €400 per pax."""
        amount, _ = compute_eu261(180, 2500, 100, RATES)
        assert amount == 40_000.0  # 100 pax × €400

    def test_180_min_long_haul(self):
        """180 min delay, >3500 km = €600 per pax."""
        amount, _ = compute_eu261(180, 5000, 100, RATES)
        assert amount == 60_000.0  # 100 pax × €600

    def test_pax_count_multiplier(self):
        """Compensation scales linearly with passenger count."""
        one = compute_eu261(200, 1000, 1, RATES)[0]
        ten = compute_eu261(200, 1000, 10, RATES)[0]
        assert ten == one * 10

    def test_description_contains_details(self):
        """Description includes pax count, compensation rate, distance, delay."""
        _, desc = compute_eu261(200, 2000, 150, RATES)
        assert "150 pax" in desc
        assert "€" in desc
        assert "200min" in desc

    def test_distance_boundary_1500(self):
        """At exactly 1500 km with 180 min delay: short-haul rate (€250)."""
        amount, _ = compute_eu261(180, 1500, 1, RATES)
        assert amount == 250.0

    def test_zero_passengers_zero_cost(self):
        """EU261 with zero passengers should cost nothing."""
        amount, _ = compute_eu261(300, 2000, 0, RATES)
        assert amount == 0.0


# ─── Holding fuel costs ─────────────────────────────────────────


class TestHoldingFuel:
    def test_wide_body_burns_more(self):
        wide = compute_holding_cost_per_tick("B77W", 5, RATES)
        narrow = compute_holding_cost_per_tick("A320", 5, RATES)
        assert wide > narrow * 2

    def test_regional_burns_least(self):
        regional = compute_holding_cost_per_tick("DH8D", 5, RATES)
        narrow = compute_holding_cost_per_tick("A320", 5, RATES)
        assert regional < narrow

    def test_scales_with_time(self):
        five = compute_holding_cost_per_tick("A320", 5, RATES)
        ten = compute_holding_cost_per_tick("A320", 10, RATES)
        assert abs(ten - five * 2) < 0.01

    def test_zero_minutes_zero_cost(self):
        assert compute_holding_cost_per_tick("A320", 0, RATES) == 0.0


# ─── Ground handling ────────────────────────────────────────────


class TestGroundHandling:
    def test_wide_body_catering_higher(self):
        wide = compute_ground_handling("B77W", 200, RATES)
        narrow = compute_ground_handling("A320", 200, RATES)
        assert wide["catering"] > narrow["catering"]
        assert wide["cleaning"] > narrow["cleaning"]

    def test_pushback_same_for_all(self):
        """Pushback cost doesn't vary by aircraft type."""
        wide = compute_ground_handling("B77W", 100, RATES)
        narrow = compute_ground_handling("A320", 100, RATES)
        assert wide["pushback"] == narrow["pushback"]

    def test_baggage_scales_with_count(self):
        low = compute_ground_handling("A320", 50, RATES)
        high = compute_ground_handling("A320", 200, RATES)
        assert high["baggage_loading"] == low["baggage_loading"] * 4

    def test_all_categories_present(self):
        result = compute_ground_handling("A320", 100, RATES)
        expected_keys = {"pushback", "catering", "cleaning", "jetbridge", "baggage_loading"}
        assert set(result.keys()) == expected_keys

    def test_all_positive(self):
        result = compute_ground_handling("A320", 100, RATES)
        for k, v in result.items():
            assert v > 0, f"{k} should be positive"


# ─── Incident costs ─────────────────────────────────────────────


class TestIncidentCosts:
    def test_known_type_direct_cost(self):
        for itype in ("runway_incursion", "baggage_fire", "security_breach", "system_failure"):
            cost = compute_incident_direct_cost(itype, RATES)
            assert cost > 0, f"{itype} should have a direct cost"

    def test_severe_weather_zero_direct(self):
        """Severe weather has zero direct cost (only response cost)."""
        assert compute_incident_direct_cost("severe_weather", RATES) == 0.0

    def test_unknown_type_zero(self):
        assert compute_incident_direct_cost("alien_invasion", RATES) == 0.0

    def test_security_breach_most_expensive(self):
        """Security breach should have highest direct cost."""
        breach = compute_incident_direct_cost("security_breach", RATES)
        for itype in ("runway_incursion", "baggage_fire", "system_failure"):
            assert breach > compute_incident_direct_cost(itype, RATES)

    def test_response_cost_base(self):
        """Response cost at ≤30 min equals base rate."""
        cost = compute_incident_response_cost("runway_incursion", 30, RATES)
        assert cost == RATES["incident_costs"]["runway_incursion"]["response_eur"]

    def test_response_cost_increases_with_time(self):
        """Response cost at 60 min > 30 min."""
        short = compute_incident_response_cost("runway_incursion", 30, RATES)
        long = compute_incident_response_cost("runway_incursion", 60, RATES)
        assert long > short

    def test_response_cost_unknown_type(self):
        assert compute_incident_response_cost("unknown", 30, RATES) == 0.0

    def test_response_extra_periods(self):
        """45 min = base + 1 extra period (25% surcharge)."""
        base = RATES["incident_costs"]["runway_incursion"]["response_eur"]
        cost = compute_incident_response_cost("runway_incursion", 45, RATES)
        expected = round(base * 1.25, 2)
        assert cost == expected


# ─── Staffing costs ──────────────────────────────────────────────


class TestStaffingCosts:
    def test_peak_hours_more_expensive(self):
        peak = compute_staffing_cost_per_hour(8, 10, 12, RATES)
        off_peak = compute_staffing_cost_per_hour(3, 2, 4, RATES)
        total_peak = sum(peak.values())
        total_off = sum(off_peak.values())
        assert total_peak > total_off

    def test_all_categories_present(self):
        result = compute_staffing_cost_per_hour(5, 5, 5, RATES)
        assert set(result.keys()) == {"security", "checkin", "gate"}

    def test_zero_resources_zero_cost(self):
        result = compute_staffing_cost_per_hour(0, 0, 0, RATES)
        assert all(v == 0 for v in result.values())


# ─── Retail revenue ──────────────────────────────────────────────


class TestRetailRevenue:
    def test_positive_with_passengers(self):
        rev = compute_retail_revenue_per_tick(2000, 10, RATES)
        assert rev > 0

    def test_zero_pax_zero_revenue(self):
        assert compute_retail_revenue_per_tick(0, 10, RATES) == 0.0

    def test_scales_with_pax(self):
        low = compute_retail_revenue_per_tick(100, 10, RATES)
        high = compute_retail_revenue_per_tick(1000, 10, RATES)
        assert high == low * 10

    def test_scales_with_time(self):
        short = compute_retail_revenue_per_tick(1000, 5, RATES)
        long = compute_retail_revenue_per_tick(1000, 10, RATES)
        assert abs(long - short * 2) < 0.01


# ─── Running totals state management ────────────────────────────


class TestRunningTotals:
    def test_cost_accumulates(self):
        _record_cost(100.0, "landing_fee", is_revenue=False)
        _record_cost(200.0, "landing_fee", is_revenue=False)
        totals = get_running_totals()
        assert totals["total_cost_eur"] == 300.0

    def test_revenue_accumulates(self):
        _record_cost(500.0, "landing_fee", is_revenue=True)
        totals = get_running_totals()
        assert totals["total_revenue_eur"] == 500.0
        assert totals["total_cost_eur"] == 0.0

    def test_net_calculation(self):
        _record_cost(1000.0, "landing_fee", is_revenue=True)
        _record_cost(400.0, "landing_fee", is_revenue=False)
        totals = get_running_totals()
        assert totals["net_eur"] == 600.0

    def test_by_category_bucketing(self):
        _record_cost(100.0, "landing_fee", is_revenue=False)
        _record_cost(200.0, "ground_handling", is_revenue=False)
        _record_cost(50.0, "landing_fee", is_revenue=False)
        totals = get_running_totals()
        assert totals["by_category"]["landing_fee"] == 150.0
        assert totals["by_category"]["ground_handling"] == 200.0

    def test_eu261_exposure_tracked(self):
        _record_cost(25000.0, "eu261_compensation", is_revenue=False)
        _record_cost(10000.0, "eu261_compensation", is_revenue=False)
        totals = get_running_totals()
        assert totals["eu261_exposure"] == 35000.0

    def test_non_eu261_not_in_exposure(self):
        _record_cost(1000.0, "landing_fee", is_revenue=False)
        totals = get_running_totals()
        assert totals["eu261_exposure"] == 0.0

    def test_last_updated_set(self):
        _record_cost(100.0, "landing_fee", is_revenue=False)
        totals = get_running_totals()
        assert totals["last_updated"] is not None

    def test_returns_dict_not_defaultdict(self):
        _record_cost(100.0, "landing_fee", is_revenue=False)
        totals = get_running_totals()
        assert type(totals["by_category"]) is dict

    def test_init_from_neo4j_restore(self):
        """init_running_totals restores from persisted state."""
        init_running_totals({
            "total_cost_eur": 50000.0,
            "total_revenue_eur": 80000.0,
            "net_eur": 30000.0,
            "by_category": {"landing_fee": 20000.0, "staffing": 30000.0},
        })
        totals = get_running_totals()
        assert totals["total_cost_eur"] == 50000.0
        assert totals["total_revenue_eur"] == 80000.0
        assert totals["by_category"]["landing_fee"] == 20000.0

    def test_init_handles_missing_keys(self):
        """init_running_totals handles missing keys gracefully."""
        init_running_totals({})
        totals = get_running_totals()
        assert totals["total_cost_eur"] == 0.0

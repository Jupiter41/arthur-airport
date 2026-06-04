"""Unit tests for cost-service P1/P2 additions:

* Gate-fee occupancy calculator (already a pure function).
* Per-airline rate overrides.
* Recommendations 95 % CI band.
* Valuation engine (EBITDA, sensitivity, thesis).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.conftest import import_service_module

# Import recommendations first — it pulls in cost_engine as a dependency.
# We then resolve cost_engine via sys.modules so both modules share the same
# global state (in particular _daily_history).
_rec = import_service_module("cost", "services.recommendations")
_engine = sys.modules["services.cost_engine"]
_val = import_service_module("cost", "services.valuation")
# Re-import recommendations to keep the same shared cost_engine after _val swap.
_rec = import_service_module("cost", "services.recommendations")
_engine = sys.modules["services.cost_engine"]
_fuel = import_service_module("cost", "services.fuel_price")

FIXTURES_PATH = (
    Path(__file__).parent.parent.parent
    / "services"
    / "cost-service"
    / "fixtures"
    / "cost_rates.json"
)
with open(FIXTURES_PATH) as f:
    RATES = json.load(f)


# ─── Gate fee ───────────────────────────────────────────────────


class TestGateFee:
    def test_zero_minutes_zero_fee(self):
        assert _engine.compute_gate_fee(0, RATES) == 0.0

    def test_one_hour_matches_hourly_rate(self):
        rate = RATES["airport_fees"]["gate_rate_per_hour_eur"]
        assert _engine.compute_gate_fee(60, RATES) == pytest.approx(rate)

    def test_partial_hour_prorated(self):
        rate = RATES["airport_fees"]["gate_rate_per_hour_eur"]
        # 30 minutes = 0.5 h
        assert _engine.compute_gate_fee(30, RATES) == pytest.approx(rate * 0.5)


# ─── Per-airline overrides ──────────────────────────────────────


class TestAirlineCodeExtraction:
    def test_iata_two_letter(self):
        assert _engine._airline_code_from_flight_number("AF1234") == "AF"

    def test_three_letter_icao_like(self):
        assert _engine._airline_code_from_flight_number("BAW123") == "BAW"

    def test_lowercase_normalised(self):
        assert _engine._airline_code_from_flight_number("af1234") == "AF"

    def test_empty_returns_none(self):
        assert _engine._airline_code_from_flight_number("") is None
        assert _engine._airline_code_from_flight_number(None) is None

    def test_numeric_only_returns_none(self):
        assert _engine._airline_code_from_flight_number("1234") is None


class TestResolveRatesForAirline:
    def test_no_code_returns_base(self):
        out = _engine.resolve_rates_for_airline(RATES, None)
        assert out is RATES  # identity — no copy when nothing changes

    def test_unknown_code_returns_base(self):
        out = _engine.resolve_rates_for_airline(RATES, "ZZ")
        assert out is RATES

    def test_known_airline_overrides_passenger_fee(self):
        # FR fixture has passenger_departure_fee_eur = 9.5 (vs base 12.0)
        out = _engine.resolve_rates_for_airline(RATES, "FR")
        assert out["airport_fees"]["passenger_departure_fee_eur"] == 9.5
        # Untouched leaves remain
        assert (
            out["airport_fees"]["landing_rate_per_tonne_eur"]
            == RATES["airport_fees"]["landing_rate_per_tonne_eur"]
        )

    def test_override_does_not_mutate_base(self):
        base_before = json.dumps(RATES, sort_keys=True)
        _engine.resolve_rates_for_airline(RATES, "EK")
        base_after = json.dumps(RATES, sort_keys=True)
        assert base_before == base_after

    def test_override_is_used_by_passenger_fee(self):
        out_base = _engine.compute_passenger_fee(100, RATES)
        out_fr = _engine.compute_passenger_fee(
            100, _engine.resolve_rates_for_airline(RATES, "FR")
        )
        assert out_fr < out_base  # FR has discounted rate


# ─── Recommendations CI ─────────────────────────────────────────


class TestRecommendationsCI:
    @pytest.fixture(autouse=True)
    def _clear_history(self):
        _engine.reset_daily_history()
        yield
        _engine.reset_daily_history()

    def test_ci_none_when_no_history(self):
        totals = {
            "total_cost_eur": 200_000,
            "by_category": {"holding_fuel": 10_000, "ground_handling": 60_000},
            "eu261_exposure": 20_000,
            "last_updated": "2024-06-15T14:30:00",
        }
        recs = _rec.generate_recommendations(totals, "2024-06-15T14:30:00", RATES)
        assert all(r["saving_eur_ci"] is None for r in recs)

    def test_ci_populated_after_two_day_transitions(self):
        # Seed the rolling history by triggering two day-transitions through
        # the engine's _record_cost path.
        _engine.init_running_totals({"sim_day": 1})
        _engine._record_cost(
            5_000.0, "eu261_compensation", is_revenue=False, sim_day=1
        )
        # Transition to day 2 — snapshot day 1.
        _engine._record_cost(
            7_000.0, "eu261_compensation", is_revenue=False, sim_day=2
        )
        # Transition to day 3 — snapshot day 2.
        _engine._record_cost(
            6_000.0, "eu261_compensation", is_revenue=False, sim_day=3
        )

        totals = _engine.get_running_totals()
        # Force trigger threshold
        totals["eu261_exposure"] = 20_000
        recs = _rec.generate_recommendations(totals, "2024-06-17T14:30:00", RATES)
        sec = next(r for r in recs if r["action"] == "open_security_lane")
        ci = sec["saving_eur_ci"]
        assert ci is not None
        assert ci["sample_days"] == 2
        assert ci["low_eur"] <= ci["high_eur"]


# ─── Valuation ─────────────────────────────────────────────────


def _sample_pnl() -> dict:
    return {
        "sim_day": 5,
        "costs": [
            {"category": "staffing", "total": 50_000.0},
            {"category": "incident_direct", "total": 8_000.0},
            {"category": "incident_response", "total": 2_000.0},
            {"category": "ground_handling", "total": 30_000.0},
            {"category": "holding_fuel", "total": 4_000.0},
            {"category": "eu261_compensation", "total": 12_000.0},
        ],
        "revenues": [
            {"category": "landing_fee", "total": 25_000.0},
            {"category": "passenger_fee", "total": 80_000.0},
            {"category": "gate_fee", "total": 5_000.0},
            {"category": "slot_revenue", "total": 6_000.0},
            {"category": "retail_revenue", "total": 14_000.0},
        ],
    }


class TestValuationEbitda:
    def test_baseline_ebitda(self):
        out = _val.build_ebitda(_sample_pnl(), horizon="day")
        assert out["revenue"]["total_eur_daily"] == 130_000.0
        assert out["airport_opex"]["total_eur_daily"] == 60_000.0
        assert out["ebitda"]["daily_eur"] == 70_000.0
        assert out["ebitda"]["margin_pct"] == pytest.approx(53.8, rel=1e-2)

    def test_horizon_year_multiplies_by_365(self):
        out = _val.build_ebitda(_sample_pnl(), horizon="year")
        assert out["multiplier_days"] == 365
        assert out["ebitda"]["horizon_eur"] == pytest.approx(70_000.0 * 365)

    def test_pass_through_excluded_from_ebitda(self):
        out = _val.build_ebitda(_sample_pnl(), horizon="day")
        assert "ground_handling" in out["pass_through"]["by_stream"]
        assert "ground_handling" not in out["airport_opex"]["by_stream"]

    def test_unknown_horizon_raises(self):
        with pytest.raises(ValueError):
            _val.build_ebitda(_sample_pnl(), horizon="decade")  # type: ignore[arg-type]


class TestValuationSensitivity:
    def test_zero_scenario_matches_baseline(self):
        base = _val.build_ebitda(_sample_pnl(), horizon="day")
        scenarios = _val.run_sensitivity(
            base,
            demand_growth=[0.0],
            fuel_price_pct=[0.0],
            eu261_rate_pct=[0.0],
        )
        assert len(scenarios) == 1
        assert scenarios[0]["ebitda_daily_eur"] == base["ebitda"]["daily_eur"]

    def test_positive_growth_increases_ebitda(self):
        base = _val.build_ebitda(_sample_pnl(), horizon="day")
        scenarios = _val.run_sensitivity(
            base,
            demand_growth=[0.10],
            fuel_price_pct=[0.0],
            eu261_rate_pct=[0.0],
        )
        assert scenarios[0]["ebitda_daily_eur"] > base["ebitda"]["daily_eur"]

    def test_cartesian_product_size(self):
        base = _val.build_ebitda(_sample_pnl(), horizon="day")
        scenarios = _val.run_sensitivity(
            base,
            demand_growth=[-0.1, 0.0, 0.1],
            fuel_price_pct=[-0.3, 0.3],
            eu261_rate_pct=[-0.5, 0.5],
        )
        assert len(scenarios) == 3 * 2 * 2


class TestValuationThesis:
    def test_thesis_exposes_required_keys(self):
        base = _val.build_ebitda(_sample_pnl(), horizon="year")
        scenarios = _val.run_sensitivity(
            base, demand_growth=[-0.05, 0.05], fuel_price_pct=[0.0], eu261_rate_pct=[0.0]
        )
        thesis = _val.build_thesis(base, scenarios)
        assert {"summary", "ebitda_range_daily_eur", "scenarios", "risk_factors", "investment_recommendation"} <= set(thesis.keys())
        # Range must respect ordering invariants.
        rng = thesis["ebitda_range_daily_eur"]
        assert rng["low"] <= rng["midpoint"] <= rng["high"]


# ─── Fuel price feed ───────────────────────────────────────────


class TestFuelPriceCoercion:
    def test_valid_price(self):
        assert _fuel._coerce_price({"price_eur_per_kg": 1.05}) == 1.05

    def test_aliases(self):
        assert _fuel._coerce_price({"price": 0.85}) == 0.85
        assert _fuel._coerce_price({"value": 1.10}) == 1.10

    def test_invalid_returns_none(self):
        assert _fuel._coerce_price({}) is None
        assert _fuel._coerce_price({"price": -1.0}) is None
        assert _fuel._coerce_price({"price": 99.0}) is None  # sanity guard
        assert _fuel._coerce_price("not a dict") is None

    def test_apply_to_rates_patches_in_place(self):
        rates = {"delay_costs": {"fuel_price_per_kg_eur": 0.9}}
        _fuel.apply_to_rates(rates, {"price_eur_per_kg": 1.20, "as_of": "2026-06-04", "source": "test"})
        assert rates["delay_costs"]["fuel_price_per_kg_eur"] == 1.20
        assert rates["_meta"]["fuel_price"]["value_eur_per_kg"] == 1.20
        assert rates["_meta"]["fuel_price"]["source"] == "test"

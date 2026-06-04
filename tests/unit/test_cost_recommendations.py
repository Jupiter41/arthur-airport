"""Unit tests for cost-service financial recommendation engine.

Tests that recommendations are triggered by the correct operational thresholds,
produce valid financial projections, and follow business rules.
"""

import json
from pathlib import Path


from tests.conftest import import_service_module

_rec = import_service_module("cost", "services.recommendations")
generate_recommendations = _rec.generate_recommendations
FinancialRecommendation = _rec.FinancialRecommendation

FIXTURES_PATH = Path(__file__).parent.parent.parent / "services" / "cost-service" / "fixtures" / "cost_rates.json"

with open(FIXTURES_PATH) as f:
    RATES = json.load(f)

SIM_TIME = "2024-06-15T14:30:00"


def _make_totals(**overrides) -> dict:
    base = {
        "total_cost_eur": 0.0,
        "total_revenue_eur": 0.0,
        "net_eur": 0.0,
        "by_category": {},
        "eu261_exposure": 0.0,
        "last_updated": SIM_TIME,
    }
    base.update(overrides)
    return base


class TestNoRecommendations:
    def test_calm_airport_returns_empty(self):
        """A healthy airport with low costs should produce no recommendations."""
        totals = _make_totals(total_cost_eur=5000)
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        assert recs == []


class TestSecurityLaneRecommendation:
    def test_triggered_by_high_eu261_exposure(self):
        """EU261 exposure > €10k triggers open_security_lane."""
        totals = _make_totals(eu261_exposure=15000)
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        actions = [r["action"] for r in recs]
        assert "open_security_lane" in actions

    def test_not_triggered_below_threshold(self):
        totals = _make_totals(eu261_exposure=5000)
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        actions = [r["action"] for r in recs]
        assert "open_security_lane" not in actions

    def test_net_benefit_positive(self):
        """The saving should exceed the staffing cost."""
        totals = _make_totals(eu261_exposure=50000)
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        lane_rec = next(r for r in recs if r["action"] == "open_security_lane")
        assert lane_rec["net_benefit_eur"] > 0
        assert lane_rec["saving_eur"] > lane_rec["cost_eur"]


class TestGroundDelayProgram:
    def test_triggered_by_high_holding_cost(self):
        totals = _make_totals(by_category={"holding_fuel": 8000})
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        actions = [r["action"] for r in recs]
        assert "ground_delay_program" in actions

    def test_not_triggered_below_threshold(self):
        totals = _make_totals(by_category={"holding_fuel": 2000})
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        actions = [r["action"] for r in recs]
        assert "ground_delay_program" not in actions

    def test_net_benefit_positive(self):
        totals = _make_totals(by_category={"holding_fuel": 20000})
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        gdp = next(r for r in recs if r["action"] == "ground_delay_program")
        assert gdp["net_benefit_eur"] > 0


class TestGateReassignment:
    def test_triggered_by_high_handling_cost(self):
        totals = _make_totals(by_category={"ground_handling": 60000})
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        actions = [r["action"] for r in recs]
        assert "gate_reassignment" in actions

    def test_not_triggered_below_threshold(self):
        totals = _make_totals(by_category={"ground_handling": 30000})
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        actions = [r["action"] for r in recs]
        assert "gate_reassignment" not in actions


class TestMakeupCarousel:
    def test_triggered_by_high_total_cost(self):
        totals = _make_totals(total_cost_eur=150000)
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        actions = [r["action"] for r in recs]
        assert "open_makeup_carousel" in actions

    def test_not_triggered_below_threshold(self):
        totals = _make_totals(total_cost_eur=50000)
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        actions = [r["action"] for r in recs]
        assert "open_makeup_carousel" not in actions


class TestRecommendationSchema:
    def test_all_recommendations_have_required_fields(self):
        """Every recommendation must match FinancialRecommendation shape."""
        totals = _make_totals(
            eu261_exposure=20000,
            total_cost_eur=200000,
            by_category={"holding_fuel": 10000, "ground_handling": 60000},
        )
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        assert len(recs) == 4  # all 4 recommendations triggered

        required = {
            "action", "description", "cost_eur", "saving_eur",
            "net_benefit_eur", "confidence", "payback_sim_minutes",
            "expiry_sim_time", "saving_eur_ci",
        }
        for rec in recs:
            assert set(rec.keys()) == required, f"Missing keys in {rec['action']}"
            # CI is None unless ≥2 historical days are available; when present
            # it must expose low/high/sample_days as numerics.
            ci = rec["saving_eur_ci"]
            if ci is not None:
                assert {"low_eur", "high_eur", "sample_days"} <= set(ci.keys())
                assert ci["low_eur"] <= ci["high_eur"]

    def test_confidence_in_valid_range(self):
        totals = _make_totals(
            eu261_exposure=20000,
            total_cost_eur=200000,
            by_category={"holding_fuel": 10000, "ground_handling": 60000},
        )
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        for rec in recs:
            assert 0.0 <= rec["confidence"] <= 1.0, f"{rec['action']} confidence out of range"

    def test_net_benefit_equals_saving_minus_cost(self):
        totals = _make_totals(
            eu261_exposure=20000,
            total_cost_eur=200000,
            by_category={"holding_fuel": 10000, "ground_handling": 60000},
        )
        recs = generate_recommendations(totals, SIM_TIME, RATES)
        for rec in recs:
            expected = round(rec["saving_eur"] - rec["cost_eur"], 2)
            assert rec["net_benefit_eur"] == expected, f"{rec['action']} net_benefit mismatch"

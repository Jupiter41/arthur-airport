"""Airport profit must never absorb airline expense or airline savings."""

from datetime import date

import pytest

from tests.conftest import import_service_module


@pytest.mark.parametrize("delay,distance,pax", [
    (179, 1000, 100), (180, 1000, 101), (180, 1500, 100),
    (180, 3500, 100), (180, 5000, 100), (240, 5000, 100), (300, 2000, 0),
])
def test_live_and_planning_full_compensation_agree(delay, distance, pax):
    live = import_service_module("cost", "services.cost_engine")
    planning = import_service_module("planning", "engine.simulation")
    from _common.financial_rates import load_default_rates

    rates = load_default_rates()
    actual = live.compute_eu261(delay, distance, pax, rates)[0]
    assert planning.PlanningSimEngine._compute_eu261(delay, distance, pax, rates) == actual
    if delay >= 180 and distance <= 1500:
        assert actual == pax * 250


def test_known_fee_pairs_and_airline_liability_do_not_cancel_airport_revenue():
    import_service_module("cost", "services.cost_engine")
    from _common.accounting import add_amount, empty_totals

    totals = empty_totals()
    for category, amount, revenue in [
        ("landing_fee", 1000, False), ("landing_fee", 1000, True),
        ("passenger_fee", 1200, False), ("passenger_fee", 1200, True),
        ("gate_fee", 200, False), ("gate_fee", 200, True),
        ("staffing", 300, False), ("incident_response", 100, False),
        ("eu261_compensation", 25000, False), ("holding_fuel", 500, False),
    ]:
        add_amount(totals, category, amount, revenue)
    assert totals["total_revenue_eur"] == 2400
    assert totals["total_cost_eur"] == 400
    assert totals["net_eur"] == 2000
    assert totals["airline_cost_eur"] == 27900
    assert set(totals["by_category"]) == {"staffing", "incident_response"}


def test_airport_npv_uses_airport_savings_and_preserves_negative_benefits():
    benefit = import_service_module("planning", "finance.benefit_extractor")
    from engine.results import KPIDistribution as KPI

    baseline = {"total_cost_eur": KPI(mean=300), "total_revenue_eur": KPI(mean=1000),
                "eu261_liability_eur": KPI(mean=25000), "avg_delay_minutes": KPI(mean=180)}
    scenario = {"total_cost_eur": KPI(mean=400), "total_revenue_eur": KPI(mean=900),
                "eu261_liability_eur": KPI(mean=0), "avg_delay_minutes": KPI(mean=0)}
    result = benefit.extract_annual_benefit(baseline, scenario, operating_days_per_year=10)
    assert result.eu261_avoided_annual == 250000
    assert result.delay_cost_avoided_annual > 0
    assert result.total_annual_benefit == -2000


def test_planning_result_separates_airline_costs():
    sim = import_service_module("planning", "engine.simulation")
    from engine.infrastructure import InfrastructureConfig

    engine = sim.PlanningSimEngine(adapter=None)
    state = sim.PlanningSimState()
    state.costs.update(landing_fees=1000, gate_fees=200, delay=100, eu261=25000, incident=50)
    state.revenues.update(landing_fees=1000, gate_fees=200)
    result = engine._build_result(state, date(2026, 1, 1), InfrastructureConfig(), 0)
    assert result.total_cost_eur == 50
    assert result.airline_cost_eur == 26300
    assert result.net_eur == 1150
    assert result.to_dict()["accounting_policy"] == "airport-v1"

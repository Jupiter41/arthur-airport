"""Rate changes must be atomic, validated and consistent across calculators."""

from copy import deepcopy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services"))
from _common.financial_rates import load_default_rates, merge_rates, rates_version, resolve_rates_for_airline


@pytest.mark.parametrize("bad", [True, -1, float("inf"), float("nan"), "42", None])
def test_invalid_late_field_does_not_apply_earlier_valid_field(bad):
    original = load_default_rates()
    before = deepcopy(original)
    with pytest.raises(ValueError):
        merge_rates(original, {"airport_fees": {"landing_rate_per_tonne_eur": 42,
                                              "passenger_departure_fee_eur": bad}})
    assert original == before


def test_unknown_nested_fields_and_invalid_tiers_are_rejected():
    rates = load_default_rates()
    for patch in ({"airport_fees": {"typo": 4}}, {"eu261": []},
                  {"airline_overrides": {"invalid": {}}}):
        with pytest.raises(ValueError):
            merge_rates(rates, patch)


def test_new_synthetic_carrier_override_uses_same_resolver_and_content_identity():
    defaults = load_default_rates()
    rates = merge_rates(defaults, {"airline_overrides": {"ZZ": {
        "airport_fees": {"passenger_departure_fee_eur": 31},
    }}})
    assert resolve_rates_for_airline(rates, "ZZ")["airport_fees"]["passenger_departure_fee_eur"] == 31
    assert defaults["airport_fees"]["passenger_departure_fee_eur"] == 12
    assert rates_version(rates) != rates_version(defaults)
    assert rates_version(rates) == rates_version(dict(reversed(list(rates.items()))))


def test_benefit_extractor_uses_snapshotted_delay_valuation_and_operating_days():
    from tests.conftest import import_service_module

    benefit = import_service_module("planning", "finance.benefit_extractor")
    from engine.results import KPIDistribution

    rates = load_default_rates()
    rates["planning_assumptions"].update(delay_cost_per_minute_eur=7, operating_days_per_year=10)
    baseline = {"avg_delay_minutes": KPIDistribution(mean=4)}
    scenario = {"avg_delay_minutes": KPIDistribution(mean=1), "total_flights": KPIDistribution(mean=5)}
    result = benefit.extract_annual_benefit(baseline, scenario, financial_rates=rates)
    assert result.delay_cost_avoided_annual == (4 - 1) * 5 * 7 * 10

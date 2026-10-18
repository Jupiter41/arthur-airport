"""Compatibility exports derived from the shared synthetic default rate table.

Live inputs use the committed cost-owner table; planning jobs use their persisted
snapshot. These names are default references, never an independently editable table.
"""

from _common.financial_rates import load_default_rates

_rates = load_default_rates()
_assumptions = _rates["planning_assumptions"]
DELAY_COST_PER_MINUTE_EUR: float = _assumptions["delay_cost_per_minute_eur"]
REBOOKING_COST_PER_PAX_EUR: float = _assumptions["rebooking_cost_per_pax_eur"]
EU261_AVERAGE_CLAIM_EUR: float = _assumptions["eu261_average_claim_eur"]
OPERATING_DAYS_PER_YEAR: int = _assumptions["operating_days_per_year"]
EU261_TIERS: tuple[tuple[int, int, int], ...] = tuple(
    (row["min_delay_minutes"], row["max_distance_km"], row["compensation_eur"])
    for row in _rates["eu261"] if not row.get("assistance_only")
)
LANDING_FEE_PER_TONNE_EUR: float = _rates["airport_fees"]["landing_rate_per_tonne_eur"]
GATE_FEE_PER_HOUR_EUR: float = _rates["airport_fees"]["gate_rate_per_hour_eur"]
PAX_DEPARTURE_FEE_EUR: float = _rates["airport_fees"]["passenger_departure_fee_eur"]

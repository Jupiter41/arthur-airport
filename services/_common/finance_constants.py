"""Single source of truth for cross-service financial constants.

Values are sourced from Eurocontrol Standard Inputs (2024) — the European
reference for ATFM delay costs, EU261 compensation tiers, and average
rebooking costs. Importing from one place avoids drift between cost-service
analytics and planning-service simulation.

If you need to tune a value, change it here. Cost-service's runtime rates
(``cost_rates.json``) override these defaults for live engine calculations;
the constants exposed here are the **canonical Eurocontrol values** used by
planning simulations (which do not consume the runtime rate table).
"""

from __future__ import annotations

# All-in cost per minute of ATFM delay (crew, fuel, pax, recovery).
DELAY_COST_PER_MINUTE_EUR: float = 102.0

# Average rebooking + accommodation cost per disrupted passenger.
REBOOKING_COST_PER_PAX_EUR: float = 285.0

# Average EU261 compensation per claiming passenger.
EU261_AVERAGE_CLAIM_EUR: float = 400.0

# Standard EU261 compensation tiers (delay_minutes, max_distance_km, eur).
# Sorted so that the first matching row is the applicable compensation.
EU261_TIERS: tuple[tuple[int, int, int], ...] = (
    (180, 1500, 250),
    (180, 3500, 400),
    (180, 99_999, 600),
    (240, 99_999, 600),
)

# Operating days per year for annualisation of daily KPIs.
OPERATING_DAYS_PER_YEAR: int = 365

# Airport fees (mid-sized European reference values).
LANDING_FEE_PER_TONNE_EUR: float = 12.0
GATE_FEE_PER_HOUR_EUR: float = 150.0
PAX_DEPARTURE_FEE_EUR: float = 12.0

"""Annual benefit extraction from scenario comparison results.

P4.2 of ROADMAP_PLANNING.md.

Converts the delta between scenario and baseline DayResults into annual
financial benefit estimates using Eurocontrol Standard Inputs values.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from _common.finance_constants import (
    DELAY_COST_PER_MINUTE_EUR,
    EU261_AVERAGE_CLAIM_EUR,
    OPERATING_DAYS_PER_YEAR,
    REBOOKING_COST_PER_PAX_EUR,
)
from engine.results import KPIDistribution

logger = logging.getLogger(__name__)

# Re-exported here for backwards-compatibility with callers that import from
# this module. The canonical definitions live in services/_common/finance_constants.py.
__all__ = [
    "DELAY_COST_PER_MINUTE_EUR",
    "EU261_AVERAGE_CLAIM_EUR",
    "OPERATING_DAYS_PER_YEAR",
    "REBOOKING_COST_PER_PAX_EUR",
    "AnnualBenefitBreakdown",
    "extract_annual_benefit",
]


@dataclass
class AnnualBenefitBreakdown:
    """Breakdown of annual financial benefits from a scenario vs baseline."""

    eu261_avoided_annual: float = 0.0
    delay_cost_avoided_annual: float = 0.0
    missed_connections_avoided_annual: float = 0.0
    revenue_uplift_annual: float = 0.0
    total_annual_benefit: float = 0.0

    def to_dict(self) -> dict:
        return {
            "eu261_avoided_annual": round(self.eu261_avoided_annual, 2),
            "delay_cost_avoided_annual": round(self.delay_cost_avoided_annual, 2),
            "missed_connections_avoided_annual": round(self.missed_connections_avoided_annual, 2),
            "revenue_uplift_annual": round(self.revenue_uplift_annual, 2),
            "total_annual_benefit": round(self.total_annual_benefit, 2),
        }


def extract_annual_benefit(
    baseline_kpis: dict[str, KPIDistribution],
    scenario_kpis: dict[str, KPIDistribution],
    operating_days_per_year: int = OPERATING_DAYS_PER_YEAR,
) -> AnnualBenefitBreakdown:
    """Translate daily KPI improvements into annual financial value.

    Computes the difference (baseline - scenario) for cost-related KPIs,
    since lower costs in the scenario = positive benefit.
    """
    def _delta_mean(key: str) -> float:
        """Return baseline.mean - scenario.mean (positive = improvement)."""
        b = baseline_kpis.get(key)
        s = scenario_kpis.get(key)
        if b is None or s is None:
            return 0.0
        return b.mean - s.mean

    # EU261 liability saved per day
    eu261_daily_saved = _delta_mean("eu261_liability_eur")
    eu261_annual = eu261_daily_saved * operating_days_per_year

    # Delay cost saved per day (minutes saved × cost per minute × flights)
    delay_minutes_saved = _delta_mean("avg_delay_minutes")
    # Use scenario's total flights as the base. Falls back to 420 only if the
    # KPI was not aggregated upstream (older runs); current runner emits it.
    flights_key = scenario_kpis.get("total_flights")
    avg_flights = flights_key.mean if flights_key and flights_key.mean > 0 else 420.0
    delay_daily = delay_minutes_saved * avg_flights * DELAY_COST_PER_MINUTE_EUR
    delay_annual = delay_daily * operating_days_per_year

    # Missed connections saved per day
    missed_saved = _delta_mean("missed_connections")
    missed_annual = missed_saved * REBOOKING_COST_PER_PAX_EUR * operating_days_per_year

    # Revenue uplift per day
    revenue_daily = -_delta_mean("total_revenue_eur")  # scenario > baseline = positive
    revenue_annual = revenue_daily * operating_days_per_year

    total = eu261_annual + delay_annual + missed_annual + revenue_annual

    return AnnualBenefitBreakdown(
        eu261_avoided_annual=eu261_annual,
        delay_cost_avoided_annual=delay_annual,
        missed_connections_avoided_annual=missed_annual,
        revenue_uplift_annual=revenue_annual,
        total_annual_benefit=total,
    )

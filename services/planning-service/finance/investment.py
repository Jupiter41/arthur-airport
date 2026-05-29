"""NPV and IRR investment calculator for capacity planning scenarios.

P4.1 of ROADMAP_PLANNING.md.

Implements discounted cash-flow analysis for infrastructure investments.
Given a capex, annual operating cost delta, and projected annual benefit
from scenario comparison, computes NPV, IRR, payback period, and a
recommendation rating.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class InvestmentResult:
    """Financial analysis output for a planning investment."""

    capex_eur: float
    annual_benefit_eur: float
    annual_opex_eur: float
    net_annual_eur: float  # benefit - opex
    npv_eur: float
    irr_pct: float  # internal rate of return (%)
    payback_years: float
    years_horizon: int
    discount_rate: float
    recommendation: str  # "invest" | "marginal" | "do not invest"

    def to_dict(self) -> dict:
        def _safe(v: float) -> float:
            """Replace inf/nan with 0 to ensure JSON-serializable output."""
            return 0.0 if (math.isinf(v) or math.isnan(v)) else v

        return {
            "capex_eur": round(self.capex_eur, 2),
            "annual_benefit_eur": round(self.annual_benefit_eur, 2),
            "annual_opex_eur": round(self.annual_opex_eur, 2),
            "net_annual_eur": round(self.net_annual_eur, 2),
            "npv_eur": round(_safe(self.npv_eur), 2),
            "irr_pct": round(_safe(self.irr_pct), 2),
            "payback_years": round(_safe(self.payback_years), 2),
            "years_horizon": self.years_horizon,
            "discount_rate": self.discount_rate,
            "recommendation": self.recommendation,
        }


def compute_investment(
    capex: float,
    annual_benefit: float,
    annual_opex: float,
    years: int,
    discount_rate: float,
) -> InvestmentResult:
    """Discounted cash-flow analysis for an infrastructure investment.

    cash_flows[0] = -capex (year 0: upfront investment)
    cash_flows[t] = annual_benefit - annual_opex (years 1..N: net annual benefit)

    Returns InvestmentResult with NPV, IRR, payback period, and recommendation.
    """
    net_annual = annual_benefit - annual_opex
    cash_flows = [-capex] + [net_annual] * years

    # NPV: sum of discounted cash flows
    npv = sum(cf / (1 + discount_rate) ** t for t, cf in enumerate(cash_flows))

    # IRR: solve for r where NPV = 0, using bisection method
    irr = _compute_irr(cash_flows)

    # Payback period: year when cumulative cash flow turns positive
    # Use years+1 as sentinel ("never pays back") instead of inf, which is not JSON-serializable.
    cumulative = -capex
    payback = float(years + 1)
    for year in range(1, years + 1):
        prev_cumulative = cumulative
        cumulative += net_annual
        if cumulative >= 0 and net_annual > 0:
            payback = year - 1 + (-prev_cumulative) / net_annual
            break

    # Recommendation based on NPV and IRR
    if npv > 0 and irr > discount_rate * 100:
        recommendation = "invest"
    elif npv > -capex * 0.1:
        recommendation = "marginal"
    else:
        recommendation = "do not invest"

    return InvestmentResult(
        capex_eur=capex,
        annual_benefit_eur=annual_benefit,
        annual_opex_eur=annual_opex,
        net_annual_eur=net_annual,
        npv_eur=npv,
        irr_pct=irr,
        payback_years=payback,
        years_horizon=years,
        discount_rate=discount_rate,
        recommendation=recommendation,
    )


def _compute_irr(cash_flows: list[float], max_iterations: int = 200,
                  tolerance: float = 1e-6) -> float:
    """Compute IRR using bisection method.

    Returns IRR as a percentage (e.g. 8.5 for 8.5%).
    Returns 0.0 if the investment never pays back.
    """
    if not cash_flows or len(cash_flows) < 2:
        return 0.0

    # Check if any positive cash flow exists
    if all(cf <= 0 for cf in cash_flows[1:]):
        return 0.0

    def npv_at_rate(rate: float) -> float:
        return sum(cf / (1 + rate) ** t for t, cf in enumerate(cash_flows))

    # Bisection between -50% and 200%
    low, high = -0.5, 2.0

    # Ensure we have a sign change
    npv_low = npv_at_rate(low)
    npv_high = npv_at_rate(high)

    if npv_low * npv_high > 0:
        # No sign change — try wider range
        high = 5.0
        npv_high = npv_at_rate(high)
        if npv_low * npv_high > 0:
            # Still no sign change — investment doesn't have a meaningful IRR
            return 0.0 if npv_low < 0 else 100.0

    for _ in range(max_iterations):
        mid = (low + high) / 2
        npv_mid = npv_at_rate(mid)

        if abs(npv_mid) < tolerance:
            return mid * 100

        if npv_low * npv_mid < 0:
            high = mid
            npv_high = npv_mid
        else:
            low = mid
            npv_low = npv_mid

    return ((low + high) / 2) * 100


def sensitivity_analysis(
    capex: float,
    annual_benefit: float,
    annual_opex: float,
    years: int,
    discount_rate: float,
    growth_scenarios: dict[str, float] | None = None,
) -> dict[str, dict]:
    """Run NPV under different demand growth assumptions.

    Returns a dict of scenario_name → InvestmentResult.to_dict().
    Default scenarios: low (1.8% CAGR), base (3.4%), high (4.8%).
    """
    if growth_scenarios is None:
        growth_scenarios = {
            "low": 0.018,
            "base": 0.034,
            "high": 0.048,
        }

    results = {}
    for name, growth_rate in growth_scenarios.items():
        # Project annual benefit growth over the horizon
        projected_benefits = [
            annual_benefit * (1 + growth_rate) ** yr
            for yr in range(years)
        ]
        avg_benefit = sum(projected_benefits) / len(projected_benefits) if projected_benefits else annual_benefit
        result = compute_investment(capex, avg_benefit, annual_opex, years, discount_rate)
        results[name] = result.to_dict()

    return results

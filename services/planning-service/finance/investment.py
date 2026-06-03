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
    irr_pct: float  # internal rate of return (%) — 0.0 if not meaningful, see irr_meaningful
    irr_meaningful: bool  # True when the cashflow series has a real IRR (a sign change)
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
            "irr_pct": round(_safe(self.irr_pct), 2) if self.irr_meaningful else None,
            "irr_meaningful": self.irr_meaningful,
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

    # IRR: solve for r where NPV = 0, using bisection method.
    # Returns (irr_percent, meaningful_flag) so the caller can distinguish
    # "no-IRR" (e.g. positive net cashflows for any rate) from a real IRR.
    irr, irr_meaningful = _compute_irr(cash_flows)

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

    # Recommendation based on NPV. If IRR is meaningful, also require it to clear the discount rate.
    if npv > 0 and (not irr_meaningful or irr > discount_rate * 100):
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
        irr_meaningful=irr_meaningful,
        payback_years=payback,
        years_horizon=years,
        discount_rate=discount_rate,
        recommendation=recommendation,
    )


def _compute_irr(cash_flows: list[float], max_iterations: int = 200,
                  tolerance: float = 1e-6) -> tuple[float, bool]:
    """Compute IRR using bisection method.

    Returns ``(irr_pct, meaningful)`` where ``meaningful`` is False when the
    cashflow series has no sign change in [-50%, 500%] and therefore no real
    IRR exists. In that case ``irr_pct`` is 0.0 — do not interpret it.
    """
    if not cash_flows or len(cash_flows) < 2:
        return 0.0, False

    # Check if any positive cash flow exists
    if all(cf <= 0 for cf in cash_flows[1:]):
        return 0.0, False

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
            # Still no sign change — investment doesn't have a meaningful IRR.
            # Caller should not use the numeric value.
            return 0.0, False

    for _ in range(max_iterations):
        mid = (low + high) / 2
        npv_mid = npv_at_rate(mid)

        if abs(npv_mid) < tolerance:
            return mid * 100, True

        if npv_low * npv_mid < 0:
            high = mid
            npv_high = npv_mid
        else:
            low = mid
            npv_low = npv_mid

    return ((low + high) / 2) * 100, True


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
        # Build a true year-by-year DCF instead of averaging benefits into an
        # annuity. Averaging destroys the growth shape and biases NPV when
        # the discount rate is close to the growth rate.
        cash_flows = [-capex]
        projected_benefits: list[float] = []
        for yr in range(1, years + 1):
            year_benefit = annual_benefit * (1 + growth_rate) ** (yr - 1)
            projected_benefits.append(year_benefit)
            cash_flows.append(year_benefit - annual_opex)

        npv = sum(cf / (1 + discount_rate) ** t for t, cf in enumerate(cash_flows))
        irr, irr_meaningful = _compute_irr(cash_flows)

        # Payback period using the actual (growing) cashflow series.
        cumulative = -capex
        payback = float(years + 1)
        for yr in range(1, years + 1):
            prev = cumulative
            cumulative += cash_flows[yr]
            if cumulative >= 0 and cash_flows[yr] > 0:
                payback = yr - 1 + (-prev) / cash_flows[yr]
                break

        avg_benefit = sum(projected_benefits) / len(projected_benefits)
        net_annual = avg_benefit - annual_opex
        if npv > 0 and (not irr_meaningful or irr > discount_rate * 100):
            recommendation = "invest"
        elif npv > -capex * 0.1:
            recommendation = "marginal"
        else:
            recommendation = "do not invest"

        result = InvestmentResult(
            capex_eur=capex,
            annual_benefit_eur=avg_benefit,
            annual_opex_eur=annual_opex,
            net_annual_eur=net_annual,
            npv_eur=npv,
            irr_pct=irr,
            irr_meaningful=irr_meaningful,
            payback_years=payback,
            years_horizon=years,
            discount_rate=discount_rate,
            recommendation=recommendation,
        )
        results[name] = result.to_dict()

    return results

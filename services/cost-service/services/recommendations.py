"""Cost-aware financial recommendation engine.

Generates prescriptive recommendations with cost/benefit analysis. Each
recommendation now ships with a 95 % confidence interval on the projected
saving, derived from the rolling 7-day history of the underlying signal
(see `cost_engine._daily_history`). When fewer than two historical days are
available, ``saving_eur_ci`` is reported as ``None`` so the dashboard can
render a "n/a" badge instead of fake-precision range.
"""

import math
from dataclasses import asdict, dataclass, field

import structlog

from services.cost_engine import get_daily_history

logger = structlog.get_logger(__name__)

# 95 % two-sided confidence band on a normally-distributed daily total.
_Z95 = 1.96


@dataclass
class FinancialRecommendation:
    action: str
    description: str
    cost_eur: float
    saving_eur: float
    net_benefit_eur: float
    confidence: float
    payback_sim_minutes: int
    expiry_sim_time: str
    saving_eur_ci: dict | None = field(default=None)


def _ci_for_signal(signal_key: str, saving_factor: float) -> dict | None:
    """Return a 95 % CI on the projected saving for a given history signal.

    ``saving_factor`` scales the underlying daily total into the recommendation
    domain (e.g. 0.3 when we believe an action could recover 30 % of EU261
    exposure). The CI half-width is the same multiplicative factor applied to
    1.96 σ of the historical population. Returns ``None`` when fewer than two
    historical days exist.
    """
    history = get_daily_history().get(signal_key, [])
    if len(history) < 2:
        return None
    mean = sum(history) / len(history)
    var = sum((x - mean) ** 2 for x in history) / (len(history) - 1)
    sigma = math.sqrt(var)
    half = _Z95 * sigma * saving_factor
    centre = mean * saving_factor
    return {
        "low_eur": round(max(0.0, centre - half), 2),
        "high_eur": round(centre + half, 2),
        "sample_days": len(history),
    }


def generate_recommendations(
    running_totals: dict,
    sim_time: str,
    rates: dict,
) -> list[dict]:
    """Generate financially-aware recommendations based on current state."""
    recs: list[dict] = []

    eu261_exposure = running_totals.get("eu261_exposure", 0.0)

    # 1. Open security lane if EU261 exposure is high
    if eu261_exposure > 10_000:
        staffing_cost = rates["staffing"]["security_officer_per_hour_eur"] * 2  # 2-hour shift
        saving = eu261_exposure * 0.3  # could prevent ~30% of exposure
        recs.append(asdict(FinancialRecommendation(
            action="open_security_lane",
            description="Open an additional security lane to reduce queue wait times and prevent EU261 exposure",
            cost_eur=round(staffing_cost, 2),
            saving_eur=round(saving, 2),
            net_benefit_eur=round(saving - staffing_cost, 2),
            confidence=0.7,
            payback_sim_minutes=30,
            expiry_sim_time=sim_time,
            saving_eur_ci=_ci_for_signal("eu261_exposure", 0.3),
        )))

    # 2. Ground delay program if holding costs are high
    holding_cost = running_totals.get("by_category", {}).get("holding_fuel", 0.0)
    if holding_cost > 5_000:
        gdp_cost = 500.0  # admin overhead
        fuel_saving = holding_cost * 0.5
        recs.append(asdict(FinancialRecommendation(
            action="ground_delay_program",
            description="Implement ground delay program to reduce holding fuel burn for approaching aircraft",
            cost_eur=round(gdp_cost, 2),
            saving_eur=round(fuel_saving, 2),
            net_benefit_eur=round(fuel_saving - gdp_cost, 2),
            confidence=0.8,
            payback_sim_minutes=15,
            expiry_sim_time=sim_time,
            saving_eur_ci=_ci_for_signal("by_category.holding_fuel", 0.5),
        )))

    # 3. Gate reassignment if ground handling costs are high
    handling_cost = running_totals.get("by_category", {}).get("ground_handling", 0.0)
    if handling_cost > 50_000:
        reassign_cost = 200.0  # pax walk time cost
        saving = handling_cost * 0.1
        recs.append(asdict(FinancialRecommendation(
            action="gate_reassignment",
            description="Reassign gates to reduce turnaround conflicts and crew overtime",
            cost_eur=round(reassign_cost, 2),
            saving_eur=round(saving, 2),
            net_benefit_eur=round(saving - reassign_cost, 2),
            confidence=0.6,
            payback_sim_minutes=45,
            expiry_sim_time=sim_time,
            saving_eur_ci=_ci_for_signal("by_category.ground_handling", 0.1),
        )))

    # 4. Open make-up carousel
    total_cost = running_totals.get("total_cost_eur", 0.0)
    if total_cost > 100_000:
        recs.append(asdict(FinancialRecommendation(
            action="open_makeup_carousel",
            description="Open additional make-up carousel to prevent baggage delays cascading into flight delays",
            cost_eur=0.0,
            saving_eur=round(total_cost * 0.02, 2),
            net_benefit_eur=round(total_cost * 0.02, 2),
            confidence=0.5,
            payback_sim_minutes=20,
            expiry_sim_time=sim_time,
            saving_eur_ci=_ci_for_signal("total_cost_eur", 0.02),
        )))

    return recs

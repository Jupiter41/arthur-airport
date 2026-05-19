"""Cost-aware financial recommendation engine.

Generates prescriptive recommendations with cost/benefit analysis.
"""

from dataclasses import dataclass, asdict

import structlog

logger = structlog.get_logger(__name__)


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
        )))

    return recs

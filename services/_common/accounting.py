"""Synthetic airport accounting policy, shared by live and planning models."""

from __future__ import annotations

ACCOUNTING_POLICY = "airport-v1"
AIRPORT_EXPENSES = ("staffing", "incident_direct", "incident_response")


def empty_totals() -> dict:
    return {"accounting_policy": ACCOUNTING_POLICY, "total_cost_eur": 0.0,
            "total_revenue_eur": 0.0, "net_eur": 0.0, "by_category": {},
            "airline_cost_eur": 0.0, "airline_by_category": {}, "eu261_exposure": 0.0}


def add_amount(totals: dict, category: str, amount: float, is_revenue: bool) -> None:
    """Classify legacy and new records identically without changing charges."""
    totals["accounting_policy"] = ACCOUNTING_POLICY
    if is_revenue:
        totals["total_revenue_eur"] += amount
    else:
        airport = category in AIRPORT_EXPENSES
        total_key = "total_cost_eur" if airport else "airline_cost_eur"
        category_key = "by_category" if airport else "airline_by_category"
        totals[total_key] = totals.get(total_key, 0.0) + amount
        categories = totals.setdefault(category_key, {})
        categories[category] = categories.get(category, 0.0) + amount
        if category == "eu261_compensation":
            totals["eu261_exposure"] = totals.get("eu261_exposure", 0.0) + amount
    totals["net_eur"] = totals["total_revenue_eur"] - totals["total_cost_eur"]


def compensation_liability(delay_minutes: float, distance_km: float,
                           pax_count: int, rates: dict) -> float:
    """Full eligible synthetic liability; no assumed claimant discount."""
    if delay_minutes < 180:
        return 0.0
    for tier in sorted(rates["eu261"], key=lambda row: row["min_delay_minutes"], reverse=True):
        if (not tier.get("assistance_only", False)
                and delay_minutes >= tier["min_delay_minutes"]
                and distance_km <= tier["max_distance_km"]):
            return round(tier["compensation_eur"] * pax_count, 2)
    return 0.0

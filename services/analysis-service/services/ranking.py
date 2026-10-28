"""Comparable impact / cost scoring for recommendations (roadmap G5).

The recommender historically ranked interventions by ``confidence_score``
alone, so a high-confidence but trivial action (e.g. an announcement) could
outrank a high-impact one (e.g. saving 40 missed connections).  This module
derives, for each recommendation, a benefit and a cost on a *common synthetic
scale* so they can be ranked by

    priority_score = impact_value * confidence_score / cost_value

**These weights are heuristic and NOT calibrated against measured outcomes**
(see ROADMAP_REAL_LDT.md §10 G8 — automatic outcome measurement is still open).
They exist to replace a confidence-only sort with one that also accounts for
the *magnitude* of the benefit and the cost of realising it.  The absolute
scale is irrelevant; only the ordering across concurrently-active
recommendations is meaningful.

Scales:
- ``impact_value``  — passenger-minutes of delay/queue time avoided.
- ``cost_value``    — "disruption-minutes": ground-delay minutes plus a small
  staff/announcement-equivalent floor so that cost is never zero.

The functions here are pure: they read only the recommendation's own
``parameters`` and the owning bottleneck's ``metrics`` / ``affected_entity_count``.
No I/O, no global state.
"""

from __future__ import annotations

from models.domain import ActionType, Bottleneck, Recommendation

# Never divide by zero and never let a "free" action look infinitely good:
# the cheapest action still costs at least this many disruption-minute units.
COST_FLOOR = 5.0

# Staff/announcement actions carry a small fixed operational cost (minutes of
# equivalent effort) rather than a delay cost.
_STAFF_LANE_COST = 20.0
_ESCORT_COST = 10.0
_SIGNAGE_COST = 8.0
_VEHICLE_REPOSITION_COST = 10.0
_BAGGAGE_HANDLING_COST = 12.0
_ANNOUNCEMENT_COST = 3.0


def _num(value, default: float = 0.0) -> float:
    """Coerce a metric/parameter to float, tolerating None / bad types."""
    try:
        if isinstance(value, bool):  # bool is an int subclass — reject
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _affected_pax(bn: Bottleneck) -> float:
    """Passenger proxy for a bottleneck, floored at 1."""
    return max(_num(bn.affected_entity_count, 1.0), 1.0)


def estimate_impact_cost(rec: Recommendation, bn: Bottleneck) -> tuple[float, float]:
    """Return ``(impact_value, cost_value)`` for a recommendation.

    Both are non-negative; ``cost_value`` is floored at :data:`COST_FLOOR`.
    """
    m = bn.metrics or {}
    p = rec.parameters or {}
    at = rec.action_type

    impact = 0.0
    cost = COST_FLOOR

    if at is ActionType.OPEN_SECURITY_LANE:
        wait = _num(m.get("forecast_wait_minutes"), 20.0)
        new_lanes = _num(p.get("new_lane_count"), 5.0)
        prev_lanes = max(new_lanes - 1.0, 1.0)
        # Per-passenger minutes saved when a lane is added (M/M/c-ish proxy).
        saved_per_pax = wait * (1.0 - prev_lanes / new_lanes)
        pax = _num(m.get("queue_depth"), 0.0) or _affected_pax(bn)
        impact = saved_per_pax * pax
        cost = _STAFF_LANE_COST

    elif at is ActionType.EARLY_GATE_CALL:
        # ~15% crowding relief, announcement-only.
        impact = 0.15 * _affected_pax(bn) * 5.0
        cost = _ANNOUNCEMENT_COST

    elif at is ActionType.REDIRECT_CHECKIN:
        # ~30% upstream feed reduction.
        impact = 0.30 * _affected_pax(bn) * 6.0
        cost = _SIGNAGE_COST

    elif at is ActionType.REASSIGN_GATE:
        # Frees gate pressure (proxy: affected flights * turnaround minutes),
        # at the cost of +5 min walk time per affected passenger.
        impact = _affected_pax(bn) * 8.0
        cost = _affected_pax(bn) * 5.0

    elif at is ActionType.DELAY_TAXI:
        hold = _num(p.get("hold_minutes"), 10.0)
        # Buys turnaround slack for the terminal's passengers.
        impact = _affected_pax(bn) * 6.0
        cost = hold * max(_num(m.get("waiting_flights"), 1.0), 1.0)

    elif at is ActionType.SWAP_GATES:
        impact = _affected_pax(bn) * 4.0
        cost = _ANNOUNCEMENT_COST * 2.0

    elif at is ActionType.HOLD_CONNECTING_FLIGHT:
        pax = _num(p.get("passengers_saved"), 0.0) or _num(m.get("passenger_count"), 0.0)
        # Saving a connection avoids a rebooking + long re-route: ~180 pax-min.
        impact = pax * 180.0
        cost = _num(p.get("hold_minutes"), 0.0) or _num(m.get("inbound_delay"), 10.0)

    elif at is ActionType.FAST_TRACK_PASSENGERS:
        pax = _num(p.get("passenger_count"), 0.0) or _affected_pax(bn)
        impact = pax * 10.0  # ~10 min saved per fast-tracked pax
        cost = _ESCORT_COST + pax * 3.0

    elif at is ActionType.REBOOK_PASSENGERS:
        pax = _num(p.get("passenger_count"), 0.0) or _affected_pax(bn)
        # Guaranteed recovery, but a worse passenger outcome than a hold.
        impact = pax * 90.0
        cost = pax * 30.0

    elif at is ActionType.GROUND_DELAY_PROGRAM:
        holdable = _num(p.get("holdable_flights"), 0.0)
        queued = _num(m.get("queued_flights"), holdable)
        # Avoids airborne-hold fuel burn / approach-queue cascade.
        impact = max(queued, 1.0) * 60.0
        stagger = _num(p.get("stagger_minutes"), 10.0)
        cost = holdable * stagger if holdable else COST_FLOOR

    elif at is ActionType.REDIRECT_BAGGAGE:
        util = _num(m.get("utilisation_pct"), 0.0)
        impact = max(util - 70.0, 0.0) * _affected_pax(bn) * 0.2 + _affected_pax(bn)
        cost = _BAGGAGE_HANDLING_COST

    elif at is ActionType.EXPEDITE_LOADING:
        impact = _affected_pax(bn) * 2.0
        cost = _BAGGAGE_HANDLING_COST

    elif at is ActionType.REDISTRIBUTE_VEHICLES:
        util = _num(m.get("utilisation_pct"), 0.0)
        impact = max(util - 75.0, 0.0) * 2.0 + _affected_pax(bn)
        cost = _VEHICLE_REPOSITION_COST

    elif at is ActionType.DEFER_TASK:
        impact = _affected_pax(bn) * 1.5
        cost = _VEHICLE_REPOSITION_COST

    elif at in (ActionType.RESOLVE_INCIDENT, ActionType.CONTAIN_INCIDENT):
        # Clearing an incident lifts its restrictions across every affected
        # flight/zone — high benefit, at the cost of committed response resources.
        impact = _affected_pax(bn) * 30.0
        cost = 30.0

    elif at is ActionType.OPEN_MAKEUP_CAROUSEL:
        # Opening a carousel prevents flight delays from cascading baggage bottlenecks.
        total_cost = _num(m.get("total_cost_eur"), 0.0)
        impact = max(total_cost * 0.02, _affected_pax(bn) * 5.0)
        cost = COST_FLOOR

    impact = max(impact, 0.0)
    cost = max(cost, COST_FLOOR)
    return impact, cost


def score_recommendation(rec: Recommendation, bn: Bottleneck) -> float:
    """Populate ``impact_value`` / ``cost_value`` / ``priority_score`` on ``rec``.

    Returns the priority score (also stored on the recommendation).
    """
    impact, cost = estimate_impact_cost(rec, bn)
    rec.impact_value = impact
    rec.cost_value = cost
    rec.priority_score = impact * rec.confidence_score / cost
    return rec.priority_score

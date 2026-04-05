"""Recommendation engine.

For each detected bottleneck, generate a ranked list of possible interventions
with projected outcome metrics.

P2-2-1 through P2-2-6.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import uuid4

from models.domain import (
    ActionType,
    Bottleneck,
    BottleneckType,
    Recommendation,
)
from services.state import OperationalState

logger = logging.getLogger(__name__)


def generate_recommendations(
    state: OperationalState,
    bottlenecks: list[Bottleneck],
    max_total: int = 3,
) -> list[Recommendation]:
    """Generate ranked recommendations for active bottlenecks.

    Returns the top ``max_total`` recommendations ranked by
    expected impact / cost ratio.
    """
    now = state.sim_time
    if now is None:
        return []

    all_recs: list[Recommendation] = []
    for bn in bottlenecks:
        if bn.resolved_at is not None:
            continue
        recs = _generate_for_bottleneck(state, bn, now)
        all_recs.extend(recs)

    # Sort by confidence * (1 / priority_rank) — higher is better
    all_recs.sort(key=lambda r: r.confidence_score, reverse=True)

    # Assign priority ranks
    for i, rec in enumerate(all_recs):
        rec.priority_rank = i + 1

    return all_recs[:max_total]


def _generate_for_bottleneck(
    state: OperationalState,
    bn: Bottleneck,
    now: datetime,
) -> list[Recommendation]:
    """Dispatch to type-specific recommendation generators."""
    handlers = {
        BottleneckType.SECURITY_QUEUE: _recs_security_queue,
        BottleneckType.GATE_UTILISATION: _recs_gate_conflict,
        BottleneckType.CONNECTION_CLUSTER: _recs_connection_recovery,
        BottleneckType.RUNWAY_CAPACITY: _recs_ground_delay_program,
        BottleneckType.BAGGAGE_THROUGHPUT: _recs_baggage_throughput,
        BottleneckType.GROUND_VEHICLE: _recs_ground_vehicle,
    }
    handler = handlers.get(bn.type)
    if handler is None:
        return []
    return handler(state, bn, now)


# ── P2-2-2: Security queue recommendations ──────────────────


def _recs_security_queue(
    state: OperationalState,
    bn: Bottleneck,
    now: datetime,
) -> list[Recommendation]:
    terminal = bn.zone
    sec = state.security.get(terminal)
    recs = []
    expiry = now + timedelta(minutes=30)

    # 1. Open additional lane
    current_lanes = sec.open_lanes if sec else 4
    if current_lanes < 8:  # Max lanes per terminal
        new_wait = bn.metrics.get("forecast_wait_minutes", 20) * (
            current_lanes / (current_lanes + 1)
        )
        recs.append(Recommendation(
            id=f"rec-{uuid4().hex[:12]}",
            bottleneck_id=bn.id,
            action_type=ActionType.OPEN_SECURITY_LANE,
            description=(
                f"Open an additional security lane in {terminal} "
                f"(currently {current_lanes} open)"
            ),
            expected_impact=(
                f"Reduce projected wait from "
                f"{bn.metrics.get('forecast_wait_minutes', 0):.0f} min to "
                f"{new_wait:.0f} min"
            ),
            cost="1 additional staff member for ~2 hours",
            confidence_score=0.85,
            expiry_sim_time=expiry,
            priority_rank=1,
            parameters={
                "terminal": terminal,
                "new_lane_count": current_lanes + 1,
            },
        ))

    # 2. Early gate call for specific flights
    departures = [
        f for f in state.flights.values()
        if f.terminal == terminal
        and f.flight_type == "departure"
        and f.status in ("scheduled", "boarding")
    ]
    if departures:
        recs.append(Recommendation(
            id=f"rec-{uuid4().hex[:12]}",
            bottleneck_id=bn.id,
            action_type=ActionType.EARLY_GATE_CALL,
            description=(
                f"Issue early gate calls for {len(departures)} departures in "
                f"{terminal} to reduce late gate arrivals"
            ),
            expected_impact="Reduce gate-area crowding by ~15%",
            cost="0 — announcement only",
            confidence_score=0.70,
            expiry_sim_time=expiry,
            priority_rank=2,
            parameters={
                "terminal": terminal,
                "flight_count": len(departures),
            },
        ))

    # 3. Redirect check-in to less congested terminal
    other_queues = {
        t: s.queue_depth
        for t, s in state.security.items()
        if t != terminal
    }
    least_busy = min(other_queues, key=other_queues.get) if other_queues else None
    if least_busy and other_queues.get(least_busy, 999) < (sec.queue_depth * 0.6 if sec else 0):
        recs.append(Recommendation(
            id=f"rec-{uuid4().hex[:12]}",
            bottleneck_id=bn.id,
            action_type=ActionType.REDIRECT_CHECKIN,
            description=(
                f"Redirect check-in flow from {terminal} to {least_busy} "
                f"(queue depth {other_queues.get(least_busy, 0)} vs "
                f"{sec.queue_depth if sec else 0})"
            ),
            expected_impact="Reduce upstream feed to congested terminal by ~30%",
            cost="Signage change + 5 min passenger confusion",
            confidence_score=0.65,
            expiry_sim_time=expiry,
            priority_rank=3,
            parameters={
                "from_terminal": terminal,
                "to_terminal": least_busy,
            },
        ))

    return recs


# ── P2-2-3: Gate conflict recommendations ───────────────────


def _recs_gate_conflict(
    state: OperationalState,
    bn: Bottleneck,
    now: datetime,
) -> list[Recommendation]:
    terminal = bn.zone
    recs = []
    expiry = now + timedelta(minutes=45)

    # 1. Pre-assign alternate gate
    free_other = {
        t: cnt for t, cnt in state.get_free_gates_by_terminal().items()
        if t != terminal and cnt > 2
    }
    if free_other:
        best_alt = max(free_other, key=free_other.get)
        recs.append(Recommendation(
            id=f"rec-{uuid4().hex[:12]}",
            bottleneck_id=bn.id,
            action_type=ActionType.REASSIGN_GATE,
            description=(
                f"Reassign next arriving flight to {best_alt} "
                f"({free_other[best_alt]} free gates) instead of {terminal}"
            ),
            expected_impact=(
                f"Free up gate pressure in {terminal}; "
                f"+5 min walk time for passengers"
            ),
            cost="5 min additional passenger walk time",
            confidence_score=0.80,
            expiry_sim_time=expiry,
            priority_rank=1,
            parameters={
                "original_terminal": terminal,
                "alternate_terminal": best_alt,
            },
        ))

    # 2. Delay inbound taxi to hold position
    waiting = state.get_flights_needing_gate()
    if waiting:
        recs.append(Recommendation(
            id=f"rec-{uuid4().hex[:12]}",
            bottleneck_id=bn.id,
            action_type=ActionType.DELAY_TAXI,
            description=(
                f"Hold {len(waiting)} inbound flight(s) at taxi position "
                f"to allow gates to vacate in {terminal}"
            ),
            expected_impact="Buy 10-15 min for current turnarounds to complete",
            cost=f"{len(waiting)} flight(s) delayed 10-15 min on ground",
            confidence_score=0.75,
            expiry_sim_time=expiry,
            priority_rank=2,
            parameters={
                "terminal": terminal,
                "hold_minutes": 10,
            },
        ))

    # 3. Swap departures between gates
    departures_at = [
        f for f in state.flights.values()
        if f.terminal == terminal and f.gate
        and f.status in ("boarding", "ready_for_departure")
    ]
    if len(departures_at) >= 2:
        recs.append(Recommendation(
            id=f"rec-{uuid4().hex[:12]}",
            bottleneck_id=bn.id,
            action_type=ActionType.SWAP_GATES,
            description=(
                f"Swap gate assignments for departure pair in {terminal} "
                f"to optimise turnover sequence"
            ),
            expected_impact="Reduce gate turnover gap by ~10 min",
            cost="Passenger confusion + gate change announcements",
            confidence_score=0.60,
            expiry_sim_time=expiry,
            priority_rank=3,
            parameters={"terminal": terminal},
        ))

    return recs


# ── P2-2-4: Connection recovery recommendations ─────────────


def _recs_connection_recovery(
    state: OperationalState,
    bn: Bottleneck,
    now: datetime,
) -> list[Recommendation]:
    recs = []
    expiry = now + timedelta(minutes=60)
    inbound = bn.metrics.get("inbound_flight", "")
    outbound = bn.metrics.get("outbound_flight", "")
    pax_count = bn.metrics.get("passenger_count", 0)
    delay = bn.metrics.get("inbound_delay", 0)

    # 1. Hold connecting flight
    if delay <= 30:
        recs.append(Recommendation(
            id=f"rec-{uuid4().hex[:12]}",
            bottleneck_id=bn.id,
            action_type=ActionType.HOLD_CONNECTING_FLIGHT,
            description=(
                f"Hold {outbound} for {delay + 10} min to allow "
                f"{pax_count} connecting passengers from {inbound}"
            ),
            expected_impact=f"Save {pax_count} connections; +{delay + 10} min delay on {outbound}",
            cost=f"{delay + 10} delay-minutes on {outbound}",
            confidence_score=0.85 if delay <= 20 else 0.70,
            expiry_sim_time=expiry,
            priority_rank=1,
            parameters={
                "outbound_flight": outbound,
                "hold_minutes": delay + 10,
                "passengers_saved": pax_count,
            },
        ))

    # 2. Fast-track through security
    recs.append(Recommendation(
        id=f"rec-{uuid4().hex[:12]}",
        bottleneck_id=bn.id,
        action_type=ActionType.FAST_TRACK_PASSENGERS,
        description=(
            f"Fast-track {pax_count} connecting passengers from {inbound} "
            f"through security with special assistance"
        ),
        expected_impact="Save ~10 min per passenger; reduce missed-connection risk by 50%",
        cost=f"1 escort staff for ~{pax_count * 3} min",
        confidence_score=0.80,
        expiry_sim_time=expiry,
        priority_rank=2,
        parameters={
            "inbound_flight": inbound,
            "passenger_count": pax_count,
        },
    ))

    # 3. Rebook on next departure (only if delay is large)
    if delay > 30:
        recs.append(Recommendation(
            id=f"rec-{uuid4().hex[:12]}",
            bottleneck_id=bn.id,
            action_type=ActionType.REBOOK_PASSENGERS,
            description=(
                f"Rebook {pax_count} passengers from {inbound} onto next "
                f"available departure (delay {delay} min exceeds MCT + 30)"
            ),
            expected_impact=f"Guaranteed rebooking for {pax_count} pax; avoid gate hold",
            cost=f"Revenue protection cost for {pax_count} rebookings",
            confidence_score=0.90,
            expiry_sim_time=expiry,
            priority_rank=1,
            parameters={
                "inbound_flight": inbound,
                "outbound_flight": outbound,
                "passenger_count": pax_count,
            },
        ))

    return recs


# ── P2-2-5: Ground delay program recommendation ─────────────


def _recs_ground_delay_program(
    state: OperationalState,
    bn: Bottleneck,
    now: datetime,
) -> list[Recommendation]:
    recs = []
    expiry = now + timedelta(minutes=90)
    cap = bn.metrics.get("capacity_pct", 100)
    queued = bn.metrics.get("queued_flights", 0)

    # Count departures that could be held at gate
    departures = [
        f for f in state.flights.values()
        if f.flight_type == "departure"
        and f.status in ("scheduled", "boarding", "ready_for_departure")
    ]
    holdable = len(departures)

    recs.append(Recommendation(
        id=f"rec-{uuid4().hex[:12]}",
        bottleneck_id=bn.id,
        action_type=ActionType.GROUND_DELAY_PROGRAM,
        description=(
            f"Initiate Ground Delay Program: hold {holdable} departures at "
            f"gate, stagger by {max(5, (100 - cap) // 10)} min intervals "
            f"to avoid airborne holding"
        ),
        expected_impact=(
            f"Eliminate holding stack fuel burn for ~{queued} flights; "
            f"reduce approach queue from {queued} to manageable levels"
        ),
        cost=f"Total programme delay: ~{holdable * 10} delay-minutes distributed across {holdable} flights",
        confidence_score=0.90,
        expiry_sim_time=expiry,
        priority_rank=1,
        parameters={
            "holdable_flights": holdable,
            "stagger_minutes": max(5, (100 - int(cap)) // 10),
            "weather_category": state.weather.category,
        },
    ))

    return recs


# ── Baggage throughput recommendations ───────────────────────


def _recs_baggage_throughput(
    state: OperationalState,
    bn: Bottleneck,
    now: datetime,
) -> list[Recommendation]:
    recs = []
    expiry = now + timedelta(minutes=30)
    zone = bn.zone
    util = bn.metrics.get("utilisation_pct", 0)

    # 1. Redirect to adjacent make-up
    recs.append(Recommendation(
        id=f"rec-{uuid4().hex[:12]}",
        bottleneck_id=bn.id,
        action_type=ActionType.REDIRECT_BAGGAGE,
        description=f"Redirect incoming bags from {zone} to adjacent make-up carousel",
        expected_impact=f"Reduce {zone} utilisation from {util:.0f}% to ~70%",
        cost="2-3 min additional bag travel time",
        confidence_score=0.75,
        expiry_sim_time=expiry,
        priority_rank=1,
        parameters={"zone": zone, "utilisation_pct": util},
    ))

    # 2. Expedite loading for departing flights
    recs.append(Recommendation(
        id=f"rec-{uuid4().hex[:12]}",
        bottleneck_id=bn.id,
        action_type=ActionType.EXPEDITE_LOADING,
        description=f"Expedite bag loading for flights using {zone} to clear backlog",
        expected_impact="Clear 20-30 bags in next 5 min",
        cost="1 additional loader for 30 min",
        confidence_score=0.70,
        expiry_sim_time=expiry,
        priority_rank=2,
        parameters={"zone": zone},
    ))

    return recs


# ── Ground vehicle recommendations ──────────────────────────


def _recs_ground_vehicle(
    state: OperationalState,
    bn: Bottleneck,
    now: datetime,
) -> list[Recommendation]:
    recs = []
    expiry = now + timedelta(minutes=30)
    vtype = bn.zone
    util = bn.metrics.get("utilisation_pct", 0)

    recs.append(Recommendation(
        id=f"rec-{uuid4().hex[:12]}",
        bottleneck_id=bn.id,
        action_type=ActionType.REDISTRIBUTE_VEHICLES,
        description=(
            f"Redistribute {vtype} vehicles from less busy areas to "
            f"meet peak demand"
        ),
        expected_impact=f"Reduce {vtype} utilisation from {util:.0f}% to ~75%",
        cost="5 min repositioning time",
        confidence_score=0.70,
        expiry_sim_time=expiry,
        priority_rank=1,
        parameters={"vehicle_type": vtype, "utilisation_pct": util},
    ))

    recs.append(Recommendation(
        id=f"rec-{uuid4().hex[:12]}",
        bottleneck_id=bn.id,
        action_type=ActionType.DEFER_TASK,
        description=(
            f"Defer non-critical {vtype} tasks (e.g. repositioning) "
            f"and prioritise active turnarounds"
        ),
        expected_impact="Free up 1-2 vehicles immediately",
        cost="Delayed repositioning of 1-2 vehicles",
        confidence_score=0.65,
        expiry_sim_time=expiry,
        priority_rank=2,
        parameters={"vehicle_type": vtype},
    ))

    return recs

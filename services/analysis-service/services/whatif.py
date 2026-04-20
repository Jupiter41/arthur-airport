"""What-if analysis engine.

Accepts proposed actions, projects their effect on operational KPIs using a
simplified in-memory model (no Kafka events or Neo4j writes), and returns
before/after comparisons.

P2-3-1 through P2-3-5.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from uuid import uuid4

from models.domain import (
    ActionType,
    AnalysisLogEntry,
    KPIProjection,
    WhatIfAction,
    WhatIfRequest,
    WhatIfResponse,
)
from services.state import OperationalState

logger = logging.getLogger(__name__)

# ── Analysis log (in-memory, survives within process lifecycle) ──

_analysis_log: list[AnalysisLogEntry] = []
MAX_LOG_ENTRIES = 500


def get_analysis_log() -> list[AnalysisLogEntry]:
    return list(_analysis_log)


def _log_entry(entry: AnalysisLogEntry) -> None:
    _analysis_log.append(entry)
    if len(_analysis_log) > MAX_LOG_ENTRIES:
        _analysis_log.pop(0)


# ── What-if projection ──────────────────────────────────────


def run_what_if(
    state: OperationalState,
    request: WhatIfRequest,
) -> WhatIfResponse:
    """P2-3-1: Run what-if projection for proposed actions.

    Creates a lightweight shadow of the current state and simulates the
    effects of each action over the requested horizon. No Kafka events
    or Neo4j writes are produced.
    """
    now = state.sim_time or datetime.now(timezone.utc)

    # 1. Compute baseline KPIs from current state
    baseline = _compute_kpis(state, action_index=-1)

    # 2. Run each action through the shadow simulation
    projections: list[KPIProjection] = []
    for i, action in enumerate(request.actions):
        shadow = _create_shadow(state)
        _apply_action_to_shadow(shadow, action, request.horizon_minutes)
        projection = _compute_kpis(shadow, action_index=i)
        projections.append(projection)

        # Log the query
        _log_entry(AnalysisLogEntry(
            id=f"wif-{uuid4().hex[:12]}",
            timestamp=now,
            entry_type="what_if",
            action=action,
            projected_outcome=projection,
        ))

    return WhatIfResponse(
        baseline=baseline,
        projections=projections,
        sim_time_at_request=now,
        horizon_minutes=request.horizon_minutes,
    )


# ── Shadow simulation ────────────────────────────────────────


def _create_shadow(state: OperationalState) -> OperationalState:
    """P2-3-2: Create lightweight shadow copy of operational state.

    Deep copies mutable nested structures while keeping a shallow copy
    for immutable data. Does not produce Kafka events or Neo4j writes.
    """
    shadow = OperationalState()
    shadow.sim_time = state.sim_time
    shadow.speed_multiplier = state.speed_multiplier
    shadow.tick_number = state.tick_number
    shadow.weather = copy.copy(state.weather)

    # Deep copy flight states
    shadow.flights = {
        fid: copy.copy(fs) for fid, fs in state.flights.items()
    }

    # Copy security state
    shadow.security = {
        t: copy.copy(s) for t, s in state.security.items()
    }

    # Copy baggage zones
    shadow.baggage_zones = {
        z: copy.copy(bz) for z, bz in state.baggage_zones.items()
    }

    # Copy vehicles
    shadow.vehicles = {
        vt: copy.copy(vs) for vt, vs in state.vehicles.items()
    }

    # Copy incidents
    shadow.active_incidents = {
        k: dict(v) for k, v in state.active_incidents.items()
    }

    return shadow


def _apply_action_to_shadow(
    shadow: OperationalState,
    action: WhatIfAction,
    horizon_minutes: int,
) -> None:
    """Apply the proposed action's effects to the shadow state."""
    handlers = {
        ActionType.OPEN_SECURITY_LANE: _sim_open_lane,
        ActionType.EARLY_GATE_CALL: _sim_early_gate_call,
        ActionType.REDIRECT_CHECKIN: _sim_redirect_checkin,
        ActionType.REASSIGN_GATE: _sim_reassign_gate,
        ActionType.DELAY_TAXI: _sim_delay_taxi,
        ActionType.SWAP_GATES: _sim_swap_gates,
        ActionType.HOLD_CONNECTING_FLIGHT: _sim_hold_flight,
        ActionType.FAST_TRACK_PASSENGERS: _sim_fast_track,
        ActionType.REBOOK_PASSENGERS: _sim_rebook,
        ActionType.GROUND_DELAY_PROGRAM: _sim_gdp,
        ActionType.REDISTRIBUTE_VEHICLES: _sim_redistribute_vehicles,
        ActionType.DEFER_TASK: _sim_defer_task,
        ActionType.REDIRECT_BAGGAGE: _sim_redirect_baggage,
        ActionType.EXPEDITE_LOADING: _sim_expedite_loading,
    }
    handler = handlers.get(action.action_type)
    if handler:
        handler(shadow, action, horizon_minutes)


# ── Action simulators ────────────────────────────────────────
# Each modifies the shadow state to project the action's effect.


def _sim_open_lane(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    terminal = action.parameters.get("terminal", "")
    if terminal in shadow.security:
        sec = shadow.security[terminal]
        old_lanes = sec.open_lanes
        sec.open_lanes = action.parameters.get("new_lane_count", old_lanes + 1)
        # Project queue reduction: new throughput ratio
        ratio = old_lanes / sec.open_lanes if sec.open_lanes else 1
        sec.queue_depth = max(0, int(sec.queue_depth * ratio))
        sec.forecast_wait_minutes *= ratio


def _sim_early_gate_call(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    terminal = action.parameters.get("terminal", "")
    if terminal in shadow.security:
        # Reduces gate area crowding — model as 15% queue reduction
        sec = shadow.security[terminal]
        sec.queue_depth = max(0, int(sec.queue_depth * 0.85))


def _sim_redirect_checkin(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    from_t = action.parameters.get("from_terminal", "")
    to_t = action.parameters.get("to_terminal", "")
    if from_t in shadow.security and to_t in shadow.security:
        transfer = shadow.security[from_t].queue_depth // 3
        shadow.security[from_t].queue_depth -= transfer
        shadow.security[to_t].queue_depth += transfer


def _sim_reassign_gate(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    # Model: one fewer flight occupying a gate in the congested terminal
    orig = action.parameters.get("original_terminal", "")
    for f in shadow.flights.values():
        if f.terminal == orig and f.status in ("approaching", "holding") and not f.gate:
            alt = action.parameters.get("alternate_terminal", "")
            f.terminal = alt
            break


def _sim_delay_taxi(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    terminal = action.parameters.get("terminal", "")
    hold_min = action.parameters.get("hold_minutes", 10)
    for f in shadow.flights.values():
        if f.terminal == terminal and f.status in ("approaching", "holding", "landed"):
            f.delay_minutes += hold_min


def _sim_swap_gates(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    # Minimal model: reduces average delay by improving turnover
    terminal = action.parameters.get("terminal", "")
    for f in shadow.flights.values():
        if f.terminal == terminal and f.status in ("boarding", "ready_for_departure"):
            f.delay_minutes = max(0, f.delay_minutes - 5)


def _sim_hold_flight(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    fid = action.parameters.get("outbound_flight", "")
    hold_min = action.parameters.get("hold_minutes", 15)
    if fid in shadow.flights:
        shadow.flights[fid].delay_minutes += hold_min


def _sim_fast_track(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    # Model: reduce security queue in the relevant terminal slightly
    inbound = action.parameters.get("inbound_flight", "")
    pax = action.parameters.get("passenger_count", 0)
    if inbound in shadow.flights:
        t = shadow.flights[inbound].terminal
        if t and t in shadow.security:
            shadow.security[t].queue_depth = max(
                0, shadow.security[t].queue_depth - pax,
            )


def _sim_rebook(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    # Model: remove connection pressure on outbound flight
    outbound = action.parameters.get("outbound_flight", "")
    if outbound in shadow.flights:
        # No longer need to hold — reduce potential delay
        shadow.flights[outbound].delay_minutes = max(
            0, shadow.flights[outbound].delay_minutes - 10,
        )


def _sim_gdp(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    stagger = action.parameters.get("stagger_minutes", 5)
    i = 0
    for f in shadow.flights.values():
        if f.flight_type == "departure" and f.status in (
            "scheduled", "boarding", "ready_for_departure",
        ):
            f.delay_minutes += stagger * i
            i += 1
    # GDP reduces holding stack pressure
    for f in shadow.flights.values():
        if f.status == "holding":
            f.delay_minutes = max(0, f.delay_minutes - 10)


def _sim_redistribute_vehicles(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    vtype = action.parameters.get("vehicle_type", "")
    if vtype in shadow.vehicles:
        v = shadow.vehicles[vtype]
        # Model: reduce dispatched count by returning 1 vehicle faster
        v.dispatched = max(0, v.dispatched - 1)
        v.utilisation_pct = (v.dispatched / v.total * 100) if v.total else 0


def _sim_defer_task(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    vtype = action.parameters.get("vehicle_type", "")
    if vtype in shadow.vehicles:
        v = shadow.vehicles[vtype]
        v.dispatched = max(0, v.dispatched - 2)
        v.utilisation_pct = (v.dispatched / v.total * 100) if v.total else 0


def _sim_redirect_baggage(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    zone = action.parameters.get("zone", "")
    if zone in shadow.baggage_zones:
        z = shadow.baggage_zones[zone]
        z.current_count = int(z.current_count * 0.7)
        z.utilisation_pct = (z.current_count / z.capacity * 100) if z.capacity else 0


def _sim_expedite_loading(
    shadow: OperationalState, action: WhatIfAction, horizon: int,
) -> None:
    zone = action.parameters.get("zone", "")
    if zone in shadow.baggage_zones:
        z = shadow.baggage_zones[zone]
        z.current_count = max(0, z.current_count - 25)
        z.utilisation_pct = (z.current_count / z.capacity * 100) if z.capacity else 0


# ── KPI computation ──────────────────────────────────────────


def _compute_kpis(state: OperationalState, action_index: int) -> KPIProjection:
    """Compute operational KPIs from state snapshot."""
    active_flights = [
        f for f in state.flights.values()
        if f.status not in ("completed", "cancelled")
    ]

    total_delay = sum(f.delay_minutes for f in active_flights)

    # Estimate missed connections from delay > 45 min
    # (simplified — real model would use MCT per airport)
    missed = sum(
        1 for f in active_flights
        if f.flight_type == "arrival" and f.delay_minutes > 45
    )

    # Average security queue depth
    avg_queue = (
        sum(s.queue_depth for s in state.security.values())
        / max(1, len(state.security))
    )

    # Cascade depth: max delay chain length (simplified)
    cascade = 0
    if active_flights:
        delays = sorted(
            [f.delay_minutes for f in active_flights if f.delay_minutes > 0],
            reverse=True,
        )
        cascade = min(len(delays), 5)

    # Gate utilisation
    free_gates = state.get_free_gates_by_terminal()
    total_gates = sum(
        14 for _ in free_gates  # 14 gates per terminal default
    )
    occupied = total_gates - sum(free_gates.values())
    gate_util = (occupied / total_gates * 100) if total_gates else 0

    # Baggage throughput
    bag_utils = [z.utilisation_pct for z in state.baggage_zones.values()]
    baggage_pct = sum(bag_utils) / max(1, len(bag_utils)) if bag_utils else 0

    # Confidence decreases with projection duration
    confidence = 0.85 if action_index < 0 else 0.70

    return KPIProjection(
        action_index=action_index,
        delay_minutes_total=total_delay,
        missed_connections=missed,
        avg_queue_depth=avg_queue,
        cascade_depth=cascade,
        gate_utilisation_pct=gate_util,
        baggage_throughput_pct=baggage_pct,
        confidence=confidence,
    )

"""What-if analysis engine.

Accepts proposed actions, projects their effect on operational KPIs using a
simplified in-memory model (no Kafka events or Neo4j writes), and returns
before/after comparisons.

P2-3-1 through P2-3-5.
"""

from __future__ import annotations

import copy
import logging
from uuid import uuid4
from _common.effects import EFFECT_MODEL_VERSION

from models.domain import (
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
    now = state.sim_time
    if now is None:
        raise ValueError("Simulation clock not available yet")

    # 1. Compute baseline KPIs from current state
    from services.effect_adapter import patch_operational, project

    # Compare both arms at the same horizon, including natural queue evolution.
    untreated, _ = project(state, "no_action", {}, request.horizon_minutes)
    base_shadow = _create_shadow(state)
    patch_operational(base_shadow, untreated.baseline)
    baseline = _compute_kpis(base_shadow, action_index=-1)

    # 2. Run each action through the shadow simulation
    projections: list[KPIProjection] = []
    for i, action in enumerate(request.actions):
        shadow = _create_shadow(state)
        result, _ = project(state, action.action_type.value, action.parameters, request.horizon_minutes)
        patch_operational(shadow, result.projected)
        projection = _compute_kpis(shadow, action_index=i)
        projection.effect_status = result.action_status[0]
        projections.append(projection)

        # Log the query
        _log_entry(AnalysisLogEntry(
            id=f"wif-{uuid4().hex[:12]}",
            effect_model_version=EFFECT_MODEL_VERSION,
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
    shadow.gates = copy.deepcopy(state.gates)
    shadow.graph_loaded = state.graph_loaded
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
    shadow.baggage_targets = copy.deepcopy(state.baggage_targets)

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
    from services.effect_adapter import patch_operational, project

    result, _ = project(shadow, action.action_type.value, action.parameters, horizon_minutes)
    patch_operational(shadow, result.projected)


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
    total_gates = len(state.gates) if state.graph_loaded else 14 * len(free_gates)
    occupied = total_gates - sum(free_gates.values())
    gate_util = (occupied / total_gates * 100) if total_gates else 0

    # Baggage throughput
    bag_utils = [z.utilisation_pct for z in state.baggage_zones.values()]
    baggage_pct = sum(bag_utils) / max(1, len(bag_utils)) if bag_utils else 0

    # Confidence decreases with projection duration
    confidence = 0.85 if action_index < 0 else 0.70

    return KPIProjection(
        action_index=action_index,
        effect_model_version=EFFECT_MODEL_VERSION,
        delay_minutes_total=total_delay,
        missed_connections=missed,
        avg_queue_depth=avg_queue,
        cascade_depth=cascade,
        gate_utilisation_pct=gate_util,
        baggage_throughput_pct=baggage_pct,
        confidence=confidence,
    )

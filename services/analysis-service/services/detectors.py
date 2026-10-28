"""Bottleneck detection engine.

Six detector functions that evaluate the current operational state and produce
Bottleneck objects when thresholds are breached.

P2-1-2 through P2-1-6.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import uuid4

from models.domain import Bottleneck, BottleneckSeverity, BottleneckType
from services.state import OperationalState

logger = logging.getLogger(__name__)

# ── Thresholds ───────────────────────────────────────────────

SECURITY_WAIT_WARNING_MIN = 20.0
SECURITY_WAIT_CRITICAL_MIN = 30.0
SECURITY_CONFIDENCE_THRESHOLD = 0.75

GATE_FREE_WARNING = 2
GATE_FREE_CRITICAL = 0

MAKEUP_UTIL_WARNING_PCT = 90.0
MAKEUP_UTIL_CRITICAL_PCT = 95.0
MAKEUP_DURATION_THRESHOLD = timedelta(minutes=5)

CONNECTION_CLUSTER_MIN_PAX = 5

VEHICLE_UTIL_WARNING_PCT = 85.0
VEHICLE_FORECAST_HORIZON_MIN = 15

RUNWAY_CAPACITY_LOW_PCT = 60.0
RUNWAY_QUEUE_THRESHOLD = 5

# Financial pressure thresholds (EUR) — sourced from cost-service CostSignalSnapshot
EU261_PRESSURE_WARNING = 10_000.0
EU261_PRESSURE_CRITICAL = 30_000.0
HOLDING_FUEL_WARNING = 5_000.0
HOLDING_FUEL_CRITICAL = 15_000.0
GROUND_HANDLING_WARNING = 50_000.0


def detect_all(
    state: OperationalState,
    existing: dict[str, Bottleneck],
) -> list[Bottleneck]:
    """Run all detectors and return newly detected bottlenecks.

    ``existing`` is the dict of currently active bottlenecks keyed by id.
    Detectors should not re-create a bottleneck that already covers the same zone.
    """
    results: list[Bottleneck] = []
    now = state.sim_time
    if now is None:
        return results

    # Keys of existing bottlenecks by (type, zone) for dedup
    active_keys = {(b.type, b.zone) for b in existing.values() if b.resolved_at is None}

    results.extend(_detect_security_queue(state, now, active_keys))
    results.extend(_detect_gate_utilisation(state, now, active_keys))
    results.extend(_detect_baggage_throughput(state, now, active_keys))
    results.extend(_detect_connection_clusters(state, now, active_keys))
    results.extend(_detect_ground_vehicle(state, now, active_keys))
    results.extend(_detect_runway_capacity(state, now, active_keys))
    results.extend(_detect_active_incidents(state, now, active_keys))
    results.extend(_detect_financial_pressure(state, now, active_keys))

    return results


def check_resolved(
    state: OperationalState,
    bottleneck: Bottleneck,
) -> bool:
    """Check if a bottleneck has naturally resolved."""
    now = state.sim_time
    if now is None:
        return False

    if bottleneck.type == BottleneckType.SECURITY_QUEUE:
        terminal = bottleneck.zone
        sec = state.security.get(terminal)
        if sec and max(sec.forecast_wait_minutes, sec.observed_wait_minutes) < SECURITY_WAIT_WARNING_MIN * 0.8:
            return True

    elif bottleneck.type == BottleneckType.GATE_UTILISATION:
        terminal = bottleneck.zone
        free = state.get_free_gates_by_terminal().get(terminal, 99)
        if free > GATE_FREE_WARNING:
            return True

    elif bottleneck.type == BottleneckType.BAGGAGE_THROUGHPUT:
        zone = bottleneck.zone
        bz = state.baggage_zones.get(zone)
        if bz and bz.utilisation_pct < MAKEUP_UTIL_WARNING_PCT * 0.9:
            return True

    elif bottleneck.type == BottleneckType.GROUND_VEHICLE:
        vtype = bottleneck.zone
        v = state.vehicles.get(vtype)
        if v and v.utilisation_pct < VEHICLE_UTIL_WARNING_PCT * 0.9:
            return True

    elif bottleneck.type == BottleneckType.RUNWAY_CAPACITY:
        if state.weather.runway_capacity_pct >= RUNWAY_CAPACITY_LOW_PCT:
            return True

    elif bottleneck.type == BottleneckType.CONNECTION_CLUSTER:
        # Connection clusters resolve when the inbound flight lands
        flight_id = bottleneck.metrics.get("inbound_flight")
        if flight_id and flight_id in state.flights:
            f = state.flights[flight_id]
            if f.status in ("arrived", "turnaround", "completed"):
                return True

    elif bottleneck.type == BottleneckType.ACTIVE_INCIDENT:
        incident_id = bottleneck.metrics.get("incident_id")
        if incident_id:
            incident = state.active_incidents.get(incident_id)
            if incident is None or incident.get("status") == "resolved":
                return True

    return False


# ── Individual detectors ─────────────────────────────────────


def _detect_security_queue(
    state: OperationalState,
    now: datetime,
    active_keys: set,
) -> list[Bottleneck]:
    """P2-1-2: Security queue bottleneck from congestion events and forecast."""
    results = []
    for terminal, sec in state.security.items():
        key = (BottleneckType.SECURITY_QUEUE, terminal)
        if key in active_keys:
            continue

        observed = sec.observed_wait_minutes
        wait = max(sec.forecast_wait_minutes, observed)
        conf = sec.forecast_confidence

        observed_congestion = observed >= SECURITY_WAIT_WARNING_MIN
        predicted_congestion = sec.forecast_wait_minutes >= SECURITY_WAIT_WARNING_MIN and conf >= SECURITY_CONFIDENCE_THRESHOLD
        if observed_congestion or predicted_congestion:
            severity = (
                BottleneckSeverity.CRITICAL
                if wait >= SECURITY_WAIT_CRITICAL_MIN
                else BottleneckSeverity.WARNING
            )
            results.append(Bottleneck(
                id=f"bn-{uuid4().hex[:12]}",
                type=BottleneckType.SECURITY_QUEUE,
                severity=severity,
                zone=terminal,
                root_cause=(f"Observed security queue wait is {observed:.0f} min in {terminal}"
                if observed_congestion else
                    f"Security queue forecast predicts {wait:.0f} min wait "
                    f"(confidence {conf:.0%}) in {terminal}"
                ),
                estimated_duration_minutes=max(15, wait - 10),
                affected_entity_count=sec.queue_depth,
                detected_at=now,
                metrics={
                    "queue_depth": sec.queue_depth,
                    "forecast_wait_minutes": wait,
                    "signal_source": "observed" if observed_congestion else "forecast",
                    "forecast_confidence": conf,
                    "open_lanes": sec.open_lanes,
                },
            ))
    return results


def _detect_gate_utilisation(
    state: OperationalState,
    now: datetime,
    active_keys: set,
) -> list[Bottleneck]:
    """P2-1-3: Gate utilisation bottleneck when free gates < threshold."""
    results = []
    free_gates = state.get_free_gates_by_terminal()
    waiting = len(state.get_flights_needing_gate())

    for terminal, free in free_gates.items():
        key = (BottleneckType.GATE_UTILISATION, terminal)
        if key in active_keys:
            continue

        if free <= GATE_FREE_WARNING and waiting > 0:
            severity = (
                BottleneckSeverity.CRITICAL
                if free <= GATE_FREE_CRITICAL
                else BottleneckSeverity.WARNING
            )
            # Count active flights at gates in this terminal
            occupied = sum(
                1 for f in state.flights.values()
                if f.terminal == terminal and f.gate
                and f.status not in ("completed", "cancelled", "departed", "airborne")
            )
            results.append(Bottleneck(
                id=f"bn-{uuid4().hex[:12]}",
                type=BottleneckType.GATE_UTILISATION,
                severity=severity,
                zone=terminal,
                root_cause=(
                    f"Only {free} free gate(s) in {terminal} "
                    f"with {waiting} flight(s) awaiting assignment"
                ),
                estimated_duration_minutes=30,
                affected_entity_count=waiting,
                detected_at=now,
                metrics={
                    "free_gates": free,
                    "flights_waiting": waiting,
                    "occupied_gates": occupied,
                },
            ))
    return results


def _detect_baggage_throughput(
    state: OperationalState,
    now: datetime,
    active_keys: set,
) -> list[Bottleneck]:
    """P2-1-4: Baggage make-up carousel bottleneck at >90% util for >5 min."""
    results = []
    for zone_name, zone in state.baggage_zones.items():
        key = (BottleneckType.BAGGAGE_THROUGHPUT, zone_name)
        if key in active_keys:
            continue

        if zone.utilisation_pct >= MAKEUP_UTIL_WARNING_PCT:
            # Track how long it's been over threshold
            if state.makeup_over_threshold_since[zone_name] is None:
                state.makeup_over_threshold_since[zone_name] = now
            since = state.makeup_over_threshold_since[zone_name]
            duration = now - since if since else timedelta()

            if duration >= MAKEUP_DURATION_THRESHOLD:
                severity = (
                    BottleneckSeverity.CRITICAL
                    if zone.utilisation_pct >= MAKEUP_UTIL_CRITICAL_PCT
                    else BottleneckSeverity.WARNING
                )
                results.append(Bottleneck(
                    id=f"bn-{uuid4().hex[:12]}",
                    type=BottleneckType.BAGGAGE_THROUGHPUT,
                    severity=severity,
                    zone=zone_name,
                    root_cause=(
                        f"Make-up zone {zone_name} at {zone.utilisation_pct:.0f}% "
                        f"utilisation for {duration.total_seconds() / 60:.0f} min"
                    ),
                    estimated_duration_minutes=15,
                    affected_entity_count=zone.current_count,
                    detected_at=now,
                    metrics={
                        "utilisation_pct": zone.utilisation_pct,
                        "current_bags": zone.current_count,
                        "capacity": zone.capacity,
                        "duration_minutes": duration.total_seconds() / 60,
                    },
                ))
        else:
            state.makeup_over_threshold_since[zone_name] = None

    return results


def _detect_connection_clusters(
    state: OperationalState,
    now: datetime,
    active_keys: set,
) -> list[Bottleneck]:
    """P2-1-5: Connection risk cluster — 5+ pax on same delayed inbound + outbound.

    Uses cached connection_clusters data from Neo4j queries (run periodically).
    """
    results = []
    for cluster in state.connection_clusters:
        inbound = cluster.get("inbound_flight", "")
        outbound = cluster.get("outbound_flight", "")
        zone_key = f"{inbound}->{outbound}"
        key = (BottleneckType.CONNECTION_CLUSTER, zone_key)
        if key in active_keys:
            continue

        pax_count = cluster.get("pax_count", 0)
        if pax_count >= CONNECTION_CLUSTER_MIN_PAX:
            results.append(Bottleneck(
                id=f"bn-{uuid4().hex[:12]}",
                type=BottleneckType.CONNECTION_CLUSTER,
                severity=BottleneckSeverity.CRITICAL,
                zone=zone_key,
                root_cause=(
                    f"{pax_count} connecting passengers on delayed {inbound} "
                    f"risk missing connection to {outbound}"
                ),
                estimated_duration_minutes=45,
                affected_entity_count=pax_count,
                detected_at=now,
                metrics={
                    "inbound_flight": inbound,
                    "outbound_flight": outbound,
                    "passenger_count": pax_count,
                    "inbound_delay": cluster.get("inbound_delay", 0),
                },
            ))
    return results


def _detect_ground_vehicle(
    state: OperationalState,
    now: datetime,
    active_keys: set,
) -> list[Bottleneck]:
    """P2-1-6: Ground vehicle bottleneck when type util >85%."""
    results = []
    for vtype, v in state.vehicles.items():
        key = (BottleneckType.GROUND_VEHICLE, vtype)
        if key in active_keys:
            continue

        if v.utilisation_pct >= VEHICLE_UTIL_WARNING_PCT and v.total > 0:
            # Estimate upcoming demand by counting flights in turnaround
            upcoming_demand = sum(
                1 for f in state.flights.values()
                if f.status in ("arrived", "turnaround")
            )
            if upcoming_demand > 0:
                results.append(Bottleneck(
                    id=f"bn-{uuid4().hex[:12]}",
                    type=BottleneckType.GROUND_VEHICLE,
                    severity=BottleneckSeverity.WARNING,
                    zone=vtype,
                    root_cause=(
                        f"{vtype} utilisation at {v.utilisation_pct:.0f}% "
                        f"({v.dispatched}/{v.total}) with {upcoming_demand} "
                        f"flights in turnaround"
                    ),
                    estimated_duration_minutes=20,
                    affected_entity_count=upcoming_demand,
                    detected_at=now,
                    metrics={
                        "utilisation_pct": v.utilisation_pct,
                        "dispatched": v.dispatched,
                        "total": v.total,
                        "upcoming_turnarounds": upcoming_demand,
                    },
                ))
    return results


def _detect_runway_capacity(
    state: OperationalState,
    now: datetime,
    active_keys: set,
) -> list[Bottleneck]:
    """Runway capacity bottleneck when weather reduces capacity below 60%."""
    key = (BottleneckType.RUNWAY_CAPACITY, "airfield")
    if key in active_keys:
        return []

    cap = state.weather.runway_capacity_pct
    if cap >= RUNWAY_CAPACITY_LOW_PCT:
        return []

    # Count flights in approach/holding queue
    queue_count = sum(
        1 for f in state.flights.values()
        if f.status in ("approach", "approaching", "holding", "ready_for_departure", "taxiing")
    )
    if queue_count < RUNWAY_QUEUE_THRESHOLD:
        return []

    severity = (
        BottleneckSeverity.CRITICAL
        if cap < 40
        else BottleneckSeverity.WARNING
    )

    return [Bottleneck(
        id=f"bn-{uuid4().hex[:12]}",
        type=BottleneckType.RUNWAY_CAPACITY,
        severity=severity,
        zone="airfield",
        root_cause=(
            f"Weather ({state.weather.category}) reduces runway capacity to "
            f"{cap:.0f}% with {queue_count} flights queued"
        ),
        estimated_duration_minutes=60,
        affected_entity_count=queue_count,
        detected_at=now,
        metrics={
            "weather_category": state.weather.category,
            "capacity_pct": cap,
            "queued_flights": queue_count,
            "visibility_m": state.weather.visibility_m,
            "wind_speed_kt": state.weather.wind_speed_kt,
        },
    )]


# ── Incident severity thresholds ────────────────────────────

INCIDENT_SEVERITY_TO_BOTTLENECK = {
    "critical": BottleneckSeverity.CRITICAL,
    "high": BottleneckSeverity.CRITICAL,
    "medium": BottleneckSeverity.WARNING,
}

INCIDENT_TYPE_DESCRIPTIONS = {
    "runway_incursion": "Runway incursion — runway closed, arrivals/departures affected",
    "security_breach": "Security breach — terminal evacuation or re-screening required",
    "system_failure": "System failure — automated subsystem degraded",
    "baggage_fire": "Baggage fire — baggage system disrupted",
    "severe_weather": "Severe weather event — capacity reduced",
}


def _detect_active_incidents(
    state: OperationalState,
    now: datetime,
    active_keys: set,
) -> list[Bottleneck]:
    """Detect bottlenecks from active critical/high incidents.

    Creates an immediate bottleneck entry for each unresolved incident with
    severity >= medium, allowing the recommendation engine to propose
    mitigations without waiting for operational metrics to degrade.
    """
    results = []
    for incident in state.active_incidents.values():
        inc_id = incident.get("id", "")
        inc_type = incident.get("type", "unknown")
        inc_severity = incident.get("severity", "low")
        inc_status = incident.get("status", "active")

        if inc_status == "resolved":
            continue

        bn_severity = INCIDENT_SEVERITY_TO_BOTTLENECK.get(inc_severity)
        if bn_severity is None:
            continue

        zone = incident.get("location", inc_type)
        key = (BottleneckType.ACTIVE_INCIDENT, zone)
        if key in active_keys:
            continue

        description = INCIDENT_TYPE_DESCRIPTIONS.get(
            inc_type, f"Active {inc_type} incident"
        )
        affected = incident.get("affected_count", 0)
        ttr = incident.get("ttr_remaining_minutes", 30)

        results.append(Bottleneck(
            id=f"bn-{uuid4().hex[:12]}",
            type=BottleneckType.ACTIVE_INCIDENT,
            severity=bn_severity,
            zone=zone,
            root_cause=description,
            estimated_duration_minutes=ttr if ttr > 0 else 30,
            affected_entity_count=affected,
            detected_at=now,
            metrics={
                "incident_id": inc_id,
                "incident_type": inc_type,
                "incident_severity": inc_severity,
                "location": zone,
            },
        ))
    return results


# ── Financial pressure detection (G5) ───────────────────────

def _detect_financial_pressure(
    state: OperationalState,
    now: datetime,
    active_keys: set,
) -> list[Bottleneck]:
    """Detect financial-pressure bottlenecks from cost-service signals.

    Fires when eu261_exposure, holding_fuel, or ground_handling costs breach
    thresholds published via CostSignalSnapshot events on cost.events.  Each
    signal produces at most one bottleneck so the recommender can generate the
    corresponding action (OPEN_SECURITY_LANE, GROUND_DELAY_PROGRAM,
    REASSIGN_GATE / OPEN_MAKEUP_CAROUSEL).
    """
    if not state.cost_signals:
        return []

    results = []
    cs = state.cost_signals

    eu261 = cs.get("eu261_exposure", 0.0)
    if eu261 >= EU261_PRESSURE_WARNING:
        key = (BottleneckType.FINANCIAL_PRESSURE, "security-eu261")
        if key not in active_keys:
            severity = (
                BottleneckSeverity.CRITICAL if eu261 >= EU261_PRESSURE_CRITICAL
                else BottleneckSeverity.WARNING
            )
            results.append(Bottleneck(
                id=f"bn-{uuid4().hex[:12]}",
                type=BottleneckType.FINANCIAL_PRESSURE,
                severity=severity,
                zone="security-eu261",
                root_cause=(
                    f"EU261 exposure €{eu261:,.0f} — queuing delays risk "
                    f"compensation claims"
                ),
                estimated_duration_minutes=60,
                affected_entity_count=0,
                detected_at=now,
                metrics={
                    "signal": "eu261_exposure",
                    "eu261_exposure": eu261,
                    "threshold": EU261_PRESSURE_WARNING,
                },
            ))

    holding = cs.get("holding_fuel", 0.0)
    if holding >= HOLDING_FUEL_WARNING:
        key = (BottleneckType.FINANCIAL_PRESSURE, "airfield-holding-fuel")
        if key not in active_keys:
            severity = (
                BottleneckSeverity.CRITICAL if holding >= HOLDING_FUEL_CRITICAL
                else BottleneckSeverity.WARNING
            )
            results.append(Bottleneck(
                id=f"bn-{uuid4().hex[:12]}",
                type=BottleneckType.FINANCIAL_PRESSURE,
                severity=severity,
                zone="airfield-holding-fuel",
                root_cause=(
                    f"Holding fuel cost €{holding:,.0f} — aircraft burning fuel "
                    f"in stack instead of landing"
                ),
                estimated_duration_minutes=30,
                affected_entity_count=0,
                detected_at=now,
                metrics={
                    "signal": "holding_fuel",
                    "holding_fuel": holding,
                    "threshold": HOLDING_FUEL_WARNING,
                },
            ))

    handling = cs.get("ground_handling", 0.0)
    if handling >= GROUND_HANDLING_WARNING:
        key = (BottleneckType.FINANCIAL_PRESSURE, "gates-ground-handling")
        if key not in active_keys:
            results.append(Bottleneck(
                id=f"bn-{uuid4().hex[:12]}",
                type=BottleneckType.FINANCIAL_PRESSURE,
                severity=BottleneckSeverity.WARNING,
                zone="gates-ground-handling",
                root_cause=(
                    f"Ground handling cost €{handling:,.0f} — gate conflicts "
                    f"inflating turnaround crew overtime"
                ),
                estimated_duration_minutes=45,
                affected_entity_count=0,
                detected_at=now,
                metrics={
                    "signal": "ground_handling",
                    "ground_handling": handling,
                    "threshold": GROUND_HANDLING_WARNING,
                },
            ))

    return results

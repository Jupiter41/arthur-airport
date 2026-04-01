"""Kafka consumer for incident-service.

Consumes:
  - sim.clock          → SimClockTick (TTR countdown + probabilistic event firing)
  - incidents.inject   → InjectIncident (manual injection)
  - weather.events     → WeatherStateChanged (auto-create severe_weather on IMC/LIFR)
  - baggage.events     → BaggageFlagged (DG class 3 → probabilistic baggage_fire)
  - passengers.events  → SecurityCongestionDetected (auto-create security_congestion)
"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta
from typing import Callable, Awaitable

from confluent_kafka import Consumer

from db.neo4j import find_active_incident_by_type_and_location
from kafka.producer import (
    emit_incident_alert,
    emit_incident_cascaded,
    emit_incident_created,
    emit_incident_status_changed,
)
from services.lifecycle import (
    create_incident,
    resolve_incident,
    set_lifecycle_callbacks,
    tick_ttr,
)
from services.cascade import fire_pending_cascades
from services.protocols import build_alert
from metrics import (
    incidents_active as m_active,
    incidents_created_total as m_created,
    incident_ttr_minutes as m_ttr,
    cascade_events_total as m_cascade,
    cascade_depth_max as m_cascade_depth,
    protocols_activated_total as m_protocols,
    envelope_invalid_total as m_envelope_invalid,
)

logger = logging.getLogger(__name__)

# ── Constants (not mutated) ──────────────────────────────────

SUPPRESSION_WINDOW_HRS = float(os.getenv("INCIDENT_SUPPRESSION_WINDOW_HRS", "2"))

BASE_PROBABILITIES = {
    "runway_incursion": float(os.getenv("PROB_RUNWAY_INCURSION_PER_HR", "0.005")),
    "baggage_fire": float(os.getenv("PROB_BAGGAGE_FIRE_PER_HR", "0.008")),
    "security_breach": float(os.getenv("PROB_SECURITY_BREACH_PER_HR", "0.010")),
    "system_failure": float(os.getenv("PROB_SYSTEM_FAILURE_PER_HR", "0.015")),
}

PEAK_HOURS = {7, 8, 9, 17, 18, 19}
RUNWAY_IDS = ["runway-09L", "runway-09R", "runway-27L", "runway-27R"]
TERMINAL_IDS = ["terminal-A", "terminal-B", "terminal-C"]
SYSTEM_SUBTYPES = ["conveyor_jam", "power_outage", "it_failure"]


# ── Class-based state holder ────────────────────────────────


class IncidentConsumerState:
    """Holds all mutable runtime state for the incident consumer.

    Eliminates module-level globals that caused UnboundLocalError bugs
    (sprints 1–3, 6) due to Python's `global` scoping rules.
    """

    MAX_PROCESSED = 20000
    MAX_ALERTS = 200

    def __init__(self) -> None:
        self.sim_time: datetime | None = None
        self.last_tick_sim_time: datetime | None = None
        self.processed_events: set[str] = set()
        self.last_prob_hour: int = -1
        self.last_incident_times: dict[str, datetime] = {}
        self.current_weather_category: str = "CAVOK"
        self.max_cascade_depth: int = 0
        self.ws_broadcast: Callable[[dict], Awaitable[None]] | None = None
        self.active_alerts: list[dict] = []

    def check_idempotency(self, event_id: str) -> bool:
        """Returns True if the event has already been processed (duplicate)."""
        if not event_id:
            return False
        if event_id in self.processed_events:
            return True
        self.processed_events.add(event_id)
        if len(self.processed_events) > self.MAX_PROCESSED:
            to_remove = list(self.processed_events)[:self.MAX_PROCESSED // 2]
            for item in to_remove:
                self.processed_events.discard(item)
        return False

    def add_alert(self, alert: dict) -> None:
        self.active_alerts.insert(0, alert)
        if len(self.active_alerts) > self.MAX_ALERTS:
            self.active_alerts.pop()


# Module-level singleton
_state = IncidentConsumerState()
_consumer: Consumer | None = None
_consumer_running = False


def set_ws_broadcast(fn):
    _state.ws_broadcast = fn


def get_sim_time() -> datetime | None:
    return _state.sim_time


def get_active_alerts() -> list[dict]:
    return list(_state.active_alerts)


def is_consumer_running() -> bool:
    return _consumer_running


# ── Lifecycle callbacks (wired at startup) ───────────────────


async def _on_incident_created(incident: dict, sim_time: datetime, parent_id: str | None):
    """Called when lifecycle creates an incident."""
    emit_incident_created(incident, sim_time)
    emit_incident_alert(incident, sim_time)

    alert = build_alert(incident, sim_time)
    _state.add_alert(alert)

    if parent_id:
        emit_incident_cascaded(parent_id, incident, sim_time)
        m_cascade.labels(parent_type=incident.get("type", "unknown")).inc()

    # Update Prometheus
    inc_type = incident.get("type", "unknown")
    severity = incident.get("severity", "unknown")
    trigger = incident.get("trigger", "unknown")
    m_created.labels(type=inc_type, severity=severity, trigger=trigger).inc()
    m_active.labels(type=inc_type, severity=severity).inc()

    protocol = incident.get("protocol", "")
    if protocol:
        m_protocols.labels(protocol=protocol).inc()

    depth = incident.get("cascade_depth", 0)
    if depth > 0:
        if depth > _state.max_cascade_depth:
            _state.max_cascade_depth = depth
            m_cascade_depth.set(depth)

    # WebSocket broadcast
    if _state.ws_broadcast:
        await _state.ws_broadcast({
            "type": "IncidentCreated",
            "sim_time": sim_time.isoformat(),
            "payload": {
                "incident_id": incident["id"],
                "incident_type": incident["type"],
                "severity": incident["severity"],
                "location": incident.get("location", ""),
                "protocol": incident.get("protocol", ""),
            },
        })


async def _on_incident_status_changed(
    incident: dict, new_status: str, sim_time: datetime, note: str
):
    """Called when lifecycle changes incident status."""
    emit_incident_status_changed(incident, new_status, sim_time, note)
    emit_incident_alert(incident, sim_time)

    alert = build_alert(incident, sim_time)
    _state.add_alert(alert)

    # Update Prometheus
    inc_type = incident.get("type", "unknown")
    severity = incident.get("severity", "unknown")
    if new_status == "resolved":
        m_active.labels(type=inc_type, severity=severity).dec()
        # Record TTR if available
        started = incident.get("started_at")
        if started:
            try:
                started_dt = datetime.fromisoformat(str(started))
                ttr_min = (sim_time - started_dt).total_seconds() / 60
                m_ttr.labels(type=inc_type).observe(ttr_min)
            except (ValueError, TypeError):
                pass

    if _state.ws_broadcast:
        await _state.ws_broadcast({
            "type": "IncidentStatusChanged",
            "sim_time": sim_time.isoformat(),
            "payload": {
                "incident_id": incident["id"],
                "new_status": new_status,
                "incident_type": incident.get("type", ""),
            },
        })


# ── Consumer setup ───────────────────────────────────────────


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": "inc-svc",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
        "session.timeout.ms": 10000,
    })


async def run_consumer() -> None:
    global _consumer, _consumer_running

    # Wire lifecycle callbacks
    set_lifecycle_callbacks(
        on_created=_on_incident_created,
        on_status_changed=_on_incident_status_changed,
    )

    _consumer = _make_consumer()
    _consumer.subscribe([
        "sim.clock",
        "incidents.inject",
        "weather.events",
        "baggage.events",
        "passengers.events",
    ])
    _consumer_running = True
    logger.info("Kafka consumer started — subscribed to 5 topics")

    loop = asyncio.get_event_loop()
    try:
        while _consumer_running:
            msgs = await loop.run_in_executor(None, lambda: _consumer.consume(200, timeout=1.0))
            if not msgs:
                continue

            latest_tick_envelope = None
            other_envelopes: list[dict] = []
            skipped_ticks = 0

            for msg in msgs:
                if msg is None or msg.error():
                    continue
                try:
                    envelope = json.loads(msg.value().decode("utf-8"))
                except Exception:
                    continue
                if envelope.get("event_type") == "SimClockTick":
                    if latest_tick_envelope is not None:
                        skipped_ticks += 1
                    latest_tick_envelope = envelope
                else:
                    other_envelopes.append(envelope)

            if skipped_ticks > 0:
                logger.debug("Skipped %d stale clock ticks", skipped_ticks)

            for envelope in other_envelopes:
                try:
                    await _dispatch(envelope)
                except Exception as e:
                    logger.error("Consumer processing error: %s", e, exc_info=True)

            if latest_tick_envelope is not None:
                try:
                    await _dispatch(latest_tick_envelope)
                except Exception as e:
                    logger.error("Consumer processing error: %s", e, exc_info=True)
    finally:
        if _consumer:
            _consumer.close()
        _consumer_running = False
        logger.info("Kafka consumer stopped")


def stop_consumer() -> None:
    global _consumer_running
    _consumer_running = False


# ── Dispatch ─────────────────────────────────────────────────


def _validate_envelope(envelope: dict) -> tuple[str | None, dict, datetime | None]:
    """Validate event envelope. Returns (event_type, payload, sim_time) or Nones on failure."""
    event_type = envelope.get("event_type")
    if not isinstance(event_type, str):
        m_envelope_invalid.labels(reason="missing_event_type").inc()
        logger.warning("Invalid envelope: missing or non-string event_type")
        return None, {}, None

    sim_time_str = envelope.get("sim_time")
    if not sim_time_str:
        m_envelope_invalid.labels(reason="missing_sim_time").inc()
        logger.warning("Invalid envelope: missing sim_time (event_type=%s)", event_type)
        return None, {}, None

    try:
        sim_time = datetime.fromisoformat(str(sim_time_str)).replace(tzinfo=None)
    except (ValueError, TypeError):
        m_envelope_invalid.labels(reason="invalid_sim_time").inc()
        logger.warning("Invalid envelope: unparseable sim_time=%r", sim_time_str)
        return None, {}, None

    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        m_envelope_invalid.labels(reason="invalid_payload").inc()
        logger.warning("Invalid envelope: payload is not a dict (event_type=%s)", event_type)
        return None, {}, None

    return event_type, payload, sim_time


async def _dispatch(envelope: dict) -> None:
    event_id = envelope.get("event_id", "")

    # Idempotency
    if _state.check_idempotency(event_id):
        return

    event_type, payload, sim_time = _validate_envelope(envelope)
    if event_type is None:
        return

    match event_type:
        case "SimClockTick":
            await _on_clock_tick(payload, sim_time)
        case "InjectIncident":
            await _on_inject(payload, sim_time)
        case "WeatherStateChanged":
            await _on_weather_changed(payload, sim_time)
        case "BaggageFlagged":
            await _on_baggage_flagged(payload, sim_time)
        case "SecurityCongestionDetected":
            await _on_security_congestion(payload, sim_time)
        case _:
            pass


# ── Event handlers ───────────────────────────────────────────


async def _on_clock_tick(payload: dict, sim_time: datetime) -> None:
    _state.sim_time = sim_time

    # Compute delta for multi-minute ticks / tick skipping
    if _state.last_tick_sim_time is not None:
        delta_minutes = max(1, round((sim_time - _state.last_tick_sim_time).total_seconds() / 60))
    else:
        delta_minutes = payload.get("step_minutes", 1)
    _state.last_tick_sim_time = sim_time

    # 1. TTR countdown
    await tick_ttr(sim_time, delta_minutes)

    # 1b. Fire any pending delayed cascades
    await fire_pending_cascades(sim_time)

    # 2. Probabilistic event evaluation — detect ALL intermediate hour
    #    boundaries within a multi-minute step (handles step_minutes > 60).
    step = payload.get("step_minutes", 1)
    if step > 1 and _state.last_prob_hour is not None:
        # Walk intermediate hours that may have been crossed
        for offset in range(step):
            candidate = sim_time - timedelta(minutes=step - 1 - offset)
            if candidate.minute == 0 and candidate.hour != _state.last_prob_hour:
                _state.last_prob_hour = candidate.hour
                await _evaluate_probabilistic_events(candidate)
    else:
        hour = sim_time.hour
        if hour != _state.last_prob_hour:
            _state.last_prob_hour = hour
            await _evaluate_probabilistic_events(sim_time)

    # 3. Update alert ages
    for alert in _state.active_alerts:
        try:
            alert_time = datetime.fromisoformat(alert["at"])
            delta = sim_time - alert_time
            alert["age_minutes"] = int(delta.total_seconds() / 60)
        except (ValueError, TypeError, KeyError):
            pass


async def _on_inject(payload: dict, sim_time: datetime) -> None:
    """Handle manual incident injection."""
    inc_type = payload.get("type", "system_failure")
    severity = payload.get("severity", "medium")
    location = payload.get("location", "unknown")
    description = payload.get("description", "")
    subtype = payload.get("subtype", "")

    await create_incident(
        type=inc_type,
        severity=severity,
        location=location,
        trigger="manual",
        sim_time=sim_time,
        description=description,
        subtype=subtype,
    )


async def _on_weather_changed(payload: dict, sim_time: datetime) -> None:
    """Auto-create severe_weather incident on IMC/LIFR."""
    new_category = payload.get("new_category", "CAVOK")
    previous_category = payload.get("previous_category", "CAVOK")
    _state.current_weather_category = new_category

    if new_category in ("IMC", "LIFR"):
        # Check if there's already an active severe_weather incident
        existing = await find_active_incident_by_type_and_location(
            "severe_weather", "KART-airfield"
        )
        if existing:
            return

        severity = "critical" if new_category == "LIFR" else "medium"
        await create_incident(
            type="severe_weather",
            severity=severity,
            location="KART-airfield",
            trigger="auto",
            sim_time=sim_time,
            description=f"Weather degraded to {new_category}.",
        )
    elif new_category in ("VMC", "CAVOK") and previous_category in ("IMC", "LIFR"):
        # Auto-resolve severe_weather incident
        existing = await find_active_incident_by_type_and_location(
            "severe_weather", "KART-airfield"
        )
        if existing:
            await resolve_incident(
                existing["id"], sim_time,
                note=f"Weather improved to {new_category}."
            )


async def _on_baggage_flagged(payload: dict, sim_time: datetime) -> None:
    """DG class 3 flagged baggage → probabilistic baggage_fire trigger."""
    dg_class = payload.get("dg_class")
    if dg_class != 3:
        return

    # 30% chance of triggering a baggage fire for DG class 3
    if random.random() < 0.30:
        location = payload.get("zone_id", "baggage-handling")
        await create_incident(
            type="baggage_fire",
            severity="high",
            location=location,
            trigger="auto",
            sim_time=sim_time,
            description="Dangerous goods class 3 item detected — fire risk.",
        )


async def _on_security_congestion(payload: dict, sim_time: datetime) -> None:
    """SecurityCongestionDetected → create security_congestion system_failure."""
    terminal = payload.get("terminal", "terminal-A")
    wait_minutes = payload.get("wait_minutes", 20)
    location = f"terminal-{terminal}" if not terminal.startswith("terminal-") else terminal

    # Check for existing congestion incident at this terminal
    existing = await find_active_incident_by_type_and_location(
        "security_congestion", location
    )
    if existing:
        return

    severity = "high" if wait_minutes > 30 else "medium"
    await create_incident(
        type="security_congestion",
        severity=severity,
        location=location,
        trigger="auto",
        sim_time=sim_time,
        description=f"Security queue wait time {wait_minutes} min exceeds threshold.",
        subtype="security_congestion",
    )


# ── Probabilistic event evaluation ──────────────────────────


def _effective_probability(event_type: str, sim_time: datetime) -> float:
    """Calculate effective probability including modifiers."""
    prob = BASE_PROBABILITIES.get(event_type, 0)

    # Peak hour multiplier
    if sim_time.hour in PEAK_HOURS:
        prob *= 1.8

    # Weather multiplier for runway incursions
    if _state.current_weather_category in ("IMC", "LIFR"):
        if event_type == "runway_incursion":
            prob *= 2.0

    # Suppression window — reduce probability if same type fired recently
    last_time = _state.last_incident_times.get(event_type)
    if last_time:
        hours_since = (sim_time - last_time).total_seconds() / 3600
        if hours_since < SUPPRESSION_WINDOW_HRS:
            prob *= 0.3

    return prob


async def _evaluate_probabilistic_events(sim_time: datetime) -> None:
    """Evaluate probabilistic incident generation (once per sim hour)."""
    for event_type, _base_prob in BASE_PROBABILITIES.items():
        prob = _effective_probability(event_type, sim_time)

        if random.random() < prob:
            # Select a random location appropriate for the type
            location = _pick_location(event_type)
            severity = _pick_severity(event_type)
            subtype = ""

            if event_type == "system_failure":
                subtype = random.choice(SYSTEM_SUBTYPES)

            # Check for existing active incident at same location
            existing = await find_active_incident_by_type_and_location(
                event_type, location
            )
            if existing:
                continue

            await create_incident(
                type=event_type,
                severity=severity,
                location=location,
                trigger="probabilistic",
                sim_time=sim_time,
                subtype=subtype,
            )

            _state.last_incident_times[event_type] = sim_time
            logger.info(
                "Probabilistic incident fired: %s severity=%s at %s",
                event_type, severity, location,
            )


def _pick_location(event_type: str) -> str:
    """Pick a random location appropriate for the incident type."""
    if event_type == "runway_incursion":
        return random.choice(RUNWAY_IDS)
    elif event_type == "security_breach":
        return random.choice(TERMINAL_IDS)
    elif event_type == "baggage_fire":
        return random.choice(["baggage-handling-A", "baggage-handling-B", "baggage-sorting"])
    elif event_type == "system_failure":
        return random.choice([
            "conveyor-sorting", "conveyor-induction-A",
            "terminal-A-power", "terminal-B-power",
            "fids-system", "check-in-system",
        ])
    return "KART-general"


def _pick_severity(event_type: str) -> str:
    """Pick severity based on weighted random for the incident type."""
    if event_type == "runway_incursion":
        return random.choice(["high", "high", "critical"])
    elif event_type == "security_breach":
        return random.choices(
            ["medium", "high", "critical"], weights=[0.5, 0.35, 0.15]
        )[0]
    elif event_type == "baggage_fire":
        return random.choice(["medium", "high"])
    elif event_type == "system_failure":
        return random.choices(
            ["low", "medium", "high"], weights=[0.3, 0.5, 0.2]
        )[0]
    return "medium"

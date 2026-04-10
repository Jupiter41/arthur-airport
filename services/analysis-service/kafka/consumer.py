"""Kafka consumer for analysis-service.

Consumes events from all domain topics to build an in-memory operational state:
  - sim.clock          → SimClockTick (time progression + bottleneck evaluation)
  - flights.events     → FlightStatusChanged, FlightGateAssigned, FlightCancelled
  - passengers.events  → PassengerStatusChanged, SecurityCongestionDetected
  - baggage.events     → BaggageStatusChanged
  - weather.events     → WeatherStateChanged
  - incidents.events   → IncidentCreated, IncidentStatusChanged
  - ground.events      → GroundVehicleDispatched, GroundVehicleReturned
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Awaitable, Callable

from confluent_kafka import Consumer

from models.domain import Bottleneck
from services.state import OperationalState
from services.detectors import check_resolved, detect_all
from services.recommender import generate_recommendations
from services.autonomous import evaluate_and_apply, evaluate_rl_agent, should_evaluate, get_settings as get_autonomous_settings
from services.anomaly import detector as anomaly_detector
from services.nlp.narration import narration as narration_engine
from kafka.producer import (
    emit_bottleneck_detected,
    emit_bottleneck_resolved,
    emit_recommendation_generated,
    emit_autonomous_action,
    emit_anomaly_detected,
    emit_narration_generated,
)
from db.neo4j import query_connection_clusters
from metrics import (
    bottlenecks_active,
    bottlenecks_detected_total,
    recommendations_generated_total,
    autonomous_actions_total,
    consumer_lag,
    envelope_invalid_total,
    anomaly_score,
    anomaly_status,
    anomaly_feature_zscore,
)

logger = logging.getLogger(__name__)

# ── Module state ─────────────────────────────────────────────

_consumer: Consumer | None = None
_running = False
_ws_broadcast: Callable[[dict], Awaitable[None]] | None = None

# Shared operational state
state = OperationalState()

# Active bottlenecks
active_bottlenecks: dict[str, Bottleneck] = {}

# Active recommendations (refreshed each evaluation cycle)
active_recommendations: list = []

# Periodic Neo4j query interval (every N ticks)
NEO4J_QUERY_INTERVAL = 10  # every 10 sim-minutes
_neo4j_tick_counter = 0


def get_sim_time() -> datetime | None:
    return state.sim_time


def get_state() -> OperationalState:
    return state


def get_active_bottlenecks() -> dict[str, Bottleneck]:
    return active_bottlenecks


def get_active_recommendations() -> list:
    return active_recommendations


def set_ws_broadcast(fn: Callable[[dict], Awaitable[None]]) -> None:
    global _ws_broadcast
    _ws_broadcast = fn


def is_consumer_running() -> bool:
    return _running


def stop_consumer() -> None:
    global _running
    _running = False


# ── Consumer loop ────────────────────────────────────────────

TOPICS = [
    "sim.clock",
    "flights.events",
    "passengers.events",
    "baggage.events",
    "weather.events",
    "incidents.events",
    "ground.events",
]


async def run_consumer() -> None:
    """Main Kafka consumer loop — poll events and update operational state."""
    global _consumer, _running, _neo4j_tick_counter

    _consumer = Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": "analysis-svc",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
        "session.timeout.ms": 30000,
        "max.poll.interval.ms": 300000,
    })
    _consumer.subscribe(TOPICS)
    _running = True

    logger.info("Analysis consumer started, subscribed to: %s", TOPICS)

    loop = asyncio.get_event_loop()

    try:
        while _running:
            msg = await loop.run_in_executor(None, lambda: _consumer.poll(0.5))
            if msg is None:
                continue
            if msg.error():
                logger.warning("Consumer error: %s", msg.error())
                continue

            try:
                envelope = json.loads(msg.value().decode("utf-8"))
            except Exception:
                envelope_invalid_total.inc()
                continue

            event_type = envelope.get("event_type", "")
            payload = envelope.get("payload", {})
            topic = msg.topic()

            consumer_lag.labels(topic=topic).inc()

            # Route to state handler
            _dispatch_event(event_type, payload, topic, envelope)

            # On clock ticks, run analysis
            if event_type == "SimClockTick":
                await _on_tick(payload)

    except Exception:
        logger.exception("Consumer fatal error")
    finally:
        _running = False
        if _consumer:
            _consumer.close()
            logger.info("Analysis consumer closed")


def _dispatch_event(
    event_type: str, payload: dict, topic: str, envelope: dict,
) -> None:
    """Route events to the appropriate state handler."""
    handlers = {
        "SimClockTick": state.on_clock_tick,
        "FlightStatusChanged": state.on_flight_status_changed,
        "FlightGateAssigned": state.on_flight_gate_assigned,
        "FlightCancelled": state.on_flight_cancelled,
        "PassengerStatusChanged": state.on_passenger_status_changed,
        "SecurityCongestionDetected": state.on_security_congestion_detected,
        "BaggageStatusChanged": state.on_baggage_status_changed,
        "WeatherStateChanged": state.on_weather_state_changed,
        "IncidentCreated": state.on_incident_created,
        "IncidentStatusChanged": state.on_incident_status_changed,
        "GroundVehicleDispatched": state.on_ground_vehicle_dispatched,
        "GroundVehicleReturned": state.on_ground_vehicle_returned,
    }

    handler = handlers.get(event_type)
    if handler:
        try:
            handler(payload)
        except Exception:
            logger.exception("Error handling event %s", event_type)

    # Record event for anomaly root cause analysis (P5-3-3)
    if event_type != "SimClockTick" and state.sim_time:
        summary = _event_summary(event_type, payload)
        anomaly_detector.record_event(event_type, state.sim_time, summary)

        # Record for narration (P5-2-3)
        significance = _event_significance(event_type, payload)
        if significance > 0:
            narration_engine.record_event(
                event_type, state.sim_time, summary, significance,
            )


def _event_summary(event_type: str, payload: dict) -> str:
    """Build a short summary string for a Kafka event (anomaly root cause)."""
    if event_type == "FlightStatusChanged":
        return (
            f"Flight {payload.get('flight_id', '?')[:8]} → "
            f"{payload.get('new_status', '?')} "
            f"(delay={payload.get('delay_minutes', 0)}min)"
        )
    if event_type == "IncidentCreated":
        return (
            f"Incident {payload.get('type', '?')} "
            f"severity={payload.get('severity', '?')} "
            f"at {payload.get('location', '?')}"
        )
    if event_type == "WeatherStateChanged":
        return f"Weather → {payload.get('category', '?')}"
    if event_type == "SecurityCongestionDetected":
        return (
            f"Security congestion {payload.get('terminal', '?')} "
            f"queue={payload.get('queue_depth', 0)}"
        )
    return event_type


def _event_significance(event_type: str, payload: dict) -> int:
    """Determine significance level for narration (0=skip, 1=routine, 2=notable, 3=critical)."""
    if event_type == "IncidentCreated":
        severity = payload.get("severity", "")
        if severity in ("critical", "high"):
            return 3
        return 2
    if event_type == "FlightStatusChanged":
        new_status = payload.get("new_status", "")
        delay = payload.get("delay_minutes", 0)
        if new_status == "cancelled":
            return 3
        if delay > 30:
            return 2
        if delay > 10:
            return 1
        return 0
    if event_type == "WeatherStateChanged":
        category = payload.get("category", "")
        if category in ("LIFR", "IMC"):
            return 2
        return 1
    if event_type == "SecurityCongestionDetected":
        return 2
    if event_type in ("FlightCTOTAssigned", "MinimumFuelWarning"):
        return 2
    return 0


async def _on_tick(payload: dict) -> None:
    """Run bottleneck detection and recommendation generation on each tick."""
    global _neo4j_tick_counter, active_recommendations

    now = state.sim_time
    if now is None:
        return

    _neo4j_tick_counter += 1

    # Periodically refresh Neo4j data (connection clusters, etc.)
    if _neo4j_tick_counter >= NEO4J_QUERY_INTERVAL:
        _neo4j_tick_counter = 0
        try:
            clusters = await query_connection_clusters()
            state.connection_clusters = clusters
        except Exception:
            logger.debug("Failed to query connection clusters", exc_info=True)

    # Check for resolved bottlenecks
    resolved_ids = []
    for bn_id, bn in active_bottlenecks.items():
        if check_resolved(state, bn):
            bn.resolved_at = now
            resolved_ids.append(bn_id)
            emit_bottleneck_resolved(bn_id, now)
            logger.info("Bottleneck resolved: %s (%s)", bn_id, bn.type)
            # Update metrics
            bottlenecks_active.labels(
                type=bn.type.value, severity=bn.severity.value,
            ).dec()

    for bn_id in resolved_ids:
        del active_bottlenecks[bn_id]

    # Detect new bottlenecks
    new_bottlenecks = detect_all(state, active_bottlenecks)
    for bn in new_bottlenecks:
        active_bottlenecks[bn.id] = bn
        emit_bottleneck_detected(bn.model_dump(mode="json"), now)
        logger.info(
            "Bottleneck detected: %s %s in %s",
            bn.severity.value, bn.type.value, bn.zone,
        )
        bottlenecks_detected_total.labels(type=bn.type.value).inc()
        bottlenecks_active.labels(
            type=bn.type.value, severity=bn.severity.value,
        ).inc()

    # Generate recommendations for all active bottlenecks
    active_list = [bn for bn in active_bottlenecks.values() if bn.resolved_at is None]
    if active_list:
        recs = generate_recommendations(state, active_list)
        active_recommendations = recs
        for rec in recs:
            emit_recommendation_generated(rec.model_dump(mode="json"), now)
            recommendations_generated_total.labels(
                action_type=rec.action_type.value,
            ).inc()
    else:
        active_recommendations = []

    # Autonomous mode evaluation
    if should_evaluate(now):
        auto_settings = get_autonomous_settings()
        actions = []

        if auto_settings.mode.value == "rl_agent":
            # P5-1-5: Use RL agent
            actions = evaluate_rl_agent(state, now)
        elif active_recommendations:
            # Rule-based / threshold mode
            actions = evaluate_and_apply(active_recommendations, now)

        for action in actions:
            emit_autonomous_action(action, now)
            autonomous_actions_total.labels(
                action_type=action.get("action_type", ""),
            ).inc()

    # P5-3-1: Anomaly detection
    anomaly_result = anomaly_detector.on_tick(
        state, active_bottleneck_count=len(active_bottlenecks),
    )
    if anomaly_result:
        # P5-3-2: Update Prometheus metrics
        anomaly_score.set(anomaly_result.score)
        status_val = {"normal": 0, "amber": 1, "red": 2}.get(
            anomaly_result.status, 0,
        )
        anomaly_status.set(status_val)
        for feat, z in anomaly_result.z_scores.items():
            anomaly_feature_zscore.labels(feature=feat).set(z)

        # Emit anomaly event for non-normal status
        if anomaly_result.status != "normal":
            emit_anomaly_detected(
                {
                    "score": anomaly_result.score,
                    "normalized_score": anomaly_result.normalized_score,
                    "status": anomaly_result.status,
                    "root_cause": anomaly_result.root_cause,
                    "root_cause_feature": anomaly_result.root_cause_feature,
                    "z_scores": anomaly_result.z_scores,
                },
                now,
            )

    # P5-2-3: Narration generation
    narration_entry = await narration_engine.on_tick(state)
    if narration_entry:
        emit_narration_generated(narration_entry, now)

    # Broadcast to WebSocket clients
    if _ws_broadcast and (new_bottlenecks or resolved_ids or active_recommendations):
        try:
            await _ws_broadcast({
                "type": "analysis_update",
                "sim_time": now.isoformat(),
                "bottlenecks": [
                    bn.model_dump(mode="json")
                    for bn in active_bottlenecks.values()
                    if bn.resolved_at is None
                ],
                "recommendations": [
                    r.model_dump(mode="json")
                    for r in active_recommendations
                ],
            })
        except Exception:
            logger.debug("WS broadcast failed", exc_info=True)

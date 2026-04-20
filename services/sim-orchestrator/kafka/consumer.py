"""Kafka consumer for sim-orchestrator — listens to flights.events for network delay propagation."""

import json
import logging
import os
import threading

from confluent_kafka import Consumer, KafkaError

from services.network import get_network_engine

logger = logging.getLogger(__name__)

_consumer: Consumer | None = None
_running = False


def init_kafka_consumer() -> None:
    """Initialize the Kafka consumer for flight events."""
    global _consumer
    _consumer = Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": "sim-orchestrator-network",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
        "session.timeout.ms": 30000,
    })
    _consumer.subscribe(["flights.events"])
    logger.info("Network Kafka consumer initialized — subscribed to flights.events")


def _poll_loop() -> None:
    """Background polling loop for flight events."""
    global _running
    while _running and _consumer is not None:
        msg = _consumer.poll(timeout=1.0)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                logger.error("Kafka consumer error: %s", msg.error())
            continue

        try:
            payload = json.loads(msg.value().decode("utf-8"))
            _handle_flight_event(payload)
        except Exception:
            logger.exception("Error processing flight event")


def _handle_flight_event(envelope: dict) -> None:
    """Process a FlightStatusChanged event for network delay propagation."""
    event_type = envelope.get("event_type", "")
    if event_type != "FlightStatusChanged":
        return

    # Extract inner payload from Kafka envelope
    payload = envelope.get("payload", {})

    direction = payload.get("direction", "")
    new_status = payload.get("new_status", "")
    delay_minutes = payload.get("delay_minutes", 0)
    flight_number = payload.get("flight_number", "")

    # Only propagate outbound (departure) delays when they are significant
    if direction != "departure":
        return
    if delay_minutes < 15:
        return
    if new_status not in ("delayed", "departed"):
        return

    # Source is always KART (home), target is the destination
    destination_iata = payload.get("destination_iata", "")
    if not destination_iata:
        return

    engine = get_network_engine()
    if not engine.enabled:
        return

    # Map IATA to ICAO for network airports
    for airport in engine.get_all_airports():
        if airport.iata == destination_iata:
            engine.propagate_delay(
                flight_number=flight_number,
                source_icao=engine.config.home,
                target_icao=airport.icao,
                delay_minutes=delay_minutes,
            )
            break


def start_consumer() -> None:
    """Start the consumer in a background thread."""
    global _running
    if _consumer is None:
        return
    _running = True
    thread = threading.Thread(target=_poll_loop, daemon=True, name="network-consumer")
    thread.start()
    logger.info("Network Kafka consumer thread started")


def stop_consumer() -> None:
    """Stop the consumer."""
    global _running
    _running = False
    if _consumer is not None:
        _consumer.close()
    logger.info("Network Kafka consumer stopped")

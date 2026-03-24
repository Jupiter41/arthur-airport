"""Kafka consumer for weather-service — consumes SimClockTick from sim.clock."""

import asyncio
import json
import logging
import os
import random
from datetime import datetime
from uuid import uuid4

from confluent_kafka import Consumer

from db.neo4j import persist_weather_state, get_current_weather
from kafka.producer import emit_weather_state_changed, emit_metar_issued
from services.fsm import evaluate_transition
from services.parameters import sample_params
from services.metar import build_metar
from services.capacity import compute_runway_capacity
from metrics import (
    weather_category as m_category,
    weather_transitions_total as m_transitions,
    visibility_m as m_visibility,
    wind_speed_kt as m_wind_speed,
    wind_gust_kt as m_wind_gust,
    runway_arrival_rate as m_arr_rate,
    runway_departure_rate as m_dep_rate,
    CATEGORY_VALUES,
)

logger = logging.getLogger(__name__)

_consumer: Consumer | None = None
_consumer_running = False

# In-memory state for weather engine
_current_category: str = "CAVOK"
_current_params = None
_current_metar: str = ""
_current_taf: str = ""
_sim_time: datetime | None = None
_last_metar_total_min: int = -1
_last_fsm_hour: int = -1
_rng = random.Random(42)

# WebSocket broadcast callback (set by main.py)
_ws_broadcast = None


def set_ws_broadcast(fn):
    global _ws_broadcast
    _ws_broadcast = fn


def get_current_state() -> dict:
    """Return current in-memory weather state for fast access."""
    return {
        "category": _current_category,
        "params": _current_params,
        "metar": _current_metar,
        "taf": _current_taf,
        "sim_time": _sim_time,
    }


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": "weather-svc",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
        "session.timeout.ms": 10000,
    })


async def _initialize_state() -> None:
    """Load current weather state from Neo4j on startup."""
    global _current_category, _current_params, _current_metar, _sim_time

    weather = await get_current_weather()
    if weather:
        _current_category = weather["category"]
        _sim_time = datetime.fromisoformat(weather["timestamp"])
        # Reconstruct params from stored state
        from services.parameters import WeatherParams
        _current_params = WeatherParams(
            category=weather["category"],
            visibility_m=weather["visibility_m"],
            wind_direction=weather["wind_direction"],
            wind_speed_kt=weather["wind_speed_kt"],
            wind_gust_kt=weather["wind_gust_kt"],
            ceiling_ft=weather["ceiling_ft"],
            temperature_c=weather["temperature_c"],
            dew_point_c=weather["dew_point_c"],
            qnh_hpa=weather["qnh_hpa"],
            phenomena=weather["phenomena"],
        )
        _current_metar = build_metar(_current_params, _sim_time)
        logger.info("Restored weather state from Neo4j: %s", _current_category)
    else:
        logger.info("No weather state in Neo4j — will initialize on first clock tick")


async def _on_clock_tick(payload: dict, sim_time: datetime) -> None:
    """Process a SimClockTick event.

    - Every simulated hour (minute==0): evaluate FSM transition
    - Every 30 simulated minutes (minute==0 or minute==30): emit METARIssued
    """
    global _current_category, _current_params, _current_metar, _current_taf
    global _sim_time, _last_metar_total_min, _last_fsm_hour

    _sim_time = sim_time
    hour = sim_time.hour
    minute = sim_time.minute

    # --- Initialize if first tick ---
    if _current_params is None:
        initial_category = os.getenv("INITIAL_WEATHER_CATEGORY", "CAVOK")
        _current_category = initial_category
        _current_params = sample_params(initial_category, _rng)
        _current_metar = build_metar(_current_params, sim_time)

        from services.metar import build_taf
        _current_taf = build_taf(_current_params, sim_time)

        weather_id = str(uuid4())
        capacity = compute_runway_capacity(_current_params)

        await persist_weather_state(
            weather_id=weather_id,
            category=initial_category,
            sim_time=sim_time,
            visibility_m=_current_params.visibility_m,
            wind_direction=_current_params.wind_direction,
            wind_speed_kt=_current_params.wind_speed_kt,
            wind_gust_kt=_current_params.wind_gust_kt,
            ceiling_ft=_current_params.ceiling_ft,
            temperature_c=_current_params.temperature_c,
            dew_point_c=_current_params.dew_point_c,
            qnh_hpa=_current_params.qnh_hpa,
            phenomena=_current_params.phenomena,
            runway_impact=capacity["runway_impact"],
        )

        params_dict = {
            "visibility_m": _current_params.visibility_m,
            "wind_direction": _current_params.wind_direction,
            "wind_speed_kt": _current_params.wind_speed_kt,
            "wind_gust_kt": _current_params.wind_gust_kt,
            "ceiling_ft": _current_params.ceiling_ft,
            "temperature_c": _current_params.temperature_c,
            "phenomena": _current_params.phenomena,
        }
        emit_weather_state_changed(
            sim_time=sim_time,
            weather_id=weather_id,
            previous_category=None,
            new_category=initial_category,
            params=params_dict,
            capacity=capacity,
        )
        emit_metar_issued(sim_time, _current_metar)
        _last_fsm_hour = hour
        _last_metar_total_min = hour * 60 + minute

        # Update Prometheus gauges
        m_category.set(CATEGORY_VALUES.get(initial_category, 0))
        m_visibility.set(_current_params.visibility_m)
        m_wind_speed.set(_current_params.wind_speed_kt)
        m_wind_gust.set(_current_params.wind_gust_kt or 0)
        m_arr_rate.set(capacity.get("recommended_arrival_rate", 32))
        m_dep_rate.set(capacity.get("recommended_departure_rate", 32))

        logger.info("Weather initialized: %s", initial_category)
        return

    # --- Hourly FSM evaluation (minute == 0 and not same hour) ---
    if minute == 0 and hour != _last_fsm_hour:
        _last_fsm_hour = hour
        previous_category = _current_category
        new_category = evaluate_transition(_current_category, _rng)

        if new_category != previous_category:
            _current_category = new_category
            _current_params = sample_params(new_category, _rng)
            _current_metar = build_metar(_current_params, sim_time)

            from services.metar import build_taf
            _current_taf = build_taf(_current_params, sim_time)

            weather_id = str(uuid4())
            capacity = compute_runway_capacity(_current_params)

            await persist_weather_state(
                weather_id=weather_id,
                category=new_category,
                sim_time=sim_time,
                visibility_m=_current_params.visibility_m,
                wind_direction=_current_params.wind_direction,
                wind_speed_kt=_current_params.wind_speed_kt,
                wind_gust_kt=_current_params.wind_gust_kt,
                ceiling_ft=_current_params.ceiling_ft,
                temperature_c=_current_params.temperature_c,
                dew_point_c=_current_params.dew_point_c,
                qnh_hpa=_current_params.qnh_hpa,
                phenomena=_current_params.phenomena,
                runway_impact=capacity["runway_impact"],
            )

            params_dict = {
                "visibility_m": _current_params.visibility_m,
                "wind_direction": _current_params.wind_direction,
                "wind_speed_kt": _current_params.wind_speed_kt,
                "wind_gust_kt": _current_params.wind_gust_kt,
                "ceiling_ft": _current_params.ceiling_ft,
                "temperature_c": _current_params.temperature_c,
                "phenomena": _current_params.phenomena,
            }
            emit_weather_state_changed(
                sim_time=sim_time,
                weather_id=weather_id,
                previous_category=previous_category,
                new_category=new_category,
                params=params_dict,
                capacity=capacity,
            )

            logger.info("Weather transition: %s -> %s", previous_category, new_category)

            # Update Prometheus gauges
            m_category.set(CATEGORY_VALUES.get(new_category, 0))
            m_visibility.set(_current_params.visibility_m)
            m_wind_speed.set(_current_params.wind_speed_kt)
            m_wind_gust.set(_current_params.wind_gust_kt or 0)
            m_arr_rate.set(capacity.get("recommended_arrival_rate", 32))
            m_dep_rate.set(capacity.get("recommended_departure_rate", 32))
            m_transitions.labels(from_cat=previous_category, to_cat=new_category).inc()

            # Broadcast to WebSocket clients
            if _ws_broadcast:
                await _ws_broadcast({
                    "event_type": "WeatherStateChanged",
                    "previous_category": previous_category,
                    "new_category": new_category,
                    "sim_time": sim_time.isoformat(),
                })

    # --- METAR every 30 simulated minutes (0 and 30) ---
    metar_interval = int(os.getenv("METAR_INTERVAL_SIM_MINUTES", "30"))
    total_min = hour * 60 + minute
    if minute % metar_interval == 0 and total_min != _last_metar_total_min:
        _last_metar_total_min = total_min
        _current_metar = build_metar(_current_params, sim_time)

        from services.metar import build_taf
        _current_taf = build_taf(_current_params, sim_time)

        emit_metar_issued(sim_time, _current_metar)

        # Broadcast to WebSocket clients
        if _ws_broadcast:
            await _ws_broadcast({
                "event_type": "METARIssued",
                "raw": _current_metar,
                "sim_time": sim_time.isoformat(),
            })


async def _dispatch(envelope: dict) -> None:
    """Route incoming Kafka messages to the appropriate handler."""
    event_type = envelope.get("event_type")
    payload = envelope.get("payload", {})
    sim_time = datetime.fromisoformat(envelope["sim_time"])

    match event_type:
        case "SimClockTick":
            await _on_clock_tick(payload, sim_time)
        case _:
            pass  # ignore unknown events


async def run_consumer() -> None:
    """Main consumer loop — runs as a background asyncio task."""
    global _consumer, _consumer_running

    await _initialize_state()

    _consumer = _make_consumer()
    _consumer.subscribe(["sim.clock"])
    _consumer_running = True

    loop = asyncio.get_event_loop()
    logger.info("Kafka consumer started — listening on sim.clock")

    try:
        while _consumer_running:
            msg = await loop.run_in_executor(None, _consumer.poll, 1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error("Consumer error: %s", msg.error())
                continue
            try:
                envelope = json.loads(msg.value().decode("utf-8"))
                await _dispatch(envelope)
            except Exception as e:
                logger.error("Processing error: %s", e, exc_info=True)
    finally:
        _consumer.close()
        _consumer_running = False
        logger.info("Kafka consumer stopped")


def stop_consumer() -> None:
    global _consumer_running
    _consumer_running = False


def is_consumer_running() -> bool:
    return _consumer_running

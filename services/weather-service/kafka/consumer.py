"""Kafka consumer for weather-service — consumes SimClockTick from sim.clock.

Supports three weather source modes via WEATHER_SOURCE env var:
  - "simulated" (default): FSM-based random weather transitions
  - "historical": Replay from IEM Mesonet CSV file (WEATHER_HISTORY_FILE)
  - "live": Fetch real METAR from Aviation Weather Center API (WEATHER_LIVE_ICAO)
"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta
from typing import Callable, Awaitable
from uuid import uuid4

from confluent_kafka import Consumer

from _common.consumer_health import ConsumerHealthTracker
from db.neo4j import persist_weather_state, get_current_weather, get_airport_identity
from kafka.producer import emit_weather_state_changed, emit_metar_issued
from services.fsm import evaluate_transition
from services.parameters import sample_params, WeatherParams
from services.metar import build_metar, build_taf
from services.capacity import compute_runway_capacity
from services.historical import HistoricalMetarSource
from services.live_metar import LiveMetarSource
from metrics import (
    weather_category as m_category,
    weather_transitions_total as m_transitions,
    visibility_m as m_visibility,
    wind_speed_kt as m_wind_speed,
    wind_gust_kt as m_wind_gust,
    runway_arrival_rate as m_arr_rate,
    runway_departure_rate as m_dep_rate,
    CATEGORY_VALUES,
    envelope_invalid_total as m_envelope_invalid,
)

logger = logging.getLogger(__name__)


# ── Class-based state holder ────────────────────────────────


class WeatherConsumerState:
    """Holds all mutable runtime state for the weather consumer.

    Eliminates module-level globals that caused repeated UnboundLocalError
    bugs across sprints 1–3 and 6 due to Python's `global` scoping rules.
    """

    def __init__(self) -> None:
        self.current_category: str = "CAVOK"
        self.current_params: WeatherParams | None = None
        self.current_metar: str = ""
        self.current_taf: str = ""
        self.airport_icao: str = os.getenv("AIRPORT_ICAO", "KART")
        self.sim_time: datetime | None = None
        self.last_metar_total_min: int = -1
        self.last_fsm_hour: int = -1
        self.rng = random.Random(42)
        self.ws_broadcast: Callable[[dict], Awaitable[None]] | None = None

        # Weather source mode: "simulated", "historical", "live"
        self.weather_source = os.getenv("WEATHER_SOURCE", "simulated").lower()
        self._historical: HistoricalMetarSource | None = None
        self._live: LiveMetarSource | None = None
        self._last_historical_hour: int = -1

        if self.weather_source == "historical":
            csv_path = os.getenv("WEATHER_HISTORY_FILE", "/app/data/weather/EGLL_30days.csv")
            self._historical = HistoricalMetarSource(csv_path)
            count = self._historical.load()
            if count == 0:
                logger.warning("Historical METAR file empty/missing — falling back to simulated")
                self.weather_source = "simulated"
            else:
                logger.info("Weather source: historical (%d observations from %s)", count, csv_path)
        elif self.weather_source == "live":
            live_icao = os.getenv("WEATHER_LIVE_ICAO", "EGLL")
            self._live = LiveMetarSource(live_icao)
            logger.info("Weather source: live METAR from %s", live_icao)
        else:
            logger.info("Weather source: simulated (FSM)")

    def get_current_state(self) -> dict:
        """Return current in-memory weather state for fast access."""
        return {
            "category": self.current_category,
            "params": self.current_params,
            "metar": self.current_metar,
            "taf": self.current_taf,
            "sim_time": self.sim_time,
            "airport_icao": self.airport_icao,
        }

    async def initialize_from_neo4j(self) -> None:
        """Load current weather state from Neo4j on startup."""
        weather = await get_current_weather()
        if weather:
            self.airport_icao = weather.get("airport_icao") or self.airport_icao
            self.current_category = weather["category"]
            self.sim_time = datetime.fromisoformat(weather["timestamp"])
            self.current_params = WeatherParams(
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
            self.current_metar = build_metar(self.current_params, self.sim_time, self.airport_icao)
            self.current_taf = build_taf(self.current_params, self.sim_time, station_icao=self.airport_icao)
            self._update_gauges(self.current_category, self.current_params)
            logger.info("Restored weather state from Neo4j: %s", self.current_category)
        else:
            airport = await get_airport_identity()
            if airport and airport.get("icao"):
                self.airport_icao = str(airport["icao"])
            logger.info("No weather state in Neo4j — will initialize on first clock tick")

    def _params_dict(self, params: WeatherParams) -> dict:
        return {
            "visibility_m": params.visibility_m,
            "wind_direction": params.wind_direction,
            "wind_speed_kt": params.wind_speed_kt,
            "wind_gust_kt": params.wind_gust_kt,
            "ceiling_ft": params.ceiling_ft,
            "temperature_c": params.temperature_c,
            "phenomena": params.phenomena,
        }

    def _apply_overrides(self, params: WeatherParams) -> WeatherParams:
        """Apply locked parameter overrides on top of generated params."""
        overrides = getattr(self, "_overrides", {})
        if not overrides:
            return params
        return WeatherParams(
            category=params.category,
            visibility_m=overrides.get("visibility_m", params.visibility_m),
            wind_direction=params.wind_direction,
            wind_speed_kt=overrides.get("wind_speed_kt", params.wind_speed_kt),
            wind_gust_kt=overrides.get("wind_gust_kt", params.wind_gust_kt),
            ceiling_ft=overrides.get("ceiling_ft", params.ceiling_ft),
            temperature_c=overrides.get("temperature_c", params.temperature_c),
            dew_point_c=params.dew_point_c,
            qnh_hpa=params.qnh_hpa,
            phenomena=params.phenomena,
        )

    def _update_gauges(self, category: str, params: WeatherParams, capacity: dict | None = None) -> None:
        m_category.set(CATEGORY_VALUES.get(category, 0))
        m_visibility.set(params.visibility_m)
        m_wind_speed.set(params.wind_speed_kt)
        m_wind_gust.set(params.wind_gust_kt or 0)
        if capacity:
            m_arr_rate.set(capacity.get("recommended_arrival_rate", capacity.get("arrival_rate", 32)))
            m_dep_rate.set(capacity.get("recommended_departure_rate", capacity.get("departure_rate", 32)))

    async def on_clock_tick(self, payload: dict, sim_time: datetime) -> None:
        """Process a SimClockTick event.

        When step_minutes > 1 (FAST/BULK mode), walks all intermediate minutes
        to detect hour boundaries (FSM eval) and METAR boundaries that would
        otherwise be missed because the tick only reports the final sim_time.

        Supports three weather modes:
          - simulated: FSM transitions at hour boundaries
          - historical: lookup from CSV data at hour boundaries
          - live: fetch real METAR at hour boundaries
        """
        self.sim_time = sim_time
        step_minutes = payload.get("step_minutes", 1)

        # --- Initialize if first tick ---
        if self.current_params is None:
            await self._initialize_first_tick(sim_time, sim_time.hour, sim_time.minute)
            return

        metar_interval = int(os.getenv("METAR_INTERVAL_SIM_MINUTES", "30"))

        # Walk all intermediate minutes covered by this tick
        for offset in range(step_minutes):
            candidate = sim_time - timedelta(minutes=step_minutes - 1 - offset)
            c_hour = candidate.hour
            c_minute = candidate.minute

            # --- Hourly weather evaluation ---
            if c_minute == 0 and c_hour != self.last_fsm_hour:
                self.last_fsm_hour = c_hour
                previous_category = self.current_category

                if self.weather_source == "historical":
                    await self._apply_historical_weather(candidate, previous_category)
                elif self.weather_source == "live":
                    await self._apply_live_weather(candidate, previous_category)
                else:
                    # Simulated FSM
                    new_category = evaluate_transition(self.current_category, self.rng)
                    if new_category != previous_category:
                        await self._apply_transition(previous_category, new_category, candidate)

            # --- METAR at configured interval ---
            total_min = c_hour * 60 + c_minute
            if c_minute % metar_interval == 0 and total_min != self.last_metar_total_min:
                self.last_metar_total_min = total_min
                self.current_metar = build_metar(self.current_params, candidate, self.airport_icao)
                self.current_taf = build_taf(self.current_params, candidate, station_icao=self.airport_icao)

                emit_metar_issued(candidate, self.current_metar)

                if self.ws_broadcast:
                    await self.ws_broadcast({
                        "event_type": "METARIssued",
                        "raw": self.current_metar,
                        "sim_time": candidate.isoformat(),
                    })

    async def _apply_historical_weather(
        self, sim_time: datetime, previous_category: str
    ) -> None:
        """Apply weather from historical METAR data."""
        if not self._historical or not self._historical.is_loaded:
            # Fall back to FSM
            new_category = evaluate_transition(self.current_category, self.rng)
            if new_category != previous_category:
                await self._apply_transition(previous_category, new_category, sim_time)
            return

        result = self._historical.get_params_at(sim_time)
        if result is None:
            # Fall back to FSM
            new_category = evaluate_transition(self.current_category, self.rng)
            if new_category != previous_category:
                await self._apply_transition(previous_category, new_category, sim_time)
            return

        params, raw_metar = result
        new_category = params.category

        # Only emit transition event if category actually changed
        if new_category != previous_category:
            await self._apply_transition_with_params(
                previous_category, new_category, sim_time, params
            )
        else:
            # Category unchanged but params may differ — update in-memory state
            self.current_params = params
            self.current_metar = build_metar(params, sim_time, self.airport_icao)
            self.current_taf = build_taf(params, sim_time, station_icao=self.airport_icao)
            capacity = compute_runway_capacity(params)
            self._update_gauges(new_category, params, capacity)

    async def _apply_live_weather(
        self, sim_time: datetime, previous_category: str
    ) -> None:
        """Apply weather from live METAR fetch."""
        if not self._live:
            new_category = evaluate_transition(self.current_category, self.rng)
            if new_category != previous_category:
                await self._apply_transition(previous_category, new_category, sim_time)
            return

        # Fetch is synchronous (cached, quick) — run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._live.fetch)

        if result is None:
            new_category = evaluate_transition(self.current_category, self.rng)
            if new_category != previous_category:
                await self._apply_transition(previous_category, new_category, sim_time)
            return

        params, raw_metar = result
        new_category = params.category

        if new_category != previous_category:
            await self._apply_transition_with_params(
                previous_category, new_category, sim_time, params
            )
        else:
            self.current_params = params
            self.current_metar = build_metar(params, sim_time, self.airport_icao)
            self.current_taf = build_taf(params, sim_time, station_icao=self.airport_icao)
            capacity = compute_runway_capacity(params)
            self._update_gauges(new_category, params, capacity)

    async def _apply_transition_with_params(
        self,
        previous_category: str,
        new_category: str,
        sim_time: datetime,
        params: WeatherParams,
    ) -> None:
        """Apply a weather transition using externally-provided parameters (historical/live)."""
        self.current_category = new_category
        self.current_params = params
        self.current_metar = build_metar(params, sim_time, self.airport_icao)
        self.current_taf = build_taf(params, sim_time, station_icao=self.airport_icao)

        weather_id = str(uuid4())
        capacity = compute_runway_capacity(params)

        await persist_weather_state(
            weather_id=weather_id,
            category=new_category,
            sim_time=sim_time,
            visibility_m=params.visibility_m,
            wind_direction=params.wind_direction,
            wind_speed_kt=params.wind_speed_kt,
            wind_gust_kt=params.wind_gust_kt,
            ceiling_ft=params.ceiling_ft,
            temperature_c=params.temperature_c,
            dew_point_c=params.dew_point_c,
            qnh_hpa=params.qnh_hpa,
            phenomena=params.phenomena,
            runway_impact=capacity["runway_impact"],
            previous_category=previous_category,
        )

        emit_weather_state_changed(
            sim_time=sim_time,
            weather_id=weather_id,
            previous_category=previous_category,
            new_category=new_category,
            params=self._params_dict(params),
            capacity=capacity,
        )

        logger.info(
            "Weather transition (%s): %s -> %s",
            self.weather_source, previous_category, new_category,
        )

        self._update_gauges(new_category, params, capacity)
        m_transitions.labels(from_cat=previous_category, to_cat=new_category).inc()

        if self.ws_broadcast:
            await self.ws_broadcast({
                "event_type": "WeatherStateChanged",
                "previous_category": previous_category,
                "new_category": new_category,
                "sim_time": sim_time.isoformat(),
                "source": self.weather_source,
            })

    async def _initialize_first_tick(self, sim_time: datetime, hour: int, minute: int) -> None:
        initial_category = os.getenv("INITIAL_WEATHER_CATEGORY", "CAVOK")

        # Try to initialize from real-world data if configured
        if self.weather_source == "historical" and self._historical and self._historical.is_loaded:
            result = self._historical.get_params_at(sim_time)
            if result:
                params, _ = result
                initial_category = params.category
                self.current_category = initial_category
                self.current_params = params
                logger.info("Weather initialized from historical data: %s", initial_category)
            else:
                self.current_category = initial_category
                self.current_params = sample_params(initial_category, self.rng)
        elif self.weather_source == "live" and self._live:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._live.fetch)
            if result:
                params, _ = result
                initial_category = params.category
                self.current_category = initial_category
                self.current_params = params
                logger.info("Weather initialized from live METAR: %s", initial_category)
            else:
                self.current_category = initial_category
                self.current_params = sample_params(initial_category, self.rng)
        else:
            self.current_category = initial_category
            self.current_params = sample_params(initial_category, self.rng)

        self.current_metar = build_metar(self.current_params, sim_time, self.airport_icao)
        self.current_taf = build_taf(self.current_params, sim_time, station_icao=self.airport_icao)

        weather_id = str(uuid4())
        capacity = compute_runway_capacity(self.current_params)

        await persist_weather_state(
            weather_id=weather_id,
            category=initial_category,
            sim_time=sim_time,
            visibility_m=self.current_params.visibility_m,
            wind_direction=self.current_params.wind_direction,
            wind_speed_kt=self.current_params.wind_speed_kt,
            wind_gust_kt=self.current_params.wind_gust_kt,
            ceiling_ft=self.current_params.ceiling_ft,
            temperature_c=self.current_params.temperature_c,
            dew_point_c=self.current_params.dew_point_c,
            qnh_hpa=self.current_params.qnh_hpa,
            phenomena=self.current_params.phenomena,
            runway_impact=capacity["runway_impact"],
            previous_category=None,
        )

        emit_weather_state_changed(
            sim_time=sim_time,
            weather_id=weather_id,
            previous_category=None,
            new_category=initial_category,
            params=self._params_dict(self.current_params),
            capacity=capacity,
        )
        emit_metar_issued(sim_time, self.current_metar)
        self.last_fsm_hour = hour
        self.last_metar_total_min = hour * 60 + minute

        self._update_gauges(initial_category, self.current_params, capacity)
        logger.info("Weather initialized: %s", initial_category)

    async def _apply_transition(
        self, previous_category: str, new_category: str, sim_time: datetime
    ) -> None:
        self.current_category = new_category
        self.current_params = sample_params(new_category, self.rng)
        self.current_metar = build_metar(self.current_params, sim_time, self.airport_icao)
        self.current_taf = build_taf(self.current_params, sim_time, station_icao=self.airport_icao)

        weather_id = str(uuid4())
        capacity = compute_runway_capacity(self.current_params)

        await persist_weather_state(
            weather_id=weather_id,
            category=new_category,
            sim_time=sim_time,
            visibility_m=self.current_params.visibility_m,
            wind_direction=self.current_params.wind_direction,
            wind_speed_kt=self.current_params.wind_speed_kt,
            wind_gust_kt=self.current_params.wind_gust_kt,
            ceiling_ft=self.current_params.ceiling_ft,
            temperature_c=self.current_params.temperature_c,
            dew_point_c=self.current_params.dew_point_c,
            qnh_hpa=self.current_params.qnh_hpa,
            phenomena=self.current_params.phenomena,
            runway_impact=capacity["runway_impact"],
            previous_category=previous_category,
        )

        emit_weather_state_changed(
            sim_time=sim_time,
            weather_id=weather_id,
            previous_category=previous_category,
            new_category=new_category,
            params=self._params_dict(self.current_params),
            capacity=capacity,
        )

        logger.info("Weather transition: %s -> %s", previous_category, new_category)

        self._update_gauges(new_category, self.current_params, capacity)
        m_transitions.labels(from_cat=previous_category, to_cat=new_category).inc()

        if self.ws_broadcast:
            await self.ws_broadcast({
                "event_type": "WeatherStateChanged",
                "previous_category": previous_category,
                "new_category": new_category,
                "sim_time": sim_time.isoformat(),
            })


# Module-level singleton — used by router and main.py
_state = WeatherConsumerState()
_consumer: Consumer | None = None
_consumer_running = False
_consumer_health = ConsumerHealthTracker()


def set_ws_broadcast(fn):
    _state.ws_broadcast = fn


def get_current_state() -> dict:
    return _state.get_current_state()


def get_weather_source() -> str:
    """Return the current runtime weather source (simulated/historical/live)."""
    return _state.weather_source


def get_sim_time() -> datetime | None:
    return _state.sim_time


def switch_weather_source(
    source: str,
    csv_path: str | None = None,
    live_icao: str | None = None,
) -> dict:
    """Switch weather source at runtime. Returns the new source configuration.

    Args:
        source: "simulated", "historical", or "live"
        csv_path: Path to CSV file (required for historical mode)
        live_icao: ICAO station code (required for live mode)
    """
    source = source.lower()
    if source not in ("simulated", "historical", "live"):
        raise ValueError(f"Invalid weather source: {source}")

    if source == "historical":
        path = csv_path or os.getenv("WEATHER_HISTORY_FILE", "/app/data/weather/EGLL_30days.csv")
        _state._historical = HistoricalMetarSource(path)
        count = _state._historical.load()
        if count == 0:
            raise ValueError(f"Historical METAR file empty/missing: {path}")
        _state.weather_source = "historical"
        logger.info("Weather source switched to historical (%d observations from %s)", count, path)
        return {"source": "historical", "file": path, "observations": count}
    elif source == "live":
        icao = live_icao or os.getenv("WEATHER_LIVE_ICAO", "EGLL")
        _state._live = LiveMetarSource(icao)
        _state.weather_source = "live"
        logger.info("Weather source switched to live METAR from %s", icao)
        return {"source": "live", "icao": icao}
    else:
        _state.weather_source = "simulated"
        _state._historical = None
        _state._live = None
        logger.info("Weather source switched to simulated (FSM)")
        return {"source": "simulated"}


def set_weather_overrides(overrides: dict) -> dict:
    """Set individual weather parameter overrides.

    Any non-null value locks that parameter regardless of the active source.
    Set a value to None to unlock it.
    """
    if not hasattr(_state, "_overrides"):
        _state._overrides = {}

    for key in ("visibility_m", "wind_speed_kt", "wind_gust_kt", "ceiling_ft", "temperature_c"):
        if key in overrides:
            val = overrides[key]
            if val is None:
                _state._overrides.pop(key, None)
            else:
                _state._overrides[key] = val

    logger.info("Weather overrides updated: %s", _state._overrides)
    return dict(_state._overrides)


def get_weather_overrides() -> dict:
    """Return current weather parameter overrides."""
    return dict(getattr(_state, "_overrides", {}))


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": "weather-svc",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
        "session.timeout.ms": 10000,
    })


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
    """Route incoming Kafka messages to the appropriate handler."""
    event_type, payload, sim_time = _validate_envelope(envelope)
    if event_type is None:
        return

    match event_type:
        case "SimClockTick":
            await _state.on_clock_tick(payload, sim_time)
        case _:
            pass  # ignore unknown events


async def run_consumer() -> None:
    """Main consumer loop — runs as a background asyncio task."""
    global _consumer, _consumer_running

    await _state.initialize_from_neo4j()

    _consumer = _make_consumer()
    _consumer.subscribe(["sim.clock"])
    _consumer_running = True

    loop = asyncio.get_event_loop()
    logger.info("Kafka consumer started — listening on sim.clock")

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
                    logger.error("Processing error: %s", e, exc_info=True)

            if latest_tick_envelope is not None:
                try:
                    await _dispatch(latest_tick_envelope)
                except Exception as e:
                    logger.error("Processing error: %s", e, exc_info=True)

            _consumer_health.mark_message()
    finally:
        _consumer.close()
        _consumer_running = False
        logger.info("Kafka consumer stopped")


def stop_consumer() -> None:
    global _consumer_running
    _consumer_running = False


def is_consumer_running() -> bool:
    return _consumer_running


def get_consumer_health() -> dict:
    """Return consumer health metrics for /health endpoint."""
    return _consumer_health.status()

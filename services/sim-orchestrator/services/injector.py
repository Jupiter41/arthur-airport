"""Probabilistic event injector — evaluates once per simulated hour."""

import logging
import os
import random
from datetime import datetime

from services.airport_config import load_airport_runtime_config
from services.fixtures import get_fixtures
from kafka.producer import emit_inject_incident
from metrics import sim_events_injected_total as m_events_injected

logger = logging.getLogger(__name__)

PEAK_HOURS = None  # loaded from fixture at runtime
_rng = random.Random()
_last_incident_time: datetime | None = None

# Active calibration preset id (``simulated`` or ``asrs_historical``).
# Initialised from the ``INCIDENT_SOURCE`` env var and runtime-switchable via
# ``set_incident_source``.
_active_source: str = os.getenv("INCIDENT_SOURCE", "simulated").lower()


def get_incident_source() -> str:
    """Return the currently active incident calibration preset id."""
    return _active_source


def list_incident_sources() -> dict:
    """Return metadata for all known calibration presets."""
    fixtures = get_fixtures()
    presets = (fixtures.get("incident_calibrations") or {}).get("presets") or {}
    return {
        "active": _active_source,
        "available": [
            {
                "id": pid,
                "label": preset.get("label", pid),
                "description": preset.get("description", ""),
                "source": preset.get("source"),
            }
            for pid, preset in presets.items()
        ],
    }


def set_incident_source(source: str) -> dict:
    """Switch the active calibration preset at runtime."""
    global _active_source
    fixtures = get_fixtures()
    presets = (fixtures.get("incident_calibrations") or {}).get("presets") or {}
    if source not in presets:
        raise ValueError(
            f"Unknown incident source '{source}'. Available: {sorted(presets)}"
        )
    previous = _active_source
    _active_source = source
    logger.info("Incident calibration source switched: %s -> %s", previous, source)
    return {"previous": previous, "active": source}


def _resolve_calibration(events_config: dict) -> dict:
    """Merge the active calibration preset on top of the base events config."""
    fixtures = get_fixtures()
    presets = (fixtures.get("incident_calibrations") or {}).get("presets") or {}
    preset = presets.get(_active_source)
    if not preset:
        return events_config

    merged = dict(events_config)
    for key in (
        "base_probabilities",
        "severity_ranges",
        "ttr_ranges_minutes",
        "locations",
    ):
        override = preset.get(key)
        if override:
            merged_value = dict(events_config.get(key, {}))
            merged_value.update(override)
            merged[key] = merged_value
    return merged


def set_seed(seed: int | None) -> None:
    if seed is not None:
        _rng.seed(seed)


def record_incident(sim_time: datetime) -> None:
    """Record that an incident happened at this time (for suppression window)."""
    global _last_incident_time
    _last_incident_time = sim_time


def _recent_incident(sim_time: datetime, window_hours: int = 2) -> bool:
    """Check if an incident happened within the suppression window."""
    if _last_incident_time is None:
        return False
    from datetime import timedelta
    return (sim_time - _last_incident_time) < timedelta(hours=window_hours)


async def evaluate_probabilistic_events(sim_time: datetime) -> None:
    """Roll the dice for each incident type at this hour boundary.

    Base probabilities are loaded from fixtures, optionally overridden by the
    active calibration preset (``simulated`` or ``asrs_historical``), then
    modified by:

    - Peak-hour multiplier (×1.8 during 07–09h and 17–19h)
    - Recent-incident suppression (×0.3 if an incident occurred < 2h ago)

    When an event fires, it emits an ``InjectIncident`` message on
    ``incidents.inject`` for the incident-service to consume.
    """
    global PEAK_HOURS
    fixtures = get_fixtures()
    events_config = _resolve_calibration(fixtures["events"])
    base_probs = events_config["base_probabilities"]
    peak_multiplier = events_config["peak_multiplier"]
    suppression_factor = events_config["suppression_factor"]
    suppression_window = events_config.get("suppression_window_hours", 2)
    severity_ranges = events_config["severity_ranges"]
    locations = events_config["locations"]
    runtime = load_airport_runtime_config()

    if PEAK_HOURS is None:
        PEAK_HOURS = set(runtime.simulation.peak_hours or events_config.get("peak_hours", [7, 8, 9, 17, 18, 19]))

    sim_hour = sim_time.hour

    for event_type, base_prob in base_probs.items():
        effective_prob = base_prob

        # Peak hour modifier
        if sim_hour in PEAK_HOURS:
            effective_prob *= peak_multiplier

        # Weather modifier (simplified — no weather state available yet)
        events_config.get("weather_multiplier", {})
        # Will be enhanced when weather service is active

        # High throughput modifier (simplified)
        events_config.get("high_throughput_multiplier", {})

        # Suppression window
        if _recent_incident(sim_time, window_hours=suppression_window):
            effective_prob *= suppression_factor

        # Roll the dice
        if _rng.random() < effective_prob:
            # Select severity
            sev_range = severity_ranges.get(event_type, ["medium", "high"])
            severity = _rng.choice(sev_range)

            # Select location
            locs = locations.get(event_type, ["unknown"])
            location = _rng.choice(locs)

            logger.info(
                "Injecting event: %s (severity=%s, location=%s, prob=%.4f, source=%s)",
                event_type, severity, location, effective_prob, _active_source,
            )

            emit_inject_incident(
                sim_time=sim_time,
                incident_type=event_type,
                severity=severity,
                location=location,
                trigger=f"probabilistic:{_active_source}",
            )
            m_events_injected.labels(type=event_type).inc()
            record_incident(sim_time)

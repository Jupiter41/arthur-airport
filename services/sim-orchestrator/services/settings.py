"""Durably checkpointed preferences, distinct from effective owner state."""

from __future__ import annotations

import logging
import os
from typing import Optional

from pydantic import BaseModel, Field

from services.airport_config import load_airport_runtime_config

logger = logging.getLogger(__name__)

_runtime = load_airport_runtime_config()


class SimSettings(BaseModel):
    """All tuneable simulation parameters."""

    # ── Demand ──────────────────────────────────────────────
    daily_flights: int = Field(_runtime.simulation.daily_flight_target, ge=50, le=5000)
    load_factor_mean: float = Field(_runtime.simulation.load_factor_mean, ge=0.1, le=1.0)
    pax_multiplier: float = Field(1.0, ge=0.1, le=5.0)
    special_event: Optional[str] = None
    hourly_weights: dict[int, int] = Field(
        default_factory=lambda: dict(_runtime.simulation.hourly_weights),
    )

    # ── Weather ─────────────────────────────────────────────
    weather_lock: Optional[str] = Field(
        None,
        description="Lock weather to a category (CAVOK, VMC, IMC, LIFR) or null for FSM",
    )
    wind_kt: int = Field(15, ge=0, le=100)
    gust_enabled: bool = False

    # ── Incidents ───────────────────────────────────────────
    runway_incursion_rate: float = Field(0.005, ge=0.0, le=1.0)
    baggage_fire_rate: float = Field(0.008, ge=0.0, le=1.0)
    security_breach_rate: float = Field(0.010, ge=0.0, le=1.0)
    system_failure_rate: float = Field(0.015, ge=0.0, le=1.0)
    suppression_window_h: float = Field(2.0, ge=0.5, le=24.0)

    # ── Security ────────────────────────────────────────────
    lanes_a: int = Field(_runtime.operations.security_lanes_open["A"], ge=1, le=20)
    lanes_b: int = Field(_runtime.operations.security_lanes_open["B"], ge=1, le=20)
    lanes_c: int = Field(_runtime.operations.security_lanes_open["C"], ge=1, le=20)
    mct_minutes: int = Field(45, ge=15, le=180)

    # ── Baggage ─────────────────────────────────────────────
    screening_units: int = Field(
        _runtime.operations.baggage.screening_units_per_terminal
        * len(_runtime.operations.security_lanes_open), ge=1, le=30,
    )
    sorting_capacity: int = Field(
        _runtime.operations.baggage.sorting_matrix_hr, ge=100, le=10000,
    )
    dg_false_positive_rate: float = Field(0.003, ge=0.0, le=0.5)

    # ── Noise & variability (Phase 1.2) ─────────────────────
    crew_delay_probability: float = Field(0.05, ge=0.0, le=1.0)
    crew_delay_min: int = Field(5, ge=1, le=60)
    crew_delay_max: int = Field(15, ge=1, le=60)
    ctot_probability_peak: float = Field(0.10, ge=0.0, le=1.0)
    ctot_delay_min: int = Field(5, ge=1, le=120)
    ctot_delay_max: int = Field(30, ge=1, le=120)
    noshow_rate: float = Field(0.03, ge=0.0, le=0.5)
    equipment_failure_rate: float = Field(0.01, ge=0.0, le=1.0)
    equipment_failure_delay_min: int = Field(8, ge=1, le=120)
    equipment_failure_delay_max: int = Field(20, ge=1, le=120)
    diversion_rate: float = Field(0.003, ge=0.0, le=0.5)
    holding_fuel_burn_kg_per_hr: int = Field(2500, ge=500, le=10000)
    holding_fuel_warn_minutes: int = Field(30, ge=10, le=120)
    holding_fuel_panpan_minutes: int = Field(45, ge=15, le=180)


# ── Module-level singleton ──────────────────────────────────

_settings = SimSettings(daily_flights=int(os.getenv("DAILY_FLIGHT_TARGET", str(_runtime.simulation.daily_flight_target))))


def get_settings() -> SimSettings:
    """Return the current settings (read-only snapshot)."""
    return _settings.model_copy(deep=True)


def settings_response() -> dict:
    """Describe storage/application truth without claiming owner execution."""
    requested = get_settings().model_dump()
    application = dict.fromkeys(requested, "stored_only")
    for key in ("daily_flights", "hourly_weights"):
        application[key] = "next_manifest"
    for key in ("lanes_a", "lanes_b", "lanes_c"):
        application[key] = "owner_command"
    for key in ("load_factor_mean", "mct_minutes", "screening_units",
                "sorting_capacity", "dg_false_positive_rate"):
        application[key] = "configuration_restart"
    return {**requested, "requested": requested, "application": application}


def update_settings(patch: dict) -> SimSettings:
    """Apply a partial update and return the new settings.

    Only fields present in *patch* are changed; unknown keys are ignored.
    Validation is enforced by Pydantic.
    """
    global _settings
    current = _settings.model_dump()
    current.update({k: v for k, v in patch.items() if k in SimSettings.model_fields})
    _settings = SimSettings(**current)
    logger.info("Settings updated: %s", list(patch.keys()))
    return _settings.model_copy(deep=True)

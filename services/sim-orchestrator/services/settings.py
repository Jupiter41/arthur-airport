"""In-memory simulation settings store.

Holds all tuneable parameters for the simulation. Services consume
the ``sim.settings`` Kafka event to pick up changes. The values here
are the *defaults* — they can be overridden at runtime via the REST
API (``PATCH /api/v1/sim/settings``).
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SimSettings(BaseModel):
    """All tuneable simulation parameters."""

    # ── Demand ──────────────────────────────────────────────
    daily_flights: int = Field(420, ge=50, le=1200)
    load_factor_mean: float = Field(0.80, ge=0.1, le=1.0)
    pax_multiplier: float = Field(1.0, ge=0.1, le=5.0)
    special_event: Optional[str] = None

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
    lanes_a: int = Field(4, ge=1, le=20)
    lanes_b: int = Field(3, ge=1, le=20)
    lanes_c: int = Field(4, ge=1, le=20)
    mct_minutes: int = Field(45, ge=15, le=180)

    # ── Baggage ─────────────────────────────────────────────
    screening_units: int = Field(6, ge=1, le=30)
    sorting_capacity: int = Field(1800, ge=100, le=10000)
    dg_false_positive_rate: float = Field(0.003, ge=0.0, le=0.5)


# ── Module-level singleton ──────────────────────────────────

_settings = SimSettings()


def get_settings() -> SimSettings:
    """Return the current settings (read-only snapshot)."""
    return _settings.model_copy()


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
    return _settings.model_copy()

"""Airport configuration loader and runtime normalization.

Canonical single source for ``config/airport.yaml`` (roadmap D6). Every service
reads operational constants from here instead of a private copy, so tuning an
airport is editing one file rather than grep-and-hope.

Exposes validated, normalized values used by seeding, schedule generation and
the per-service operational constants (peak hours, walking/apron speeds,
cascade depth, weather capacity thresholds).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

WEATHER_CATEGORIES = ("CAVOK", "VMC", "IMC", "LIFR")

WIND_THRESHOLD_KEYS = ("crosswind", "crosswind_heavy", "tailwind")
WIND_REDUCTION_KEYS = ("crosswind", "crosswind_heavy", "tailwind")


class AirportIdentity(BaseModel):
    name: str = "Arthur International Airport"
    iata: str = "ART"
    icao: str = "KART"
    timezone: str = "America/Arthur"


class AirportRunway(BaseModel):
    id: str
    length_m: int = Field(default=3500, ge=500)
    ils: bool = False


class AirportInfrastructure(BaseModel):
    terminals: int = Field(default=3, ge=1, le=26)
    gates_per_terminal: list[int] = Field(default_factory=lambda: [14, 14, 14])
    runways: list[AirportRunway] = Field(
        default_factory=lambda: [
            AirportRunway(id="09L/27R", length_m=3500, ils=True),
            AirportRunway(id="09R/27L", length_m=3500, ils=False),
        ]
    )

    @model_validator(mode="after")
    def validate_structure(self) -> "AirportInfrastructure":
        if len(self.gates_per_terminal) != self.terminals:
            raise ValueError("gates_per_terminal length must match terminals")
        if any(v < 1 for v in self.gates_per_terminal):
            raise ValueError("each gates_per_terminal value must be >= 1")
        if not self.runways:
            raise ValueError("at least one runway pair is required")
        return self


class AirportSimulation(BaseModel):
    daily_flight_target: int = Field(default=420, ge=20, le=5000)
    load_factor_mean: float = Field(default=0.80, ge=0.1, le=0.99)
    peak_hours: list[int] = Field(default_factory=lambda: [7, 8, 9, 17, 18, 19])
    hourly_weights: dict[int, int] = Field(
        default_factory=lambda: {
            5: 2,
            6: 8,
            7: 14,
            8: 16,
            9: 12,
            10: 10,
            11: 9,
            12: 8,
            13: 9,
            14: 10,
            15: 10,
            16: 12,
            17: 15,
            18: 14,
            19: 10,
            20: 7,
            21: 5,
            22: 3,
        }
    )

    @model_validator(mode="after")
    def validate_peak_hours(self) -> "AirportSimulation":
        if not self.peak_hours:
            raise ValueError("peak_hours cannot be empty")
        invalid = [h for h in self.peak_hours if h < 0 or h > 23]
        if invalid:
            raise ValueError(f"peak_hours contains invalid values: {invalid}")
        return self


class AirportFlightTypes(BaseModel):
    domestic: float = Field(default=0.42, ge=0.0, le=1.0)
    international_short: float = Field(default=0.28, ge=0.0, le=1.0)
    international_long: float = Field(default=0.18, ge=0.0, le=1.0)
    cargo: float = Field(default=0.08, ge=0.0, le=1.0)
    charter: float = Field(default=0.04, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_sum(self) -> "AirportFlightTypes":
        total = (
            self.domestic
            + self.international_short
            + self.international_long
            + self.cargo
            + self.charter
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"flight_types weights must sum to ~1.0 (got {total:.3f})")
        return self

    @property
    def normalized(self) -> dict[str, float]:
        total = (
            self.domestic
            + self.international_short
            + self.international_long
            + self.cargo
            + self.charter
        )
        if total == 0:
            return {
                "domestic": 1.0,
                "international_short": 0.0,
                "international_long": 0.0,
                "cargo": 0.0,
                "charter": 0.0,
            }
        return {
            "domestic": self.domestic / total,
            "international_short": self.international_short / total,
            "international_long": self.international_long / total,
            "cargo": self.cargo / total,
            "charter": self.charter / total,
        }


class AirportAirlineOverride(BaseModel):
    code: str
    name: str
    market_share: float = Field(ge=0.0, le=1.0)
    hub_terminal: str | None = None


class AirportAccessibility(BaseModel):
    """1C — accessibility & special assistance pool sizing."""

    total_per_terminal: dict[str, int] = Field(
        default_factory=lambda: {"A": 8, "B": 12, "C": 8}
    )
    sla_target_pct: float = Field(default=90.0, ge=0.0, le=100.0)
    boarding_cutoff_minutes: int = Field(default=15, ge=0)
    max_dispatch_wait_minutes: int = Field(default=30, ge=0)


# ── D6: operational constants ─────────────────────────────────


class WeatherCategoryCapacity(BaseModel):
    arrival: int = Field(ge=0)
    departure: int = Field(ge=0)
    runways: int = Field(ge=1)


def _default_weather_capacity() -> dict[str, WeatherCategoryCapacity]:
    return {
        "CAVOK": WeatherCategoryCapacity(arrival=32, departure=32, runways=2),
        "VMC": WeatherCategoryCapacity(arrival=28, departure=28, runways=2),
        "IMC": WeatherCategoryCapacity(arrival=18, departure=16, runways=1),
        "LIFR": WeatherCategoryCapacity(arrival=8, departure=6, runways=1),
    }


def _default_wind_thresholds() -> dict[str, int]:
    return {"crosswind": 25, "crosswind_heavy": 35, "tailwind": 10}


def _default_wind_reductions() -> dict[str, float]:
    return {"crosswind": 0.85, "crosswind_heavy": 0.60, "tailwind": 0.70}


class AirportOperations(BaseModel):
    """D6 operational constants — tuning an airport is editing one file."""

    walking_speed_m_min: float = Field(default=84.0, gt=0)
    apron_speed_m_min: float = Field(default=83.3, gt=0)
    cascade_max_depth: int = Field(default=5, ge=1)

    weather_capacity: dict[str, WeatherCategoryCapacity] = Field(
        default_factory=_default_weather_capacity
    )
    wind_thresholds_kt: dict[str, int] = Field(default_factory=_default_wind_thresholds)
    wind_reductions: dict[str, float] = Field(default_factory=_default_wind_reductions)

    @model_validator(mode="after")
    def validate_weather(self) -> "AirportOperations":
        missing_cat = [c for c in WEATHER_CATEGORIES if c not in self.weather_capacity]
        if missing_cat:
            raise ValueError(
                f"operations.weather_capacity must cover {WEATHER_CATEGORIES}; missing {missing_cat}"
            )
        missing_thr = [
            k for k in WIND_THRESHOLD_KEYS if k not in self.wind_thresholds_kt
        ]
        if missing_thr:
            raise ValueError(
                f"operations.wind_thresholds_kt must include {WIND_THRESHOLD_KEYS}; missing {missing_thr}"
            )
        missing_red = [k for k in WIND_REDUCTION_KEYS if k not in self.wind_reductions]
        if missing_red:
            raise ValueError(
                f"operations.wind_reductions must include {WIND_REDUCTION_KEYS}; missing {missing_red}"
            )
        return self


class AirportConfig(BaseModel):
    identity: AirportIdentity = Field(default_factory=AirportIdentity)
    infrastructure: AirportInfrastructure = Field(default_factory=AirportInfrastructure)
    simulation: AirportSimulation = Field(default_factory=AirportSimulation)
    flight_types: AirportFlightTypes = Field(default_factory=AirportFlightTypes)
    airlines: list[AirportAirlineOverride] = Field(default_factory=list)
    accessibility: AirportAccessibility = Field(default_factory=AirportAccessibility)
    operations: AirportOperations = Field(default_factory=AirportOperations)


@dataclass(frozen=True)
class AirportRuntimeConfig:
    identity: AirportIdentity
    infrastructure: AirportInfrastructure
    simulation: AirportSimulation
    flight_types: AirportFlightTypes
    airlines: list[AirportAirlineOverride]
    accessibility: AirportAccessibility
    operations: AirportOperations

    @property
    def terminal_codes(self) -> list[str]:
        return [chr(ord("A") + i) for i in range(self.infrastructure.terminals)]

    @property
    def gates_per_terminal_map(self) -> dict[str, int]:
        return {
            code: self.infrastructure.gates_per_terminal[idx]
            for idx, code in enumerate(self.terminal_codes)
        }

    @property
    def total_gates(self) -> int:
        return sum(self.infrastructure.gates_per_terminal)

    @property
    def runway_pairs(self) -> list[AirportRunway]:
        return self.infrastructure.runways

    @property
    def runway_directions(self) -> list[dict[str, Any]]:
        directions: list[dict[str, Any]] = []
        for pair in self.infrastructure.runways:
            parts = [p.strip() for p in pair.id.split("/") if p.strip()]
            if not parts:
                continue
            if len(parts) == 1:
                directions.append(
                    {
                        "id": parts[0],
                        "length_m": pair.length_m,
                        "ils": pair.ils,
                        "pair_id": pair.id,
                    }
                )
                continue
            for part in parts:
                directions.append(
                    {
                        "id": part,
                        "length_m": pair.length_m,
                        "ils": pair.ils,
                        "pair_id": pair.id,
                    }
                )
        return directions

    @property
    def departure_runway_ids(self) -> list[str]:
        ids: list[str] = []
        for pair in self.infrastructure.runways:
            parts = [p.strip() for p in pair.id.split("/") if p.strip()]
            if parts:
                ids.append(parts[0])
        return ids or ["09L"]

    @property
    def arrival_runway_ids(self) -> list[str]:
        ids: list[str] = []
        for pair in self.infrastructure.runways:
            parts = [p.strip() for p in pair.id.split("/") if p.strip()]
            if len(parts) >= 2:
                ids.append(parts[1])
            elif parts:
                ids.append(parts[0])
        return ids or ["27R"]

    @property
    def load_factor_beta_params(self) -> tuple[float, float]:
        # Keep a stable concentration while shifting mean.
        concentration = 10.0
        alpha = max(0.1, self.simulation.load_factor_mean * concentration)
        beta = max(0.1, (1.0 - self.simulation.load_factor_mean) * concentration)
        return alpha, beta


_cached_runtime: AirportRuntimeConfig | None = None


def _candidate_paths() -> list[Path]:
    env_path = os.getenv("AIRPORT_CONFIG_PATH")
    paths: list[Path] = []
    if env_path:
        paths.append(Path(env_path))

    # Repository root fallback when running locally.
    # - Local: services/_common/airport_config.py → parents[2] = repo root
    # - Docker: /app/_common/airport_config.py → /app/config/airport.yaml
    current = Path(__file__).resolve()
    for depth in [4, 3, 2]:  # Try 5, 4, 3 levels up
        if depth < len(current.parents):
            repo_root = current.parents[depth]
            candidate = repo_root / "config" / "airport.yaml"
            if candidate.exists():
                paths.append(candidate)

    # Container default path.
    paths.append(Path("/app/config/airport.yaml"))

    return paths


def _load_raw_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError("airport config root must be a mapping")
    return raw


def _runtime_from_model(model: AirportConfig) -> AirportRuntimeConfig:
    return AirportRuntimeConfig(
        identity=model.identity,
        infrastructure=model.infrastructure,
        simulation=model.simulation,
        flight_types=model.flight_types,
        airlines=model.airlines,
        accessibility=model.accessibility,
        operations=model.operations,
    )


def load_airport_runtime_config(force_reload: bool = False) -> AirportRuntimeConfig:
    global _cached_runtime
    if _cached_runtime is not None and not force_reload:
        return _cached_runtime

    config_model: AirportConfig | None = None
    last_error: Exception | None = None

    for path in _candidate_paths():
        if not path.exists():
            continue
        try:
            raw = _load_raw_yaml(path)
            config_model = AirportConfig.model_validate(raw)
            break
        except Exception as exc:  # pragma: no cover - validation path
            last_error = exc

    if config_model is None:
        if last_error is not None:
            raise RuntimeError(f"Invalid airport config: {last_error}") from last_error
        config_model = AirportConfig()

    _cached_runtime = _runtime_from_model(config_model)
    return _cached_runtime

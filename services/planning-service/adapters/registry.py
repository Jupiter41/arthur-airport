"""Adapter registry — selects the appropriate adapter at runtime from config.

Adapters are selected based on configuration in config/planning.yaml or
runtime parameters. Each data domain (schedule, weather, demand) can use
a different adapter.

Example config:
    adapters:
      schedule: "simulation"     # or "bts", "opensky"
      weather:  "mesonet"        # or "simulation"
      demand:   "bts_t100"       # or "simulation", "eurocontrol"
"""

from __future__ import annotations

import logging
from pathlib import Path

from .base import AbstractAdapter
from .bts import BTSAdapter
from .eurocontrol import EurocontrolDemandAdapter
from .mesonet import MesonetAdapter
from .opensky import OpenSkyAdapter
from .simulation import SimulationAdapter

logger = logging.getLogger(__name__)


# Default data file paths (relative to project root)
_DEFAULT_BTS_PATH = Path("data/bts/T100_reference.csv")
_DEFAULT_WEATHER_PATH = Path("data/weather/EGLL_30days.csv")


def get_schedule_adapter(
    source: str = "simulation",
    *,
    bts_csv_path: str | Path | None = None,
    daily_flight_target: int = 420,
    seed: int | None = None,
) -> AbstractAdapter:
    """Return a schedule adapter by name.

    Args:
        source: Adapter name — 'simulation', 'bts', or 'opensky'.
        bts_csv_path: Path to BTS T-100 CSV (for 'bts' source).
        daily_flight_target: Flight count target (for 'simulation' source).
        seed: Random seed for deterministic results (for 'simulation' source).
    """
    match source:
        case "simulation":
            adapter = SimulationAdapter(daily_flight_target=daily_flight_target, seed=seed)
        case "bts":
            path = Path(bts_csv_path) if bts_csv_path else _DEFAULT_BTS_PATH
            adapter = BTSAdapter(path)
        case "opensky":
            adapter = OpenSkyAdapter()
        case _:
            raise ValueError(f"Unknown schedule adapter: {source}")

    logger.info("Schedule adapter: %s (real_data=%s)", adapter.source_name, adapter.is_real_data)
    return adapter


def get_weather_adapter(
    source: str = "simulation",
    *,
    mesonet_csv_path: str | Path | None = None,
    seed: int | None = None,
) -> AbstractAdapter:
    """Return a weather adapter by name.

    Args:
        source: Adapter name — 'simulation' or 'mesonet'.
        mesonet_csv_path: Path to Mesonet CSV (for 'mesonet' source).
        seed: Random seed (for 'simulation' source).
    """
    match source:
        case "simulation":
            adapter = SimulationAdapter(seed=seed)
        case "mesonet":
            path = Path(mesonet_csv_path) if mesonet_csv_path else _DEFAULT_WEATHER_PATH
            adapter = MesonetAdapter(path)
        case _:
            raise ValueError(f"Unknown weather adapter: {source}")

    logger.info("Weather adapter: %s (real_data=%s)", adapter.source_name, adapter.is_real_data)
    return adapter


def get_demand_adapter(
    source: str = "simulation",
    *,
    bts_csv_path: str | Path | None = None,
    eurocontrol_scenario: str = "base",
    base_year_pax: int = 30_000_000,
    seed: int | None = None,
) -> AbstractAdapter:
    """Return a demand adapter by name.

    Args:
        source: Adapter name — 'simulation', 'bts_t100', or 'eurocontrol'.
        bts_csv_path: Path to BTS CSV (for 'bts_t100' source).
        eurocontrol_scenario: Growth scenario (for 'eurocontrol' source).
        base_year_pax: Baseline annual passengers (for 'eurocontrol' source).
        seed: Random seed (for 'simulation' source).
    """
    match source:
        case "simulation":
            adapter = SimulationAdapter(seed=seed)
        case "bts_t100" | "bts":
            path = Path(bts_csv_path) if bts_csv_path else _DEFAULT_BTS_PATH
            adapter = BTSAdapter(path)
        case "eurocontrol":
            adapter = EurocontrolDemandAdapter(base_year_pax=base_year_pax, scenario=eurocontrol_scenario)
        case _:
            raise ValueError(f"Unknown demand adapter: {source}")

    logger.info("Demand adapter: %s (real_data=%s)", adapter.source_name, adapter.is_real_data)
    return adapter


def list_available_adapters() -> dict[str, list[str]]:
    """List all available adapter names by domain."""
    return {
        "schedule": ["simulation", "bts", "opensky"],
        "weather": ["simulation", "mesonet"],
        "demand": ["simulation", "bts_t100", "eurocontrol"],
    }

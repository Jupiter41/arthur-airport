"""Airport configuration loader — canonical implementation lives in ``_common``.

Roadmap D6 moved the loader to ``_common/airport_config.py`` so every service
reads operational constants from one place. This module is kept as a re-export
so existing sim-orchestrator call sites
(``from services.airport_config import load_airport_runtime_config``) keep
working without churn.
"""

from _common.airport_config import (  # noqa: F401
    AirportAccessibility,
    AirportConfig,
    AirportFlightTypes,
    AirportIdentity,
    AirportInfrastructure,
    AirportOperations,
    AirportRuntimeConfig,
    AirportRunway,
    AirportSimulation,
    AirportAirlineOverride,
    WeatherCategoryCapacity,
    load_airport_runtime_config,
)

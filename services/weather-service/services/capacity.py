"""Runway capacity calculation based on weather conditions."""

from _common.airport_config import load_airport_runtime_config

from services.parameters import WeatherParams

_operations = load_airport_runtime_config().operations

# Capacity rates per weather category (D6 — single source: config/airport.yaml)
_BASE_CAPACITY = _operations.weather_capacity
_WIND_THRESHOLDS = _operations.wind_thresholds_kt
_WIND_REDUCTIONS = _operations.wind_reductions

# Runway impact labels per category
_RUNWAY_IMPACT = {
    "CAVOK": "none",
    "VMC":   "none",
    "IMC":   "reduced_rate",
    "LIFR":  "single_runway",
}

# Severity labels per category
_SEVERITY = {
    "CAVOK": "none",
    "VMC":   "low",
    "IMC":   "moderate",
    "LIFR":  "severe",
}

# Summary messages per category
_SUMMARY = {
    "CAVOK": "Clear skies. Full capacity. All runways operational.",
    "VMC":   "Visual conditions. Near-full capacity.",
    "IMC":   "Instrument conditions. Reduced arrival rate. ILS runway 09L only.",
    "LIFR":  "Low IFR. Severe restrictions. CAT III ILS 09L only. Expect delays.",
}


def compute_runway_capacity(params: WeatherParams) -> dict:
    """Compute runway capacity based on weather parameters.

    Applies crosswind and tailwind reductions on top of category-based
    base rates per the spec.
    """
    base = _BASE_CAPACITY[params.category]

    arrival_rate = base.arrival
    departure_rate = base.departure

    # Crosswind reduction
    if params.wind_speed_kt > _WIND_THRESHOLDS["crosswind_heavy"]:
        arrival_rate = int(arrival_rate * _WIND_REDUCTIONS["crosswind_heavy"])
        departure_rate = int(departure_rate * _WIND_REDUCTIONS["crosswind_heavy"])
    elif params.wind_speed_kt > _WIND_THRESHOLDS["crosswind"]:
        arrival_rate = int(arrival_rate * _WIND_REDUCTIONS["crosswind"])
        departure_rate = int(departure_rate * _WIND_REDUCTIONS["crosswind"])

    # Tailwind reduction (simplified: wind direction > 180 = tailwind on 09L)
    tailwind = params.wind_direction > 180
    if tailwind and params.wind_speed_kt > _WIND_THRESHOLDS["tailwind"]:
        arrival_rate = int(arrival_rate * _WIND_REDUCTIONS["tailwind"])
        departure_rate = int(departure_rate * _WIND_REDUCTIONS["tailwind"])

    return {
        "arrival_rate": arrival_rate,
        "departure_rate": departure_rate,
        "active_runways": base.runways,
        "ils_required": params.category in ("IMC", "LIFR"),
        "active_runway": "09L" if params.category in ("IMC", "LIFR") else "09L/27R",
        "runway_impact": _RUNWAY_IMPACT[params.category],
    }


def compute_impact_summary(params: WeatherParams, capacity: dict) -> dict:
    """Compute the full impact summary for the REST /weather/impact endpoint."""
    crosswind_kt = params.wind_speed_kt  # simplified — full crosswind component
    return {
        "category": params.category,
        "severity": _SEVERITY[params.category],
        "summary": _SUMMARY[params.category],
        "arrival_rate": capacity["arrival_rate"],
        "departure_rate": capacity["departure_rate"],
        "crosswind_kt": crosswind_kt,
        "crosswind_limit_kt": _WIND_THRESHOLDS["crosswind_heavy"],
        "operations_normal": params.category in ("CAVOK", "VMC"),
    }

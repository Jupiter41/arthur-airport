"""Runway capacity calculation based on weather conditions."""

from services.parameters import WeatherParams

# Base capacity rates per weather category
_BASE_CAPACITY = {
    "CAVOK": {"arrival": 32, "departure": 32, "runways": 2},
    "VMC":   {"arrival": 28, "departure": 28, "runways": 2},
    "IMC":   {"arrival": 18, "departure": 16, "runways": 1},
    "LIFR":  {"arrival": 8,  "departure": 6,  "runways": 1},
}

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

    arrival_rate = base["arrival"]
    departure_rate = base["departure"]

    # Crosswind reduction
    if params.wind_speed_kt > 35:
        arrival_rate = int(arrival_rate * 0.60)
        departure_rate = int(departure_rate * 0.60)
    elif params.wind_speed_kt > 25:
        arrival_rate = int(arrival_rate * 0.85)
        departure_rate = int(departure_rate * 0.85)

    # Tailwind reduction (simplified: wind direction > 180 = tailwind on 09L)
    tailwind = params.wind_direction > 180
    if tailwind and params.wind_speed_kt > 10:
        arrival_rate = int(arrival_rate * 0.70)
        departure_rate = int(departure_rate * 0.70)

    return {
        "arrival_rate": arrival_rate,
        "departure_rate": departure_rate,
        "active_runways": base["runways"],
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
        "crosswind_limit_kt": 35,
        "operations_normal": params.category in ("CAVOK", "VMC"),
    }

"""ML feature engineering — 12 features for queue depth prediction.

Feature vector must be consistent between training and inference.
Uses FEATURE_COLS list to enforce column order.
"""

import json
from datetime import datetime
from pathlib import Path

FEATURE_COLS = [
    "hour_of_day",
    "day_of_week",
    "month",
    "season",
    "weather_category",
    "flights_departing_next_90min",
    "expected_pax_next_90min",
    "load_factor_avg_today",
    "active_incident_in_terminal",
    "adjacent_terminal_congested",
    "is_special_event",
    "event_pax_multiplier",
]

WEATHER_ENCODING = {"CAVOK": 0, "VMC": 1, "IMC": 2, "LIFR": 3}

# Load special events from fixtures
_events: list[dict] | None = None


def _load_events() -> list[dict]:
    global _events
    if _events is not None:
        return _events
    events_path = Path(__file__).parent.parent / "fixtures" / "events.json"
    if events_path.exists():
        with open(events_path) as f:
            _events = json.load(f)
    else:
        _events = []
    return _events


def get_active_event(sim_time: datetime, terminal: str) -> dict | None:
    """Check if a special event is active at the given sim_time for the terminal."""
    events = _load_events()
    month = sim_time.month
    day = sim_time.day

    for event in events:
        if terminal not in event.get("terminals", []):
            continue

        start_m = event["start_month"]
        start_d = event["start_day"]
        end_m = event["end_month"]
        end_d = event["end_day"]

        # Handle year-wrapping events (e.g. Dec 18 - Jan 5)
        if start_m <= end_m:
            if (month > start_m or (month == start_m and day >= start_d)) and \
               (month < end_m or (month == end_m and day <= end_d)):
                return event
        else:
            # Wraps around year boundary
            if (month > start_m or (month == start_m and day >= start_d)) or \
               (month < end_m or (month == end_m and day <= end_d)):
                return event

    return None


def build_features(
    terminal: str,
    sim_time: datetime,
    weather_category: str,
    flights_next_90: dict[str, int],
    pax_next_90: dict[str, float],
    load_factor_today: float,
    incident_active: dict[str, bool],
    adjacent_congested: dict[str, bool],
) -> dict:
    """Build the 12-feature vector for a given terminal and sim_time."""
    month = sim_time.month
    season = (month % 12) // 3  # 0=winter(Dec-Feb), 1=spring, 2=summer, 3=autumn

    event = get_active_event(sim_time, terminal)

    return {
        "hour_of_day": sim_time.hour,
        "day_of_week": sim_time.weekday(),
        "month": month,
        "season": season,
        "weather_category": WEATHER_ENCODING.get(weather_category, 0),
        "flights_departing_next_90min": flights_next_90.get(terminal, 0),
        "expected_pax_next_90min": float(pax_next_90.get(terminal, 0)),
        "load_factor_avg_today": load_factor_today,
        "active_incident_in_terminal": int(incident_active.get(terminal, False)),
        "adjacent_terminal_congested": int(adjacent_congested.get(terminal, False)),
        "is_special_event": int(event is not None),
        "event_pax_multiplier": event["pax_multiplier"] if event else 1.0,
    }

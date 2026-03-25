"""Prometheus metrics for weather-service."""

from prometheus_client import Counter, Gauge

# Map category names to numeric values for gauge
CATEGORY_VALUES = {"CAVOK": 0, "VMC": 1, "IMC": 2, "LIFR": 3}

weather_category = Gauge(
    "weather_category",
    "0=CAVOK 1=VMC 2=IMC 3=LIFR",
)

weather_transitions_total = Counter(
    "weather_transitions_total",
    "FSM transitions",
    ["from_cat", "to_cat"],
)

visibility_m = Gauge(
    "visibility_m",
    "Current visibility in meters",
)

wind_speed_kt = Gauge(
    "wind_speed_kt",
    "Current wind speed in knots",
)

wind_gust_kt = Gauge(
    "wind_gust_kt",
    "Current gust speed in knots",
)

runway_arrival_rate = Gauge(
    "runway_arrival_rate",
    "Max arrivals per hour",
)

runway_departure_rate = Gauge(
    "runway_departure_rate",
    "Max departures per hour",
)

holding_stack_depth = Gauge(
    "holding_stack_depth",
    "Arrivals in holding",
)

flights_delayed_by_weather_total = Counter(
    "flights_delayed_by_weather_total",
    "Weather-caused delays",
    ["category"],
)

envelope_invalid_total = Counter(
    "envelope_invalid_total",
    "Invalid Kafka event envelopes dropped",
    ["reason"],
)

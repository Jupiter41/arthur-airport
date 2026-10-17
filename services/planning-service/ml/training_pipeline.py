"""ML model training pipeline — loads data, trains demand + delay models.

P6.3 of ROADMAP_PLANNING.md.

Can be invoked via REST API or CLI.
"""

from __future__ import annotations

import csv
import calendar
from collections import defaultdict
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_BTS_PATH = "/app/data/bts/T100_reference.csv"


def build_demand_training_data(bts_path: str = DEFAULT_BTS_PATH) -> list[dict]:
    """Build training records from BTS T-100 CSV for the demand model."""
    path = Path(bts_path)
    if not path.exists():
        logger.warning("BTS CSV not found at %s", bts_path)
        return []

    # Aggregate monthly route observations before building features. Current
    # month passengers are the label; only earlier months may enter history.
    monthly: dict[tuple[str, str, int, int], dict] = {}
    try:
        with open(path, newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            for raw in reader:
                row = {key.strip().upper(): value for key, value in raw.items() if key}
                try:
                    year, month = int(row["YEAR"]), int(row["MONTH"])
                    days = calendar.monthrange(year, month)[1]
                    pax = float(row["PASSENGERS"])
                    departures = float(row["DEPARTURES_PERFORMED"])
                    distance = float(row.get("DISTANCE", 0))
                    origin, destination = row["ORIGIN"].strip(), row["DEST"].strip()
                    if pax <= 0 or departures <= 0 or not origin or not destination:
                        continue
                    key = (origin, destination, year, month)
                    observation = monthly.setdefault(key, {"pax": 0.0, "distance": distance, "days": days})
                    observation["pax"] += pax
                except (ValueError, KeyError, TypeError):
                    continue
        history: dict[tuple[str, str], list[float]] = defaultdict(list)
        records: list[dict] = []
        for (origin, destination, year, month), observation in sorted(
            monthly.items(), key=lambda item: (item[0][2], item[0][3], item[0][:2]),
        ):
            route_history = history[origin, destination]
            actual = observation["pax"] / observation["days"]
            if route_history:
                records.append({
                    "origin": origin, "destination": destination,
                    "year": year, "month": month, "day_of_week": 2,
                    "is_holiday": 0,
                    "distance_km": observation["distance"] * 1.609344,
                    "historical_avg_pax": sum(route_history) / len(route_history),
                    "growth_trend": 0.034, "is_hub_connection": 0,
                    "actual_pax": actual,
                })
            route_history.append(actual)
        logger.info("built %d lagged demand training records from %s", len(records), bts_path)
        return records
    except (OSError, csv.Error) as exc:
        logger.error("failed to build training data: %s", exc)
        return []


def build_delay_training_data(bts_path: str = DEFAULT_BTS_PATH) -> list[dict]:
    """Build synthetic delay training data from BTS load factors.

    Real delay data would come from BTS On-Time Performance dataset.
    This generates approximate labels from load factors and seasonal patterns.
    """
    path = Path(bts_path)
    if not path.exists():
        return []

    records: list[dict] = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    pax = int(float(row.get("PASSENGERS", "0")))
                    seats = int(float(row.get("SEATS", "0")))
                    month = int(float(row.get("MONTH", "1")))
                    distance = float(row.get("DISTANCE", "0"))

                    if pax <= 0 or seats <= 0:
                        continue

                    lf = pax / seats
                    # Synthetic delay label: high load + peak month → more delays
                    peak_month = month in (6, 7, 8, 12)
                    was_delayed = 1 if (lf > 0.85 and peak_month) or lf > 0.95 else 0

                    for hour in (8, 12, 16, 20):  # Sample hours
                        records.append({
                            "hour": hour,
                            "day_of_week": 2,
                            "month": month,
                            "weather_category": 0,
                            "aircraft_type_code": 0,
                            "flights_prev_2h": 20,
                            "distance_km": distance * 1.609344,
                            # No observed OTP is available in this aggregate.
                            # In particular, never encode the target in a feature.
                            "historical_otp": 0.8,
                            "target_source": "synthetic_heuristic",
                            "was_delayed": was_delayed,
                        })
                except (ValueError, KeyError):
                    continue

        logger.info("built %d delay training records from %s", len(records), bts_path)
    except Exception as e:
        logger.error("failed to build delay training data: %s", e)

    return records


def run_training_pipeline(bts_path: str = DEFAULT_BTS_PATH) -> dict:
    """Train both demand and delay models from BTS data.

    Returns training metrics for both models.
    """
    from ml.demand_model import get_demand_model
    from ml.delay_model import get_delay_model

    results = {"demand": {}, "delay": {}}

    # Train demand model
    demand_data = build_demand_training_data(bts_path)
    if demand_data:
        demand_model = get_demand_model()
        # Set route baselines from training data
        from collections import defaultdict
        route_totals: dict[tuple[str, str], list[float]] = defaultdict(list)
        for rec in demand_data:
            key = (rec["origin"], rec["destination"])
            route_totals[key].append(rec["actual_pax"])
        baselines = {k: sum(v) / len(v) for k, v in route_totals.items()}
        demand_model.set_route_baselines(baselines)
        results["demand"] = demand_model.train(demand_data)
    else:
        results["demand"] = {"error": "no training data available"}

    # Train delay model
    delay_data = build_delay_training_data(bts_path)
    if delay_data:
        delay_model = get_delay_model()
        results["delay"] = delay_model.train(delay_data)
    else:
        results["delay"] = {"error": "no training data available"}

    logger.info("training pipeline complete", results=results)
    return results

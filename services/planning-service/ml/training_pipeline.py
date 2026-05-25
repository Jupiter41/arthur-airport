"""ML model training pipeline — loads data, trains demand + delay models.

P6.3 of ROADMAP_PLANNING.md.

Can be invoked via REST API or CLI.
"""

from __future__ import annotations

import csv
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

    records: list[dict] = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    pax = int(float(row.get("PASSENGERS", "0")))
                    int(float(row.get("SEATS", "0")))
                    deps = int(float(row.get("DEPARTURES_PERFORMED", "0")))
                    distance = float(row.get("DISTANCE", "0"))
                    month = int(float(row.get("MONTH", "1")))

                    if pax <= 0 or deps <= 0:
                        continue

                    daily_pax = pax / 30  # Monthly → daily estimate
                    records.append({
                        "origin": row.get("ORIGIN", "").strip(),
                        "destination": row.get("DEST", "").strip(),
                        "month": month,
                        "day_of_week": 2,  # Wednesday as average
                        "is_holiday": 0,
                        "distance_km": distance * 1.852,  # statute miles → km
                        "historical_avg_pax": daily_pax,
                        "growth_trend": 0.034,
                        "is_hub_connection": 0,
                        "actual_pax": daily_pax,
                    })
                except (ValueError, KeyError):
                    continue

        logger.info("built %d demand training records from %s", len(records), bts_path)
    except Exception as e:
        logger.error("failed to build training data: %s", e)

    return records


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
                            "distance_km": distance * 1.852,
                            "historical_otp": 1.0 - (0.15 if was_delayed else 0.05),
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

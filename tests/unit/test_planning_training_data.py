"""No current/future target may be used as a demand predictor."""

import importlib.util
from pathlib import Path

import pytest


def pipeline():
    path = (
        Path(__file__).resolve().parents[2]
        / "services/planning-service/ml/training_pipeline.py"
    )
    spec = importlib.util.spec_from_file_location("planning_training_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demand_history_uses_only_prior_months_and_actual_calendar_days(tmp_path):
    csv = tmp_path / "synthetic.csv"
    csv.write_text(
        "YEAR,MONTH,ORIGIN,DEST,PASSENGERS,DEPARTURES_PERFORMED,DISTANCE\n"
        "2026,3,ART,XAA,9300,30,1000\n"
        "2026,1,ART,XAA,3100,30,1000\n"
        "2026,2,ART,XAA,5600,30,1000\n",
        encoding="utf-8",
    )
    rows = pipeline().build_demand_training_data(str(csv))
    assert len(rows) == 2
    assert rows[0]["month"] == 2
    assert rows[0]["historical_avg_pax"] == 100
    assert rows[0]["actual_pax"] == 200
    assert rows[1]["historical_avg_pax"] == 150
    assert rows[1]["actual_pax"] == 300
    assert rows[0]["distance_km"] == pytest.approx(1609.344)


def test_single_month_cannot_train_itself(tmp_path):
    csv = tmp_path / "synthetic.csv"
    csv.write_text(
        "YEAR,MONTH,ORIGIN,DEST,PASSENGERS,DEPARTURES_PERFORMED,DISTANCE\n"
        "2026,1,ART,XAA,3100,30,1000\n",
        encoding="utf-8",
    )
    assert pipeline().build_demand_training_data(str(csv)) == []

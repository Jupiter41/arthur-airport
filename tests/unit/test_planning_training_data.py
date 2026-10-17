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


def test_synthetic_delay_features_do_not_encode_label_and_use_statute_miles(tmp_path):
    csv = tmp_path / "synthetic.csv"
    csv.write_text(
        "MONTH,PASSENGERS,SEATS,DISTANCE\n"
        "1,50,100,1000\n"
        "7,99,100,1000\n", encoding="utf-8",
    )
    rows = pipeline().build_delay_training_data(str(csv))
    assert {row["was_delayed"] for row in rows} == {0, 1}
    assert {row["historical_otp"] for row in rows} == {0.8}
    assert {row["target_source"] for row in rows} == {"synthetic_heuristic"}
    assert all(row["distance_km"] == pytest.approx(1609.344) for row in rows)


def delay_model(monkeypatch):
    import sys
    from tests.conftest import import_service_module

    for key in list(sys.modules):
        if key == "ml" or key.startswith("ml."):
            monkeypatch.delitem(sys.modules, key)
    return import_service_module("planning", "ml.delay_model")


def test_delay_training_reports_synthetic_source_and_no_undefined_auc(monkeypatch):
    import json
    import lightgbm as lgb

    module = delay_model(monkeypatch)
    factory = lgb.LGBMClassifier
    monkeypatch.setattr(lgb, "LGBMClassifier", lambda **kw: factory(n_jobs=1, **kw))
    rows = [{**dict.fromkeys(module.DELAY_FEATURES, 0), "hour": i % 24,
             "historical_otp": 0.8, "was_delayed": i % 2 if i < 40 else 1,
             "target_source": "synthetic_heuristic"} for i in range(50)]
    model = module.DelayModel()
    result = model.train(rows)
    assert result["trained"] is True
    assert result["auc"] is None  # holdout has only one class: AUC undefined
    assert result["calibrated"] is False
    json.dumps(result, allow_nan=False)
    prediction = model.predict(hour=12, day_of_week=2, month=7, weather_category=0)
    assert prediction.model_source == "lgbm_synthetic"
    assert 0 <= prediction.p_delay_15min <= 1


def test_delay_training_rejects_single_class_history(monkeypatch):
    module = delay_model(monkeypatch)
    assert module.DelayModel().train([{"was_delayed": 0}] * 20)["trained"] is False

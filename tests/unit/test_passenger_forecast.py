"""Forecast inputs and validation must describe the simulated airport."""

import asyncio
import importlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tests.conftest import import_service_module

NOW = datetime(2026, 1, 1, 10)


def passenger_module(name, monkeypatch):
    # Other services also use a top-level `ml` package. Isolate this context.
    for key in list(sys.modules):
        if key == "ml" or key.startswith("ml."):
            monkeypatch.delitem(sys.modules, key)
    return import_service_module("passenger", name)


def test_departures_are_specific_to_terminal_and_future_window(monkeypatch):
    features = passenger_module("ml.features", monkeypatch)
    rows = [
        {"terminal_id": "terminal-A", "estimated_time": "2026-01-01T10:10:00Z", "pax_count": 120},
        {"terminal_id": "B", "estimated_time": "2026-01-01T11:45:00Z", "pax_count": 80},
        {"terminal_id": "terminal-A", "estimated_time": "2026-01-01T09:00:00Z", "pax_count": 900},
    ]
    counts, pax = features.departure_totals(rows, NOW)
    assert counts == {"A": 1, "B": 0, "C": 0}
    assert pax == {"A": 120, "B": 0, "C": 0}
    counts, pax = features.departure_totals(rows, NOW + timedelta(minutes=30))
    assert counts == {"A": 0, "B": 1, "C": 0}
    assert pax["B"] == 80


def test_forecast_endpoint_uses_schedule_and_context_not_demo_constants(monkeypatch):
    passenger_module("ml.features", monkeypatch)
    # The route's consumer import is an input boundary; avoid starting a broker.
    consumer = SimpleNamespace(
        get_sim_time=lambda: NOW,
        get_security=lambda: SimpleNamespace(get=lambda terminal: SimpleNamespace(
            effective_throughput=lambda predicted: 360.0,
        )),
        get_alerts=lambda: [], get_at_risk_connections=lambda: [],
        get_forecast_context=lambda terminal: {
            "weather_category": "IMC", "load_factor_today": 0.75,
            "incident_active": {terminal: True},
            "adjacent_congested": {terminal: True},
        },
    )
    monkeypatch.setitem(sys.modules, "kafka.consumer", consumer)
    router = importlib.import_module("routers.passengers")
    seen = []

    async def departures(clock, horizon):
        assert clock == NOW and horizon == 120
        return [{"terminal_id": "terminal-B", "estimated_time": "2026-01-01T10:20:00", "pax_count": 200}]

    def predict(terminal, features):
        seen.append(features)
        return int(features["expected_pax_next_90min"] * 0.35), "schedule_ratio"

    monkeypatch.setattr(router, "get_forecast_departures", departures)
    monkeypatch.setattr(router, "predict_with_source", predict)
    result = asyncio.run(router.flow_forecast("B", 30))
    assert [p["predicted_queue_depth"] for p in result["forecast"]] == [70, 70, 70, 70, 0, 0]
    assert all(f["weather_category"] == 2 for f in seen)
    assert all(f["active_incident_in_terminal"] == 1 for f in seen)
    assert all(f["adjacent_terminal_congested"] == 1 for f in seen)
    assert result["congestion_risk"]["confidence"] is None
    assert result["congestion_risk"]["confidence_calibrated"] is False

    async def unavailable(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(router, "get_forecast_departures", unavailable)
    with pytest.raises(router.HTTPException) as error:
        asyncio.run(router.flow_forecast("B", 30))
    assert error.value.status_code == 503


def training_rows(features):
    return pd.DataFrame([
        {**dict.fromkeys(features.FEATURE_COLS, 0), "hour_of_day": i / 60,
         "expected_pax_next_90min": i * 2,
         "sim_time": (NOW + timedelta(minutes=i)).isoformat(), "target": i}
        for i in range(500)
    ]).sample(frac=1, random_state=42)


def test_training_holdout_is_chronological_and_never_fitted(tmp_path, monkeypatch):
    training = passenger_module("ml.training", monkeypatch)
    features = importlib.import_module("ml.features")
    monkeypatch.setattr(training, "TRAINING_ENABLED", True, raising=False)
    monkeypatch.setattr(training, "TRAINING_DIR", tmp_path)
    monkeypatch.setattr(training, "MODELS_DIR", tmp_path)
    training_rows(features).to_parquet(tmp_path / "A.parquet", index=False)
    fitted, evaluated = [], []

    class Model:
        def fit(self, x, y):
            fitted.extend(y.tolist())

        def predict(self, x):
            evaluated.extend(x["expected_pax_next_90min"].tolist())
            return np.array(x["expected_pax_next_90min"]) / 2

    monkeypatch.setattr(training, "make_model", Model)
    monkeypatch.setattr(training.joblib, "dump", lambda model, path: Path(path).write_text("test"))
    assert training.retrain_sync("A") == 0
    assert fitted == list(range(400))
    assert evaluated == list(range(800, 1000, 2))
    assert (tmp_path / "forecast_A.lgbm").read_text() == "test"


def test_actual_lightgbm_artifact_can_train_reload_and_predict(tmp_path, monkeypatch):
    training = passenger_module("ml.training", monkeypatch)
    features = importlib.import_module("ml.features")
    inference = importlib.import_module("ml.inference")
    monkeypatch.setattr(training, "TRAINING_ENABLED", True, raising=False)
    monkeypatch.setattr(training, "TRAINING_DIR", tmp_path)
    monkeypatch.setattr(training, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(inference, "MODELS_DIR", tmp_path)
    factory = training.make_model
    monkeypatch.setattr(training, "make_model", lambda: factory().set_params(n_jobs=1))
    training_rows(features).to_parquet(tmp_path / "A.parquet", index=False)
    mae = training.retrain_sync("A")
    assert mae is not None and np.isfinite(mae)
    inference.load_models()
    value, source = inference.predict_with_source("A", training_rows(features).iloc[0].to_dict())
    assert value >= 0 and source == "lightgbm"
    value, source = inference.predict_with_source("B", {"expected_pax_next_90min": 100})
    assert value == 35 and source == "schedule_ratio"


def test_failed_parquet_write_retains_buffer_and_previous_history(tmp_path, monkeypatch):
    training = passenger_module("ml.training", monkeypatch)
    monkeypatch.setattr(training, "TRAINING_ENABLED", True, raising=False)
    monkeypatch.setattr(training, "TRAINING_DIR", tmp_path)
    training.add_training_row("A", {}, 2, NOW)
    (tmp_path / "A.parquet").write_bytes(b"previous file")
    monkeypatch.setattr(training.pd, "read_parquet", lambda path: pd.DataFrame([
        {"sim_time": "2026-01-01T09:59:00", "target": 1},
    ]))

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail)
    with pytest.raises(OSError, match="disk full"):
        training.flush_to_parquet("A")
    assert len(training._buffers["A"]) == 1
    assert (tmp_path / "A.parquet").read_bytes() == b"previous file"


def test_retraining_without_artifact_does_not_claim_success(tmp_path, monkeypatch):
    training = passenger_module("ml.training", monkeypatch)
    monkeypatch.setattr(training, "TRAINING_ENABLED", True, raising=False)
    monkeypatch.setattr(training, "TRAINING_DIR", tmp_path)
    assert asyncio.run(training.maybe_retrain(3)) is False
    assert training._last_retrain_day == 0

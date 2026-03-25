"""ML inference — prediction + fallback + hot-reload.

Before the model is trained (day 1-3), uses a simple fallback formula:
  forecast = expected_pax_next_90min × 0.35
"""

import logging
import os
from pathlib import Path

import joblib
import pandas as pd

from ml.features import FEATURE_COLS

logger = logging.getLogger(__name__)

MODELS_DIR = Path(os.getenv("MODELS_PATH", "/app/models"))
FALLBACK_RATIO = float(os.getenv("FORECAST_FALLBACK_QUEUE_RATIO", "0.35"))

_models: dict[str, object] = {}
_feature_importances: dict[str, dict[str, float]] = {}


def load_models() -> None:
    """Load all trained LightGBM models from disk and extract feature importances.

    Called at startup and after each retrain to hot-reload updated models.
    """
    for terminal in ("A", "B", "C"):
        path = MODELS_DIR / f"forecast_{terminal}.lgbm"
        if path.exists():
            try:
                _models[terminal] = joblib.load(path)
                # Extract feature importances
                model = _models[terminal]
                if hasattr(model, "feature_importances_"):
                    importances = model.feature_importances_
                    total = sum(importances)
                    if total > 0:
                        _feature_importances[terminal] = {
                            col: round(imp / total, 3)
                            for col, imp in zip(FEATURE_COLS, importances)
                        }
                logger.info("Loaded model for terminal %s from %s", terminal, path)
            except Exception as e:
                logger.error("Failed to load model for %s: %s", terminal, e)


def is_model_trained(terminal: str) -> bool:
    return terminal in _models


def predict(terminal: str, features: dict) -> int | None:
    """Predict queue depth. Returns None only on error."""
    model = _models.get(terminal)
    if model is None:
        return fallback_forecast(features)

    try:
        X = pd.DataFrame([features])[FEATURE_COLS]
        pred = model.predict(X)[0]
        return max(0, int(pred))
    except Exception as e:
        logger.error("Prediction error for %s: %s", terminal, e)
        return fallback_forecast(features)


def fallback_forecast(features: dict) -> int:
    """Day-1 fallback: simple ratio of expected pax."""
    pax = features.get("expected_pax_next_90min", 0)
    return max(0, int(float(pax) * FALLBACK_RATIO))


def get_feature_importance(terminal: str) -> dict[str, float] | None:
    """Get feature importances for a terminal model."""
    return _feature_importances.get(terminal)

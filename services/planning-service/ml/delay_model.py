"""ML delay prediction — P(delay > 15 min) for a given flight context.

P6.2 of ROADMAP_PLANNING.md.

Uses LightGBM classifier.  Falls back to a simple rule-based estimator
when no trained model is available.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

DELAY_FEATURES = [
    "hour",
    "day_of_week",
    "month",
    "weather_category",  # 0=CAVOK, 1=VMC, 2=IMC, 3=LIFR
    "aircraft_type_code",
    "flights_prev_2h",
    "distance_km",
    "historical_otp",  # on-time performance 0-1
]


@dataclass
class DelayPrediction:
    """Predicted probability and expected delay for a flight."""
    flight_context: dict
    p_delay_15min: float  # P(delay > 15 min)
    expected_delay_minutes: float
    model_source: str  # "lgbm" | "heuristic"


@dataclass
class DelayModel:
    """LightGBM delay classifier with heuristic fallback."""

    _model: object | None = None
    _trained: bool = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(self, training_data: list[dict]) -> dict:
        """Train delay prediction model.

        Each record needs DELAY_FEATURES + 'was_delayed' (bool).
        """
        if not training_data:
            return {"error": "no training data", "trained": False}

        try:
            import lightgbm as lgb
            import numpy as np
        except ImportError:
            logger.warning("lightgbm not available — using heuristic delay model")
            return {"error": "lightgbm not installed", "trained": False}

        X = []
        y = []
        for row in training_data:
            features = [row.get(f, 0) for f in DELAY_FEATURES]
            X.append(features)
            y.append(int(row.get("was_delayed", 0)))

        X_arr = np.array(X, dtype=float)
        y_arr = np.array(y, dtype=int)

        split = int(len(X_arr) * 0.8)
        X_train, X_val = X_arr[:split], X_arr[split:]
        y_train, y_val = y_arr[:split], y_arr[split:]

        model = lgb.LGBMClassifier(
            n_estimators=200,
            learning_rate=0.05,
            max_depth=5,
            num_leaves=31,
            random_state=42,
            verbose=-1,
        )
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)])

        self._model = model
        self._trained = True

        preds = model.predict_proba(X_val)[:, 1]
        from sklearn.metrics import roc_auc_score
        try:
            auc = float(roc_auc_score(y_val, preds))
        except Exception:
            auc = 0.0

        logger.info("delay model trained: AUC=%.3f", auc)
        return {"trained": True, "samples": len(X_arr), "auc": round(auc, 3)}

    def predict(
        self,
        hour: int,
        day_of_week: int,
        month: int,
        weather_category: int,
        aircraft_type_code: int = 0,
        flights_prev_2h: int = 20,
        distance_km: float = 1000,
        historical_otp: float = 0.80,
    ) -> DelayPrediction:
        """Predict delay probability for a flight."""
        ctx = {
            "hour": hour,
            "day_of_week": day_of_week,
            "month": month,
            "weather_category": weather_category,
            "flights_prev_2h": flights_prev_2h,
        }

        if self._trained and self._model is not None:
            return self._predict_lgbm(ctx, hour, day_of_week, month,
                                       weather_category, aircraft_type_code,
                                       flights_prev_2h, distance_km, historical_otp)

        return self._predict_heuristic(ctx, hour, weather_category,
                                        flights_prev_2h, historical_otp)

    def _predict_lgbm(self, ctx, hour, dow, month, wx, ac, flights, dist, otp):
        import numpy as np
        features = np.array([[hour, dow, month, wx, ac, flights, dist, otp]])
        p = float(self._model.predict_proba(features)[0, 1])
        exp_delay = p * 35  # Average delay when delayed ~35 min
        return DelayPrediction(
            flight_context=ctx, p_delay_15min=round(p, 3),
            expected_delay_minutes=round(exp_delay, 1), model_source="lgbm",
        )

    def _predict_heuristic(self, ctx, hour, weather_cat, flights_prev_2h, otp):
        """Rule-based delay probability estimation."""
        base_p = 0.15  # 15% base delay probability

        # Weather impact
        wx_mult = {0: 0.7, 1: 1.0, 2: 1.8, 3: 3.0}.get(weather_cat, 1.0)
        base_p *= wx_mult

        # Peak hour congestion (07-09, 17-19)
        if hour in (7, 8, 9, 17, 18, 19):
            base_p *= 1.4

        # High traffic load
        if flights_prev_2h > 30:
            base_p *= 1.2
        elif flights_prev_2h < 10:
            base_p *= 0.8

        # Historical OTP influence
        base_p *= (1.0 - otp) * 2 + 0.5

        p = min(0.95, max(0.02, base_p))
        exp_delay = p * 35
        return DelayPrediction(
            flight_context=ctx, p_delay_15min=round(p, 3),
            expected_delay_minutes=round(exp_delay, 1), model_source="heuristic",
        )

    def to_dict(self) -> dict:
        return {
            "trained": self._trained,
            "model_source": "lgbm" if self._trained else "heuristic",
            "features": DELAY_FEATURES,
        }


_delay_model = DelayModel()


def get_delay_model() -> DelayModel:
    return _delay_model

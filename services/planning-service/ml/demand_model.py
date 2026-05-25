"""ML demand forecasting — predicts daily flight counts by route + date.

P6.1 of ROADMAP_PLANNING.md.

Uses LightGBM to model demand as a function of seasonality, day of week,
route distance, and historical traffic.  Falls back to a simple seasonal
heuristic when LightGBM is not available or no training data exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import structlog

logger = structlog.get_logger(__name__)

# Feature names in the training matrix
DEMAND_FEATURES = [
    "month",
    "day_of_week",
    "is_holiday",
    "distance_km",
    "historical_avg_pax",
    "growth_trend",
    "is_hub_connection",
]

# US public holidays (month, day) — simplified
US_HOLIDAYS = {
    (1, 1), (1, 20), (2, 17), (5, 26), (7, 4), (9, 1),
    (10, 13), (11, 11), (11, 27), (12, 25),
}

# Seasonal adjustment factors (indexed by month 1-12)
SEASONAL_FACTORS = [
    0.85, 0.82, 0.95, 1.00, 1.05, 1.20,
    1.25, 1.22, 1.05, 0.98, 0.88, 0.90,
]


@dataclass
class DemandForecast:
    """Predicted passenger demand for a route on a given date."""
    origin: str
    destination: str
    forecast_date: date
    predicted_daily_pax: float
    confidence_low: float  # p10
    confidence_high: float  # p90
    model_source: str  # "lgbm" | "heuristic"


@dataclass
class DemandModel:
    """LightGBM-based demand model with heuristic fallback.

    The model learns from BTS T-100 historical data.  When no trained
    model exists, a deterministic seasonal heuristic provides reasonable
    estimates calibrated to a medium-sized US airport (~8 M annual pax).
    """

    _model: object | None = None  # LGBMRegressor when trained
    _trained: bool = False
    _route_baselines: dict[tuple[str, str], float] = field(default_factory=dict)
    _global_daily_avg: float = 25_000.0  # ~8M annual / 320 operating days

    @property
    def is_trained(self) -> bool:
        return self._trained

    def set_route_baselines(self, baselines: dict[tuple[str, str], float]) -> None:
        """Set per-route daily baselines from BTS data."""
        self._route_baselines = dict(baselines)

    def train(self, training_data: list[dict]) -> dict:
        """Train the LightGBM demand model from historical records.

        Each record: {origin, destination, month, day_of_week, is_holiday,
                      distance_km, historical_avg_pax, growth_trend,
                      is_hub_connection, actual_pax}

        Returns training metrics.
        """
        if not training_data:
            return {"error": "no training data", "trained": False}

        try:
            import lightgbm as lgb
            import numpy as np
        except ImportError:
            logger.warning("lightgbm not available — using heuristic model")
            return {"error": "lightgbm not installed", "trained": False}

        X = []
        y = []
        for row in training_data:
            features = [row.get(f, 0) for f in DEMAND_FEATURES]
            X.append(features)
            y.append(row["actual_pax"])

        X_arr = np.array(X, dtype=float)
        y_arr = np.array(y, dtype=float)

        # Temporal split: last 20% for validation
        split = int(len(X_arr) * 0.8)
        X_train, X_val = X_arr[:split], X_arr[split:]
        y_train, y_val = y_arr[:split], y_arr[split:]

        model = lgb.LGBMRegressor(
            n_estimators=200,
            learning_rate=0.05,
            max_depth=6,
            num_leaves=31,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbose=-1,
        )
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
        )

        self._model = model
        self._trained = True

        # Validation metrics
        preds = model.predict(X_val)
        mae = float(np.mean(np.abs(preds - y_val)))
        rmse = float(np.sqrt(np.mean((preds - y_val) ** 2)))

        logger.info("demand model trained: MAE=%.1f RMSE=%.1f", mae, rmse)
        return {
            "trained": True,
            "samples": len(X_arr),
            "mae": round(mae, 1),
            "rmse": round(rmse, 1),
            "features": DEMAND_FEATURES,
        }

    def predict(
        self,
        origin: str,
        destination: str,
        forecast_date: date,
        distance_km: float = 1000.0,
        is_hub: bool = False,
    ) -> DemandForecast:
        """Predict daily passenger demand for a route on a given date."""
        month = forecast_date.month
        dow = forecast_date.weekday()
        is_holiday = (month, forecast_date.day) in US_HOLIDAYS
        historical = self._route_baselines.get((origin, destination), 0.0)
        growth = 0.034  # Default 3.4% CAGR

        if self._trained and self._model is not None:
            return self._predict_lgbm(
                origin, destination, forecast_date, month, dow,
                is_holiday, distance_km, historical, growth, is_hub,
            )

        return self._predict_heuristic(
            origin, destination, forecast_date, month, dow,
            is_holiday, distance_km, historical, is_hub,
        )

    def _predict_lgbm(
        self, origin, destination, forecast_date, month, dow,
        is_holiday, distance_km, historical, growth, is_hub,
    ) -> DemandForecast:
        """Use trained LightGBM model."""
        import numpy as np

        features = np.array([[
            month, dow, int(is_holiday), distance_km,
            historical, growth, int(is_hub),
        ]])
        pred = float(self._model.predict(features)[0])
        pred = max(0, pred)

        # Confidence from model uncertainty (±20% as rough estimate)
        low = pred * 0.80
        high = pred * 1.20

        return DemandForecast(
            origin=origin,
            destination=destination,
            forecast_date=forecast_date,
            predicted_daily_pax=round(pred, 0),
            confidence_low=round(low, 0),
            confidence_high=round(high, 0),
            model_source="lgbm",
        )

    def _predict_heuristic(
        self, origin, destination, forecast_date, month, dow,
        is_holiday, distance_km, historical, is_hub,
    ) -> DemandForecast:
        """Heuristic demand prediction when no ML model is available."""
        # Base from route history or global average
        if historical > 0:
            base = historical
        elif distance_km > 0:
            # Distance-based heuristic: shorter routes have more demand
            base = max(20, 500 - distance_km * 0.08)
        else:
            base = 100

        # Seasonal adjustment
        seasonal = SEASONAL_FACTORS[month - 1]
        pred = base * seasonal

        # Day-of-week adjustment (weekend slightly lower)
        if dow >= 5:
            pred *= 0.85

        # Holiday boost
        if is_holiday:
            pred *= 1.15

        # Hub connection boost
        if is_hub:
            pred *= 1.30

        pred = max(0, pred)
        low = pred * 0.70
        high = pred * 1.30

        return DemandForecast(
            origin=origin,
            destination=destination,
            forecast_date=forecast_date,
            predicted_daily_pax=round(pred, 0),
            confidence_low=round(low, 0),
            confidence_high=round(high, 0),
            model_source="heuristic",
        )

    def forecast_route_range(
        self,
        origin: str,
        destination: str,
        start_date: date,
        days: int = 30,
        distance_km: float = 1000.0,
        is_hub: bool = False,
    ) -> list[DemandForecast]:
        """Forecast demand for a route over a date range."""
        from datetime import timedelta
        return [
            self.predict(origin, destination, start_date + timedelta(days=i),
                         distance_km, is_hub)
            for i in range(days)
        ]

    def to_dict(self) -> dict:
        return {
            "trained": self._trained,
            "model_source": "lgbm" if self._trained else "heuristic",
            "route_baselines_count": len(self._route_baselines),
            "features": DEMAND_FEATURES,
        }


# Module-level singleton
_demand_model = DemandModel()


def get_demand_model() -> DemandModel:
    return _demand_model
